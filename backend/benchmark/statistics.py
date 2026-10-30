from __future__ import annotations

import math
import statistics as st


def summarize(samples: list[float]) -> dict:
    if not samples:
        return {"n": 0, "median": None, "mean": None, "stdev": None, "iqr": None, "min": None, "max": None, "cv_pct": None}
    s = sorted(samples)
    n = len(s)
    med = st.median(s)
    if n >= 4:
        q = st.quantiles(s, n=4, method="inclusive")
        iqr = q[2] - q[0]
    else:
        iqr = s[-1] - s[0]
    sd = st.stdev(s) if n >= 2 else 0.0
    mean = st.fmean(s)
    return {"n": n, "median": med, "mean": mean, "stdev": sd, "iqr": iqr, "min": s[0], "max": s[-1],
            "cv_pct": (sd / mean * 100) if mean else None}


def speedup(baseline_ms: float | None, candidate_ms: float | None) -> float | None:
    if not baseline_ms or not candidate_ms or candidate_ms <= 0:
        return None
    return baseline_ms / candidate_ms


def time_reduction_pct(baseline_ms: float | None, candidate_ms: float | None) -> float | None:
    """Positive = faster, negative = slowdown."""
    if not baseline_ms or candidate_ms is None:
        return None
    return 100.0 * (baseline_ms - candidate_ms) / baseline_ms


def practical_tie(best: dict, other: dict, tie_pct: float) -> bool:
    """True when the gap between two medians is within measurement noise (IQR/2) or the configured tolerance."""
    gap = abs(other["median"] - best["median"])
    noise = max(best.get("iqr") or 0.0, other.get("iqr") or 0.0) / 2
    return gap <= max(noise, best["median"] * tie_pct / 100.0)


def geometric_mean(values: list[float]) -> float | None:
    vals = [v for v in values if v and v > 0]
    if not vals:
        return None
    return math.exp(sum(math.log(v) for v in vals) / len(vals))
