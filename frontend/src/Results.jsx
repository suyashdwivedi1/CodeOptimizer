import React, { useEffect, useState } from "react";
import { api, downloadUrl } from "./api.js";
import CodeEditor from "./CodeEditor.jsx";
import Charts, { Legend } from "./Charts.jsx";
import { NA, fmtBytes, fmtMs, fmtPct, fmtX } from "./util.js";

export function Banner({ r }) {
  if (!r) return null;
  const cls = r.status !== "completed" ? "bad" : ["clear"].includes(r.winner_status) ? "ok" : "warn";
  const text = r.status !== "completed" ? (r.error_summary || r.status) : r.report?.headline || r.error_summary || "Completed";
  return <div className={`banner ${cls}`}><div><b>{r.status === "completed" ? "Result:" : `${r.status.toUpperCase()}:`}</b> {text}
    {r.winner_status === "practical_tie" && <div className="sub">Differences are within measurement noise, so no single winner is highlighted.</div>}
    {r.winner_status === "below_threshold" && <div className="sub">The program runs too fast to measure reliably.</div>}</div></div>;
}

// The answer to "what should I use and how much faster is it", before any detail.
export function Summary({ exp }) {
  if (exp.status !== "completed" || !exp.variants?.length) return null;
  const best = exp.variants.find((v) => v.id === exp.best_variant_id);
  const base = exp.variants.find((v) => v.is_baseline);
  const ml = exp.variants.find((v) => v.ml_selected);
  return (
    <section className="summary">
      <div className="lead">
        <div className="k">Fastest correct variant</div>
        <div className="big">{best ? best.strategy_id : "No single winner"}</div>
        {best && <div className="sub2">{best.name}</div>}
      </div>
      <div className="lead">
        <div className="k">Speedup over -O0</div>
        <div className="big">{best ? fmtX(best.speedup) : NA}</div>
        {best && <div className="sub2">{fmtPct(best.time_reduction_pct)} run time</div>}
      </div>
      <div className="aside">
        <div><span>Baseline</span><b>{fmtMs(base?.median_ms)}</b></div>
        <div><span>Fastest</span><b>{fmtMs(best?.median_ms)}</b></div>
        <div><span>Model pick</span><b>{ml ? ml.strategy_id : "none"}</b></div>
      </div>
    </section>
  );
}

function Badge({ v }) {
  if (v.is_winner) return <span className="tag win">winner</span>;
  if (v.duplicate_of) return <span className="tag">same as {v.duplicate_of}</span>;
  if (v.correctness_status === "failed") return <span className="tag bad">incorrect</span>;
  if (v.compile_status === "failed") return <span className="tag bad">compile failed</span>;
  if (v.compile_status === "skipped") return <span className="tag">skipped</span>;
  return null;
}

export function VariantTable({ variants, selected, onSelect }) {
  return (
    <div className="tablewrap"><table className="tbl">
      <thead><tr><th>Variant</th><th className="r key">Median</th><th className="r key">Speedup</th><th className="r">Time change</th><th className="r">Size</th><th>Compile</th><th>Correct</th><th className="r">Runs</th><th></th></tr></thead>
      <tbody>{variants.map((v) => (
        <tr key={v.id} className={`${selected === v.id ? "sel" : ""} ${v.is_winner ? "winrow" : ""}`} onClick={() => onSelect(v.id)}>
          <td><b>{v.strategy_id}</b>{v.ml_selected && <span className="tag ml" title="Top pick of the trained ML model">ML pick</span>}{v.is_baseline && <span className="tag">baseline</span>}<div className="dim small">{v.kind.replace("_", " ")}</div></td>
          <td className="r key">{fmtMs(v.median_ms)}</td><td className="r key">{fmtX(v.speedup)}</td>
          <td className="r dim">{fmtPct(v.time_reduction_pct)}</td><td className="r dim">{fmtBytes(v.binary_size)}</td>
          <td className="dim">{v.compile_status}</td><td className="dim">{v.correctness_status}</td><td className="r dim">{v.benchmark_count || NA}</td><td><Badge v={v} /></td>
        </tr>))}</tbody>
    </table></div>
  );
}

export function VariantDetail({ exp, v }) {
  const [tab, setTab] = useState("source");
  const [src, setSrc] = useState(null);
  const [ir, setIr] = useState(null);
  useEffect(() => { setSrc(null); setIr(null); setTab(v.has_source ? "source" : "ir"); }, [v.id]);
  useEffect(() => {
    if (tab === "source" && src == null) api.source(exp.id, v.id).then(setSrc).catch((e) => setSrc({ error: e.message }));
    if (tab === "ir" && ir == null) api.ir(exp.id, v.id).then(setIr).catch((e) => setIr({ error: e.message }));
  }, [tab, v.id]);
  const text = tab === "source" ? src?.source : ir?.ir;
  const copy = () => text && navigator.clipboard?.writeText(text);
  return (
    <section className="panel">
      <div className="panel-h"><h3>Variant {v.strategy_id}: {v.name}</h3>
        <div className="tabs">{["source", "ir", "passes", "benchmark"].map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{{ source: "Source", ir: "LLVM IR", passes: "Passes and flags", benchmark: "Benchmark" }[t]}</button>)}</div></div>
      <div className="detail">
        {tab === "source" && (src?.error ? <div className="note">{src.error}</div> : src ? <>
          <div className="toolbar"><span className="dim">{src.kind === "transformed" ? "Transformed source (real source-level change)" : "Original input (unchanged)"}</span>
            <button className="btn sm" onClick={copy}>Copy</button>
            <a className="btn sm" href={downloadUrl(exp.id, v.id, "source")}>Download</a></div>
          <div className="code"><CodeEditor value={src.source} readOnly language={exp.language} /></div></> : <div className="empty">Loading</div>)}
        {tab === "ir" && (ir?.error ? <div className="note">{ir.error}</div> : ir ? <>
          <div className="toolbar"><span className="dim">Post-optimisation LLVM IR for this configuration</span>
            <button className="btn sm" onClick={copy}>Copy</button>
            <a className="btn sm" href={downloadUrl(exp.id, v.id, "ir")}>Download .ll</a></div>
          <div className="code"><CodeEditor value={ir.ir} readOnly language="ll" /></div></> : <div className="empty">Generating IR</div>)}
        {tab === "passes" && <div className="pad">
          <p className="dim">{v.description}</p>
          <div className="kv"><span>Flags</span><code>{(v.flags || []).join(" ") || NA}</code></div>
          {v.pipeline && <div className="kv"><span>Pass pipeline</span><code className="wrap">{v.pipeline.slice(0, 600)}{v.pipeline.length > 600 ? "..." : ""}</code></div>}
          <div className="kv"><span>Techniques with a pass present</span><span>{(v.techniques || []).map((t) => <span key={t} className="tag">{t}</span>)}{!v.techniques?.length && "none"}</span></div>
          <div className="kv"><span>Compile time</span><span>{fmtMs(v.compile_time_ms)}</span></div>
          {v.applied_passes?.length > 0 && <details><summary>{v.applied_passes.length} top-level passes</summary><div className="passlist">{v.applied_passes.map((p, i) => <code key={i}>{p.slice(0, 90)}</code>)}</div></details>}
          {v.remarks?.length > 0 && <><h4>Vectorisation remarks (LLVM)</h4>{v.remarks.slice(0, 12).map((r, i) => <div key={i} className={`remark ${r.status}`}>line {r.line}: {r.message}</div>)}</>}
          {v.warnings?.map((w, i) => <div key={i} className="note">{w}</div>)}
        </div>}
        {tab === "benchmark" && <div className="pad">
          <div className="grid4">
            {[["Median", fmtMs(v.median_ms)], ["Mean", fmtMs(v.mean_ms)], ["Std-dev", fmtMs(v.stdev_ms)], ["IQR", fmtMs(v.iqr_ms)], ["Min", fmtMs(v.min_ms)], ["Max", fmtMs(v.max_ms)], ["Samples", v.benchmark_count ?? NA], ["Peak RSS", v.peak_rss_kb ? `${(v.peak_rss_kb / 1024).toFixed(1)} MB` : NA]].map(([k, x]) => <div key={k} className="stat"><div className="k">{k}</div><div className="v">{x}</div></div>)}
          </div>
          {v.failure_reason && <div className="note bad">{v.failure_reason}</div>}
          {v.duplicate_of && <div className="note">Machine code is byte-identical to {v.duplicate_of}, so it is not benchmarked separately.</div>}
          {v.samples_ms && <div className="dim small">Raw samples (ms): {v.samples_ms.map((x) => x.toFixed(2)).join(", ")}</div>}
        </div>}
      </div>
    </section>
  );
}

export function MLDecision({ exp }) {
  const p = exp.ml_prediction;
  if (!p) return null;
  return (
    <section className="panel minor">
      <div className="panel-h"><h3>ML decision</h3><span className={`tag ${p.is_ml ? "ml" : "warn"}`}>{p.is_ml ? `trained model ${p.model_version}` : "not ML, fallback order"}</span></div>
      <div className="pad">
        <p className="dim">{p.note}</p>
        <div className="kv"><span>Top pick</span><b>{p.top_pick}</b></div>
        <div className="kv"><span>Inference time</span><span>{p.inference_ms?.toFixed(1)} ms</span></div>
        <table className="tbl small"><thead><tr><th>Rank</th><th>Strategy</th><th className="r">{p.is_ml ? "Predicted time vs O2" : NA}</th><th className="r">Spread</th><th className="r">Measured</th></tr></thead>
          <tbody>{p.ranking.slice(0, 8).map((r) => {
            const v = exp.variants.find((x) => x.strategy_id === r.strategy_id);
            return <tr key={r.strategy_id}><td>{r.rank}</td><td>{r.strategy_id}</td><td className="r">{r.predicted_rel_time != null ? `${r.predicted_rel_time.toFixed(3)}×` : NA}</td><td className="r">{r.spread != null ? r.spread.toFixed(3) : NA}</td><td className="r">{v?.median_ms != null ? fmtMs(v.median_ms) : v?.duplicate_of ? `identical binary to ${v.duplicate_of}` : v ? "not measured" : "not evaluated"}</td></tr>;
          })}</tbody></table>
        {exp.report?.ml_pick && <div className="note">ML pick measured at {fmtMs(exp.report.ml_pick.median_ms)}, which is {exp.report.ml_pick.regret_vs_best_pct.toFixed(1)}% slower than the best measured variant{exp.report.ml_pick.vs_o2_speedup != null ? `; ${exp.report.ml_pick.vs_o2_speedup.toFixed(2)}× vs O2` : ""}.</div>}
        {p.explanation && <><h4>Features the model relies on</h4><div className="dim small">{p.explanation.method}. {p.explanation.caveat}</div>
          {p.explanation.top_features.map((f) => <div key={f.feature} className="fbar"><span>{f.feature}</span><div><i style={{ width: `${Math.min(100, f.importance * 300)}%` }} /></div><em>{f.value.toFixed(f.value % 1 ? 2 : 0)} ({f.relative} median)</em></div>)}</>}
      </div>
    </section>
  );
}

export function Complexity({ exp }) {
  const c = exp.complexity; const b = exp.variants.find((v) => v.is_baseline); const best = exp.variants.find((v) => v.id === exp.best_variant_id);
  if (!c) return null;
  return (
    <section className="panel minor"><div className="panel-h"><h3>Complexity analysis</h3></div>
      <div className="split pad">
        <div><h4>Algorithmic (heuristic estimate)</h4>
          <div className="kv"><span>Time</span><b>{c.time.estimate}</b></div><div className="kv"><span>Space</span><b>{c.space.estimate}</b></div>
          <div className="dim small">{c.method}</div>{c.time.reasons.map((r, i) => <div key={i} className="dim small">{r}</div>)}</div>
        <div><h4>Empirical (measured)</h4>
          <div className="kv"><span>Baseline</span><b>{fmtMs(b?.median_ms)}</b></div><div className="kv"><span>Fastest variant</span><b>{best ? `${best.strategy_id}: ${fmtMs(best.median_ms)}` : NA}</b></div>
          <div className="kv"><span>Speedup</span><b>{fmtX(best?.speedup)}</b></div>
          <div className="dim small">{c.note}</div></div>
      </div></section>
  );
}

export function WhatIf({ exp, onChange }) {
  const [data, setData] = useState(null); const [busy, setBusy] = useState(null); const [err, setErr] = useState("");
  useEffect(() => { api.whatif(exp.id).then(setData).catch(() => {}); }, [exp.id, exp.variants.length]);
  if (!data) return null;
  const run = async (id) => { setBusy(id); setErr(""); try { await api.whatifRun(exp.id, [id]); await onChange(); } catch (e) { setErr(e.message); } setBusy(null); };
  return (
    <section className="panel minor"><div className="panel-h"><h3>What-if: compare configurations</h3></div>
      <div className="pad"><div className="dim small">Measured values come from this experiment. Unmeasured configurations show no numbers until you run them.</div>
        {err && <div className="note bad">{err}</div>}
        <table className="tbl small"><thead><tr><th>Configuration</th><th>Flags / pipeline</th><th className="r">Median</th><th className="r">Speedup</th><th></th></tr></thead>
          <tbody>{data.strategies.map((s) => <tr key={s.id}><td><b>{s.id}</b></td><td className="dim">{s.flags.join(" ") || s.pipeline?.slice(0, 50)}</td>
            <td className="r">{s.measured ? fmtMs(s.median_ms) : s.duplicate_of ? `same as ${s.duplicate_of}` : <span className="dim">unmeasured</span>}</td><td className="r">{s.measured ? fmtX(s.speedup) : NA}</td>
            <td className="r">{!s.measured && !s.duplicate_of && s.available && s.status !== "skipped" && <button className="btn sm" disabled={busy != null} onClick={() => run(s.id)}>{busy === s.id ? "Measuring" : "Measure"}</button>}{!s.available && <span className="dim">{s.unavailable_reason}</span>}</td></tr>)}</tbody></table></div></section>
  );
}

export default function Results({ exp, reload }) {
  const [sel, setSel] = useState(null);
  useEffect(() => { setSel(exp.best_variant_id || exp.variants[0]?.id); }, [exp.id]);
  const v = exp.variants.find((x) => x.id === sel);
  const failed = exp.status !== "completed";
  return (
    <div className="results">
      <Banner r={exp} />
      <Summary exp={exp} />
      {!failed && exp.report?.notes?.map((n, i) => <div key={i} className="note">{n}</div>)}
      {!failed && exp.report?.skipped_strategies && Object.keys(exp.report.skipped_strategies).length > 0 && <div className="note">Unavailable strategies: {Object.entries(exp.report.skipped_strategies).map(([k, w]) => `${k} (${w})`).join("; ")}</div>}
      {exp.variants.length > 0 && <>
        <section className="panel main"><div className="panel-h"><h2>Performance</h2><Legend /></div><Charts variants={exp.variants} part="main" /></section>
        <section className="panel main"><div className="panel-h"><h2>Variants</h2><span className="dim small">Baseline plus {exp.variants.filter((x) => !x.is_baseline).length} candidates. Select a row to inspect it.</span></div>
          <VariantTable variants={exp.variants} selected={sel} onSelect={setSel} /></section>
        {v && <VariantDetail exp={exp} v={v} />}
        <details className="more"><summary>More charts: size, standard levels, noise</summary><Charts variants={exp.variants} part="minor" /></details>
        <details className="more"><summary>ML decision and complexity</summary><div className="stack"><MLDecision exp={exp} /><Complexity exp={exp} /></div></details>
        {exp.status === "completed" && <details className="more"><summary>What-if configurations</summary><WhatIf exp={exp} onChange={reload} /></details>}
        {exp.report && <details className="more"><summary>Measurement method</summary><div className="pad dim small">
          {exp.report.environment && <>Mode <b>{exp.report.environment.mode}</b>, {exp.report.environment.repetitions} repetitions plus {exp.report.environment.warmup} warm-up, {exp.report.environment.timer}. Platform {exp.report.environment.platform}; {exp.report.environment.clang}.<br /></>}
          Practical-tie tolerance {exp.report.noise_tie_pct}% (or IQR/2); reliability threshold {exp.report.reliable_min_ms} ms. {exp.report.empirical_note}</div></details>}
      </>}
    </div>
  );
}
