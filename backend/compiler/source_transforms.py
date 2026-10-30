"""Source-level transformations. Only token-aware, semantics-preserving rewrites are implemented.

`loop_pragmas` scans the source with a small C/C++ lexer (so comments, string/char literals, raw strings and
preprocessor lines are never touched) and inserts a `#pragma clang loop ...` hint before each for-loop that is
not nested inside parentheses. Pragmas are optimisation hints: they cannot change program semantics (we do NOT use
`vectorize(assume_safety)`). The result is still compiled and checked against the baseline output."""
from __future__ import annotations

import re
from dataclasses import dataclass

PRAGMA = "#pragma clang loop vectorize(enable) interleave(enable) unroll_count(4)"


@dataclass
class TransformResult:
    source: str
    changes: int
    notes: list[str]


def _scan_code_spans(src: str):
    """Yield (index, char) for characters that are real code (not comment/string/char/preprocessor)."""
    i, n = 0, len(src)
    at_line_start = True
    while i < n:
        c = src[i]
        if c == "/" and src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == "\n":
            at_line_start = True
            yield i, c
            i += 1
            continue
        if at_line_start and c in " \t":
            yield i, c
            i += 1
            continue
        if at_line_start and c == "#":  # preprocessor directive with line continuations
            while i < n:
                j = src.find("\n", i)
                if j < 0:
                    i = n
                    break
                if src[j - 1] == "\\" or (j >= 2 and src[j - 2:j] == "\\\r"):
                    i = j + 1
                    continue
                i = j
                break
            continue
        at_line_start = False
        if c == "R" and src.startswith('R"', i) and (i == 0 or not (src[i - 1].isalnum() or src[i - 1] == "_")):
            m = re.match(r'R"([^()\\ ]{0,16})\(', src[i:])
            if m:
                end = src.find(")" + m.group(1) + '"', i + m.end())
                i = n if end < 0 else end + len(m.group(1)) + 2
                continue
        if c == '"' or c == "'":
            q, j = c, i + 1
            while j < n and src[j] != q:
                j += 2 if src[j] == "\\" else 1
            i = j + 1
            continue
        yield i, c
        i += 1


def loop_pragmas(src: str, language: str = "c") -> TransformResult:
    code = {}
    for idx, ch in _scan_code_spans(src):
        code[idx] = ch
    insert_at: list[int] = []
    depth_paren = 0
    n = len(src)
    i = 0
    while i < n:
        ch = code.get(i)
        if ch is None:
            i += 1
            continue
        if ch == "(":
            depth_paren += 1
        elif ch == ")":
            depth_paren = max(0, depth_paren - 1)
        elif ch == "f" and src.startswith("for", i) and depth_paren == 0:
            before_ok = i == 0 or not (src[i - 1].isalnum() or src[i - 1] == "_")
            after = src[i + 3] if i + 3 < n else ""
            after_ok = after == "" or not (after.isalnum() or after == "_")
            if before_ok and after_ok and all(i + k in code for k in range(3)):
                insert_at.append(i)
                i += 3
                continue
        i += 1
    if not insert_at:
        return TransformResult(src, 0, ["No for-loops found in code regions; nothing to transform."])
    out, last = [], 0
    for pos in insert_at:
        out.append(src[last:pos])
        out.append("\n" + PRAGMA + "\n")
        last = pos
    out.append(src[last:])
    return TransformResult("".join(out), len(insert_at),
                           [f"Inserted loop hints before {len(insert_at)} for-loop(s)."])


TRANSFORMS = {"loop_pragmas": loop_pragmas}
