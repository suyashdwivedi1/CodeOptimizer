"""Compilation helpers around clang / clang++ / opt / llc. All commands are argv lists."""
from __future__ import annotations

import hashlib
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings
from . import detection
from .process import ProcResult, run

IS_WINDOWS = sys.platform.startswith("win")
EXE_SUFFIX = ".exe" if IS_WINDOWS else ""

DEFAULT_STD = {"c": "-std=c17", "cpp": "-std=c++17"}

_FLAG_ALLOW = [
    re.compile(r"^-O(0|1|2|3|s|z)$"),
    re.compile(r"^-f(no-)?(vectorize|slp-vectorize|unroll-loops|inline-functions|inline|loop-interchange)$"),
    re.compile(r"^-std=(c(89|99|11|17|23)|gnu(89|99|11|17|23)|c\+\+(11|14|17|20|23)|gnu\+\+(11|14|17|20|23))$"),
    re.compile(r"^-Wno-[a-z0-9-]+$"),
    re.compile(r"^-g0$"),
]
_MLLVM_ALLOW = [re.compile(r"^-inline-threshold=\d{1,5}$"), re.compile(r"^-unroll-threshold=\d{1,5}$")]

_INCLUDE_RE = re.compile(r'^\s*#\s*(include|include_next|embed|import)\s*"([^"]*)"', re.M)


class CompilerError(Exception):
    pass


def validate_flags(flags: list[str]) -> list[str]:
    """Allow-list every compiler option; anything else is rejected (no arbitrary -Xclang, -load, @file...)."""
    i = 0
    while i < len(flags):
        f = flags[i]
        if f == "-mllvm":
            if i + 1 >= len(flags) or not any(p.match(flags[i + 1]) for p in _MLLVM_ALLOW):
                raise CompilerError(f"-mllvm option not allowed: {flags[i + 1:i + 2]}")
            i += 2
            continue
        if not any(p.match(f) for p in _FLAG_ALLOW):
            raise CompilerError(f"Compiler flag not on allow-list: {f}")
        i += 1
    return flags


def check_source_includes(source: str) -> None:
    for m in _INCLUDE_RE.finditer(source):
        target = m.group(2)
        if target.startswith(("/", "\\")) or ".." in target or re.match(r"^[A-Za-z]:", target):
            raise CompilerError(f'Local #include of "{target}" is not allowed (only system headers or same-directory files).')


def clang_for(language: str) -> str:
    tool = "clang++" if language == "cpp" else "clang"
    path = detection.tool_path(tool)
    if not path:
        raise CompilerError(f"{tool} is not installed or not found. Run scripts/check_environment.py for help.")
    return path


def source_filename(language: str) -> str:
    return "program.cpp" if language == "cpp" else "program.c"


@dataclass
class StepResult:
    ok: bool
    cmd: list[str]
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    elapsed_ms: float = 0.0
    timed_out: bool = False
    error: str | None = None

    @classmethod
    def from_proc(cls, r: ProcResult) -> "StepResult":
        return cls(ok=r.ok, cmd=r.argv, stdout=r.stdout_text, stderr=r.stderr_text, returncode=r.returncode,
                   elapsed_ms=r.elapsed_ms, timed_out=r.timed_out, error=r.error)

    def reason(self) -> str:
        if self.error:
            return self.error
        if self.timed_out:
            return "timed out"
        txt = self.stderr.strip() or self.stdout.strip()
        return txt[:2000] or f"exit status {self.returncode}"


def _lang_flags(language: str, flags: list[str]) -> list[str]:
    out = list(flags)
    if not any(f.startswith("-std=") for f in out):
        out.append(DEFAULT_STD[language])
    return out


def compile_exe(src: Path, language: str, flags: list[str], out: Path, extra: list[str] | None = None) -> StepResult:
    flags = _lang_flags(language, validate_flags(list(flags)))
    cmd = [clang_for(language), *flags, *(extra or []), str(src), "-o", str(out)]
    if not IS_WINDOWS and language == "c":
        cmd.append("-lm")
    return StepResult.from_proc(run(cmd, cwd=src.parent, timeout=settings.compile_timeout_s, limit_resources=False))


def syntax_check(src: Path, language: str) -> StepResult:
    cmd = [clang_for(language), *_lang_flags(language, []), "-fsyntax-only", "-Wall", "-Wextra", str(src)]
    return StepResult.from_proc(run(cmd, cwd=src.parent, timeout=settings.compile_timeout_s))


def emit_ir(src: Path, language: str, flags: list[str], out: Path, extra: list[str] | None = None) -> StepResult:
    flags = _lang_flags(language, validate_flags(list(flags)))
    cmd = [clang_for(language), *flags, *(extra or []), "-S", "-emit-llvm", str(src), "-o", str(out)]
    return StepResult.from_proc(run(cmd, cwd=src.parent, timeout=settings.compile_timeout_s))


def emit_unoptimized_ir(src: Path, language: str, out: Path) -> StepResult:
    """O0 IR without the `optnone` attribute so that `opt` pipelines are allowed to transform it."""
    return emit_ir(src, language, ["-O0"], out, extra=["-Xclang", "-disable-O0-optnone"])


def verify_ir(ll: Path) -> StepResult:
    opt = detection.tool_path("opt")
    if not opt:
        return StepResult(ok=False, cmd=[], error="opt not installed")
    return StepResult.from_proc(run([opt, "-passes=verify", "-disable-output", str(ll)], cwd=ll.parent, timeout=60))


def run_opt(ll_in: Path, pipeline: str, ll_out: Path, remarks: bool = False) -> StepResult:
    opt = detection.tool_path("opt")
    if not opt:
        return StepResult(ok=False, cmd=[], error="opt not installed")
    cmd = [opt, f"-passes={pipeline}", "-S", str(ll_in), "-o", str(ll_out)]
    if remarks:
        cmd += ["-pass-remarks=loop-vectorize|slp-vectorizer", "-pass-remarks-missed=loop-vectorize",
                "-pass-remarks-analysis=loop-vectorize"]
    return StepResult.from_proc(run(cmd, cwd=ll_in.parent, timeout=settings.compile_timeout_s))


def ir_to_exe(ll: Path, out: Path, language: str) -> StepResult:
    """Lower optimised IR with llc -O2 (PIC object) and link with clang. Time of both steps is summed."""
    llc = detection.tool_path("llc")
    if not llc:
        return StepResult(ok=False, cmd=[], error="llc not installed")
    obj = ll.with_suffix(".o" if not IS_WINDOWS else ".obj")
    t0 = time.perf_counter()
    r1 = StepResult.from_proc(run([llc, "-O2", "-relocation-model=pic", "-filetype=obj", str(ll), "-o", str(obj)],
                                  cwd=ll.parent, timeout=settings.compile_timeout_s))
    if not r1.ok:
        return r1
    link = [clang_for(language), str(obj), "-o", str(out)]
    if not IS_WINDOWS and language == "c":
        link.append("-lm")
    r2 = StepResult.from_proc(run(link, cwd=ll.parent, timeout=settings.compile_timeout_s))
    r2.elapsed_ms = (time.perf_counter() - t0) * 1000
    return r2


def pipeline_passes(pipeline: str, ll_ref: Path) -> list[str]:
    """Return the expanded list of top-level passes for display (`opt -print-pipeline-passes`)."""
    opt = detection.tool_path("opt")
    if not opt:
        return []
    r = run([opt, f"-passes={pipeline}", "-print-pipeline-passes", "-disable-output", str(ll_ref)],
            cwd=ll_ref.parent, timeout=30)
    text = (r.stdout_text or r.stderr_text).strip()
    return _split_top_level(text)


def _split_top_level(text: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch in "(<":
            depth += 1
        elif ch in ")>":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return [p for p in parts if p]


_PASS_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")


def pass_names(text: str) -> set[str]:
    """All pass identifiers appearing anywhere in a (nested) pipeline string."""
    return set(_PASS_NAME_RE.findall(text))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_remarks(stderr: str) -> list[dict]:
    """Parse clang `-Rpass*` and opt `-pass-remarks*` output into structured remarks."""
    out = []
    rx = re.compile(r"^(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+): remark: (?P<msg>.*?)(?: \[(?P<flag>-R[\w=-]+)\])?$")
    for line in stderr.splitlines():
        m = rx.match(line.strip())
        if not m:
            continue
        msg = m.group("msg")
        flag = m.group("flag") or ""
        lowered = msg.lower()
        if "vectorized loop" in lowered or "vectorized" in lowered and "slp" not in flag and "loop" in flag:
            status = "vectorized"
        elif "slp" in flag or "vectorized" in lowered:
            status = "vectorized"
        elif "missed" in flag or "not vectorized" in lowered or "cannot" in lowered or "loop not" in lowered:
            status = "missed"
        else:
            status = "analysis"
        out.append({"line": int(m.group("line")), "col": int(m.group("col")), "message": msg, "status": status,
                    "pass": flag})
    return out[:60]
