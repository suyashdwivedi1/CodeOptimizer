"""Generate the benchmark corpus, measure every strategy on every program, train and evaluate the model.

    python -m backend.ml.train --data-dir data/benchmarks --output-dir artifacts [--mode quick|full] [--skip-collect]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

from ..analysis.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, vectorize
from ..compiler import detection
from ..compiler import passes as reg
from ..config import settings
from . import dataset as ds
from .evaluation import cross_validate, make_model
from .explainability import importances

TRAIN_LOCK = threading.Lock()


def _read_csv(p: Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_matrices(processed: Path) -> dict:
    meas = _read_csv(processed / "measurements.csv")
    feats = {r["program_id"]: r for r in _read_csv(processed / "features.csv")}
    by_prog: dict[str, dict[str, dict]] = {}
    for r in meas:
        by_prog.setdefault(r["program_id"], {})[r["strategy_id"]] = r
    strategy_ids = [s.id for s in reg.STRATEGIES if s.id != reg.BASELINE_ID and any(s.id in p for p in by_prog.values())]
    ok_ids, X, Y, T, T0, C, groups, excluded = [], [], [], [], [], [], [], []
    for pid, rows in by_prog.items():
        def med(sid):
            r = rows.get(sid)
            return float(r["median_ms"]) if r and r["median_ms"] != "" else None
        t0, t2 = med("O0"), med("O2")
        if t0 is None or t2 is None:
            excluded.append((pid, "baseline or O2 not measured"))
            continue
        if t0 < settings.reliable_min_ms:
            excluded.append((pid, f"O0 runtime {t0:.2f} ms below the {settings.reliable_min_ms:g} ms reliability threshold"))
            continue
        y, t, c = [], [], []
        for sid in strategy_ids:
            m = med(sid)
            r = rows.get(sid)
            comp = float(r["compile_ms"]) if r and r["compile_ms"] not in ("", None) else np.nan
            if m is None:
                # not applicable (skipped) -> behaves like O2's code; incorrect -> penalised as unoptimised
                incorrect = bool(r and r["correctness"] == "failed")
                m = t0 if incorrect else t2
            y.append(np.log(m / t2)); t.append(m); c.append(comp)
        f = feats[pid]
        X.append(vectorize({k: float(f[k]) for k in FEATURE_NAMES})); Y.append(y); T.append(t); T0.append(t0); C.append(c)
        groups.append(f["family"]); ok_ids.append(pid)
    C = np.array(C, dtype=float) if C else np.zeros((0, len(strategy_ids)))
    if C.size:
        C = np.where(np.isnan(C), np.nanmedian(C), C)
    return {"program_ids": ok_ids, "strategy_ids": strategy_ids, "X": np.array(X), "Y": np.array(Y), "T": np.array(T),
            "T0": np.array(T0), "C": C, "groups": np.array(groups), "excluded": excluded}


def train_from_processed(processed: Path, output_dir: Path, mode: str, progress=None, seed: int = 0) -> dict:
    t_start = time.time()
    if progress:
        progress("train", 0, 3, "building matrices")
    d = build_matrices(processed)
    n = len(d["program_ids"])
    if n < 6:
        raise RuntimeError(f"Only {n} usable programs after filtering — cannot train. Excluded: {d['excluded'][:5]}")
    if progress:
        progress("evaluate", 1, 3, f"grouped cross-validation on {n} programs")
    cv = cross_validate(d["X"], d["Y"], d["T"], d["T0"], d["C"], d["groups"], d["strategy_ids"], d["program_ids"], seed)
    if progress:
        progress("train", 2, 3, "fitting final model")
    model = make_model(seed).fit(d["X"], d["Y"])
    imps = importances(model, d["X"], d["Y"], FEATURE_NAMES, seed)
    meta = json.loads((processed / "dataset_meta.json").read_text()) if (processed / "dataset_meta.json").exists() else {}
    version = "rf-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    metrics = {"cross_validation": cv, "n_programs_used": n, "n_excluded": len(d["excluded"]), "excluded": d["excluded"][:30],
               "label_distribution": cv.get("oracle_label_distribution") if cv.get("available") else None,
               "dataset": meta, "training_seconds": round(time.time() - t_start, 2)}
    bundle = {"model": model, "version": version, "trained_at": datetime.now(timezone.utc).isoformat(),
              "model_type": "RandomForestRegressor (multi-output): log(time_strategy / time_O2)",
              "feature_names": FEATURE_NAMES, "feature_schema_version": FEATURE_SCHEMA_VERSION, "strategy_ids": d["strategy_ids"],
              "dataset_size": int(n * len(d["strategy_ids"])), "n_programs": n, "training_mode": mode,
              "feature_importances": imps["impurity"], "permutation_importances_train": imps["permutation_train"],
              "feature_medians": {k: float(v) for k, v in zip(FEATURE_NAMES, np.median(d["X"], axis=0))},
              "metrics": metrics, "toolchain": detection.detect()["clang_version"]}
    output_dir.mkdir(parents=True, exist_ok=True)
    tmp = output_dir / "model.joblib.tmp"
    joblib.dump(bundle, tmp)
    tmp.replace(output_dir / "model.joblib")
    (output_dir / "evaluation_report.json").write_text(json.dumps({k: v for k, v in bundle.items() if k != "model"}, indent=2, default=float))
    _record(bundle, output_dir / "model.joblib")
    from . import predict
    predict.load_model(force=True)
    if progress:
        progress("train", 3, 3, f"model {version} saved")
    return bundle


def _record(bundle: dict, path: Path) -> None:
    from ..database import init_db, session_scope
    from ..models import MLModelRecord

    init_db()
    with session_scope() as s:
        s.add(MLModelRecord(version=bundle["version"], dataset_version=ds.DATASET_VERSION, dataset_size=bundle["dataset_size"],
                            model_type=bundle["model_type"], feature_schema_version=bundle["feature_schema_version"],
                            training_mode=bundle["training_mode"], metrics=json.loads(json.dumps(bundle["metrics"], default=float)),
                            artifact_path=str(path), status="ready", training_seconds=bundle["metrics"]["training_seconds"]))


def run_training(data_dir: Path, output_dir: Path, processed_dir: Path, mode: str = "quick", reps: int | None = None,
                 skip_collect: bool = False, progress=None) -> dict:
    if not TRAIN_LOCK.acquire(blocking=False):
        raise RuntimeError("A training job is already running")
    try:
        d = detection.detect()
        if not d["can_compile_c"]:
            raise RuntimeError("clang not found — cannot collect benchmark measurements. " + " ".join(d["problems"]))
        processed_dir.mkdir(parents=True, exist_ok=True)
        if not skip_collect or not (processed_dir / "measurements.csv").exists():
            programs = ds.generate_programs(data_dir, mode)
            r = reps or (9 if mode == "full" else 5)
            ds.collect_measurements(programs, processed_dir, r, 2 if mode == "full" else 1, progress)
        return train_from_processed(processed_dir, output_dir, mode, progress)
    finally:
        TRAIN_LOCK.release()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=str(settings.benchmarks_dir), help="where benchmark sources are written")
    ap.add_argument("--output-dir", default=str(settings.artifacts_dir))
    ap.add_argument("--processed-dir", default=str(settings.processed_dir))
    ap.add_argument("--mode", choices=["quick", "full"], default="quick", help="quick: 36 programs; full: 72 programs")
    ap.add_argument("--reps", type=int, default=None, help="timed repetitions per candidate (default 5 quick / 9 full)")
    ap.add_argument("--skip-collect", action="store_true", help="reuse data/processed/measurements.csv")
    a = ap.parse_args(argv)

    def prog(stage, i, n, msg):
        print(f"[{stage}] {i}/{n} {msg}", flush=True)

    try:
        b = run_training(Path(a.data_dir), Path(a.output_dir), Path(a.processed_dir), a.mode, a.reps, a.skip_collect, prog)
    except Exception as exc:
        print(f"Training failed: {exc}", file=sys.stderr)
        return 1
    cv = b["metrics"]["cross_validation"]
    print(f"\nModel {b['version']} saved to {Path(a.output_dir) / 'model.joblib'}")
    if cv.get("available"):
        print(cv["method"], "—", cv["verdict"])
        for k, v in cv["strategies"].items():
            print(f"  {v['name']:44s} near-opt {v['near_optimal_rate']:.0%}  regret {v['mean_regret_pct']:6.1f}%  beats-O2 {v['beats_O2_pct']:4.0f}%  worse-than-O2 {v['worse_than_O2_pct']:4.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
