async function req(path, opts = {}) {
  const r = await fetch(path, opts);
  if (r.status === 204) return null;
  let body = null;
  try { body = await r.json(); } catch { /* non-json */ }
  if (!r.ok) {
    const e = body?.error || {};
    const err = new Error(e.message || `HTTP ${r.status}`);
    err.code = e.code; err.status = r.status; err.details = e.details; throw err;
  }
  return body;
}
const J = (method, data) => ({ method, headers: { "content-type": "application/json" }, body: JSON.stringify(data) });
export const api = {
  health: () => req("/api/health"),
  compiler: () => req("/api/compiler/status"),
  mlStatus: () => req("/api/ml/status"),
  mlMetrics: () => req("/api/ml/metrics"),
  train: (d) => req("/api/ml/train", J("POST", d)),
  samples: () => req("/api/samples"),
  sample: (n) => req(`/api/samples/${encodeURIComponent(n)}`),
  analyze: (d) => req("/api/analyze", J("POST", d)),
  upload: (file) => { const f = new FormData(); f.append("file", file); return req("/api/upload", { method: "POST", body: f }); },
  optimize: (d) => req("/api/optimize", J("POST", d)),
  cancel: (id) => req(`/api/experiments/${id}/cancel`, { method: "POST" }),
  results: (id) => req(`/api/experiments/${id}/results`),
  list: (q) => req(`/api/experiments?${new URLSearchParams(q)}`),
  remove: (id) => req(`/api/experiments/${id}`, { method: "DELETE" }),
  source: (id, v) => req(`/api/experiments/${id}/variants/${v}/source`),
  ir: (id, v) => req(`/api/experiments/${id}/variants/${v}/ir`),
  whatif: (id) => req(`/api/experiments/${id}/whatif`),
  whatifRun: (id, strategies) => req(`/api/experiments/${id}/whatif`, J("POST", { strategies })),
  stages: () => req("/api/pipeline/stages"),
};
export const downloadUrl = (id, v, kind) => `/api/experiments/${id}/variants/${v}/download?kind=${kind}`;
