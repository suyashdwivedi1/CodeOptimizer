"""Model loading, inference, ranking and explanation. Never raises when the model is missing."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import joblib
import numpy as np

from ..analysis.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, vectorize
from ..config import settings
from ..compiler import passes as reg

_lock = threading.Lock()
_cached: dict | None = None
_cached_mtime: float | None = None

# Order used when no trained model exists: a conventional, documented default — NOT an ML prediction.
FALLBACK_ORDER = ["O2", "O3", "O3-unroll", "O2-novec", "Os", "ir-vector", "src-loop-hints", "O2-inline",
                  "ir-loop", "ir-inline-gvn", "ir-scalar", "O1"]


def load_model(force: bool = False) -> dict | None:
    global _cached, _cached_mtime
    path = settings.model_path
    with _lock:
        if not path.exists():
            _cached, _cached_mtime = None, None
            return None
        mtime = path.stat().st_mtime
        if _cached is not None and _cached_mtime == mtime and not force:
            return _cached
        try:
            bundle = joblib.load(path)
            if bundle.get("feature_schema_version") != FEATURE_SCHEMA_VERSION or bundle.get("feature_names") != FEATURE_NAMES:
                bundle["_incompatible"] = True
            _cached, _cached_mtime = bundle, mtime
        except Exception as exc:  # corrupted / incompatible pickle
            _cached, _cached_mtime = {"_error": f"{type(exc).__name__}: {exc}"}, mtime
        return _cached


def status() -> dict:
    b = load_model()
    if b is None:
        return {"state": "not_trained", "label": "Model not trained — baseline mode", "available": False,
                "train_command": "python -m backend.ml.train --data-dir data/benchmarks --output-dir artifacts"}
    if "_error" in b:
        return {"state": "error", "label": "Model file unreadable — baseline mode", "available": False, "error": b["_error"],
                "train_command": "python -m backend.ml.train --data-dir data/benchmarks --output-dir artifacts"}
    if b.get("_incompatible"):
        return {"state": "incompatible", "label": "Model feature schema mismatch — retrain", "available": False,
                "train_command": "python -m backend.ml.train --data-dir data/benchmarks --output-dir artifacts"}
    return {"state": "ready", "label": f"Trained model {b['version']}", "available": True, "version": b["version"],
            "trained_at": b["trained_at"], "model_type": b["model_type"], "dataset_size": b["dataset_size"],
            "n_programs": b.get("n_programs"), "feature_schema_version": b["feature_schema_version"],
            "feature_names": b["feature_names"], "strategy_ids": b["strategy_ids"], "training_mode": b.get("training_mode"),
            "metrics": b.get("metrics")}


def predict(feats: dict, available_ids: list[str]) -> dict:
    """Rank `available_ids` best-first. Returns source='trained-model' only when the real model produced the ranking."""
    t0 = time.perf_counter()
    b = load_model()
    usable = b is not None and "_error" not in b and not b.get("_incompatible")
    if not usable:
        order = [s for s in FALLBACK_ORDER if s in available_ids] + [s for s in available_ids if s not in FALLBACK_ORDER]
        order = [s for s in order if s != reg.BASELINE_ID]
        return {"source": "fallback-default-order", "model_version": None, "is_ml": False,
                "note": "No usable trained model: candidates were ordered by a fixed default list. This is NOT an ML prediction.",
                "ranking": [{"strategy_id": s, "rank": i + 1, "predicted_rel_time": None, "score": None}
                            for i, s in enumerate(order)],
                "top_pick": order[0] if order else None, "inference_ms": (time.perf_counter() - t0) * 1000,
                "explanation": None}
    x = np.array([vectorize(feats)], dtype=float)
    model = b["model"]
    per_tree = np.array([t.predict(x)[0] for t in model.estimators_])  # (n_trees, n_strategies) log(time_s / time_O2)
    mean, std = per_tree.mean(axis=0), per_tree.std(axis=0)
    ids = b["strategy_ids"]
    rows = []
    for j, sid in enumerate(ids):
        if sid in available_ids and sid != reg.BASELINE_ID:
            rows.append({"strategy_id": sid, "predicted_rel_time": float(np.exp(mean[j])), "spread": float(std[j]),
                         "score": float(-mean[j])})
    rows.sort(key=lambda r: r["predicted_rel_time"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return {"source": "trained-model", "is_ml": True, "model_version": b["version"],
            "note": ("Scores are model-predicted run time relative to -O2 (1.0 = same as O2, lower = faster). They are "
                     "regression outputs, not calibrated probabilities; 'spread' is the std-dev across the forest's trees."),
            "ranking": rows, "top_pick": rows[0]["strategy_id"] if rows else None,
            "inference_ms": (time.perf_counter() - t0) * 1000, "explanation": explain(b, feats)}


def explain(b: dict, feats: dict, top: int = 8) -> dict:
    """Global RandomForest feature importances combined with this program's values vs the training median.
    Importance describes what the model relies on overall; it is not a causal explanation of this prediction."""
    imps = b.get("feature_importances", {})
    med = b.get("feature_medians", {})
    vec = dict(zip(FEATURE_NAMES, vectorize(feats)))
    rows = []
    for name, imp in sorted(imps.items(), key=lambda kv: -kv[1])[:top]:
        v = vec.get(name, 0.0)
        m = med.get(name)
        rows.append({"feature": name, "importance": float(imp), "value": float(feats.get(name, 0.0) or 0.0),
                     "model_value": float(v), "training_median": m,
                     "relative": None if m is None else ("above" if v > m * 1.05 + 1e-9 else "below" if v < m * 0.95 - 1e-9 else "near")})
    return {"method": "RandomForest impurity importances (global) + this program's value vs training median",
            "caveat": "Feature importance indicates reliance of the model, not causation.", "top_features": rows}
