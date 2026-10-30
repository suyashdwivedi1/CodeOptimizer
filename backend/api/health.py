from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text

from .. import __version__
from ..compiler import detection
from ..compiler import passes as reg
from ..config import settings
from ..database import engine
from ..ml import predict
from ..services import progress_service as ps

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health():
    db_ok = True
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    d = detection.detect()
    m = predict.status()
    return {"status": "ok" if db_ok else "degraded", "version": __version__, "time": datetime.now(timezone.utc).isoformat(),
            "database": "ok" if db_ok else "error", "compiler": {"available": d["can_compile_c"], "version": d["clang_version"],
                                                                  "cpp": d["can_compile_cpp"], "ir_pipelines": d["can_use_ir_pipelines"]},
            "ml": {"state": m["state"], "label": m["label"]}}


@router.get("/compiler/status")
def compiler_status(refresh: bool = False):
    d = detection.detect(refresh=refresh)
    out = {k: v for k, v in d.items() if k != "pass_support"}
    strategies = []
    for lang in ("c",):
        ok, skipped = reg.available_strategies(lang)
        strategies = [{**s.to_dict(), "available": s.id not in skipped, "unavailable_reason": skipped.get(s.id)} for s in reg.STRATEGIES]
    out["strategies"] = strategies
    out["limits"] = {"max_source_bytes": settings.max_source_bytes, "max_stdin_bytes": settings.max_stdin_bytes,
                     "run_timeout_s": settings.run_timeout_s, "compile_timeout_s": settings.compile_timeout_s,
                     "max_output_bytes": settings.max_output_bytes, "run_memory_limit_mb": settings.run_memory_limit_mb,
                     "quick_reps": settings.quick_reps, "rigorous_reps": settings.rigorous_reps,
                     "reliable_min_ms": settings.reliable_min_ms, "noise_tie_pct": settings.noise_tie_pct,
                     "max_candidates": settings.max_candidates}
    out["isolation_warning"] = ("Uploaded programs are compiled and executed natively on this machine. Timeouts, memory "
                                "limits and temp directories are NOT a security sandbox. Only run code you trust.")
    return out


@router.get("/pipeline/stages")
def stages():
    return [{"id": i, "label": l} for i, l in ps.STAGES]
