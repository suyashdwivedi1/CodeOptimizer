import React from "react";
import { Bar, BarChart, CartesianGrid, Cell, ErrorBar, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

// One restrained palette. Blue marks the result that matters, orange marks the
// model's pick, everything else stays quiet.
const C = { base: "#9aa3ad", opt: "#a9c1de", win: "#0b5cad", ml: "#b45309", grid: "#e6e9ee", axis: "#5b6572", ink: "#14181f" };
const tt = {
  contentStyle: { background: "#fff", border: "1px solid #c9cfd6", borderRadius: 3, fontSize: 12, boxShadow: "none", color: "#14181f" },
  labelStyle: { color: "#14181f", fontWeight: 600 }, cursor: { fill: "#f3f5f8" }, isAnimationActive: false,
};

function Box({ title, note, children, minor }) {
  return <figure className={`chart ${minor ? "minor" : ""}`}><figcaption><span className="chart-t">{title}</span>{note && <span className="chart-n">{note}</span>}</figcaption>{children}</figure>;
}

export function Legend() {
  return <span className="legend"><i className="c-win" />winner <i className="c-ml" />model pick <i className="c-opt" />other variant <i className="c-base" />baseline</span>;
}

// Horizontal bar chart: category names stay readable and values line up on one axis.
export function HBar({ data, dataKey = "value", fmt = (v) => v, colorOf, refX, err, nameWidth = 100, height, axisUnit = "" }) {
  const h = height || Math.max(150, data.length * 30 + 54);
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 28, left: 4, bottom: 4 }} barCategoryGap="24%">
        <CartesianGrid stroke={C.grid} horizontal={false} />
        <XAxis type="number" stroke={C.grid} tick={{ fill: C.axis, fontSize: 11 }} tickFormatter={(v) => `${v}${axisUnit}`} domain={[0, "auto"]} />
        <YAxis type="category" dataKey="name" width={nameWidth} stroke={C.grid} tick={{ fill: C.ink, fontSize: 12 }} interval={0} />
        <Tooltip {...tt} formatter={(v) => fmt(+v)} />
        {refX != null && <ReferenceLine x={refX} stroke={C.axis} strokeDasharray="4 4" />}
        <Bar dataKey={dataKey} isAnimationActive={false} maxBarSize={22}>
          {data.map((d, i) => <Cell key={i} fill={colorOf ? colorOf(d) : C.win} />)}
          {err && <ErrorBar dataKey="err" direction="x" stroke={C.ink} width={4} />}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

const color = (d) => (d.v.is_winner ? C.win : d.v.is_baseline ? C.base : d.v.ml_selected ? C.ml : C.opt);
const measured = (variants) => variants.filter((v) => v.median_ms != null);

export default function Charts({ variants, part = "all" }) {
  const m = measured(variants);
  if (!m.length) return <div className="empty">No measurements to chart.</div>;
  const time = m.map((v) => ({ name: v.strategy_id, v, median: v.median_ms, err: [v.median_ms - v.min_ms, v.max_ms - v.median_ms] }));
  const sp = m.map((v) => ({ name: v.strategy_id, v, speedup: v.speedup }));
  const size = variants.filter((v) => v.binary_size).map((v) => ({ name: v.strategy_id, v, kb: v.binary_size / 1024 }));
  const levels = ["O0", "O1", "O2", "O3"].map((id) => m.find((v) => v.strategy_id === id)).filter(Boolean);
  const mlv = m.find((v) => v.ml_selected);
  const lv = levels.map((v) => ({ name: v.strategy_id, v, median: v.median_ms }));
  if (mlv && !levels.includes(mlv)) lv.push({ name: `ML: ${mlv.strategy_id}`, v: mlv, median: mlv.median_ms });
  else if (mlv) lv.forEach((d) => { if (d.v === mlv) d.name = `${d.name} (ML pick)`; });
  const vari = m.map((v) => ({ name: v.strategy_id, v, cv: v.median_ms ? (v.iqr_ms / v.median_ms) * 100 : 0 }));
  const ms = (v) => `${v.toFixed(2)} ms`;
  const main = part !== "minor", rest = part !== "main";
  return (
    <div className={`charts ${part === "main" ? "two" : ""}`}>
      {main && <>
        <Box title="Speedup over -O0" note="Higher is better. Dashed line is 1×, the baseline.">
          <HBar data={sp} dataKey="speedup" colorOf={color} fmt={(v) => `${v.toFixed(2)}×`} refX={1} axisUnit="×" />
        </Box>
        <Box title="Execution time" note="Median in milliseconds, whiskers show min to max. Lower is better.">
          <HBar data={time} dataKey="median" colorOf={color} fmt={ms} err axisUnit=" ms" />
        </Box>
      </>}
      {rest && <>
        <Box minor title="Executable size" note="Kilobytes of the linked binary, including runtime stubs.">
          <HBar data={size} dataKey="kb" colorOf={color} fmt={(v) => `${v.toFixed(2)} KB`} axisUnit=" KB" />
        </Box>
        <Box minor title="Standard levels against the ML pick" note={mlv ? "Median time. The pick comes from the trained model." : "No trained-model pick in this run."}>
          <HBar data={lv} dataKey="median" colorOf={color} fmt={ms} nameWidth={130} axisUnit=" ms" />
        </Box>
        <Box minor title="Measurement noise" note="Interquartile range as a percentage of the median. Higher means noisier.">
          <HBar data={vari} dataKey="cv" colorOf={() => C.base} fmt={(v) => `${v.toFixed(1)}%`} axisUnit="%" />
        </Box>
      </>}
    </div>
  );
}
export { Box as ChartBox, C as COLORS, tt as TOOLTIP };
