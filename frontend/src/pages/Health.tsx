import { motion } from "framer-motion";
import { Activity, CheckCircle2, CircleAlert, Database, FlaskConical, XCircle } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PipelineHealth, SkillRow } from "../api/types";
import {
  Card, CardHeader, Chip, CountUp, cx, fadeUp, Page, PageTitle, RetryState, Skeleton, SkeletonLines, stagger, Tooltip,
} from "../components/ui";
import { longDate, num, timeAgo } from "../lib/format";

const TARGETS = [
  { key: "tercile", label: "Tercile (below/normal/above)", metric: "rpss", metricLabel: "RPSS" },
  { key: "heavy_day", label: "Heavy-rain day (≥ 64.5 mm)", metric: "bss", metricLabel: "BSS" },
  { key: "dry_week", label: "Fully dry week", metric: "bss", metricLabel: "BSS" },
  { key: "weekly_total_mm", label: "Weekly total (quantiles)", metric: "qss", metricLabel: "QSS" },
];
const SEASONS = [
  { key: "ALL", label: "All seasons" },
  { key: "SWM", label: "SW monsoon (Jun–Sep)" },
  { key: "NEM", label: "NE monsoon (Oct–Dec)" },
];
// Order of pipeline stages from ingestion to forecast.
const STAGES = ["boundaries", "rainfall", "indices", "aggregate", "climatology", "features", "quality", "ml:validate", "ml:train", "ml:predict"];

export default function Health() {
  const health = useQuery({ queryKey: ["pipeline-health"], queryFn: api.pipelineHealth, refetchInterval: 30_000 });
  const skill = useQuery({ queryKey: ["model-skill"], queryFn: () => api.modelSkill({ model: "lgbm" }) });
  const h = health.data;

  return (
    <Page>
      <PageTitle title="System health"
        subtitle="Live status of the data pipeline (Segment 1) and the validated forecast model (Segment 2)."
        right={h && <StatusPill status={h.status} />} />

      <Card className="p-5">
        <p className="mb-4 flex items-center gap-1.5 text-[13px] font-medium"><Activity className="h-4 w-4 text-muted" /> Pipeline stages · latest run of each</p>
        {h ? <StageDots runs={h.recent_runs} /> : <Skeleton className="h-14" />}
      </Card>

      <motion.div variants={stagger} className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {h ? (
          <>
            <Metric label="Daily rainfall rows" value={h.table_counts.rainfall_daily} foot="IMD 0.25° grid → 38 districts, 1991 →" />
            <Metric label="Feature rows" value={h.table_counts.features_daily} foot="rolling sums, anomalies, MJO/ONI/DMI" />
            <Metric label="Forecast rows" value={h.table_counts.forecasts} foot={`latest run ${longDate(h.forecasts.latest_issue_date)}`} />
            <Metric label="Rainfall freshness" value={h.rainfall.lag_days ?? 0} format={(n) => `${Math.round(n)} day${Math.round(n) === 1 ? "" : "s"}`}
              foot={`last observed day ${longDate(h.rainfall.last_date)}`} />
          </>
        ) : Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-28" />)}
      </motion.div>

      <Card className="mt-4">
        <CardHeader icon={<FlaskConical className="h-4 w-4" />} title="Validated model skill"
          subtitle={skill.data ? <>Model <span className="font-mono">{skill.data.model_version}</span> · trained {skill.data.meta.trained?.slice(0, 10)} on {skill.data.meta.train_years?.join("–")} · {skill.data.meta.n_features} features</> : "Loading…"}
          right={<Chip title={skill.data?.note}>vs climatology · 5–95% CI</Chip>} />
        <div className="px-5 pb-5">
          {skill.data ? <SkillTable rows={skill.data.rows} /> : skill.isError ? <RetryState onRetry={() => skill.refetch()} /> : <SkeletonLines n={8} />}
        </div>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader icon={<CheckCircle2 className="h-4 w-4" />} title="Data quality checks"
            subtitle={h ? `${h.quality.summary.pass} pass · ${h.quality.summary.warn} warn · ${h.quality.summary.fail} fail · report ${h.quality.report_generated ?? ""}` : "…"} />
          <div className="px-5 pb-5">
            {h ? (
              <motion.ul initial="hidden" animate="show" variants={stagger} className="divide-y divide-line">
                {h.quality.checks.map((c) => (
                  <motion.li key={c.check} variants={fadeUp} className="flex gap-3 py-2 text-[13px]">
                    {c.status === "PASS" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-accent-600" />
                      : c.status === "WARN" ? <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                        : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />}
                    <div><p className="font-medium">{c.check}</p><p className="text-muted">{c.detail}</p></div>
                  </motion.li>
                ))}
              </motion.ul>
            ) : <SkeletonLines n={6} />}
          </div>
        </Card>
        <Card>
          <CardHeader icon={<Database className="h-4 w-4" />} title="Recent pipeline runs" subtitle="From the pipeline_runs table" />
          <div className="px-5 pb-5">
            {h ? (
              <motion.ul initial="hidden" animate="show" variants={stagger} className="divide-y divide-line">
                {h.recent_runs.map((r) => (
                  <motion.li key={r.id} variants={fadeUp} className="py-2 text-[13px]">
                    <div className="flex items-center gap-2">
                      <span className={cx("h-2 w-2 rounded-full", r.status === "success" ? "bg-accent-600" : r.status === "failed" ? "bg-red-500" : "bg-amber-500")} />
                      <span className="font-mono text-[12px]">{r.stage}</span>
                      <span className="text-muted">{r.status}</span>
                      <span className="ml-auto text-[12px] text-faint">{num(r.rows_written)} rows · {r.duration_s ? `${Math.round(r.duration_s)} s` : "—"} · {timeAgo(r.started_at)}</span>
                    </div>
                    {r.message && <p className="mt-0.5 truncate pl-4 text-[12px] text-muted" title={r.message}>{r.message}</p>}
                  </motion.li>
                ))}
              </motion.ul>
            ) : health.isError ? <RetryState onRetry={() => health.refetch()} /> : <SkeletonLines n={6} />}
          </div>
        </Card>
      </div>

      {h && (
        <Card className="mt-4 p-5">
          <p className="mb-3 text-[13px] font-medium">All table row counts</p>
          <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {Object.entries(h.table_counts).map(([t, n]) => (
              <div key={t} className="rounded-xl bg-subtle px-3 py-2">
                <p className="truncate font-mono text-[11px] text-muted">{t}</p>
                <p className="text-sm font-semibold tabular-nums">{n < 0 ? "missing" : num(n)}</p>
              </div>
            ))}
          </div>
        </Card>
      )}
    </Page>
  );
}

function StatusPill({ status }: { status: PipelineHealth["status"] }) {
  const s = status === "ok" ? ["All systems normal", "bg-accent-50 text-accent-800 ring-accent-200 dark:bg-accent-500/10 dark:text-accent-400 dark:ring-accent-500/30"]
    : status === "ok_with_warnings" ? ["Running · minor warnings", "bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30"]
      : ["Degraded", "bg-red-50 text-red-700 ring-red-200 dark:bg-red-500/10 dark:text-red-300 dark:ring-red-500/30"];
  return (
    <span className={cx("inline-flex items-center gap-2 rounded-full px-3 py-1 text-[13px] font-medium ring-1 ring-inset", s[1])}>
      <motion.span className="h-2 w-2 rounded-full bg-current" animate={{ opacity: [1, 0.4, 1] }} transition={{ duration: 2, repeat: Infinity }} />
      {s[0]}
    </span>
  );
}

function StageDots({ runs }: { runs: PipelineHealth["recent_runs"] }) {
  const latest = (stage: string) => runs.find((r) => r.stage === stage || r.stage.endsWith(`:${stage}`) || r.stage === `daily:${stage}`);
  return (
    <div className="flex items-start overflow-x-auto pb-1">
      {STAGES.map((st, i) => {
        const r = latest(st);
        const color = !r ? "bg-zinc-300 dark:bg-zinc-600" : r.status === "success" ? "bg-accent-600" : r.status === "failed" ? "bg-red-500" : "bg-amber-500";
        return (
          <div key={st} className="flex items-start">
            <motion.div initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * 0.08, duration: 0.25 }}
              className="flex w-20 flex-col items-center text-center">
              <span className="relative flex h-4 w-4 items-center justify-center">
                {r?.status === "success" && (
                  <motion.span className={cx("absolute inset-0 rounded-full", color)} animate={{ scale: [1, 1.8], opacity: [0.4, 0] }}
                    transition={{ duration: 2, repeat: Infinity, delay: i * 0.2 }} />
                )}
                <span className={cx("relative h-3 w-3 rounded-full", color)} />
              </span>
              <span className="mt-2 font-mono text-[11px]">{st}</span>
              <span className="text-[10px] text-faint">{r ? timeAgo(r.finished_at ?? r.started_at) : "not in last 10 runs"}</span>
            </motion.div>
            {i < STAGES.length - 1 && (
              <motion.div className="mt-[7px] h-px w-6 origin-left bg-line" initial={{ scaleX: 0 }} animate={{ scaleX: 1 }}
                transition={{ delay: i * 0.08 + 0.1, duration: 0.2 }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function SkillTable({ rows }: { rows: SkillRow[] }) {
  const [season, setSeason] = useState("ALL");
  const pick = (target: string, metric: string, lead: number) =>
    rows.find((r) => r.target === target && r.metric === metric && r.lead_week === lead && r.season === season && r.model === "lgbm");
  // Common scale for the CI bars across the table.
  const vals = rows.filter((r) => r.season === season && TARGETS.some((t) => t.key === r.target && t.metric === r.metric))
    .flatMap((r) => [r.ci_low ?? 0, r.ci_high ?? 0, r.value ?? 0]);
  const lo = Math.min(-0.05, ...vals);
  const hi = Math.max(0.1, ...vals);
  const x = (v: number) => ((v - lo) / (hi - lo)) * 100;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex rounded-xl bg-subtle p-1 text-[12px]">
          {SEASONS.map((s) => (
            <button key={s.key} onClick={() => setSeason(s.key)}
              className={cx("rounded-lg px-3 py-1.5 font-medium", season === s.key ? "bg-surface text-fg ring-1 ring-line" : "text-muted")}>
              {s.label}
            </button>
          ))}
        </div>
        <span className="text-[12px] text-muted">Bar: 5–95% bootstrap CI · dot: score · line at 0 = climatology · green = skill proven (CI above 0)</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-[13px]">
          <thead>
            <tr className="text-left text-[12px] text-muted">
              <th className="pb-2 font-medium">Target</th>
              {[1, 2, 3, 4].map((l) => <th key={l} className="pb-2 font-medium">Week {l}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {TARGETS.map((t) => (
              <tr key={t.key}>
                <td className="py-3 pr-4">
                  <p className="font-medium">{t.label}</p>
                  <p className="text-[11px] text-faint">{t.metricLabel}</p>
                </td>
                {[1, 2, 3, 4].map((l) => {
                  const r = pick(t.key, t.metric, l);
                  if (!r || r.value === null) return <td key={l} className="py-3 text-faint">—</td>;
                  const skillful = (r.ci_low ?? -1) > 0;
                  return (
                    <td key={l} className="py-3 pr-4">
                      <Tooltip content={<>{t.metricLabel} {r.value.toFixed(3)} (CI {r.ci_low?.toFixed(3)} to {r.ci_high?.toFixed(3)}), {num(r.n_samples)} forecasts over {r.n_years} test years.</>}>
                        <div tabIndex={0} className="w-full min-w-[120px] cursor-help">
                          <div className="flex items-baseline justify-between">
                            <span className={cx("font-semibold tabular-nums", skillful ? "text-accent-700 dark:text-accent-400" : r.value < 0 ? "text-muted" : "")}>
                              {r.value >= 0 ? "+" : ""}{r.value.toFixed(3)}
                            </span>
                          </div>
                          <div className="relative mt-1.5 h-2 rounded-full bg-subtle">
                            <span className="absolute top-[-2px] h-3 w-px bg-faint" style={{ left: `${x(0)}%` }} />
                            <motion.span className={cx("absolute top-0 h-2 rounded-full", skillful ? "bg-accent-600/70" : "bg-zinc-400/60 dark:bg-zinc-500/60")}
                              initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }}
                              style={{ left: `${x(r.ci_low ?? r.value)}%`, width: `${Math.max(1, x(r.ci_high ?? r.value) - x(r.ci_low ?? r.value))}%` }} />
                            <motion.span layout className="absolute top-[-1px] h-2.5 w-2.5 -translate-x-1/2 rounded-full border-2 border-surface bg-fg"
                              style={{ left: `${x(r.value)}%` }} />
                          </div>
                        </div>
                      </Tooltip>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Metric({ label, value, foot, format }: { label: string; value: number; foot: string; format?: (n: number) => string }) {
  return (
    <Card className="p-5">
      <p className="text-[13px] text-muted">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums"><CountUp value={value} format={format} /></p>
      <p className="mt-1 text-[12px] text-muted">{foot}</p>
    </Card>
  );
}
