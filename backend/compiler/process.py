"""Bounded subprocess execution. NOT a sandbox: it applies timeouts, output caps, a scrubbed
environment and (on POSIX) address-space / CPU / file-size rlimits. See README 'Safety'."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings

IS_WINDOWS = sys.platform.startswith("win")


@dataclass
class ProcResult:
    argv: list[str]
    returncode: int | None
    stdout: bytes = b""
    stderr: bytes = b""
    elapsed_ms: float = 0.0
    timed_out: bool = False
    output_truncated: bool = False
    error: str | None = None  # launch failure (e.g. missing binary)
    max_rss_kb: int | None = None
    cpu_ms: float | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and not self.timed_out and self.returncode == 0

    @property
    def stdout_text(self) -> str:
        return self.stdout.decode("utf-8", errors="replace")

    @property
    def stderr_text(self) -> str:
        return self.stderr.decode("utf-8", errors="replace")


def scrubbed_env(extra_path_dirs: list[str] | None = None) -> dict[str, str]:
    """Pass only what a toolchain needs; never leak API keys or tokens."""
    keep = ["PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE",
            "LANG", "LC_ALL", "LD_LIBRARY_PATH", "INCLUDE", "LIB", "VCINSTALLDIR", "VSINSTALLDIR",
            "WindowsSdkDir", "UniversalCRTSdkDir", "ProgramFiles", "ProgramFiles(x86)", "ProgramData",
            "LOCALAPPDATA", "APPDATA", "COMSPEC", "PATHEXT"]
    env = {k: os.environ[k] for k in keep if k in os.environ}
    if extra_path_dirs:
        env["PATH"] = os.pathsep.join(extra_path_dirs + [env.get("PATH", "")])
    return env


def _preexec(mem_mb: int, cpu_s: int):
    def fn():  # pragma: no cover - runs in child
        import resource

        try:
            if mem_mb > 0:
                lim = mem_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
            resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except Exception:
            pass
        os.setsid()

    return fn


def run(argv: list[str], *, cwd: Path | str, timeout: float, stdin: bytes | None = None,
        limit_resources: bool = False, mem_mb: int | None = None, max_output: int | None = None,
        env: dict[str, str] | None = None) -> ProcResult:
    """Run argv (never a shell string). stdout/stderr are captured via temp files so a noisy child
    cannot exhaust memory; they are truncated to `max_output` bytes."""
    max_output = max_output or settings.max_output_bytes
    t0 = time.perf_counter()
    res = ProcResult(argv=list(argv), returncode=None)
    kwargs: dict = {}
    if not IS_WINDOWS and limit_resources:
        kwargs["preexec_fn"] = _preexec(mem_mb if mem_mb is not None else settings.run_memory_limit_mb,
                                        int(timeout) + 2)
    elif not IS_WINDOWS:
        kwargs["start_new_session"] = True
    with tempfile.TemporaryFile() as fo, tempfile.TemporaryFile() as fe:
        try:
            proc = subprocess.Popen(argv, cwd=str(cwd), stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                    stdout=fo, stderr=fe, env=env or scrubbed_env(), shell=False, **kwargs)
        except (OSError, ValueError) as exc:
            res.error = f"{type(exc).__name__}: {exc}"
            res.elapsed_ms = (time.perf_counter() - t0) * 1000
            return res
        timer = None
        try:
            if stdin is not None:
                try:
                    proc.stdin.write(stdin)
                    proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            if not IS_WINDOWS:
                import threading

                flag = {"t": False}

                def _expire():
                    flag["t"] = True
                    _kill(proc, reap=False)

                timer = threading.Timer(timeout, _expire)
                timer.start()
                _, status, ru = os.wait4(proc.pid, 0)
                timer.cancel()
                proc.returncode = os.waitstatus_to_exitcode(status)
                res.max_rss_kb = int(ru.ru_maxrss)
                res.cpu_ms = (ru.ru_utime + ru.ru_stime) * 1000
                res.timed_out = flag["t"]
            else:
                proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            res.timed_out = True
            _kill(proc)
        except ChildProcessError:
            proc.wait()
        finally:
            if timer is not None:
                timer.cancel()
        res.returncode = proc.returncode
        res.elapsed_ms = (time.perf_counter() - t0) * 1000
        for f, attr in ((fo, "stdout"), (fe, "stderr")):
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(0)
            data = f.read(max_output)
            if size > max_output:
                res.output_truncated = True
            setattr(res, attr, data)
    return res


def _kill(proc: subprocess.Popen, reap: bool = True) -> None:
    try:
        if not IS_WINDOWS:
            import signal

            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    if reap:
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
