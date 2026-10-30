"""Input validation, compiler-diagnostic parsing and heuristic warnings (clearly labelled as heuristic)."""
from __future__ import annotations

import re
from pathlib import Path

from ..config import settings
from ..compiler.compilation import CompilerError, check_source_includes
from .features import code_only

EXT_LANG = {".c": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp"}

# Defense in depth only (trivially bypassable) — see README "Safety".
DENY = [
    (r"\b(system|popen|_popen|fork|vfork|execl|execlp|execle|execv|execvp|execve|CreateProcess[AW]?|ShellExecute[AW]?|WinExec)\s*\(",
     "process-spawning call"),
    (r"\b(asm|__asm__|__asm|_asm)\b", "inline assembly"),
    (r"\b(remove|unlink|rmdir|rename|chmod|chown)\s*\(", "file-system modification call"),
    (r"#\s*include\s*<(windows\.h|unistd\.h|sys/socket\.h|winsock2\.h|sys/ptrace\.h)>", "OS/network header"),
    (r"\b(socket|connect|bind|ptrace|dlopen|LoadLibrary[AW]?)\s*\(", "network / dynamic-loading call"),
]
NONDET = [
    (r"\b(time|clock|clock_gettime|gettimeofday|getpid|QueryPerformanceCounter)\s*\(", "wall-clock/PID call"),
    (r"std::random_device|std::chrono::\w*clock", "non-deterministic API"),
    (r"\bsrand\s*\(\s*time", "time-seeded RNG"),
]


class ValidationError(ValueError):
    def __init__(self, message: str, code: str = "invalid_input"):
        super().__init__(message)
        self.code = code


def language_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    return EXT_LANG.get(Path(filename).suffix.lower())


def validate_source(source: str, language: str, filename: str | None = None, stdin: str = "") -> tuple[str, list[str]]:
    """Return (normalised_language, warnings) or raise ValidationError."""
    warnings: list[str] = []
    if language not in ("c", "cpp"):
        raise ValidationError("language must be 'c' or 'cpp'", "bad_language")
    if filename:
        ext = Path(filename).suffix.lower()
        if ext not in EXT_LANG:
            raise ValidationError(f"Unsupported file extension '{ext or '(none)'}'. Allowed: .c, .cpp, .cc, .cxx", "bad_extension")
        if EXT_LANG[ext] != language:
            raise ValidationError(f"File extension '{ext}' does not match selected language '{language}'.", "language_mismatch")
    if not source or not source.strip():
        raise ValidationError("Source is empty.", "empty")
    raw = source.encode("utf-8", errors="strict")
    if len(raw) > settings.max_source_bytes:
        raise ValidationError(f"Source is {len(raw)} bytes; limit is {settings.max_source_bytes}.", "too_large")
    if "\x00" in source:
        raise ValidationError("Source contains NUL bytes (binary file?).", "binary")
    if len(stdin.encode("utf-8")) > settings.max_stdin_bytes:
        raise ValidationError(f"stdin data exceeds {settings.max_stdin_bytes} bytes.", "stdin_too_large")
    code = code_only(source)
    for pattern, what in DENY:
        if re.search(pattern, code) or re.search(pattern, source if "include" in pattern else ""):
            raise ValidationError(f"Rejected: {what} is not allowed because the program is executed locally.", "denied_construct")
    if not re.search(r"\bmain\s*\(", code):
        raise ValidationError("No main() function found: an executable cannot be built and benchmarked.", "no_main")
    try:
        check_source_includes(source)
    except CompilerError as exc:
        raise ValidationError(str(exc), "bad_include")
    for pattern, what in NONDET:
        if re.search(pattern, code):
            warnings.append(f"Heuristic: uses {what}; output may differ between runs and fail the correctness check.")
    if re.search(r"\b(scanf|gets|getchar|std::cin|fgets|getline)\b", code):
        warnings.append("Program reads stdin: supply benchmark input in the stdin box (same data is used for every variant).")
    return language, warnings


_DIAG_RE = re.compile(r"^(?P<file>.+?):(?P<line>\d+):(?P<col>\d+): (?P<sev>warning|error|note|fatal error): (?P<msg>.*)$")


def parse_diagnostics(stderr: str, workdir: str | None = None) -> list[dict]:
    out = []
    for line in stderr.splitlines():
        m = _DIAG_RE.match(line.strip())
        if not m:
            continue
        out.append({"file": Path(m.group("file")).name, "line": int(m.group("line")), "col": int(m.group("col")),
                    "severity": m.group("sev").replace("fatal error", "error"), "message": m.group("msg")})
    return out[:80]


def opportunities(feats: dict, remarks: list[dict], o0_instr: int | None = None, o2_instr: int | None = None) -> list[dict]:
    """Heuristic list of optimisation opportunities, each carrying the evidence it is based on."""
    ops = []
    if feats.get("src_loops", 0) or feats.get("ir_loops", 0):
        ops.append({"title": "Loop optimisations", "kind": "heuristic",
                    "evidence": f"{feats.get('ir_loops', feats.get('src_loops', 0))} loop(s), max depth {feats.get('src_max_loop_depth', 0)}",
                    "detail": "LICM, strength reduction, unrolling and vectorisation can apply to loop bodies."})
    vec = [r for r in remarks if r["status"] == "vectorized"]
    missed = [r for r in remarks if r["status"] == "missed"]
    if vec:
        ops.append({"title": "Vectorisation achieved", "kind": "compiler-remark",
                    "evidence": f"{len(vec)} loop(s) vectorised at -O3 (LLVM remarks)", "detail": vec[0]["message"]})
    if missed:
        ops.append({"title": "Vectorisation blocked", "kind": "compiler-remark",
                    "evidence": f"{len(missed)} loop(s) not vectorised", "detail": missed[0]["message"]})
    if feats.get("ir_calls", 0) >= 3 and feats.get("src_functions", 0) > 1:
        ops.append({"title": "Inlining candidates", "kind": "heuristic",
                    "evidence": f"{feats.get('ir_calls')} calls across {feats.get('src_functions')} functions",
                    "detail": "Small helper functions may be inlined, enabling further folding."})
    if feats.get("ratio_branch", 0) > 0.08:
        ops.append({"title": "Branch-heavy code", "kind": "heuristic",
                    "evidence": f"conditional branches = {feats['ratio_branch']:.1%} of IR instructions",
                    "detail": "SimplifyCFG / select conversion may help; vectorisation is less likely."})
    if o0_instr and o2_instr and o2_instr < o0_instr:
        ops.append({"title": "Redundancy removed by -O2", "kind": "measured-ir",
                    "evidence": f"IR instructions {o0_instr} → {o2_instr} ({100 * (o0_instr - o2_instr) / o0_instr:.0f}% fewer)",
                    "detail": "Dead code, redundant loads/stores and common sub-expressions were eliminated."})
    return ops
