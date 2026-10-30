"""Repeated, warmed-up timing of an executable with identical stdin for every candidate."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..compiler.process import run
from ..config import settings
from .statistics import summarize


@dataclass
class BenchResult:
    ok: bool
    samples_ms: list[float] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    peak_rss_kb: int | None = None
    reps_requested: int = 0
    reps_done: int = 0
    reduced_for_budget: bool = False
    failure: str | None = None


def benchmark_exe(exe: Path, stdin: bytes, reps: int, warmup: int, budget_s: float | None = None,
                  timeout: float | None = None) -> BenchResult:
    timeout = timeout or settings.run_timeout_s
    res = BenchResult(ok=False, reps_requested=reps)
    first_times = []
    for _ in range(max(0, warmup)):
        r = run([str(exe)], cwd=exe.parent, timeout=timeout, stdin=stdin, limit_resources=True)
        if r.timed_out or r.error:
            res.failure = "timed out during warm-up" if r.timed_out else r.error
            return res
        first_times.append(r.elapsed_ms)
    n = reps
    if budget_s and first_times:
        est = max(first_times) / 1000.0
        if est > 0 and est * reps > budget_s:
            n = max(3, int(budget_s / est))
            res.reduced_for_budget = n < reps
    samples = []
    for _ in range(n):
        r = run([str(exe)], cwd=exe.parent, timeout=timeout, stdin=stdin, limit_resources=True)
        if r.timed_out:
            res.failure = f"timed out after {timeout:g}s during benchmark"
            return res
        if r.error:
            res.failure = r.error
            return res
        samples.append(r.elapsed_ms)
        if r.max_rss_kb:
            res.peak_rss_kb = max(res.peak_rss_kb or 0, r.max_rss_kb)
    res.samples_ms = samples
    res.stats = summarize(samples)
    res.reps_done = len(samples)
    res.ok = True
    return res


def benchmark_many(exes: dict[str, Path], stdin: bytes, reps: int, warmup: int, budget_s: float | None = None,
                   timeout: float | None = None, cancel=None) -> dict[str, BenchResult]:
    """Round-robin timing: each repetition runs every executable once, in a rotating order, so slow drift
    (thermal throttling, background load) affects all candidates equally instead of the ones measured last."""
    timeout = timeout or settings.run_timeout_s
    results = {k: BenchResult(ok=False, reps_requested=reps) for k in exes}
    alive = dict(exes)
    first: dict[str, float] = {}
    for _ in range(max(0, warmup)):
        for k, exe in list(alive.items()):
            r = run([str(exe)], cwd=exe.parent, timeout=timeout, stdin=stdin, limit_resources=True)
            if r.timed_out or r.error:
                results[k].failure = "timed out during warm-up" if r.timed_out else r.error
                alive.pop(k)
            else:
                first[k] = max(first.get(k, 0.0), r.elapsed_ms)
    n = reps
    if budget_s and first:
        est = sum(first.values()) / 1000.0  # one round over all executables
        if est > 0 and est * reps > budget_s:
            n = max(3, int(budget_s / est))
    samples: dict[str, list[float]] = {k: [] for k in alive}
    rss: dict[str, int] = {}
    for rep in range(n):
        if cancel and cancel():
            break
        keys = list(alive)
        shift = rep % max(1, len(keys))
        for k in keys[shift:] + keys[:shift]:
            exe = alive[k]
            r = run([str(exe)], cwd=exe.parent, timeout=timeout, stdin=stdin, limit_resources=True)
            if r.timed_out or r.error:
                results[k].failure = f"timed out after {timeout:g}s during benchmark" if r.timed_out else r.error
                alive.pop(k, None)
                continue
            samples[k].append(r.elapsed_ms)
            if r.max_rss_kb:
                rss[k] = max(rss.get(k, 0), r.max_rss_kb)
    for k in alive:
        res = results[k]
        res.samples_ms = samples[k]
        res.stats = summarize(samples[k])
        res.reps_done = len(samples[k])
        res.reduced_for_budget = n < reps
        res.peak_rss_kb = rss.get(k)
        res.ok = res.reps_done > 0
    return results
