import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, BellRing, Map as MapIcon, Send, ThumbsUp, Users } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Severity } from "../api/types";
import { HazardItem } from "../components/HazardItem";
import { MapLegend, RiskMap } from "../components/RiskMap";
import {
  Card, CardHeader, Chip, CountUp, cx, EmptyState, Page, PageTitle, RetryState, Skeleton, SkeletonLines, stagger,
} from "../components/ui";
import { useAppState } from "../lib/appState";
import { compact, day, longDate, pct } from "../lib/format";
import { useTheme } from "../lib/theme";

export default function Overview() {
  const { date } = useAppState();
  const nav = useNavigate();
  const [theme] = useTheme();
  const [filter, setFilter] = useState<"alerts" | "all">("alerts");
  const overview = useQuery({ queryKey: ["overview", date], queryFn: () => api.overview(date), refetchInterval: 15_000 });
  const districts = useQuery({ queryKey: ["districts", date], queryFn: () => api.districts(date) });
  // MOCK block-level demo data (Madurai); the map works without it.
  const blocks = useQuery({ queryKey: ["blocks", "madurai", date], queryFn: () => api.blocks("madurai", date), retry: 0 });
  const hazards = useQuery({
    queryKey: ["hazards", date],
    queryFn: () => api.hazards({ date }),
    refetchInterval: 20_000,
  });
  const o = overview.data;
  const ctx = o?.context;
  const shown = (hazards.data?.hazards ?? []).filter((h) => filter === "all" || h.severity !== "info");
  const goDistrict = (slug: string) => nav(`/app/district/${slug}${location.search}`);

  return (
    <Page>
      <PageTitle
        title="Overview"
        subtitle={ctx ? <ContextLine ctx={ctx} /> : <Skeleton className="h-4 w-72" />}
      />

      <motion.div variants={stagger} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={<AlertTriangle className="h-4 w-4" />} label="Districts on alert" loading={!o}
          value={o?.districts.with_alerts ?? 0}
          foot={o && <><Dot s="warning" /> {o.districts.warning} warning · <Dot s="watch" /> {o.districts.watch} watch · of {o.districts.total}</>} />
        <Kpi icon={<BellRing className="h-4 w-4" />} label="Advisories to review" loading={!o}
          value={o?.advisories.pending_review ?? 0}
          foot={o && <>{o.advisories.by_status.approved ?? 0} approved · {o.advisories.by_status.sent ?? 0} sent</>}
          onClick={() => nav(`/app/advisories${location.search}`)} />
        <Kpi icon={<Users className="h-4 w-4" />} label="Farmers in alert districts" loading={!o}
          value={o?.farmers.in_alert_districts ?? 0} format={(n) => compact(Math.round(n))}
          foot={o && <>of {compact(o.farmers.registered_total)} registered <span className="text-faint">(mock)</span></>} />
        <Kpi icon={<Send className="h-4 w-4" />} label="Messages delivered" loading={!o}
          value={o?.delivery.delivered ?? 0} format={(n) => compact(Math.round(n))}
          foot={o && (o.delivery.broadcasts
            ? <>{o.delivery.broadcasts} broadcasts · {pct(o.delivery.read_rate)} read</>
            : <>No broadcasts yet for this date</>)}
          onClick={() => nav(`/app/delivery${location.search}`)} />
      </motion.div>

      <div className="mt-4 grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader icon={<MapIcon className="h-4 w-4" />} title="District risk map"
            subtitle="Worst hazard per district · hover for details, click to open"
            right={<MapLegend withBlocks={!!blocks.data?.blocks.length} />} />
          <div className="h-[460px] px-3 pb-3">
            {districts.data ? (
              <RiskMap data={districts.data} dark={theme === "dark"} onSelect={goDistrict} blocks={blocks.data?.blocks} />
            ) : districts.isError ? (
              <RetryState onRetry={() => districts.refetch()} />
            ) : (
              <Skeleton className="h-full w-full" />
            )}
          </div>
        </Card>

        <Card className="flex flex-col lg:col-span-2">
          <CardHeader title="Live alerts" subtitle={hazards.data ? `${hazards.data.count} hazards detected` : "Loading…"}
            right={
              <div className="flex rounded-lg bg-subtle p-0.5 text-[12px]">
                {(["alerts", "all"] as const).map((k) => (
                  <button key={k} onClick={() => setFilter(k)}
                    className={cx("rounded-md px-2.5 py-1 font-medium", filter === k ? "bg-surface text-fg ring-1 ring-line" : "text-muted")}>
                    {k === "alerts" ? "Watch + warning" : "All"}
                  </button>
                ))}
              </div>
            } />
          <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3 lg:max-h-[460px]">
            {hazards.data ? (
              shown.length ? (
                <motion.ul key={`${date}-${filter}`} initial="hidden" animate="show" variants={stagger}>
                  {shown.slice(0, 60).map((h) => (
                    <HazardItem key={h.id} h={h} onClick={() => goDistrict(h.district.toLowerCase().replace(/ /g, "-"))} />
                  ))}
                </motion.ul>
              ) : (
                <EmptyState title="No watch or warning alerts">
                  All districts look calm for this date. Switch to "All" to see informational signals.
                </EmptyState>
              )
            ) : hazards.isError ? (
              <RetryState onRetry={() => hazards.refetch()} />
            ) : (
              <SkeletonLines n={8} />
            )}
          </div>
        </Card>
      </div>

      {o && (
        <motion.div variants={stagger} className="mt-4 grid gap-4 md:grid-cols-3">
          <Card className="p-5">
            <p className="text-[13px] text-muted">Week 1 outlook (all districts)</p>
            <p className="mt-2 text-2xl font-semibold tabular-nums">
              <CountUp value={o.forecast_week1.mean_q50_mm ?? 0} format={(n) => `${n.toFixed(1)} mm`} />
            </p>
            <p className="mt-1 text-[13px] text-muted">
              average median weekly rain · {o.forecast_week1.districts_above_normal_favoured} districts lean above normal,{" "}
              {o.forecast_week1.districts_below_normal_favoured} below
            </p>
          </Card>
          <Card className="p-5">
            <p className="text-[13px] text-muted">Hazards by type</p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {Object.entries(o.hazards.by_type).map(([t, v]) => (
                <Chip key={t}>{t.replace("_", " ")} · {v.districts}</Chip>
              ))}
              {!Object.keys(o.hazards.by_type).length && <span className="text-sm text-faint">None</span>}
            </div>
          </Card>
          <FeedbackCard />
        </motion.div>
      )}
    </Page>
  );
}

/** Live farmer feedback (polls every 4 s, so a 👍 in the Farmer app shows up here). */
function FeedbackCard() {
  const q = useQuery({ queryKey: ["feedback", "all"], queryFn: () => api.feedbackSummary(), refetchInterval: 4000 });
  const t = q.data?.totals;
  return (
    <Card className="p-5">
      <p className="flex items-center gap-1.5 text-[13px] text-muted"><ThumbsUp className="h-3.5 w-3.5" /> Farmer feedback · live</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums">
        {t?.total ? <CountUp value={(t.positive_rate ?? 0) * 100} format={(n) => `${Math.round(n)}% useful`} /> : "—"}
      </p>
      <p className="mt-1 text-[12px] text-muted">{t ? <>{t.up} 👍 · {t.down} 👎 · {t.real} from the Farmer app</> : "…"}</p>
      <ul className="mt-3 space-y-1.5">
        <AnimatePresence initial={false}>
          {(q.data?.recent_comments ?? []).slice(0, 3).map((c) => (
            <motion.li key={c.id} layout initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className="truncate text-[12px]">
              {c.rating === 1 ? "👍" : "👎"} <span className="text-muted">{c.district} · {c.crop}:</span> {c.comment}
              {!c.simulated && <span className="ml-1 rounded bg-accent-50 px-1 text-[10px] text-accent-800 dark:bg-accent-500/10 dark:text-accent-400">app</span>}
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
    </Card>
  );
}

function Dot({ s }: { s: Severity }) {
  const c = s === "warning" ? "bg-red-500" : s === "watch" ? "bg-amber-500" : "bg-sky-500";
  return <span className={cx("inline-block h-1.5 w-1.5 rounded-full align-middle", c)} />;
}

function Kpi({ icon, label, value, foot, loading, format, onClick }: {
  icon: ReactNode; label: string; value: number; foot?: ReactNode; loading: boolean;
  format?: (n: number) => string; onClick?: () => void;
}) {
  return (
    <Card onClick={onClick} className={cx("p-5", onClick && "cursor-pointer transition-colors hover:bg-subtle/60")}>
      <div className="flex items-center gap-2 text-[13px] text-muted">{icon}{label}</div>
      {loading ? (
        <>
          <Skeleton className="mt-3 h-8 w-20" />
          <Skeleton className="mt-3 h-3 w-40" />
        </>
      ) : (
        <>
          <p className="mt-2 text-3xl font-semibold tracking-tight tabular-nums"><CountUp value={value} format={format} /></p>
          <p className="mt-1.5 text-[12px] text-muted">{foot}</p>
        </>
      )}
    </Card>
  );
}

export function ContextLine({ ctx }: { ctx: { issue_date: string; forecast_source: string; model_version: string; forecast_issue_date: string; observed_through: string | null; note: string | null } }) {
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span>Issue date {longDate(ctx.issue_date)}</span>
      <span className="text-faint">·</span>
      <span className={cx(ctx.forecast_source === "real" && "font-medium text-accent-700 dark:text-accent-400")}>
        {ctx.forecast_source === "real" ? `Real model ${ctx.model_version}` : "Mock forecasts"}
      </span>
      {ctx.forecast_issue_date !== ctx.issue_date && (
        <><span className="text-faint">·</span><span>run of {day(ctx.forecast_issue_date)}</span></>
      )}
      <span className="text-faint">·</span>
      <span>IMD rain observed to {day(ctx.observed_through)}</span>
    </span>
  );
}
