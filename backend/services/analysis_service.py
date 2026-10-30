"""Shared analysis steps used both by POST /api/analyze and by the optimisation pipeline."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from ..analysis import complexity as cx
from ..analysis import diagnostics as dg
from ..analysis import features as ft
from ..compiler import compilation as cc
from ..compiler import detection
from ..compiler.process import run
from ..config import settings
from .candidates import REMARK_FLAGS


def check_syntax(src: Path, language: str) -> tuple[bool, list[dict], str]:
    step = cc.syntax_check(src, language)
    diags = dg.parse_diagnostics(step.stderr)
    ok = step.ok and not any(d["severity"] == "error" for d in diags)
    return ok, diags, step.stderr if not ok else ""


def vectorization_remarks(src: Path, language: str, flags=("-O3",)) -> list[dict]:
    cmd = [cc.clang_for(language), *cc._lang_flags(language, list(flags)), *REMARK_FLAGS, "-c", str(src), "-o", str(src.parent / "remarks.o")]
    r = run(cmd, cwd=src.parent, timeout=settings.compile_timeout_s)
    try:
        (src.parent / "remarks.o").unlink()
    except OSError:
        pass
    return cc.parse_remarks(r.stderr_text)


def ir_instr_count(src: Path, language: str, flags: list[str], out: Path) -> int | None:
    step = cc.emit_ir(src, language, flags, out)
    if not step.ok:
        return None
    return ft.ir_features(out.read_text(errors="replace"))["ir_instr"]


def compute_features(src: Path, language: str, unopt_ll: Path | None, work: Path) -> tuple[dict, list[str]]:
    notes: list[str] = []
    ir_text, loops_text = None, ""
    if unopt_ll is not None:
        ir_text, loops_text, err = ft.ir_for_features(unopt_ll, work / "features.ll")
        if err:
            notes.append(f"IR features unavailable: {err}")
    else:
        notes.append("LLVM IR features unavailable (no IR); using source-level heuristics only.")
    feats = ft.extract(src.read_text(encoding="utf-8"), language, ir_text, loops_text)
    return feats, notes


def build_analysis(source: str, language: str, filename: str | None, feats: dict, diags: list[dict], remarks: list[dict],
                   warnings: list[str], ir_ok: bool, o0_instr: int | None, o2_instr: int | None, compile_ok: bool) -> dict:
    d = detection.detect()
    detail = feats.get("_ir_detail") or {}
    return {
        "language": language, "filename": filename,
        "compiler_version": d["clang_version"], "llvm_version": d["llvm_version"],
        "compilation_status": "ok" if compile_ok else "error",
        "source_lines": len(source.splitlines()),
        "features": ft.public_features(feats),
        "feature_schema_version": ft.FEATURE_SCHEMA_VERSION,
        "ir_stats": detail, "ir_available": bool(ir_ok),
        "loops": {"source_count_heuristic": feats.get("src_loops"), "source_max_depth_heuristic": feats.get("src_max_loop_depth"),
                  "ir_count": feats.get("ir_loops") if ir_ok else None, "ir_max_depth": feats.get("ir_max_loop_depth") if ir_ok else None},
        "metric_provenance": {"src_*": "lexer-based heuristic (estimate)", "ir_*": "LLVM IR after mem2reg / opt print<loops> (compiler-derived)"},
        "vectorization_remarks": remarks,
        "o0_ir_instructions": o0_instr, "o2_ir_instructions": o2_instr,
        "opportunities": dg.opportunities(ft.public_features(feats), remarks, o0_instr, o2_instr),
        "diagnostics": diags, "warnings": warnings,
        "complexity": cx.estimate(source, feats),
    }


def analyze_source(source: str, language: str, filename: str | None = None) -> dict:
    """Standalone analysis for POST /api/analyze (no benchmarking, no ML)."""
    language, warnings = dg.validate_source(source, language, filename)
    work = Path(tempfile.mkdtemp(prefix="an-", dir=settings.work_dir))
    try:
        src = work / cc.source_filename(language)
        src.write_text(source, encoding="utf-8")
        ok, diags, _ = check_syntax(src, language)
        if not ok:
            return {"language": language, "filename": filename, "compilation_status": "error", "diagnostics": diags,
                    "compiler_version": detection.detect()["clang_version"], "warnings": warnings,
                    "source_lines": len(source.splitlines())}
        unopt = work / "unopt.ll"
        ir_ok = False
        if cc.emit_unoptimized_ir(src, language, unopt).ok:
            v = cc.verify_ir(unopt)
            ir_ok = v.ok or v.error == "opt not installed"
            if v.error == "opt not installed":
                warnings.append("opt not installed: IR verification skipped.")
        feats, notes = compute_features(src, language, unopt if ir_ok else None, work)
        warnings += notes
        remarks = vectorization_remarks(src, language)
        o0 = feats.get("_ir_detail", {}).get("instr") if ir_ok else None
        o2 = ir_instr_count(src, language, ["-O2"], work / "o2.ll")
        return build_analysis(source, language, filename, feats, diags, remarks, warnings, ir_ok, o0, o2, True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
