from __future__ import annotations

import numpy as np
from sklearn.inspection import permutation_importance


def importances(model, X: np.ndarray, Y: np.ndarray, names: list[str], seed: int = 0) -> dict:
    """Impurity importances (global) and permutation importance on the TRAINING data (optimistic, relative only)."""
    imp = {n: float(v) for n, v in zip(names, model.feature_importances_)}
    perm = {}
    try:
        r = permutation_importance(model, X, Y, n_repeats=5, random_state=seed, scoring="neg_mean_squared_error", n_jobs=1)
        perm = {n: float(v) for n, v in zip(names, r.importances_mean)}
    except Exception:
        pass
    return {"impurity": imp, "permutation_train": perm}
