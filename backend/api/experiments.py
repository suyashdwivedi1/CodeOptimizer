import asyncio
import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, or_, select

from ..compiler import compilation as cc
from ..config import settings
from ..database import session_scope
from ..models import Experiment, Variant
from ..compiler import passes as reg
from ..schemas import WhatIfRequest
from ..services import optimization_service as svc
from ..services import progress_service as ps

router = APIRouter(prefix="/api/experiments", tags=["experiments"])
ACTIVE = ("queued", "running")


def _err(status: int, code: str, msg: str):
    return HTTPException(status, detail={"code": code, "message": msg})


def ser_variant(v: Variant, with_samples: bool = True) -> dict:
    d = {c: getattr(v, c) for c in ("id", "experiment_id", "strategy_id", "name", "kind", "is_baseline", "description", "flags",
                                    "pipeline", "techniques", "compile_status", "correctness_status", "failure_reason", "binary_size",
                                    "peak_rss_kb", "median_ms", "mean_ms", "stdev_ms", "iqr_ms", "min_ms", "max_ms", "benchmark_count",
                                    "speedup", "time_reduction_pct", "compile_time_ms", "opt_time_ms", "duplicate_of", "ml_selected",
                                    "ml_score", "ml_rank", "is_winner", "below_threshold", "added_via_whatif", "remarks", "warnings")}
    d["has_source"] = bool(v.source_path) or v.is_baseline
    d["source_kind"] = "transformed" if v.source_path else ("original" if v.is_baseline else None)
    d["has_ir"] = True
    d["applied_passes"] = (v.applied_passes or [])[:400]
    d["samples_ms"] = v.samples_ms if with_samples else None
    return d


def ser_experiment(e: Experiment, full: bool = False) -> dict:
    d = {c: getattr(e, c) for c in ("id", "language", "filename", "label", "compiler_version", "llvm_version", "status",
                                    "error_summary", "mode", "repetitions", "warmup", "ml_model_version", "ml_source",
                                    "selected_strategy", "best_variant_id", "winner_status", "baseline_median_ms", "best_median_ms",
                                    "duration_ms", "source_hash")}
    d["created_at"] = e.created_at.isoformat() if e.created_at else None
    d["finished_at"] = e.finished_at.isoformat() if e.finished_at else None
    best = next((v for v in e.variants if v.id == e.best_variant_id), None)
    d["best_strategy"] = best.strategy_id if best else None
    d["best_speedup"] = best.speedup if best else None
    if full:
        d.update(source=e.source_text, stdin=e.stdin_text, analysis=e.analysis, ml_prediction=e.ml_prediction,
                 complexity=e.complexity, report=e.report, variants=[ser_variant(v) for v in e.variants])
    return d


def _get(s, exp_id: str) -> Experiment:
    e = s.get(Experiment, exp_id)
    if e is None:
        raise _err(404, "not_found", f"Experiment {exp_id} not found")
    return e


@router.get("")
def list_experiments(limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0), status: str | None = None,
                     language: str | None = None, q: str | None = None,
                     sort: str = Query("created_desc", pattern="^(created_desc|created_asc|speedup_desc|baseline_desc)$")):
    with session_scope() as s:
        stmt = select(Experiment)
        if status:
            stmt = stmt.where(Experiment.status == status)
        if language:
            stmt = stmt.where(Experiment.language == language)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(Experiment.label.ilike(like), Experiment.filename.ilike(like), Experiment.id.ilike(like),
                                  Experiment.selected_strategy.ilike(like)))
        total = s.scalar(select(func.count()).select_from(stmt.subquery()))
        order = {"created_desc": Experiment.created_at.desc(), "created_asc": Experiment.created_at.asc(),
                 "baseline_desc": Experiment.baseline_median_ms.desc()}.get(sort)
        if sort == "speedup_desc":
            order = (Experiment.baseline_median_ms / Experiment.best_median_ms).desc()
        rows = s.scalars(stmt.order_by(order).limit(limit).offset(offset)).all()
        return {"total": total, "limit": limit, "offset": offset, "items": [ser_experiment(e) for e in rows]}


@router.get("/{exp_id}")
def get_experiment(exp_id: str):
    with session_scope() as s:
        e = _get(s, exp_id)
        d = ser_experiment(e)
        d["variant_count"] = len(e.variants)
        return d


@router.get("/{exp_id}/results")
def get_results(exp_id: str):
    with session_scope() as s:
        return ser_experiment(_get(s, exp_id), full=True)


@router.delete("/{exp_id}", status_code=204)
def delete_experiment(exp_id: str):
    with session_scope() as s:
        e = _get(s, exp_id)
        if e.status in ACTIVE:
            raise _err(409, "experiment_active", "Cancel the running experiment before deleting it.")
        s.delete(e)
    ps.forget(exp_id)
    shutil.rmtree(settings.experiments_dir / exp_id, ignore_errors=True)
    return Response(status_code=204)


@router.post("/{exp_id}/cancel")
def cancel(exp_id: str):
    with session_scope() as s:
        _get(s, exp_id)
    if not ps.request_cancel(exp_id):
        raise _err(409, "not_cancellable", "Experiment is not running.")
    return {"status": "cancelling"}


# ------------------------------------------------------------------ SSE
@router.get("/{exp_id}/events")
async def events(exp_id: str, after: int = 0, last_event_id: str | None = Header(None)):
    with session_scope() as s:
        _get(s, exp_id)
    try:
        start = max(after, int(last_event_id)) if last_event_id else after
    except ValueError:
        start = after

    async def gen():
        seen, idle = start, 0.0
        yield "retry: 2000\n\n"
        while True:
            evs, terminal = ps.events_after(exp_id, seen)
            for e in evs:
                seen = e["seq"]
                yield f"id: {e['seq']}\nevent: progress\ndata: {json.dumps(e)}\n\n"
                idle = 0.0
            if terminal and not evs:
                return
            if not evs:
                # experiment known to DB but with no live bus/events (e.g. killed server): do not hang forever
                with session_scope() as s:
                    e = s.get(Experiment, exp_id)
                    if e and e.status not in ACTIVE and not terminal:
                        yield f"event: progress\ndata: {json.dumps({'seq': seen + 1, 'experiment_id': exp_id, 'stage': 'experiment', 'status': e.status, 'message': e.error_summary or 'finished', 'data': {}})}\n\n"
                        return
                idle += 0.25
                if idle >= 15:
                    yield ": keep-alive\n\n"
                    idle = 0.0
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


# ------------------------------------------------------------------ variant artefacts
def _variant(s, exp_id: str, variant_id: int) -> tuple[Experiment, Variant]:
    e = _get(s, exp_id)
    v = s.get(Variant, variant_id)
    if v is None or v.experiment_id != exp_id:
        raise _err(404, "not_found", "Variant not found in this experiment")
    return e, v


def _safe(path: str | None, exp_id: str) -> Path | None:
    if not path:
        return None
    p = Path(path).resolve()
    root = (settings.experiments_dir / exp_id).resolve()
    return p if root in p.parents and p.is_file() else None


def _source_for(e: Experiment, v: Variant) -> tuple[str, str] | None:
    p = _safe(v.source_path, e.id)
    if p:
        return p.read_text(encoding="utf-8"), "transformed"
    if v.is_baseline:
        return e.source_text, "original"
    return None


@router.get("/{exp_id}/variants/{variant_id}/source")
def variant_source(exp_id: str, variant_id: int):
    with session_scope() as s:
        e, v = _variant(s, exp_id, variant_id)
        got = _source_for(e, v)
        if got is None:
            raise _err(404, "no_source_artifact",
                       f"'{v.strategy_id}' is a compiler-level variant: LLVM transforms it internally and no transformed C/C++ source "
                       "exists. See the LLVM IR tab for the optimised program.")
        return {"variant_id": v.id, "strategy_id": v.strategy_id, "kind": got[1], "language": e.language, "source": got[0]}


@router.get("/{exp_id}/variants/{variant_id}/download")
def variant_download(exp_id: str, variant_id: int, kind: str = Query("source", pattern="^(source|ir)$")):
    with session_scope() as s:
        e, v = _variant(s, exp_id, variant_id)
        if kind == "ir":
            text = _ir_text(e, v)
            return Response(text, media_type="text/plain; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{e.id}_{v.strategy_id}.ll"'})
        got = _source_for(e, v)
        if got is None:
            raise _err(404, "no_source_artifact", "This variant has no source artifact; download the LLVM IR instead (?kind=ir).")
        ext = ".cpp" if e.language == "cpp" else ".c"
        return Response(got[0], media_type="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{e.id}_{v.strategy_id}{ext}"'})


def _ir_text(e: Experiment, v: Variant) -> str:
    p = _safe(v.ir_path, e.id)
    if p is None:
        strat = reg.get(v.strategy_id)
        root = settings.experiments_dir / e.id
        d = root / "variants" / v.strategy_id
        d.mkdir(parents=True, exist_ok=True)
        src = d / cc.source_filename(e.language)
        got = _source_for(e, v)
        src.write_text(got[0] if got else e.source_text, encoding="utf-8")
        out = d / "emitted.ll"
        flags = list(v.flags or ["-O0"])
        if strat is not None and strat.kind == "ir_pipeline":
            raise _err(404, "ir_missing", "Optimised IR file for this pipeline variant is no longer on disk.")
        step = cc.emit_ir(src, e.language, flags, out)
        if not step.ok:
            raise _err(500, "ir_failed", step.reason()[:500])
        p = out
    data = p.read_text(errors="replace")
    return data[:2_000_000] + ("\n; ... truncated ...\n" if len(data) > 2_000_000 else "")


@router.get("/{exp_id}/variants/{variant_id}/ir")
async def variant_ir(exp_id: str, variant_id: int):
    def work():
        with session_scope() as s:
            e, v = _variant(s, exp_id, variant_id)
            return {"variant_id": v.id, "strategy_id": v.strategy_id, "ir": _ir_text(e, v),
                    "note": "Post-optimisation LLVM IR for this configuration" if v.id else ""}
    return await run_in_threadpool(work)


# ------------------------------------------------------------------ what-if
@router.get("/{exp_id}/whatif")
def whatif_options(exp_id: str):
    with session_scope() as s:
        e = _get(s, exp_id)
        measured = {v.strategy_id: v for v in e.variants}
        avail, skipped = reg.available_strategies(e.language)
        out = []
        for st in reg.STRATEGIES:
            v = measured.get(st.id)
            out.append({**st.to_dict(), "measured": bool(v and v.median_ms is not None), "variant_id": v.id if v else None,
                        "median_ms": v.median_ms if v else None, "speedup": v.speedup if v else None,
                        "duplicate_of": v.duplicate_of if v else None, "available": st.id not in skipped,
                        "unavailable_reason": skipped.get(st.id), "status": (v.compile_status if v else "unmeasured")})
        return {"experiment_id": exp_id, "baseline_median_ms": e.baseline_median_ms, "strategies": out}


@router.post("/{exp_id}/whatif")
async def whatif(exp_id: str, req: WhatIfRequest):
    with session_scope() as s:
        e = _get(s, exp_id)
        if e.status in ACTIVE:
            raise _err(409, "experiment_active", "Wait for the experiment to finish.")
        if e.status != "completed":
            raise _err(409, "experiment_failed", "Only completed experiments can be extended.")
    try:
        return await run_in_threadpool(svc.whatif_measure, exp_id, req.strategies)
    except ValueError as exc:
        raise _err(422, "unknown_strategy", str(exc))
    except RuntimeError as exc:
        raise _err(500, "whatif_failed", str(exc))
