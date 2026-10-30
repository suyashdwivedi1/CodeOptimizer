"""Heuristic algorithmic-complexity estimate. This is NOT a proof: it reads loop nesting and a few idioms."""
from __future__ import annotations

import re

from .features import code_only

SUP = {0: "1", 1: "n", 2: "n²", 3: "n³"}


def estimate(source: str, feats: dict) -> dict:
    code = code_only(source)
    depth = int(feats.get("src_max_loop_depth", 0))
    reasons: list[str] = []
    log_loop = bool(re.search(r"(?:/=\s*2\b|>>=\s*1\b|\*=\s*2\b|<<=\s*1\b|/\s*2\s*[;)])", code)) and feats.get("src_loops", 0) > 0
    sort_call = bool(re.search(r"\b(qsort|std::sort|std::stable_sort|sort)\s*\(", code))
    recursion = bool(feats.get("src_has_recursion"))
    time_est, conf = "Not determined", "none"
    if recursion:
        reasons.append("Recursive call detected; recurrences are not solved by this analysis.")
    elif sort_call:
        time_est, conf = "O(n log n)", "low"
        reasons.append("Library sort call detected (typically O(n log n)).")
    elif depth == 0:
        time_est, conf = "O(1)", "low"
        reasons.append("No loops or recursion found; straight-line code over fixed-size data.")
    else:
        base = SUP.get(depth, f"n^{depth}")
        if log_loop and depth == 1:
            time_est, conf = "O(log n)", "low"
            reasons.append("Single loop whose counter is halved/doubled (heuristic pattern match).")
        elif log_loop:
            time_est, conf = f"O({base} log n)", "low"
            reasons.append("Loop nest containing a halving/doubling counter (heuristic).")
        else:
            time_est, conf = f"O({base})", "low"
        reasons.append(f"Maximum loop nesting depth ≈ {depth}; n is the loop bound / input size.")
    arrays = bool(re.search(r"\b(malloc|calloc|realloc|new)\b|std::vector|\[\s*\w+\s*\]", code))
    space = "O(n)" if arrays else "O(1)"
    sreasons = ["Arrays/dynamic allocation present (size may be a constant)."] if arrays else ["No arrays or allocation found."]
    if recursion:
        space, sreasons = "Not determined", ["Recursion depth unknown."]
    return {
        "method": "static heuristic (loop nesting + idiom matching) — not a compiler proof",
        "time": {"estimate": time_est, "confidence": conf, "reasons": reasons},
        "space": {"estimate": space, "confidence": "low" if space != "Not determined" else "none", "reasons": sreasons},
        "note": ("Ordinary compiler optimisations change constant factors (instruction selection, vectorisation, "
                 "inlining, unrolling) but not the asymptotic class of the algorithm. A faster measured run does not "
                 "mean the complexity improved."),
    }
