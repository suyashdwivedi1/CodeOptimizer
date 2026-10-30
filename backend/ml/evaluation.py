"""Grouped (leave-family-out) cross-validation of the strategy ranker against real measurements and baselines."""
from __future__ import annotations

import time

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import GroupKFold

NEAR = 1.03  # picks within 3% of the best measured candidate count as "near-optimal" (differences below noise)


def make_model(seed: int = 0) -> RandomForestRegressor:
    return RandomForestRegressor(n_estimators=300, max_features=0.6, min_samples_leaf=1, random_state=seed, n_jobs=2)


def _summ(name: str, pick: np.ndarray, T: np.ndarray, best: np.ndarray, o2: int, t_o0: np.ndarray, comp: np.ndarray) -> dict:
    n = len(T)
    tp = T[np.arange(n), pick]
    tb = T[np.arange(n), best]
    to2 = T[:, o2]
    return {
        "name": name,
        "top1_accuracy": float(np.mean(pick == best)),
        "near_optimal_rate": float(np.mean(tp <= tb * NEAR)),
        "mean_regret_pct": float(np.mean(100 * (tp / tb - 1))),
        "median_regret_pct": float(np.median(100 * (tp / tb - 1))),
        "median_speedup_vs_O0": float(np.median(t_o0 / tp)),
        "geomean_speedup_vs_O2": float(np.exp(np.mean(np.log(to2 / tp)))),
        "beats_O2_pct": float(100 * np.mean(tp < to2 / NEAR)),
        "ties_O2_pct": float(100 * np.mean((tp >= to2 / NEAR) & (tp <= to2 * NEAR))),
        "worse_than_O2_pct": float(100 * np.mean(tp > to2 * NEAR)),
        "median_compile_ms": float(np.median(comp[np.arange(n), pick])),
    }


def cross_validate(X: np.ndarray, Y: np.ndarray, T: np.ndarray, t_o0: np.ndarray, comp: np.ndarray, groups: np.ndarray,
                   strategy_ids: list[str], program_ids: list[str], seed: int = 0) -> dict:
    """Y = log(time/time_O2) per strategy; T = measured medians (ms). Every prediction is out-of-fold and the held-out
    program's whole family is excluded from training, so near-duplicate parametrisations cannot leak."""
    n = len(X)
    ug = np.unique(groups)
    if n < 8 or len(ug) < 3:
        return {"available": False, "reason": f"Too little data for grouped CV ({n} programs, {len(ug)} families)."}
    o2 = strategy_ids.index("O2")
    folds = min(5, len(ug))
    pred = np.zeros_like(Y)
    fixed_pick = np.zeros(n, dtype=int)
    for tr, te in GroupKFold(n_splits=folds).split(X, Y, groups):
        m = make_model(seed).fit(X[tr], Y[tr])
        pred[te] = m.predict(X[te])
        fixed_pick[te] = int(np.argmin(Y[tr].mean(axis=0)))  # best fixed strategy chosen on training programs only
    best = Y.argmin(axis=1)
    ml_pick = pred.argmin(axis=1)
    top3_hit = np.array([best[i] in np.argsort(pred[i])[:3] or T[i, np.argsort(pred[i])[:3]].min() <= T[i, best[i]] * NEAR for i in range(n)])
    strategies = {
        "ml": _summ("ML-selected (held-out)", ml_pick, T, best, o2, t_o0, comp),
        "always_o2": _summ("Always -O2", np.full(n, o2), T, best, o2, t_o0, comp),
        "best_fixed": _summ("Best fixed strategy (train-fold choice)", fixed_pick, T, best, o2, t_o0, comp),
    }
    if "O3" in strategy_ids:
        strategies["always_o3"] = _summ("Always -O3", np.full(n, strategy_ids.index("O3")), T, best, o2, t_o0, comp)
    strategies["oracle"] = _summ("Oracle (best measured — upper bound)", best, T, best, o2, t_o0, comp)
    strategies["ml"]["top3_near_optimal_rate"] = float(np.mean(top3_hit))
    # per-program table
    rows = []
    for i in range(n):
        rows.append({"program_id": program_ids[i], "family": str(groups[i]), "oracle": strategy_ids[best[i]], "ml_pick": strategy_ids[ml_pick[i]],
                     "o2_ms": float(T[i, o2]), "ml_ms": float(T[i, ml_pick[i]]), "best_ms": float(T[i, best[i]])})
    # inference latency of the final-size model
    t0 = time.perf_counter()
    mm = make_model(seed).fit(X, Y)
    fit_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    for _ in range(50):
        mm.predict(X[:1])
    infer_ms = (time.perf_counter() - t0) / 50 * 1000
    verdict = ("ML selection beat always-O2 on mean regret" if strategies["ml"]["mean_regret_pct"] < strategies["always_o2"]["mean_regret_pct"] - 0.5
               else "ML selection did NOT clearly beat always-O2 on mean regret" if strategies["ml"]["mean_regret_pct"] > strategies["always_o2"]["mean_regret_pct"] + 0.5
               else "ML selection and always-O2 are statistically indistinguishable on this data")
    return {"available": True, "method": f"GroupKFold by program family, {folds} folds", "n_programs": n, "n_families": int(len(ug)),
            "near_optimal_threshold": f"within {int((NEAR - 1) * 100)}% of best measured", "strategies": strategies,
            "per_program": rows, "inference_ms": infer_ms, "fit_seconds": fit_s, "verdict": verdict,
            "oracle_label_distribution": {strategy_ids[k]: int((best == k).sum()) for k in range(len(strategy_ids)) if (best == k).any()}}
