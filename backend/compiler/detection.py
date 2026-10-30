"""Detect clang / clang++ / opt / llc individually and probe which LLVM pass pipelines work."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from ..config import settings
from .process import run, scrubbed_env

EXE = ".exe" if sys.platform.startswith("win") else ""
_lock = threading.Lock()
_cache: dict | None = None

COMMON_DIRS = [
    r"C:\Program Files\LLVM\bin",
    r"C:\Program Files (x86)\LLVM\bin",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\LLVM\bin"),
    "/usr/local/opt/llvm/bin", "/opt/homebrew/opt/llvm/bin",
] + [f"/usr/lib/llvm-{v}/bin" for v in range(21, 12, -1)]

TINY_IR = """define i32 @f(i32 %a, i32 %b) {
entry:
  %s = add i32 %a, %b
  ret i32 %s
}
"""


def _find(tool: str, override: str) -> str | None:
    if override:
        p = Path(override)
        if p.is_file():
            return str(p)
        w = shutil.which(override)
        if w:
            return w
    if settings.llvm_bin_dir:
        c = Path(settings.llvm_bin_dir) / (tool + EXE)
        if c.is_file():
            return str(c)
    w = shutil.which(tool)
    if w:
        return w
    for d in COMMON_DIRS:
        c = Path(d) / (tool + EXE)
        if c.is_file():
            return str(c)
    return None


def _version(path: str) -> str | None:
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=15, env=scrubbed_env())
        out = (r.stdout or r.stderr).strip()
        return out.splitlines()[0] if out else None
    except Exception:
        return None


def _llvm_major(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"(?:clang|LLVM) version (\d+)", text) or re.search(r"version (\d+)\.", text)
    return int(m.group(1)) if m else None


def detect(refresh: bool = False) -> dict:
    global _cache
    with _lock:
        if _cache is not None and not refresh:
            return _cache
        tools = {}
        for name, override in (("clang", settings.clang_path), ("clang++", settings.clangxx_path),
                               ("opt", settings.opt_path), ("llc", settings.llc_path)):
            path = _find(name, override)
            ver = _version(path) if path else None
            tools[name] = {"available": bool(path and ver), "path": path, "version": ver}
        clang_ver = tools["clang"]["version"]
        opt_ver = tools["opt"]["version"]
        opt_text = None
        if tools["opt"]["available"]:
            try:
                r = subprocess.run([tools["opt"]["path"], "--version"], capture_output=True, text=True, timeout=15,
                                   env=scrubbed_env())
                opt_text = r.stdout
                m = re.search(r"LLVM version (\S+)", opt_text)
                opt_ver = f"LLVM {m.group(1)}" if m else opt_ver
            except Exception:
                pass
        _cache = {
            "tools": tools,
            "clang_version": clang_ver,
            "llvm_version": opt_ver,
            "llvm_major": _llvm_major(opt_text) or _llvm_major(clang_ver),
            "can_compile_c": tools["clang"]["available"],
            "can_compile_cpp": tools["clang++"]["available"],
            "can_use_ir_pipelines": tools["clang"]["available"] and tools["opt"]["available"] and tools["llc"]["available"],
            "platform": sys.platform,
            "pass_support": {},
            "problems": [],
        }
        probs = _cache["problems"]
        if not tools["clang"]["available"]:
            probs.append("clang not found. Install LLVM (https://github.com/llvm/llvm-project/releases) or set CLANG_PATH / LLVM_BIN_DIR.")
        if not tools["clang++"]["available"]:
            probs.append("clang++ not found: C++ input is disabled.")
        if not tools["opt"]["available"]:
            probs.append("opt not found: custom LLVM pass-pipeline candidates are disabled (clang -O levels still work).")
        if not tools["llc"]["available"]:
            probs.append("llc not found: custom LLVM pass-pipeline candidates are disabled.")
        return _cache


def tool_path(name: str) -> str | None:
    return detect()["tools"].get(name, {}).get("path")


def probe_pipeline(pipeline: str) -> tuple[bool, str]:
    """Check that the installed `opt` accepts a pass pipeline (pass names differ between versions)."""
    d = detect()
    cache = d["pass_support"]
    if pipeline in cache:
        return cache[pipeline]
    opt = tool_path("opt")
    if not opt:
        return False, "opt not installed"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.ll"
        p.write_text(TINY_IR)
        r = run([opt, f"-passes={pipeline}", "-S", str(p), "-o", os.devnull if os.name != "nt" else "NUL"],
                cwd=td, timeout=30)
    ok = r.ok
    cache[pipeline] = (ok, "" if ok else (r.stderr_text.strip().splitlines() or ["rejected by opt"])[0][:200])
    return cache[pipeline]
