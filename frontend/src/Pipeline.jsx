import React from "react";
import { NA } from "./util.js";

const LABEL = { pending: "waiting", running: "running", completed: "done", failed: "failed", skipped: "skipped" };

export default function Pipeline({ stages, state, connection }) {
  return (
    <section className="panel minor">
      <div className="panel-h"><h3>Pipeline progress</h3>
        {connection && <span className={`tag ${connection === "live" ? "ok" : connection === "reconnecting" ? "warn" : ""}`}>{connection}</span>}
      </div>
      {!stages.length && <div className="empty">No stages reported yet.</div>}
      <ol className="stages">
        {stages.map((s, i) => {
          const st = state[s.id] || { status: "pending" };
          return (
            <li key={s.id} className={`stage ${st.status}`}>
              <span className="num">{i + 1}</span>
              <div className="body">
                <div className="name">{s.label}</div>
                {st.message && st.status !== "pending" && <div className="msg">{st.message}</div>}
                {st.logs?.map((l, j) => <div key={j} className="msg log">{l}</div>)}
              </div>
              <div className="state"><span className={`sq ${st.status}`} />{LABEL[st.status] || st.status}
                <span className="time">{st.elapsed_ms != null ? `${(st.elapsed_ms / 1000).toFixed(2)} s` : st.ts ? new Date(st.ts).toLocaleTimeString() : ""}</span></div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
