import {
  Area, Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { ForecastRow, RainfallPoint } from "../api/types";
import { day, num } from "../lib/format";

const axis = { stroke: "var(--av-faint)", fontSize: 11, tickLine: false, axisLine: false } as const;

function ChartTooltip({ active, payload, label, rows }: {
  active?: boolean; payload?: { name: string; value: unknown; color?: string }[]; label?: string;
  rows: (p: Record<string, unknown>) => [string, string][];
}) {
  if (!active || !payload?.length) return null;
  const datum = (payload[0] as unknown as { payload: Record<string, unknown> }).payload;
  return (
    <div className="rounded-xl border border-line bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium">{label}</div>
      {rows(datum).map(([k, v]) => (
        <div key={k} className="flex justify-between gap-4 text-muted"><span>{k}</span><span className="tabular-nums text-fg">{v}</span></div>
      ))}
    </div>
  );
}

/** p10–p90 band with the median line, per lead week. */
export function BandChart({ rows }: { rows: ForecastRow[] }) {
  const data = rows.map((r) => ({
    label: `Wk ${r.lead_week} · ${day(r.week_start)}`,
    band: [r.q10_mm, r.q90_mm] as [number, number],
    q10: r.q10_mm, q50: r.q50_mm, q90: r.q90_mm,
  }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
        <defs>
          <linearGradient id="band" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#16a34a" stopOpacity={0.28} />
            <stop offset="100%" stopColor="#16a34a" stopOpacity={0.08} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke="var(--av-line)" />
        <XAxis dataKey="label" {...axis} />
        <YAxis {...axis} unit=" mm" width={56} />
        <Tooltip cursor={{ stroke: "var(--av-line)" }}
          content={<ChartTooltip rows={(p) => [["90th pct", `${num(p.q90 as number, 1)} mm`], ["Median", `${num(p.q50 as number, 1)} mm`], ["10th pct", `${num(p.q10 as number, 1)} mm`]]} />} />
        <Area type="monotone" dataKey="band" stroke="none" fill="url(#band)" animationDuration={500} />
        <Line type="monotone" dataKey="q50" stroke="#15803d" strokeWidth={2} dot={{ r: 3, fill: "#15803d" }} animationDuration={500} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/** Observed daily rain (bars) against the daily normal (line). */
export function RainChart({ series }: { series: RainfallPoint[] }) {
  const data = series.map((p) => ({ label: day(p.date), rain: p.rain_mm ?? 0, normal: p.normal_mm ?? null }));
  return (
    <ResponsiveContainer width="100%" height={200}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
        <CartesianGrid vertical={false} stroke="var(--av-line)" />
        <XAxis dataKey="label" {...axis} interval="preserveStartEnd" minTickGap={24} />
        <YAxis {...axis} unit=" mm" width={56} />
        <Tooltip cursor={{ fill: "var(--av-subtle)" }}
          content={<ChartTooltip rows={(p) => [["Observed", `${num(p.rain as number, 1)} mm`], ["Normal", `${num(p.normal as number, 1)} mm`]]} />} />
        <Bar dataKey="rain" fill="#0ea5e9" radius={[3, 3, 0, 0]} animationDuration={500} />
        <Line type="monotone" dataKey="normal" stroke="var(--av-faint)" strokeDasharray="4 3" strokeWidth={1.5} dot={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
