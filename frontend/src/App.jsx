import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import CodeEditor from "./CodeEditor.jsx";
import Pipeline from "./Pipeline.jsx";
import Results, { Banner, Complexity, VariantTable, WhatIf } from "./Results.jsx";
import Charts, { HBar, Legend } from "./Charts.jsx";
import { COLORS } from "./Charts.jsx";
import { NA, fmtMs, fmtTime, fmtX } from "./util.js";
import site from "./site.config.js";

const DEFAULT_SRC = `#include <stdio.h>\n\nint main(void) {\n    long s = 0;\n    for (int i = 0; i < 1000; i++) s += i;\n    printf("%ld\\n", s);\n    return 0;\n}\n`;
const NAV = [["overview", "Overview"], ["optimizer", "Code optimizer"], ["analysis", "Analysis"], ["benchmarks", "Benchmarks"], ["history", "Experiment history"], ["ml", "ML model"], ["settings", "Settings"]];
const TITLES = Object.fromEntries(NAV);

export default function App() {
  const [page, setPage] = useState("optimizer");
  const [health, setHealth] = useState(null);
  const [ml, setMl] = useState(null);
  const [stages, setStages] = useState([]);
  const [src, setSrc] = useState(DEFAULT_SRC);
  const [lang, setLang] = useState("c");
  const [filename, setFilename] = useState(null);
  const [stdin, setStdin] = useState("");
  const [mode, setMode] = useState("quick");
  const [useMl, setUseMl] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [samples, setSamples] = useState([]);
  const [analysis, setAnalysis] = useState(null);
  const [exp, setExp] = useState(null);
  const [expId, setExpId] = useState(null);
  const [pstate, setPstate] = useState({});
  const [conn, setConn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const esRef = useRef(null);

  useEffect(() => { document.title = `${TITLES[page]} | ${site.siteName}`; }, [page]);
  const refreshStatus = useCallback(() => { api.health().then(setHealth).catch(() => setHealth(null)); api.mlStatus().then(setMl).catch(() => {}); }, []);
  useEffect(() => { refreshStatus(); api.stages().then(setStages).catch(() => {}); api.samples().then(setSamples).catch(() => {}); const t = setInterval(refreshStatus, 15000); return () => clearInterval(t); }, []);
  useEffect(() => { const h = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } }; window.addEventListener("beforeunload", h); return () => window.removeEventListener("beforeunload", h); }, [dirty]);

  const confirmDiscard = () => !dirty || window.confirm("You have unsaved edits in the editor. Replace them?");
  const setSource = (s, l, f) => { setSrc(s); if (l) setLang(l); setFilename(f ?? null); setDirty(false); setAnalysis(null); };

  const loadSample = async (name) => { if (!name || !confirmDiscard()) return; try { const s = await api.sample(name); setSource(s.source, s.language, s.name); setStdin(s.stdin || ""); } catch (e) { setError(e.message); } };
  const upload = async (file) => { if (!file || !confirmDiscard()) return; setError(""); try { const r = await api.upload(file); setSource(r.source, r.language, r.filename); } catch (e) { setError(`Upload rejected: ${e.message}`); } };
  const clear = () => { if (confirmDiscard()) { setSource("", null, null); } };
  const reset = () => { if (!confirmDiscard()) return; closeEs(); setSource(DEFAULT_SRC, "c", null); setStdin(""); setExp(null); setExpId(null); setPstate({}); setConn(""); setError(""); };

  const runAnalysis = async () => {
    setError(""); setBusy(true);
    try { const a = await api.analyze({ source: src, language: lang, filename }); setAnalysis(a); if (a.compilation_status === "error") setError("Compilation failed. See the diagnostics in the editor and on the Analysis page."); }
    catch (e) { setError(e.message); } setBusy(false);
  };

  const closeEs = () => { esRef.current?.close(); esRef.current = null; };
  const loadResults = async (id) => { const r = await api.results(id); setExp(r); setAnalysis(r.analysis || null); return r; };

  const subscribe = (id) => {
    closeEs(); setConn("connecting");
    const es = new EventSource(`/api/experiments/${id}/events`); esRef.current = es;
    es.onopen = () => setConn("live");
    es.onerror = () => setConn(es.readyState === EventSource.CLOSED ? "disconnected" : "reconnecting");
    es.addEventListener("progress", (m) => {
      const ev = JSON.parse(m.data);
      if (ev.stage === "experiment") { es.close(); setConn("finished"); setBusy(false); loadResults(id).then(refreshStatus); return; }
      setPstate((p) => {
        const cur = p[ev.stage] || { logs: [] };
        if (ev.status === "info") return { ...p, [ev.stage]: { ...cur, logs: [...(cur.logs || []), ev.message] } };
        return { ...p, [ev.stage]: { ...cur, status: ev.status, message: ev.message, elapsed_ms: ev.elapsed_ms, ts: ev.ts } };
      });
    });
  };

  const optimize = async () => {
    setError(""); setExp(null); setPstate({}); setBusy(true);
    try {
      const r = await api.optimize({ source: src, language: lang, filename, stdin, mode, use_ml: useMl, label: filename || "editor" });
      setExpId(r.experiment_id); subscribe(r.experiment_id);
    } catch (e) { setError(e.message); setBusy(false); }
  };
  const cancel = async () => { try { await api.cancel(expId); } catch (e) { setError(e.message); } };
  const openExperiment = async (id) => {
    setExpId(id); setPstate({}); const r = await loadResults(id); setSrc(r.source); setLang(r.language); setStdin(r.stdin || ""); setFilename(r.filename); setDirty(false);
    const ev = {}; try { const text = await fetch(`/api/experiments/${id}/events`).then((x) => x.text()); text.split("\n\n").forEach((blk) => { const l = blk.split("\n").find((z) => z.startsWith("data: ")); if (l) { const e = JSON.parse(l.slice(6)); if (e.stage !== "experiment" && e.status !== "info") ev[e.stage] = { status: e.status, message: e.message, elapsed_ms: e.elapsed_ms, ts: e.ts, logs: [] }; } }); } catch {}
    setPstate(ev); setConn(""); setPage("optimizer");
  };

  const diag = analysis?.diagnostics || [];
  const mlLabel = ml ? (ml.available ? `ML model ${ml.version}` : "ML model not trained (baseline mode)") : "ML model unknown";
  const compilerOk = health?.compiler?.available;

  return (
    <div className="app">
      <aside className="side">
        <div className="brand"><span className="mark" aria-hidden="true"><i /><i /><i /></span><div><b>{site.siteName}</b></div></div>
        <nav aria-label="Sections">{NAV.map(([id, label]) => <button key={id} className={page === id ? "on" : ""} aria-current={page === id ? "page" : undefined} onClick={() => setPage(id)}>{label}</button>)}</nav>
        <div className="side-f">
          <div>Clang/LLVM and scikit-learn</div>
          <div className="legal"><a href="#/privacy">Privacy policy</a><a href="#/terms">Terms and conditions</a></div>
        </div>
      </aside>
      <div className="main">
        <header className="top">
          <ul className="status" aria-label="System status">
            <li><span className={`sq ${compilerOk ? "completed" : "failed"}`} />{compilerOk ? (health.compiler.version?.replace(/\(.*\)/, "").trim() || "Compiler ready") : "Compiler missing"}</li>
            <li><span className={`sq ${ml?.available ? "ml" : "skipped"}`} />{mlLabel}</li>
            <li><span className="sq pending" />{expId ? `Experiment ${expId}` : "No experiment open"}</li>
          </ul>
        </header>
        <main className="content">
          <h1>{TITLES[page]}</h1>
          {error && <div className="banner bad"><div>{error}</div><button className="x" aria-label="Dismiss" onClick={() => setError("")}>Dismiss</button></div>}
          {page === "overview" && <Overview health={health} ml={ml} go={setPage} open={openExperiment} />}
          {page === "optimizer" && (
            <>
              <div className="warn-strip">Programs are compiled and executed natively on the host machine. Timeouts and temporary directories are not a security sandbox, so only submit code you trust.</div>
              <div className="opt-top">
                <section className="panel main editor-panel">
                  <div className="panel-h"><h2>Source{filename ? `: ${filename}` : ""}{dirty && <span className="tag warn">edited</span>}</h2>
                    <div className="row">
                      <select aria-label="Language" value={lang} onChange={(e) => setLang(e.target.value)}><option value="c">C</option><option value="cpp">C++</option></select>
                      <select aria-label="Sample program" value="" onChange={(e) => loadSample(e.target.value)}><option value="">Sample program</option>{samples.map((s) => <option key={s.name} value={s.name}>{s.title}</option>)}</select>
                      <label className="btn sm">Upload file<input type="file" hidden accept=".c,.cpp,.cc,.cxx" onChange={(e) => { upload(e.target.files[0]); e.target.value = ""; }} /></label>
                      <button className="btn sm" onClick={clear}>Clear</button>
                    </div></div>
                  <div className="drop" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files[0]); }}>
                    <CodeEditor value={src} language={lang} markers={diag} onChange={(v) => { setSrc(v); setDirty(true); }} />
                  </div>
                  <div className="panel-f">
                    <textarea className="stdin" aria-label="Program input" placeholder="Program input (optional, identical for every variant)" value={stdin} onChange={(e) => setStdin(e.target.value)} rows={1} />
                    <select aria-label="Benchmark mode" value={mode} onChange={(e) => setMode(e.target.value)}><option value="quick">Quick (few repetitions)</option><option value="rigorous">Rigorous (many repetitions)</option></select>
                    <label className="chk" title="Turn off to see the non-ML fallback order"><input type="checkbox" checked={useMl} onChange={(e) => setUseMl(e.target.checked)} />Use ML</label>
                    <span className="grow" />
                    <button className="btn" disabled={busy} onClick={runAnalysis}>Run analysis</button>
                    <button className="btn" onClick={reset}>Reset</button>
                    {busy && expId && conn !== "" && conn !== "finished" ? <button className="btn danger" onClick={cancel}>Cancel run</button> : <button className="btn primary" disabled={busy} onClick={optimize}>Optimize code</button>}
                  </div>
                </section>
                <div className="col">
                  <Pipeline stages={stages} state={pstate} connection={conn} />
                  <AnalysisSummary a={analysis} compact />
                </div>
              </div>
              {exp ? <Results exp={exp} reload={() => loadResults(exp.id)} /> : <div className="empty big">Choose Optimize code to compile, optimise, verify and benchmark the program. Results and charts appear here.</div>}
            </>
          )}
          {page === "analysis" && <AnalysisPage a={analysis} run={runAnalysis} busy={busy} />}
          {page === "benchmarks" && <BenchPage exp={exp} reload={() => exp && loadResults(exp.id)} />}
          {page === "history" && <HistoryPage open={openExperiment} />}
          {page === "ml" && <MLPage ml={ml} refresh={refreshStatus} />}
          {page === "settings" && <SettingsPage />}
        </main>
      </div>
    </div>
  );
}

function Stat({ k, v, tone }) { return <div className={`stat ${tone || ""}`}><div className="k">{k}</div><div className="v">{v ?? NA}</div></div>; }

function AnalysisSummary({ a, compact }) {
  if (!a) return <section className="panel minor"><div className="panel-h"><h3>Analysis summary</h3></div><div className="empty">Run analysis or optimize to see compiler-derived features.</div></section>;
  const f = a.features || {};
  return (
    <section className="panel minor"><div className="panel-h"><h3>Analysis summary</h3><span className={`tag ${a.compilation_status === "ok" ? "ok" : "bad"}`}>{a.compilation_status}</span></div>
      <div className="pad">
        {a.compilation_status === "error" && a.diagnostics.map((d, i) => <div key={i} className={`remark ${d.severity === "error" ? "missed" : ""}`}>{d.file}:{d.line}:{d.col} {d.severity}: {d.message}</div>)}
        {a.compilation_status === "ok" && <>
          <div className="grid4">
            <Stat k="Language" v={a.language?.toUpperCase()} /><Stat k="Lines" v={a.source_lines} /><Stat k="Functions (est.)" v={f.src_functions} />
            <Stat k="Loops (IR)" v={a.loops?.ir_count ?? `${a.loops?.source_count_heuristic} est.`} /><Stat k="Max loop depth" v={a.loops?.ir_max_depth ?? a.loops?.source_max_depth_heuristic} />
            <Stat k="Cond. branches (IR)" v={f.ir_cond_br} /><Stat k="IR instructions" v={f.ir_instr} /><Stat k="Loads/Stores" v={`${f.ir_loads ?? NA}/${f.ir_stores ?? NA}`} />
          </div>
          <div className="dim small">Compiler: {a.compiler_version}. Values marked IR come from LLVM. Values marked est. are lexer heuristics.</div>
          {a.opportunities?.length > 0 && <><h4>Detected opportunities</h4>{a.opportunities.map((o, i) => <div key={i} className="opp"><b>{o.title}</b> <span className="tag">{o.kind}</span><div className="dim small">{o.evidence}</div></div>)}</>}
          {a.warnings?.map((w, i) => <div key={i} className="note">{w}</div>)}
          {a.diagnostics?.filter((d) => d.severity === "warning").slice(0, compact ? 3 : 20).map((d, i) => <div key={i} className="note">line {d.line}: {d.message}</div>)}
        </>}
      </div></section>
  );
}

function AnalysisPage({ a, run, busy }) {
  if (!a) return <div className="empty big">No analysis yet. <button className="btn" onClick={run} disabled={busy}>Analyse the editor contents</button></div>;
  const ir = a.ir_stats || {};
  return (<div className="stack">
    <AnalysisSummary a={a} />
    {a.compilation_status === "ok" && <>
      <section className="panel minor"><div className="panel-h"><h3>Feature vector (schema v{a.feature_schema_version})</h3></div><div className="pad"><div className="dim small">{Object.entries(a.metric_provenance || {}).map(([k, v]) => `${k}: ${v}`).join(" · ")}</div>
        <div className="grid4">{Object.entries(a.features).map(([k, v]) => <Stat key={k} k={k} v={typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(3)) : v} />)}</div></div></section>
      <section className="panel minor"><div className="panel-h"><h3>LLVM IR statistics (O0 IR, mem2reg)</h3></div><div className="pad"><div className="grid4">{Object.entries(ir).map(([k, v]) => <Stat key={k} k={k} v={v} />)}</div>
        <div className="dim small">IR instructions at -O0: {a.o0_ir_instructions ?? NA}, at -O2: {a.o2_ir_instructions ?? NA}</div></div></section>
      <section className="panel"><div className="panel-h"><h2>Vectorisation diagnostics (clang -O3 remarks)</h2></div><div className="pad">
        {a.vectorization_remarks?.length ? a.vectorization_remarks.map((r, i) => <div key={i} className={`remark ${r.status}`}>line {r.line}: {r.message}</div>) : <div className="dim">No loop-vectoriser remarks were produced.</div>}</div></section>
      <Complexity exp={{ complexity: a.complexity, variants: [], best_variant_id: null }} />
    </>}
  </div>);
}

function BenchPage({ exp, reload }) {
  if (!exp || !exp.variants?.length) return <div className="empty big">Run an optimisation, or open one from history, to see benchmark data.</div>;
  return (<div className="stack"><Banner r={exp} />
    <section className="panel main"><div className="panel-h"><h2>Performance</h2><Legend /></div><Charts variants={exp.variants} part="main" /></section>
    <section className="panel main"><div className="panel-h"><h2>Benchmark results for {exp.id}</h2></div><VariantTable variants={exp.variants} selected={null} onSelect={() => {}} /></section>
    <section className="panel minor"><div className="panel-h"><h3>Size, standard levels and noise</h3></div><Charts variants={exp.variants} part="minor" /></section>
    {exp.status === "completed" && <WhatIf exp={exp} onChange={reload} />}</div>);
}

function HistoryPage({ open }) {
  const [data, setData] = useState({ items: [], total: 0 }); const [q, setQ] = useState(""); const [sort, setSort] = useState("created_desc"); const [status, setStatus] = useState(""); const [lang, setLang] = useState(""); const [offset, setOffset] = useState(0);
  const load = () => { const p = { limit: 15, offset, sort }; if (q) p.q = q; if (status) p.status = status; if (lang) p.language = lang; api.list(p).then(setData).catch(() => {}); };
  useEffect(load, [q, sort, status, lang, offset]);
  const del = async (id) => { if (!window.confirm(`Delete ${id} and its files?`)) return; try { await api.remove(id); load(); } catch (e) { alert(e.message); } };
  return (<section className="panel main"><div className="panel-h"><h2>{data.total} experiments</h2>
    <div className="row"><input aria-label="Filter" placeholder="Filter by label, id or strategy" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
      <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option><option>completed</option><option>failed</option><option>cancelled</option></select>
      <select aria-label="Language" value={lang} onChange={(e) => setLang(e.target.value)}><option value="">C and C++</option><option value="c">C</option><option value="cpp">C++</option></select>
      <select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)}><option value="created_desc">Newest</option><option value="created_asc">Oldest</option><option value="speedup_desc">Best speedup</option><option value="baseline_desc">Slowest baseline</option></select></div></div>
    <div className="tablewrap"><table className="tbl"><thead><tr><th>Label</th><th>Best strategy</th><th className="r key">Speedup</th><th className="r">Baseline</th><th className="r">Best time</th><th>Status</th><th>Date</th><th>ML pick</th><th>Lang</th><th>ID</th><th></th></tr></thead>
      <tbody>{data.items.map((e) => <tr key={e.id} onClick={() => open(e.id)}><td><b>{e.label}</b></td><td>{e.best_strategy || NA}</td><td className="r key">{fmtX(e.best_speedup)}</td>
        <td className="r dim">{fmtMs(e.baseline_median_ms)}</td><td className="r">{fmtMs(e.best_median_ms)}</td><td><span className={`tag ${e.status === "completed" ? "ok" : "bad"}`}>{e.status}</span></td>
        <td className="dim">{fmtTime(e.created_at)}</td><td className="dim">{e.selected_strategy || NA}{e.ml_source && e.ml_source !== "trained-model" && <span className="tag warn">fallback</span>}</td><td className="dim">{e.language}</td><td className="mono dim">{e.id}</td>
        <td onClick={(ev) => ev.stopPropagation()}><button className="btn sm" onClick={() => del(e.id)}>Delete</button></td></tr>)}
        {!data.items.length && <tr><td colSpan={11} className="empty">No experiments yet.</td></tr>}</tbody></table></div>
    <div className="panel-f"><button className="btn sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 15))}>Previous</button><span className="dim small">{data.total ? offset + 1 : 0} to {Math.min(offset + 15, data.total)} of {data.total}</span><button className="btn sm" disabled={offset + 15 >= data.total} onClick={() => setOffset(offset + 15)}>Next</button></div></section>);
}

function MLPage({ ml, refresh }) {
  const [m, setM] = useState(null); const [mode, setMode] = useState("quick"); const [err, setErr] = useState("");
  const load = () => api.mlMetrics().then(setM).catch(() => setM(null));
  useEffect(() => { load(); }, [ml?.version]);
  const job = ml?.training_job;
  useEffect(() => { if (job?.state !== "running") return; const t = setInterval(() => { refresh(); }, 2000); return () => clearInterval(t); }, [job?.state]);
  const train = async () => { setErr(""); try { await api.train({ mode }); refresh(); } catch (e) { setErr(e.message); } };
  const cv = m?.metrics?.cross_validation;
  const imp = m ? Object.entries(m.feature_importances).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([name, value]) => ({ name, value })) : [];
  const dist = cv?.oracle_label_distribution ? Object.entries(cv.oracle_label_distribution).map(([name, value]) => ({ name, value })) : [];
  return (<div className="stack">
    {cv?.available && <section className="panel main"><div className="panel-h"><h2>Held-out evaluation</h2><span className="dim small">{cv.method}; {cv.n_programs} programs, {cv.n_families} families</span></div><div className="pad">
      <div className={`note ${cv.verdict.includes("NOT") || cv.verdict.includes("indistinguishable") ? "" : "ok"}`}><b>{cv.verdict}.</b> Evidence for any claim comes only from these out-of-family measurements. Near-optimal means within 3% of the best measured candidate.</div>
      <div className="tablewrap"><table className="tbl"><thead><tr><th>Policy</th><th className="r key">Near-optimal</th><th className="r key">Beats O2</th><th className="r">Top-1</th><th className="r">Mean regret</th><th className="r">Median speedup vs O0</th><th className="r">Worse than O2</th></tr></thead>
        <tbody>{Object.values(cv.strategies).map((s) => <tr key={s.name}><td><b>{s.name}</b></td><td className="r key">{(s.near_optimal_rate * 100).toFixed(0)}%</td><td className="r key">{s.beats_O2_pct.toFixed(0)}%</td><td className="r">{(s.top1_accuracy * 100).toFixed(0)}%</td><td className="r">{s.mean_regret_pct.toFixed(1)}%</td><td className="r">{s.median_speedup_vs_O0.toFixed(2)}×</td><td className="r">{s.worse_than_O2_pct.toFixed(0)}%</td></tr>)}</tbody></table></div>
      <div className="dim small">Inference time {cv.inference_ms.toFixed(1)} ms per program. The oracle is the best measured candidate, an upper bound and not a prediction. Top-3 near-optimal rate: {(cv.strategies.ml.top3_near_optimal_rate * 100).toFixed(0)}%.</div></div></section>}
    {m && <div className="charts">
      <figure className="chart"><figcaption><span className="chart-t">Feature importance</span><span className="chart-n">Impurity-based and global. Shows what the model relies on, not causation.</span></figcaption><HBar data={imp} fmt={(v) => v.toFixed(3)} nameWidth={150} /></figure>
      {dist.length > 0 && <figure className="chart"><figcaption><span className="chart-t">Training data: best strategy per program</span><span className="chart-n">Number of programs for which each strategy was fastest. Ties go to the first.</span></figcaption><HBar data={dist} fmt={(v) => `${v} programs`} colorOf={() => COLORS.opt} nameWidth={100} /></figure>}
    </div>}
    <section className="panel minor"><div className="panel-h"><h3>Model status</h3><span className={`tag ${ml?.available ? "ml" : "warn"}`}>{ml?.label || "unknown"}</span></div><div className="pad">
      {!ml?.available && <div className="note">No usable trained model, so the optimizer runs in baseline mode (fixed candidate order, labelled as not ML). Train one below or run <code>python -m backend.ml.train --data-dir data/benchmarks --output-dir artifacts</code>.</div>}
      {m && <div className="grid4"><Stat k="Version" v={m.version} /><Stat k="Trained" v={fmtTime(m.trained_at)} /><Stat k="Programs" v={m.n_programs} /><Stat k="Samples (program × strategy)" v={m.dataset_size} /><Stat k="Model" v="Random forest (regression and ranking)" /><Stat k="Feature schema" v={`v${m.feature_schema_version}`} /><Stat k="Features" v={m.feature_names.length} /><Stat k="Training mode" v={m.training_mode} /></div>}
      <div className="row" style={{ marginTop: 12 }}><select aria-label="Training mode" value={mode} onChange={(e) => setMode(e.target.value)}><option value="quick">Quick (36 programs, about 4 min)</option><option value="full">Full (72 programs, 15 min or more)</option></select>
        <button className="btn" disabled={job?.state === "running"} onClick={train}>{ml?.available ? "Retrain" : "Train"} model</button></div>
      {err && <div className="note bad">{err}</div>}
      {job?.state === "running" && <div className="note">Training: {job.stage} {job.done}/{job.total}. {job.message}. Benchmarks are timing-sensitive, so avoid running other heavy work.</div>}
      {job?.state === "failed" && <div className="note bad">{job.error}</div>}
    </div></section>
  </div>);
}

function SettingsPage() {
  const [c, setC] = useState(null);
  useEffect(() => { api.compiler().then(setC).catch(() => {}); }, []);
  if (!c) return <div className="empty big">Loading compiler status</div>;
  return (<div className="stack">
    <section className="panel"><div className="panel-h"><h2>Toolchain (auto-detected)</h2><button className="btn sm" onClick={() => api.compiler().then(setC)}>Refresh</button></div><div className="pad">
      {c.problems?.map((p, i) => <div key={i} className="note bad">{p}</div>)}
      <table className="tbl small"><thead><tr><th>Tool</th><th>Status</th><th>Path</th><th>Version</th></tr></thead><tbody>{Object.entries(c.tools).map(([k, t]) => <tr key={k}><td>{k}</td><td><span className={`tag ${t.available ? "ok" : "bad"}`}>{t.available ? "found" : "missing"}</span></td><td className="mono dim">{t.path || NA}</td><td className="dim">{t.version?.split("\n")[0]}</td></tr>)}</tbody></table>
      <div className="dim small">Override with CLANG_PATH or LLVM_BIN_DIR in .env (see .env.example).</div></div></section>
    <section className="panel minor"><div className="panel-h"><h3>Optimisation strategies</h3></div><div className="pad"><table className="tbl small"><thead><tr><th>ID</th><th>Kind</th><th>Flags / pipeline</th><th>Available</th></tr></thead><tbody>{c.strategies.map((s) => <tr key={s.id}><td><b>{s.id}</b></td><td>{s.kind}</td><td className="mono dim">{s.flags.join(" ") || s.pipeline?.slice(0, 70)}</td><td>{s.available ? <span className="tag ok">yes</span> : <span className="tag bad" title={s.unavailable_reason}>{s.unavailable_reason}</span>}</td></tr>)}</tbody></table></div></section>
    <section className="panel minor"><div className="panel-h"><h3>Limits and safety</h3></div><div className="pad"><div className="grid4">{Object.entries(c.limits).map(([k, v]) => <Stat key={k} k={k} v={v} />)}</div><div className="note">{c.isolation_warning}</div></div></section>
  </div>);
}

function Overview({ health, ml, go, open }) {
  const [recent, setRecent] = useState(null);
  useEffect(() => { api.list({ limit: 20, sort: "created_desc" }).then((d) => setRecent(d.items)).catch(() => setRecent([])); }, []);
  const done = (recent || []).filter((e) => e.status === "completed" && e.best_speedup != null);
  const speed = done.slice(0, 10).reverse().map((e) => ({ name: (e.label || e.id).slice(0, 16), value: +e.best_speedup.toFixed(3) }));
  const counts = {}; done.forEach((e) => { if (e.best_strategy) counts[e.best_strategy] = (counts[e.best_strategy] || 0) + 1; });
  const wins = Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([name, value]) => ({ name, value }));
  return (<div className="stack">
    <section className="panel main"><div className="panel-h"><h2>Speedup over -O0, latest experiments</h2><button className="btn primary sm" onClick={() => go("optimizer")}>Open code optimizer</button></div>
      {recent === null ? <div className="empty">Loading</div> : speed.length ? <div className="pad"><HBar data={speed} fmt={(v) => `${v.toFixed(2)}×`} refX={1} axisUnit="×" nameWidth={130} /><div className="dim small">One bar per completed experiment, newest at the bottom. Dashed line is the -O0 baseline.</div></div> : <div className="empty">No completed experiments yet. Run one from the code optimizer and the chart fills in from the real measurements.</div>}
    </section>
    <div className="two-col">
      <section className="panel"><div className="panel-h"><h2>Winning strategies</h2></div>
        {wins.length ? <div className="pad"><HBar data={wins} fmt={(v) => `${v} experiments`} colorOf={() => COLORS.opt} /><div className="dim small">Which strategy was fastest, across the experiments shown above.</div></div> : <div className="empty">Nothing to chart yet.</div>}</section>
      <section className="panel"><div className="panel-h"><h2>Recent experiments</h2><button className="btn sm" onClick={() => go("history")}>All history</button></div>
        <div className="tablewrap"><table className="tbl"><tbody>{(recent || []).slice(0, 6).map((e) => <tr key={e.id} onClick={() => open(e.id)}><td><b>{e.label}</b></td><td>{e.best_strategy || NA}</td><td className="r key">{fmtX(e.best_speedup)}</td><td><span className={`tag ${e.status === "completed" ? "ok" : "bad"}`}>{e.status}</span></td></tr>)}{recent && !recent.length && <tr><td className="empty">No experiments yet.</td></tr>}</tbody></table></div></section>
    </div>
    <section className="panel minor"><div className="panel-h"><h3>How a run works</h3></div><ol className="steps">
      {["Source goes in", "Clang produces LLVM IR", "Features are extracted", "The model ranks strategies", "At least four distinct variants are built", "Each output is checked against -O0", "Variants are benchmarked (median and IQR)", "The measured winner is reported"].map((s, i) => <li key={i}>{s}</li>)}
    </ol><div className="pad dim small">The winner comes only from measured, correct, non-duplicate variants. Close results are reported as a practical tie.</div></section>
    <section className="panel minor"><div className="panel-h"><h3>System</h3></div><div className="pad"><div className="grid4">
      <Stat k="Backend" v={health ? health.status : "offline"} tone={health ? "ok" : "bad"} /><Stat k="Compiler" v={health?.compiler?.available ? health.compiler.version?.replace(/\(.*\)/, "") : "missing"} tone={health?.compiler?.available ? "ok" : "bad"} />
      <Stat k="IR pass pipelines" v={health?.compiler?.ir_pipelines ? "available" : "unavailable"} /><Stat k="ML model" v={ml?.available ? ml.version : "not trained"} tone={ml?.available ? "ok" : "warn"} /></div></div></section>
  </div>);
}
