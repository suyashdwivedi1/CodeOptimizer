"""Versioned feature extraction. Compiler-derived features come from LLVM IR (after mem2reg so loads/stores are
real memory traffic, not stack spills) and `opt -passes=print<loops>`; source features are lexer-based heuristics
and are labelled as estimates."""
from __future__ import annotations

import math
import re
from pathlib import Path

from ..compiler import compilation
from ..compiler.source_transforms import _scan_code_spans

FEATURE_SCHEMA_VERSION = "1"

FEATURE_NAMES: list[str] = [
    "src_lines", "src_functions", "src_loops", "src_max_loop_depth", "src_branches", "src_array_accesses",
    "src_fp_tokens", "src_calls", "src_log_max_literal", "src_has_recursion",
    "ir_instr", "ir_bb", "ir_loops", "ir_max_loop_depth", "ir_loads", "ir_stores", "ir_gep", "ir_calls",
    "ir_fp_ops", "ir_int_ops", "ir_cond_br", "ir_phi", "ir_vec_instr",
    "ratio_branch", "ratio_mem", "ratio_fp", "ratio_call", "ratio_loop_bb",
]
_LOG_FEATURES = {"src_lines", "src_functions", "src_loops", "src_branches", "src_array_accesses", "src_fp_tokens",
                 "src_calls", "ir_instr", "ir_bb", "ir_loops", "ir_loads", "ir_stores", "ir_gep", "ir_calls",
                 "ir_fp_ops", "ir_int_ops", "ir_cond_br", "ir_phi", "ir_vec_instr"}

FEATURE_INFO = {
    "src_": "source-level, lexer heuristic (estimate)",
    "ir_": "LLVM IR after mem2reg (compiler-derived)",
    "ratio_": "ratio of IR counts (compiler-derived)",
}

KEYWORDS_NOT_CALLS = {"if", "for", "while", "switch", "return", "sizeof", "catch", "defined", "alignof", "decltype",
                      "static_assert", "else", "do", "case"}


def code_only(src: str) -> str:
    """Source with comments, string/char literals and preprocessor lines blanked out (positions preserved)."""
    keep = {i for i, _ in _scan_code_spans(src)}
    return "".join(c if (i in keep or c == "\n") else " " for i, c in enumerate(src))


_FUNC_RE = re.compile(r"(?m)^[ \t]*(?:template\s*<[^>]*>\s*)?(?:[A-Za-z_][\w:<>,\*&\s]*?[\s\*&])([A-Za-z_]\w*)\s*\(([^;{}()]*(?:\([^)]*\)[^;{}()]*)*)\)\s*(?:const\s*)?(?:noexcept\s*)?\{")


def source_features(src: str, language: str = "c") -> dict:
    code = code_only(src)
    lines = [ln for ln in code.splitlines() if ln.strip()]
    funcs = [m.group(1) for m in _FUNC_RE.finditer(code) if m.group(1) not in KEYWORDS_NOT_CALLS]
    loops, depth = loop_structure(code)
    branches = len(re.findall(r"\b(?:if|switch|case)\b|\?|&&|\|\|", code))
    arr = code.count("[")
    fp = len(re.findall(r"\b(?:float|double)\b|\d\.\d*(?:[eE][-+]?\d+)?f?\b", code))
    calls = len([m for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", code) if m.group(1) not in KEYWORDS_NOT_CALLS])
    lits = [int(x) for x in re.findall(r"\b(\d{1,12})\b", code)]
    # recursion heuristic: function name called within its own body
    recursion = 0
    for name in set(funcs):
        body_calls = len(re.findall(rf"\b{re.escape(name)}\s*\(", code))
        if body_calls >= 2 and name != "main":  # definition + at least one more call site (may be a normal caller)
            m = re.search(rf"\b{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{", code)
            if m:
                start = m.end()
                d, i = 1, start
                while i < len(code) and d:
                    d += (code[i] == "{") - (code[i] == "}")
                    i += 1
                if re.search(rf"\b{re.escape(name)}\s*\(", code[start:i]):
                    recursion = 1
    return {
        "src_lines": len(lines), "src_functions": len(funcs), "src_loops": loops, "src_max_loop_depth": depth,
        "src_branches": branches, "src_array_accesses": arr, "src_fp_tokens": fp, "src_calls": calls,
        "src_log_max_literal": math.log10(max(lits)) if lits and max(lits) > 0 else 0.0,
        "src_has_recursion": recursion, "_function_names": funcs,
    }


def loop_structure(code: str) -> tuple[int, int]:
    """(loop count, max nesting depth) via a brace/statement stack. Heuristic: handles braced and single-statement
    loop bodies and ignores the `while` that terminates do-while."""
    n, i = len(code), 0
    stack: list[str] = []  # 'B' loop brace, 'b' other brace, 'S' braceless loop statement
    loops = maxd = 0
    depth = lambda: sum(1 for s in stack if s in "BS")
    paren = 0
    while i < n:
        c = code[i]
        m = re.match(r"(for|while)\b", code[i:]) if c in "fw" and (i == 0 or not (code[i - 1].isalnum() or code[i - 1] == "_")) else None
        if m:
            j = i + len(m.group(1))
            while j < n and code[j].isspace():
                j += 1
            if j < n and code[j] == "(":
                d, k = 0, j
                while k < n:
                    d += (code[k] == "(") - (code[k] == ")")
                    k += 1
                    if d == 0:
                        break
                tail = code[k:].lstrip()
                prev = code[:i].rstrip()
                if m.group(1) == "while" and prev.endswith("}") and tail.startswith(";"):
                    i = k
                    continue  # do { } while (...);
                loops += 1
                if tail.startswith("{"):
                    stack.append("B")
                    i = code.index("{", k) + 1
                else:
                    stack.append("S")
                    i = k
                maxd = max(maxd, depth())
                continue
        if c == "{":
            stack.append("b")
        elif c == "}":
            if stack:
                stack.pop()
            while stack and stack[-1] == "S":
                stack.pop()
        elif c == "(":
            paren += 1
        elif c == ")":
            paren = max(0, paren - 1)
        elif c == ";" and paren == 0:
            while stack and stack[-1] == "S":
                stack.pop()
        i += 1
    return loops, maxd


_ARITH_INT = {"add", "sub", "mul", "sdiv", "udiv", "srem", "urem", "shl", "lshr", "ashr", "and", "or", "xor", "icmp"}
_ARITH_FP = {"fadd", "fsub", "fmul", "fdiv", "frem", "fneg", "fcmp"}
_CAST = {"sext", "zext", "trunc", "bitcast", "fptosi", "fptoui", "sitofp", "uitofp", "fpext", "fptrunc", "ptrtoint",
         "inttoptr", "addrspacecast"}
_LABEL_RE = re.compile(r"^([\w.$-]+|\"[^\"]+\"):(\s*;.*)?$")


def ir_features(ll_text: str, loops_text: str = "") -> dict:
    counts = dict.fromkeys(["instr", "bb", "load", "store", "gep", "call", "intrinsic_call", "fp", "int", "cond_br",
                            "uncond_br", "phi", "vec", "alloca", "cast", "select", "switch", "ret", "functions"], 0)
    in_fn = False
    for raw in ll_text.splitlines():
        line = raw.rstrip()
        if line.startswith("define "):
            in_fn = True
            counts["functions"] += 1
            counts["bb"] += 1  # entry block has no label line
            continue
        if line.startswith("}"):
            in_fn = False
            continue
        if not in_fn:
            continue
        s = line.strip()
        if not s or s.startswith(";"):
            continue
        if _LABEL_RE.match(s):
            counts["bb"] += 1
            continue
        body = s.split("=", 1)[1].strip() if re.match(r"^%[\w.$-]+\s*=", s) else s
        body = re.sub(r"^(tail|musttail|notail)\s+", "", body)
        op = body.split(None, 1)[0] if body else ""
        counts["instr"] += 1
        if re.search(r"<\d+ x ", s):
            counts["vec"] += 1
        if op == "load":
            counts["load"] += 1
        elif op == "store":
            counts["store"] += 1
        elif op == "getelementptr":
            counts["gep"] += 1
        elif op == "call":
            if "@llvm." in body.split("(")[0] or " @llvm." in body:
                counts["intrinsic_call"] += 1
            else:
                counts["call"] += 1
        elif op in _ARITH_FP:
            counts["fp"] += 1
        elif op in _ARITH_INT:
            counts["int"] += 1
        elif op == "br":
            counts["cond_br" if body.startswith("br i1") else "uncond_br"] += 1
        elif op == "phi":
            counts["phi"] += 1
        elif op == "alloca":
            counts["alloca"] += 1
        elif op in _CAST:
            counts["cast"] += 1
        elif op == "select":
            counts["select"] += 1
        elif op == "switch":
            counts["switch"] += 1
        elif op == "ret":
            counts["ret"] += 1
    depths = [int(m.group(1)) for m in re.finditer(r"Loop at depth (\d+)", loops_text)]
    return {
        "ir_instr": counts["instr"], "ir_bb": counts["bb"], "ir_loops": len(depths),
        "ir_max_loop_depth": max(depths) if depths else 0, "ir_loads": counts["load"], "ir_stores": counts["store"],
        "ir_gep": counts["gep"], "ir_calls": counts["call"], "ir_fp_ops": counts["fp"], "ir_int_ops": counts["int"],
        "ir_cond_br": counts["cond_br"], "ir_phi": counts["phi"], "ir_vec_instr": counts["vec"],
        "_ir_detail": counts,
    }


def extract(source: str, language: str, ir_text: str | None, loops_text: str = "") -> dict:
    feats = source_features(source, language)
    if ir_text:
        feats.update(ir_features(ir_text, loops_text))
        feats["_ir_available"] = True
    else:
        feats["_ir_available"] = False
    n = max(feats.get("ir_instr", 0), 1)
    bb = max(feats.get("ir_bb", 0), 1)
    feats["ratio_branch"] = feats.get("ir_cond_br", 0) / n
    feats["ratio_mem"] = (feats.get("ir_loads", 0) + feats.get("ir_stores", 0)) / n
    feats["ratio_fp"] = feats.get("ir_fp_ops", 0) / n
    feats["ratio_call"] = feats.get("ir_calls", 0) / n
    feats["ratio_loop_bb"] = feats.get("ir_loops", 0) / bb
    return feats


def ir_for_features(unopt_ll: Path, out_ll: Path) -> tuple[str | None, str, str | None]:
    """Run mem2reg+loop-simplify with loop printing. Returns (ir_text, loops_text, error)."""
    from ..compiler import detection
    from ..compiler.process import run

    opt = detection.tool_path("opt")
    if not opt:
        return None, "", "opt not installed: LLVM IR features unavailable"
    r = run([opt, "-passes=function(mem2reg,loop-simplify),print<loops>", "-S", str(unopt_ll), "-o", str(out_ll)],
            cwd=unopt_ll.parent, timeout=60)
    if not r.ok and r.returncode != 0:
        return None, "", r.stderr_text[:500]
    try:
        return out_ll.read_text(errors="replace"), r.stderr_text, None
    except OSError as exc:
        return None, "", str(exc)


def vectorize(feats: dict) -> list[float]:
    """Fixed-order numeric vector (missing -> 0, counts -> log1p) shared by training and inference."""
    out = []
    for name in FEATURE_NAMES:
        v = feats.get(name, 0.0) or 0.0
        v = float(v)
        out.append(math.log1p(max(v, 0.0)) if name in _LOG_FEATURES else v)
    return out


def public_features(feats: dict) -> dict:
    return {k: v for k, v in feats.items() if not k.startswith("_")}
