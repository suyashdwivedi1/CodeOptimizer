"""The experiment pipeline. Every stage emits real progress events; nothing here is simulated."""
from __future__ import annotations

import os
import platform
import secrets
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from ..analysis import diagnostics as dg
from ..benchmark.runner import benchmark_many
from ..benchmark.statistics import practical_tie, speedup, time_reduction_pct
from ..compiler import compilation as cc
from ..compiler import correctness as co
from ..compiler import detection
from ..compiler import passes as reg
from ..config import settings
from ..database import session_scope
from ..ml import predict as mlp
from ..models import Experiment, Variant
from . import analysis_service as an
from . import progress_service as ps
from .candidates import CandidateBuild, compile_candidate, prepare_candidate

BENCH_LOCK = threading.Lock()  # timing runs must not overlap each other
_executor = ThreadPoolExecutor(max_workers=max(1, settings.max_concurrent_experiments), thread_name_prefix="exp")


class StageFailed(Exception):
    pass


class Cancelled(Exception):
    pass


def new_experiment_id() -> str:
    return datetime.now(timezone.utc).strftime("exp-%Y%m%d-%H%M%S-") + secrets.token_hex(2)


def create_experiment(*, source: str, language: str, filename: str | None, label: str | None, stdin: str, mode: str,
                      repetitions: int | None, use_ml: bool) -> str:
    language, _ = dg.validate_source(source, language, filename, stdin)
    exp_id = new_experiment_id()
    d = detection.detect()
    reps = repetitions or (settings.rigorous_reps if mode == "rigorous" else settings.quick_reps)
    reps = max(3, min(int(reps), 200))
    warm = settings.rigorous_warmup if mode == "rigorous" else settings.quick_warmup
    with session_scope() as s:
        s.add(Experiment(id=exp_id, language=language, filename=filename, label=label or filename or "untitled",
                         source_hash=sha256(source.encode()).hexdigest(), source_text=source, stdin_text=stdin,
                         compiler_version=d["clang_version"], llvm_version=d["llvm_version"], status="queued", mode=mode,
                         repetitions=reps, warmup=warm,
                         report={"use_ml": use_ml}))
    ps.get_bus(exp_id)
    ps.emit(exp_id, "source_received", "pending", "Queued")
    _executor.submit(_run_safely, exp_id)
    return exp_id


def _run_safely(exp_id: str) -> None:
    try:
        ExperimentRunner(exp_id).run()
    except Exception as exc:  # pragma: no cover - last-resort guard
        ps.emit(exp_id, "experiment", "failed", f"Internal error: {type(exc).__name__}: {exc}")
        with session_scope() as s:
            e = s.get(Experiment, exp_id)
            if e:
                e.status, e.error_summary = "failed", f"Internal error: {type(exc).__name__}: {exc}"


class _Ctx:
    def __init__(self):
        self.message = ""
        self.data: dict = {}


class ExperimentRunner:
    def __init__(self, exp_id: str):
        self.id = exp_id
        self.bus = ps.get_bus(exp_id)
        with session_scope() as s:
            e = s.get(Experiment, exp_id)
            self.language, self.source, self.stdin = e.language, e.source_text, e.stdin_text.encode("utf-8")
            self.filename, self.mode, self.reps, self.warm = e.filename, e.mode, e.repetitions, e.warmup
            self.use_ml = (e.report or {}).get("use_ml", True)
        self.root = settings.experiments_dir / exp_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.src_path = self.root / cc.source_filename(self.language)
        self.t0 = time.perf_counter()
        self.done_stages: set[str] = set()
        self.analysis: dict = {}
        self.feats: dict = {}
        self.warnings: list[str] = []
        self.diags: list[dict] = []
        self.unopt_ll: Path | None = None
        self.prediction: dict | None = None
        self.builds: dict[str, CandidateBuild] = {}
        self.order: list[str] = []
        self.skipped: dict[str, str] = {}
        self.corr: dict[str, tuple[bool, str | None]] = {}
        self.bench: dict = {}
        self.report: dict = {"use_ml": self.use_ml}

    # ---------------------------------------------------------------- plumbing
    def cancelled(self) -> bool:
        return self.bus.cancel.is_set()

    @contextmanager
    def stage(self, sid: str, running_msg: str):
        if self.cancelled():
            raise Cancelled()
        t0 = time.perf_counter()
        ps.emit(self.id, sid, "running", running_msg)
        ctx = _Ctx()
        try:
            yield ctx
        except StageFailed as exc:
            ps.emit(self.id, sid, "failed", str(exc), elapsed_ms=(time.perf_counter() - t0) * 1000)
            self.done_stages.add(sid)
            raise
        except Cancelled:
            raise
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            ps.emit(self.id, sid, "failed", msg, elapsed_ms=(time.perf_counter() - t0) * 1000)
            self.done_stages.add(sid)
            raise StageFailed(msg) from exc
        else:
            ps.emit(self.id, sid, "completed", ctx.message or running_msg, data=ctx.data,
                    elapsed_ms=(time.perf_counter() - t0) * 1000)
            self.done_stages.add(sid)

    def skip(self, sid: str, reason: str) -> None:
        ps.emit(self.id, sid, "skipped", reason)
        self.done_stages.add(sid)

    def log(self, sid: str, msg: str, data: dict | None = None) -> None:
        ps.emit(self.id, sid, "info", msg, data=data)

    # ---------------------------------------------------------------- main
    def run(self) -> None:
        with session_scope() as s:
            s.get(Experiment, self.id).status = "running"
        status, error = "completed", None
        try:
            self._pipeline()
        except StageFailed as exc:
            status, error = "failed", str(exc)
        except Cancelled:
            status, error = "cancelled", "Cancelled by user"
        finally:
            for sid, _ in ps.STAGES:
                if sid not in self.done_stages:
                    ps.emit(self.id, sid, "skipped",
                            "Not reached: " + (error or "experiment ended early") if status != "completed" else "Not applicable")
            self._persist(status, error)
            ps.emit(self.id, "experiment", status, error or self.report.get("headline", "Experiment finished"),
                    elapsed_ms=(time.perf_counter() - self.t0) * 1000)
            self._cleanup_binaries()

    def _pipeline(self) -> None:
        with self.stage("source_received", "Receiving source") as c:
            self.src_path.write_text(self.source, encoding="utf-8")
            c.message = f"{len(self.source.encode())} bytes, {len(self.source.splitlines())} lines, language={self.language}"
        with self.stage("input_validation", "Validating size, encoding and constructs") as c:
            try:
                _, self.warnings = dg.validate_source(self.source, self.language, self.filename, self.stdin.decode("utf-8", "replace"))
            except dg.ValidationError as exc:
                raise StageFailed(str(exc))
            c.message = "Input accepted" + (f" with {len(self.warnings)} warning(s)" if self.warnings else "")
        with self.stage("compiler_check", "Detecting clang / opt / llc") as c:
            d = detection.detect()
            tool = "clang++" if self.language == "cpp" else "clang"
            if not d["tools"][tool]["available"]:
                raise StageFailed(f"{tool} is not installed. Install LLVM and set LLVM_BIN_DIR (see README).")
            c.message = f"{d['clang_version']}; opt={'yes' if d['tools']['opt']['available'] else 'no'}; llc={'yes' if d['tools']['llc']['available'] else 'no'}"
        with self.stage("compilation", "Syntax check with -Wall -Wextra") as c:
            ok, self.diags, _ = an.check_syntax(self.src_path, self.language)
            errs = [x for x in self.diags if x["severity"] == "error"]
            if not ok:
                self.analysis = {"compilation_status": "error", "diagnostics": self.diags, "language": self.language,
                                 "compiler_version": detection.detect()["clang_version"], "warnings": self.warnings,
                                 "source_lines": len(self.source.splitlines())}
                first = errs[0] if errs else {"line": "?", "message": "compilation failed"}
                raise StageFailed(f"{len(errs)} compile error(s); first: line {first['line']}: {first['message']}")
            c.message = f"Compiles cleanly ({sum(1 for x in self.diags if x['severity'] == 'warning')} warning(s))"
        ir_ok = False
        with self.stage("ir_generation", "Emitting unoptimised LLVM IR") as c:
            self.unopt_ll = self.root / "unoptimized.ll"
            step = cc.emit_unoptimized_ir(self.src_path, self.language, self.unopt_ll)
            if not step.ok:
                self.unopt_ll = None
                self.warnings.append("LLVM IR generation failed: " + step.reason()[:300])
                c.message = "IR generation failed; continuing with flag-based candidates only"
            else:
                v = cc.verify_ir(self.unopt_ll)
                if v.error == "opt not installed":
                    ir_ok = True
                    self.warnings.append("opt not installed: IR not verified, IR pass-pipeline candidates disabled.")
                    c.message = "IR emitted (verifier unavailable: opt missing)"
                elif not v.ok:
                    self.unopt_ll = None
                    self.warnings.append("IR verifier rejected the module: " + v.reason()[:300])
                    c.message = "IR rejected by verifier"
                else:
                    ir_ok = True
                    c.message = f"IR verified ({self.unopt_ll.stat().st_size} bytes)"
        with self.stage("feature_extraction", "Extracting features and vectorisation remarks") as c:
            self.feats, notes = an.compute_features(self.src_path, self.language, self.unopt_ll if ir_ok else None, self.root)
            self.warnings += notes
            remarks = an.vectorization_remarks(self.src_path, self.language)
            o0 = self.feats.get("_ir_detail", {}).get("instr") if ir_ok else None
            o2 = an.ir_instr_count(self.src_path, self.language, ["-O2"], self.root / "o2.ll")
            self.analysis = an.build_analysis(self.source, self.language, self.filename, self.feats, self.diags, remarks,
                                              self.warnings, ir_ok, o0, o2, True)
            c.message = (f"{len([k for k in self.feats if not k.startswith('_')])} features; "
                         f"{sum(1 for r in remarks if r['status'] == 'vectorized')} vectorised loop(s) at -O3")
        avail, self.skipped = reg.available_strategies(self.language)
        if not ir_ok or self.unopt_ll is None:
            for s in avail:
                if s.kind == "ir_pipeline":
                    self.skipped.setdefault(s.id, "unoptimised IR unavailable")
            avail = [s for s in avail if s.kind != "ir_pipeline"]
        avail_ids = [s.id for s in avail]
        with self.stage("ml_inference", "Ranking strategies") as c:
            if self.use_ml:
                self.prediction = mlp.predict(self.feats, avail_ids)
            else:
                self.prediction = _fallback_prediction(avail_ids, "ML disabled for this run (use_ml=false)")
            p = self.prediction
            c.message = (f"{'Trained model ' + str(p['model_version']) if p['is_ml'] else 'No ML'}: top pick {p['top_pick']} "
                         f"({p['inference_ms']:.1f} ms)") if p["is_ml"] else f"Fallback order (not ML): {p['top_pick']} first"
            c.data = {"source": p["source"], "top_pick": p["top_pick"]}
        by_id = {s.id: s for s in avail}
        with self.stage("candidate_generation", "Selecting candidates") as c:
            refs = [x for x in reg.REFERENCE_LEVELS if x in by_id]
            ranked = [r["strategy_id"] for r in self.prediction["ranking"]]
            extra = [x for x in ranked if x not in refs][: max(0, settings.max_candidates - len(refs))]
            sel = [reg.BASELINE_ID] + sorted(refs + extra, key=lambda x: ranked.index(x) if x in ranked else 99)
            self.order = sel
            self.report["pool_ranked"] = ranked
            c.message = f"{len(sel) - 1} candidates + baseline: " + ", ".join(sel[1:])
            c.data = {"selected": sel, "unavailable": self.skipped}
        self._build(self.order, by_id)
        self._distinct_top_up(by_id, ranked)
        self._benchmark_and_rank()

    # ---------------------------------------------------------------- build / check
    def _build(self, ids: list[str], by_id: dict[str, "reg.Strategy"]) -> None:
        new = [i for i in ids if i not in self.builds]
        with self.stage("optimization", f"Running transforms for {len(new)} strategies") as c:
            n_ir = n_src = n_flag = 0
            for sid in new:
                if self.cancelled():
                    raise Cancelled()
                cb = prepare_candidate(by_id[sid], self.language, self.src_path, self.unopt_ll, self.root)
                self.builds[sid] = cb
                k = by_id[sid].kind
                n_ir += k == "ir_pipeline"
                n_src += k == "source"
                n_flag += k in ("baseline", "level", "flags")
                if cb.status in ("failed", "skipped"):
                    self.log("optimization", f"{sid}: {cb.status} — {cb.failure}")
            c.message = (f"{n_ir} `opt` pass pipeline(s), {n_src} source rewrite(s); {n_flag} flag-based candidate(s) are "
                         "optimised by LLVM inside the compile step")
        with self.stage("variant_compilation", f"Compiling {len(new)} executables") as c:
            todo = [self.builds[i] for i in new]
            with ThreadPoolExecutor(max_workers=settings.build_workers) as pool:
                list(pool.map(compile_candidate, todo))
            ok = [b.strategy.id for b in todo if b.status == "ok"]
            bad = [(b.strategy.id, b.failure) for b in todo if b.status == "failed"]
            for sid, why in bad:
                self.log("variant_compilation", f"{sid} failed: {str(why)[:200]}")
            c.message = f"{len(ok)} compiled, {len(bad)} failed, {sum(1 for b in todo if b.status == 'skipped')} skipped"
        with self.stage("correctness", "Comparing outputs against the -O0 baseline") as c:
            base = self.builds.get(reg.BASELINE_ID)
            if base is None or base.status != "ok":
                raise StageFailed("Baseline (-O0) failed to build: " + (base.failure if base else "missing"))
            if not hasattr(self, "ref"):
                inputs = [self.stdin] + ([b""] if self.stdin else [])
                self.ref = co.build_reference(base.exe, inputs)
                if not self.ref.ok:
                    raise StageFailed("Baseline program cannot be used as a reference: " + (self.ref.reason or "unknown"))
                rc = self.ref.outputs[0].returncode
                if rc != 0:
                    self.warnings.append(f"Baseline exits with status {rc}; variants are required to reproduce the same status and stdout.")
            for sid in new:
                cb = self.builds[sid]
                if sid == reg.BASELINE_ID:
                    self.corr[sid] = (True, None)
                elif cb.status == "ok":
                    self.corr[sid] = co.check_against(self.ref, cb.exe)
            first_hash: dict[str, str] = {}
            for sid in self.order + [i for i in self.builds if i not in self.order]:
                cb = self.builds.get(sid)
                if cb and cb.exe_hash:
                    first_hash.setdefault(cb.exe_hash, sid)
            self.dup = {sid: first_hash[cb.exe_hash] for sid, cb in self.builds.items()
                        if cb.exe_hash and first_hash[cb.exe_hash] != sid}
            good = [s for s, (ok_, _) in self.corr.items() if ok_ and s != reg.BASELINE_ID and s not in self.dup]
            wrong = [s for s, (ok_, _) in self.corr.items() if not ok_]
            for s in wrong:
                self.log("correctness", f"{s} REJECTED: {self.corr[s][1]}")
            c.message = (f"{len(good)} distinct valid, {len(wrong)} incorrect, {len(self.dup)} duplicate binary(ies)"
                         + (": " + ", ".join(f"{k}≡{v}" for k, v in self.dup.items()) if self.dup else ""))

    def _distinct_top_up(self, by_id, ranked: list[str]) -> None:
        for _ in range(2):
            good = [s for s, (ok_, _) in self.corr.items() if ok_ and s != reg.BASELINE_ID and s not in self.dup]
            need = settings.min_distinct_valid - len(good)
            if need <= 0:
                return
            rest = [i for i in ranked if i not in self.builds]
            if not rest:
                self.report.setdefault("notes", []).append(
                    f"Only {len(good)} distinct valid optimised candidate(s) could be produced for this program; no further strategies remain.")
                return
            add = rest[: need + 1]
            self.log("candidate_generation", f"Only {len(good)} distinct valid candidate(s); adding {', '.join(add)}")
            self.order += add
            self._build(add, by_id)

    # ---------------------------------------------------------------- benchmark / rank
    def _benchmark_and_rank(self) -> None:
        measurable = {sid: cb for sid, cb in self.builds.items()
                      if cb.status == "ok" and self.corr.get(sid, (False,))[0] and sid not in self.dup}
        with self.stage("benchmark", f"Timing {len(measurable)} executables ({self.reps} reps, {self.warm} warm-up)") as c:
            budget = settings.benchmark_budget_rigorous_s if self.mode == "rigorous" else settings.benchmark_budget_quick_s
            with BENCH_LOCK:
                self.bench = benchmark_many({k: v.exe for k, v in measurable.items()}, self.stdin, self.reps, self.warm,
                                            budget_s=budget, cancel=self.cancelled)
            if self.cancelled():
                raise Cancelled()
            okb = [k for k, v in self.bench.items() if v.ok]
            base = self.bench.get(reg.BASELINE_ID)
            if not base or not base.ok:
                raise StageFailed("Baseline benchmark failed: " + (base.failure if base else "no result"))
            c.message = f"{len(okb)} measured; baseline median {base.stats['median']:.3f} ms over {base.reps_done} runs"
            if base.reduced_for_budget:
                c.message += f" (repetitions reduced to fit the {budget:g}s budget)"
        with self.stage("ranking", "Computing speedups and selecting a winner") as c:
            self.winner_info = self._rank()
            c.message = self.winner_info["headline"]
        with self.stage("report", "Assembling report") as c:
            self._build_report()
            c.message = "Report stored"

    def _rank(self) -> dict:
        base = self.bench[reg.BASELINE_ID]
        bmed = base.stats["median"]
        measured = {k: v for k, v in self.bench.items() if v.ok}
        below = bmed < settings.reliable_min_ms
        self.metrics: dict[str, dict] = {}
        for k, v in measured.items():
            self.metrics[k] = {"speedup": speedup(bmed, v.stats["median"]), "reduction": time_reduction_pct(bmed, v.stats["median"])}
        ordered = sorted(measured.items(), key=lambda kv: kv[1].stats["median"])
        info = {"winner": None, "status": "none", "tied": [], "best": None, "headline": ""}
        opt_valid = [k for k in measured if k != reg.BASELINE_ID]
        if not opt_valid:
            info["headline"] = "No optimised variant passed correctness validation — no successful optimisation to report."
            return info
        best_id, best = ordered[0]
        info["best"] = best_id
        runner_id, runner = ordered[1]
        if below:
            info["status"] = "below_threshold"
            info["headline"] = (f"Baseline runs in {bmed:.2f} ms, below the {settings.reliable_min_ms:g} ms reliability threshold: "
                                f"differences are not trustworthy. Fastest measured: {best_id}.")
        elif practical_tie({"median": best.stats["median"], "iqr": best.stats["iqr"]},
                           {"median": runner.stats["median"], "iqr": runner.stats["iqr"]}, settings.noise_tie_pct):
            tied = [k for k, v in ordered if practical_tie({"median": best.stats["median"], "iqr": best.stats["iqr"]},
                                                           {"median": v.stats["median"], "iqr": v.stats["iqr"]}, settings.noise_tie_pct)]
            info["status"], info["tied"] = "practical_tie", tied
            info["headline"] = f"Practical tie within measurement noise: {', '.join(tied)}. Fastest median: {best_id}."
        else:
            info["status"], info["winner"] = "clear", best_id
            if best_id == reg.BASELINE_ID:
                info["status"] = "baseline_best"
                info["headline"] = "No optimised variant beat the -O0 baseline."
            else:
                m = self.metrics[best_id]
                info["headline"] = f"Winner: {best_id} — {m['speedup']:.2f}× faster than baseline ({m['reduction']:.1f}% less time)."
        info["below_threshold"] = below
        return info

    def _build_report(self) -> None:
        pick = (self.prediction or {}).get("top_pick")
        ml_info = None
        if pick and pick in self.bench and self.bench[pick].ok:
            best = min(v.stats["median"] for v in self.bench.values() if v.ok)
            o2 = self.bench.get("O2")
            ml_info = {"strategy": pick, "median_ms": self.bench[pick].stats["median"],
                       "regret_vs_best_pct": 100 * (self.bench[pick].stats["median"] / best - 1),
                       "vs_o2_speedup": (o2.stats["median"] / self.bench[pick].stats["median"]) if o2 and o2.ok else None,
                       "is_trained_model": bool(self.prediction["is_ml"])}
        self.report.update({
            "winner_status": self.winner_info["status"], "tied": self.winner_info["tied"], "headline": self.winner_info["headline"],
            "skipped_strategies": self.skipped, "ml_pick": ml_info,
            "environment": {"platform": platform.platform(), "python": sys.version.split()[0], "cpu_count": os.cpu_count(),
                            "clang": detection.detect()["clang_version"], "mode": self.mode, "repetitions": self.reps,
                            "warmup": self.warm, "timer": "wall-clock of process launch+run (perf_counter), round-robin order"},
            "reliable_min_ms": settings.reliable_min_ms, "noise_tie_pct": settings.noise_tie_pct,
            "warnings": self.warnings,
            "empirical_note": "Speedups are measured constant-factor changes for this input; they do not change algorithmic complexity.",
        })

    # ---------------------------------------------------------------- persistence
    def _persist(self, status: str, error: str | None) -> None:
        rank_of = {r["strategy_id"]: r for r in (self.prediction or {}).get("ranking", [])}
        top = (self.prediction or {}).get("top_pick")
        win = getattr(self, "winner_info", None) or {}
        with session_scope() as s:
            e = s.get(Experiment, self.id)
            e.status, e.error_summary = status, error
            e.finished_at = datetime.now(timezone.utc)
            e.duration_ms = (time.perf_counter() - self.t0) * 1000
            e.analysis, e.complexity = self.analysis or None, (self.analysis or {}).get("complexity")
            e.ml_prediction = self.prediction
            e.ml_model_version = (self.prediction or {}).get("model_version")
            e.ml_source = (self.prediction or {}).get("source")
            e.selected_strategy = top
            e.report = {**self.report, "stage_order": [s_[0] for s_ in ps.STAGES]}
            e.winner_status = win.get("status")
            base = self.bench.get(reg.BASELINE_ID) if self.bench else None
            e.baseline_median_ms = base.stats["median"] if base and base.ok else None
            if status == "completed" and not win.get("best") and not error:
                e.error_summary = win.get("headline")
            for sid in [i for i in self.order if i in self.builds]:
                cb = self.builds[sid]
                v = Variant(experiment_id=self.id, strategy_id=sid, name=cb.strategy.name, kind=cb.strategy.kind,
                            is_baseline=sid == reg.BASELINE_ID, description=cb.strategy.description,
                            flags=list(cb.strategy.flags), pipeline=cb.strategy.pipeline or cb.pipeline_text or None,
                            applied_passes=cb.applied_passes[:400], techniques=cb.techniques,
                            source_path=str(cb.source_path) if cb.source_path else None,
                            ir_path=str(cb.ir_path) if cb.ir_path else None,
                            compile_status={"ok": "ok", "failed": "failed", "skipped": "skipped"}.get(cb.status, cb.status),
                            compile_time_ms=cb.compile_ms, opt_time_ms=cb.opt_ms, object_hash=cb.exe_hash,
                            duplicate_of=getattr(self, "dup", {}).get(sid), remarks=cb.remarks[:40], warnings=cb.warnings,
                            ml_selected=(sid == top and bool((self.prediction or {}).get("is_ml"))),
                            ml_score=(rank_of.get(sid) or {}).get("predicted_rel_time"), ml_rank=(rank_of.get(sid) or {}).get("rank"),
                            failure_reason=cb.failure)
                try:
                    v.binary_size = cb.exe.stat().st_size if cb.exe and cb.exe.exists() else None
                except OSError:
                    pass
                if sid in self.corr:
                    v.correctness_status = "passed" if self.corr[sid][0] else "failed"
                    if not self.corr[sid][0]:
                        v.failure_reason = self.corr[sid][1]
                elif cb.status == "ok":
                    v.correctness_status = "not_run"
                else:
                    v.correctness_status = "n/a"
                b = self.bench.get(sid) if self.bench else None
                if b and b.ok:
                    st = b.stats
                    v.median_ms, v.mean_ms, v.stdev_ms, v.iqr_ms = st["median"], st["mean"], st["stdev"], st["iqr"]
                    v.min_ms, v.max_ms, v.samples_ms, v.benchmark_count = st["min"], st["max"], b.samples_ms, b.reps_done
                    v.peak_rss_kb = b.peak_rss_kb
                    m = getattr(self, "metrics", {}).get(sid)
                    if m:
                        v.speedup, v.time_reduction_pct = m["speedup"], m["reduction"]
                    v.below_threshold = bool(win.get("below_threshold"))
                elif b and not b.ok:
                    v.failure_reason = b.failure
                v.is_winner = bool(win.get("winner") == sid)
                s.add(v)
            s.flush()
            if win.get("best"):
                bv = next((x for x in s.query(Variant).filter_by(experiment_id=self.id, strategy_id=win["best"])), None)
                if bv:
                    e.best_variant_id = bv.id
                    e.best_median_ms = bv.median_ms

    def _cleanup_binaries(self) -> None:
        for p in self.root.rglob("*"):
            if p.is_file() and (p.name in ("program", "program.exe") or p.suffix in (".o", ".obj")) and p.parent.name != self.root.name:
                try:
                    p.unlink()
                except OSError:
                    pass
        for f in ("features.ll", "o2.ll"):
            try:
                (self.root / f).unlink()
            except OSError:
                pass


def _fallback_prediction(avail_ids: list[str], note: str) -> dict:
    order = [s for s in mlp.FALLBACK_ORDER if s in avail_ids] + [s for s in avail_ids if s not in mlp.FALLBACK_ORDER]
    order = [s for s in order if s != reg.BASELINE_ID]
    return {"source": "fallback-default-order", "model_version": None, "is_ml": False, "note": note,
            "ranking": [{"strategy_id": s, "rank": i + 1, "predicted_rel_time": None, "score": None} for i, s in enumerate(order)],
            "top_pick": order[0] if order else None, "inference_ms": 0.0, "explanation": None}


# ------------------------------------------------------------------------------ what-if
def whatif_measure(exp_id: str, strategy_ids: list[str]) -> dict:
    """Measure additional, previously unmeasured strategies on the stored program. The baseline is re-measured in the
    same round-robin session and the new variants' speedups are relative to THAT baseline reading."""
    with session_scope() as s:
        e = s.get(Experiment, exp_id)
        if e is None:
            raise KeyError(exp_id)
        language, source, stdin, reps, warm = e.language, e.source_text, e.stdin_text.encode(), e.repetitions or 7, e.warmup or 1
        have = {v.strategy_id for v in e.variants}
    unknown = [i for i in strategy_ids if reg.get(i) is None]
    if unknown:
        raise ValueError(f"Unknown strategies: {unknown}")
    todo = [i for i in strategy_ids if i not in have and i != reg.BASELINE_ID]
    if not todo:
        return {"measured": [], "message": "All requested strategies were already measured."}
    root = settings.experiments_dir / exp_id
    root.mkdir(parents=True, exist_ok=True)
    src = root / cc.source_filename(language)
    src.write_text(source, encoding="utf-8")
    unopt = root / "unoptimized.ll"
    unopt_ok = unopt.exists() or cc.emit_unoptimized_ir(src, language, unopt).ok
    builds: dict[str, CandidateBuild] = {}
    for sid in [reg.BASELINE_ID] + todo:
        st = reg.get(sid)
        ok, why = reg.availability(st, language)
        if not ok:
            cb = CandidateBuild(strategy=st, dir=root, status="failed", failure=why)
        else:
            cb = compile_candidate(prepare_candidate(st, language, src, unopt if unopt_ok else None, root))
        builds[sid] = cb
    if builds[reg.BASELINE_ID].status != "ok":
        raise RuntimeError("Baseline rebuild failed: " + str(builds[reg.BASELINE_ID].failure))
    ref = co.build_reference(builds[reg.BASELINE_ID].exe, [stdin] + ([b""] if stdin else []))
    valid = {}
    for sid, cb in builds.items():
        if cb.status == "ok" and (sid == reg.BASELINE_ID or co.check_against(ref, cb.exe)[0]):
            valid[sid] = cb
    with BENCH_LOCK:
        res = benchmark_many({k: v.exe for k, v in valid.items()}, stdin, reps, warm, budget_s=settings.benchmark_budget_quick_s)
    base = res.get(reg.BASELINE_ID)
    if not base or not base.ok:
        raise RuntimeError("Baseline re-measurement failed")
    out = []
    with session_scope() as s:
        for sid in todo:
            cb, b = builds[sid], res.get(sid)
            exists = s.query(Variant).filter_by(experiment_id=exp_id, strategy_id=sid).first()
            if exists:
                continue
            ok_corr = sid in valid
            v = Variant(experiment_id=exp_id, strategy_id=sid, name=cb.strategy.name, kind=cb.strategy.kind,
                        description=cb.strategy.description, flags=list(cb.strategy.flags), pipeline=cb.strategy.pipeline or cb.pipeline_text or None,
                        applied_passes=cb.applied_passes[:400], techniques=cb.techniques,
                        source_path=str(cb.source_path) if cb.source_path else None, ir_path=str(cb.ir_path) if cb.ir_path else None,
                        compile_status=cb.status if cb.status in ("ok", "failed", "skipped") else "failed",
                        correctness_status="passed" if ok_corr else ("failed" if cb.status == "ok" else "n/a"),
                        failure_reason=cb.failure, compile_time_ms=cb.compile_ms, opt_time_ms=cb.opt_ms,
                        object_hash=cb.exe_hash, remarks=cb.remarks[:40], added_via_whatif=True,
                        warnings=cb.warnings + [f"Measured later via what-if; speedup is relative to a baseline re-measured in the same session ({base.stats['median']:.3f} ms)."])
            try:
                v.binary_size = cb.exe.stat().st_size if cb.exe else None
            except OSError:
                pass
            if b and b.ok:
                st = b.stats
                v.median_ms, v.mean_ms, v.stdev_ms, v.iqr_ms = st["median"], st["mean"], st["stdev"], st["iqr"]
                v.min_ms, v.max_ms, v.samples_ms, v.benchmark_count = st["min"], st["max"], b.samples_ms, b.reps_done
                v.peak_rss_kb = b.peak_rss_kb
                v.speedup = speedup(base.stats["median"], st["median"])
                v.time_reduction_pct = time_reduction_pct(base.stats["median"], st["median"])
            s.add(v)
            out.append(sid)
    for p in root.rglob("*"):
        if p.is_file() and (p.name in ("program", "program.exe") or p.suffix in (".o", ".obj")):
            p.unlink(missing_ok=True)
    return {"measured": out, "baseline_median_ms": base.stats["median"]}
