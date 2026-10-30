"""Configuration registry: every candidate records the exact flags / pass pipeline it uses.
Pipelines are probed against the installed `opt`; unsupported ones are reported, never faked."""
from __future__ import annotations

import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import detection
from .compilation import clang_for, pass_names, validate_flags
from .process import run

BASELINE_ID = "O0"
REFERENCE_LEVELS = ["O1", "O2", "O3"]  # always evaluated: they are the conventional comparison points


@dataclass(frozen=True)
class Strategy:
    id: str
    name: str
    kind: str  # baseline | level | flags | ir_pipeline | source
    description: str
    flags: tuple[str, ...] = ()
    pipeline: str | None = None  # opt -passes= string for ir_pipeline
    source_transform: str | None = None  # key into source_transforms.TRANSFORMS
    semantics_preserving: bool = True

    def to_dict(self) -> dict:
        d = asdict(self)
        d["flags"] = list(self.flags)
        return d


STRATEGIES: list[Strategy] = [
    Strategy("O0", "Baseline (-O0)", "baseline", "No optimisation; reference for correctness and speedup.", ("-O0",)),
    Strategy("O1", "Clang -O1", "level", "Basic scalar optimisation (inlining of trivial functions, SROA, CSE, DCE).", ("-O1",)),
    Strategy("O2", "Clang -O2", "level", "Standard pipeline: GVN, LICM, loop vectorisation, SLP, inlining.", ("-O2",)),
    Strategy("O3", "Clang -O3", "level", "O2 plus more aggressive inlining and unrolling.", ("-O3",)),
    Strategy("Os", "Clang -Os", "level", "Optimise for code size while keeping most O2 transformations.", ("-Os",)),
    Strategy("O2-novec", "-O2 without vectorisation", "flags",
             "O2 with loop and SLP vectorisation disabled; helps where vector code is slower or bigger.",
             ("-O2", "-fno-vectorize", "-fno-slp-vectorize")),
    Strategy("O3-unroll", "-O3 with forced unrolling", "flags",
             "O3 plus -funroll-loops (runtime/partial unrolling of loops).", ("-O3", "-funroll-loops")),
    Strategy("O2-inline", "-O2 with aggressive inlining", "flags",
             "O2 with inline threshold raised to 1000 (inlining expands call-heavy code).",
             ("-O2", "-mllvm", "-inline-threshold=1000")),
    Strategy("ir-scalar", "IR: scalar clean-up pipeline", "ir_pipeline",
             "Hand-picked LLVM passes on O0 IR (mem2reg, SCCP, InstCombine, EarlyCSE, ADCE, SimplifyCFG), then llc -O2.",
             pipeline="function(mem2reg,sccp,instcombine,early-cse,adce,simplifycfg,instcombine)"),
    Strategy("ir-loop", "IR: loop optimisation pipeline", "ir_pipeline",
             "mem2reg, InstCombine, loop canonicalisation, LICM, loop strength reduction, full/partial unroll, GVN, DCE.",
             pipeline="function(mem2reg,instcombine,simplifycfg,loop-simplify,lcssa,loop-mssa(licm),loop-rotate,"
                      "loop-mssa(loop-reduce),loop-unroll,instcombine,gvn,adce,simplifycfg)"),
    Strategy("ir-inline-gvn", "IR: inlining + GVN pipeline", "ir_pipeline",
             "mem2reg, call-graph inliner, then InstCombine, GVN, ADCE and SimplifyCFG.",
             pipeline="function(mem2reg),cgscc(inline),function(instcombine,gvn,adce,simplifycfg)"),
    Strategy("ir-vector", "IR: vectorisation pipeline", "ir_pipeline",
             "Canonicalise loops, then LoopVectorize and SLP vectoriser with clean-up (vectorisation as its own strategy).",
             pipeline="function(mem2reg,sroa,instcombine,simplifycfg,loop-simplify,lcssa,loop-rotate,indvars,"
                      "loop-vectorize,slp-vectorizer,instcombine,simplifycfg,adce)"),
    Strategy("src-loop-hints", "Source: loop pragmas + -O2", "source",
             "Token-aware source rewrite inserting `#pragma clang loop vectorize/interleave/unroll_count` hints "
             "before every top-level for-loop, compiled with -O2. Hints never change semantics.",
             flags=("-O2",), source_transform="loop_pragmas"),
]

_BY_ID = {s.id: s for s in STRATEGIES}

TECHNIQUES = {
    "Constant folding": {"instcombine", "sccp", "ipsccp", "early-cse"},
    "Constant propagation": {"sccp", "ipsccp", "correlated-propagation"},
    "Dead-code elimination": {"dce", "adce", "bdce", "globaldce", "dse"},
    "Common-subexpression elimination": {"early-cse", "gvn", "newgvn"},
    "Copy propagation": {"mem2reg", "sroa", "gvn"},
    "Loop-invariant code motion": {"licm"},
    "Loop unrolling": {"loop-unroll", "loop-unroll-full"},
    "Loop vectorisation": {"loop-vectorize", "slp-vectorizer"},
    "Function inlining": {"inline", "inliner-wrapper"},
    "Strength reduction": {"loop-reduce", "indvars"},
}


def get(strategy_id: str) -> Strategy | None:
    return _BY_ID.get(strategy_id)


def techniques_from_passes(passes_text: str) -> list[str]:
    names = pass_names(passes_text)
    if re.search(r"loop-vectorize<[^>]*(?<!no-)vectorize-forced-only", passes_text):
        names.discard("loop-vectorize")  # vectorizer only runs on loops carrying explicit pragmas
    return [t for t, needed in TECHNIQUES.items() if names & needed]


_flag_pipeline_cache: dict[tuple, str] = {}


def flags_pipeline(language: str, flags: tuple[str, ...]) -> str:
    """Exact pass pipeline clang builds for these flags (via -mllvm -print-pipeline-passes)."""
    key = (language, flags)
    if key in _flag_pipeline_cache:
        return _flag_pipeline_cache[key]
    text = ""
    try:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / ("t.cpp" if language == "cpp" else "t.c")
            src.write_text("int f(int a){return a+1;}\n")
            cmd = [clang_for(language), *validate_flags(list(flags)), "-mllvm", "-print-pipeline-passes", "-c",
                   str(src), "-o", str(Path(td) / "t.o")]
            r = run(cmd, cwd=td, timeout=30)
            text = (r.stdout_text + r.stderr_text).strip().splitlines()[0] if (r.stdout_text + r.stderr_text).strip() else ""
    except Exception:
        text = ""
    _flag_pipeline_cache[key] = text
    return text


def availability(strategy: Strategy, language: str) -> tuple[bool, str]:
    d = detection.detect()
    if language == "cpp" and not d["can_compile_cpp"]:
        return False, "clang++ not installed"
    if language == "c" and not d["can_compile_c"]:
        return False, "clang not installed"
    if strategy.kind == "ir_pipeline":
        if not d["can_use_ir_pipelines"]:
            return False, "opt/llc not installed"
        ok, why = detection.probe_pipeline(strategy.pipeline or "")
        if not ok:
            return False, f"pass pipeline unsupported by this LLVM ({why})"
    return True, ""


def available_strategies(language: str) -> tuple[list[Strategy], dict[str, str]]:
    ok, skipped = [], {}
    for s in STRATEGIES:
        good, why = availability(s, language)
        if good:
            ok.append(s)
        else:
            skipped[s.id] = why
    return ok, skipped
