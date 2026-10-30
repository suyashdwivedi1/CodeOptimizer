import threading
import time

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..ml import predict, train
from ..schemas import TrainRequest

router = APIRouter(prefix="/api/ml", tags=["ml"])

_job: dict = {"state": "idle"}
_job_lock = threading.Lock()


@router.get("/status")
def ml_status():
    st = predict.status()
    st["training_job"] = dict(_job)
    return st


@router.get("/metrics")
def ml_metrics():
    b = predict.load_model()
    if not b or "_error" in b:
        raise HTTPException(404, detail={"code": "model_missing", "message": "No trained model. Run training first.",
                                          "train_command": "python -m backend.ml.train --data-dir data/benchmarks --output-dir artifacts"})
    return {"version": b["version"], "trained_at": b["trained_at"], "model_type": b["model_type"], "toolchain": b.get("toolchain"),
            "dataset_size": b["dataset_size"], "n_programs": b.get("n_programs"), "training_mode": b.get("training_mode"),
            "feature_schema_version": b["feature_schema_version"], "feature_names": b["feature_names"], "strategy_ids": b["strategy_ids"],
            "feature_importances": b["feature_importances"], "permutation_importances_train": b.get("permutation_importances_train"),
            "metrics": b["metrics"]}


@router.post("/train", status_code=202)
def start_training(req: TrainRequest):
    with _job_lock:
        if _job.get("state") == "running":
            raise HTTPException(409, detail={"code": "training_running", "message": "A training job is already running."})
        _job.clear()
        _job.update(state="running", stage="starting", done=0, total=1, message="", started=time.time(), mode=req.mode)

    def progress(stage, i, n, msg):
        _job.update(stage=stage, done=i, total=n, message=msg)

    def work():
        try:
            b = train.run_training(settings.benchmarks_dir, settings.artifacts_dir, settings.processed_dir, req.mode, req.reps,
                                   req.skip_collect, progress)
            _job.update(state="completed", message=f"Model {b['version']} trained", version=b["version"], finished=time.time())
        except Exception as exc:
            _job.update(state="failed", error=f"{type(exc).__name__}: {exc}", finished=time.time())

    threading.Thread(target=work, name="train", daemon=True).start()
    return {"state": "running", "status_url": "/api/ml/status"}
