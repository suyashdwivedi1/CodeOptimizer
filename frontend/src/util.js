export const NA = "n/a";
export const fmtMs = (v) => (v == null ? NA : v >= 100 ? `${v.toFixed(1)} ms` : v >= 1 ? `${v.toFixed(2)} ms` : `${(v * 1000).toFixed(0)} µs`);
export const fmtX = (v) => (v == null ? NA : `${v.toFixed(2)}×`);
export const fmtPct = (v) => (v == null ? NA : v === 0 ? "0.0%" : `${v > 0 ? "-" : "+"}${Math.abs(v).toFixed(1)}%`);
export const fmtBytes = (v) => (v == null ? NA : v > 1024 ? `${(v / 1024).toFixed(1)} KB` : `${v} B`);
export const fmtTime = (s) => (s ? new Date(s).toLocaleString() : NA);
export function download(name, text) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  a.download = name; a.click(); URL.revokeObjectURL(a.href);
}
export const EXT = { c: ".c", cpp: ".cpp" };
