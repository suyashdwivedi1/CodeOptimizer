from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from ..analysis import diagnostics as dg
from ..compiler import detection
from ..schemas import OptimizeRequest, OptimizeResponse
from ..services import optimization_service as svc

router = APIRouter(prefix="/api", tags=["optimize"])


@router.post("/optimize", response_model=OptimizeResponse, status_code=202)
async def optimize(req: OptimizeRequest):
    d = detection.detect()
    if not (d["can_compile_cpp"] if req.language == "cpp" else d["can_compile_c"]):
        raise HTTPException(503, detail={"code": "compiler_missing", "message": "; ".join(d["problems"]) or "Compiler not found"})
    try:
        exp_id = await run_in_threadpool(svc.create_experiment, source=req.source, language=req.language, filename=req.filename,
                                         label=req.label, stdin=req.stdin, mode=req.mode, repetitions=req.repetitions,
                                         use_ml=req.use_ml)
    except dg.ValidationError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": str(exc)})
    return OptimizeResponse(experiment_id=exp_id, events_url=f"/api/experiments/{exp_id}/events",
                            results_url=f"/api/experiments/{exp_id}/results")
