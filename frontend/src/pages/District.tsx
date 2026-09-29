import { motion } from "framer-motion";
import { ArrowLeft, BellRing, CloudLightning, Droplets, Sprout, SunDim, Waves } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { CropStage, ForecastRow, Hazard } from "../api/types";
import { BandChart, RainChart } from "../components/charts";
import { ConfidenceBadge, TercileBar } from "../components/forecastBits";
import { HAZARD_ICON } from "../components/HazardItem";
import {
  Card, CardHeader, Chip, EmptyState, fadeUp, ObservedBadge, Page, PageTitle, RetryState, SeverityChip, Skeleton,
  SkeletonLines, stagger,
} from "../components/ui";
import { useAppState } from "../lib/appState";
import { CROP_EMOJI, day, HAZARD_LABEL, isObserved, num, pct, range, titleCase } from "../lib/format";
import { ContextLine } from "./Overview";

export default function District() {
  const { slug = "" } = useParams();
  const { date } = useAppState();
  const fc = useQuery({ queryKey: ["forecast", slug, date], queryFn: () => api.forecast(slug, date) });
  const rain = useQuery({ queryKey: ["rainfall", slug, 30], queryFn: () => api.rainfall(slug, 30) });
  const crops = useQuery({ queryKey: ["crop-calendar", slug, date], queryFn: () => api.cropCalendar(slug, date) });
  const adv = useQuery({
    queryKey: ["advisories", "district", slug, date],
    queryFn: () => api.advisories({ district: slug, date, limit: 20 }),
  });
  const d = fc.data;

  if (fc.isError) {
    return <Page><RetryState title="We couldn't load this district" onRetry={() => fc.refetch()} /></Page>;
  }

  return (
    <Page>
      <motion.div variants={fadeUp}>
        <Link to={`/app/overview${location.search}`} className="mb-3 inline-flex items-center gap-1.5 text-[13px] text-muted hover:text-fg">
          <ArrowLeft className="h-3.5 w-3.5" /> Overview
        </Link>
      </motion.div>
      <PageTitle
        title={d ? <span className="flex items-center gap-2">{d.district.name}{d.district.coastal && <Chip>Coastal</Chip>}</span> : <Skeleton className="h-7 w-48" />}
        subtitle={d ? <ContextLine ctx={d.context} /> : <Skeleton className="h-4 w-72" />}
        right={d?.forecast[0] && <ConfidenceBadge level={d.forecast[0].confidence} />}
      />

      {/* 4-week cards */}
      <motion.div variants={stagger} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {d ? d.forecast.map((w) => <WeekCard key={w.lead_week} w={w} />)
          : Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-52" />)}
      </motion.div>

      <div className="mt-4 grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader title="Weekly rain range" subtitle="Shaded: 10th–90th percentile of the weekly total · line: median" />
          <div className="px-3 pb-4">{d ? <BandChart rows={d.forecast} /> : <Skeleton className="mx-2 h-52" />}</div>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader title="Hazard timeline" subtitle="Observed now, then forecast weeks 1–4" />
          <div className="px-5 pb-5">{d ? <HazardTimeline hazards={d.hazards} /> : <SkeletonLines n={5} />}</div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader title="Last 30 days of rain" icon={<Droplets className="h-4 w-4" />}
            subtitle={rain.data
              ? <>{num(rain.data.total_mm, 1)} mm vs {num(rain.data.normal_mm, 1)} mm normal ({num(rain.data.percent_of_normal)}%) · {rain.data.wet_days} wet days · to {day(rain.data.end)}</>
              : "Observed IMD gridded rainfall"}
            right={<ObservedBadge />} />
          <div className="px-3 pb-4">
            {rain.data ? <RainChart series={rain.data.series} />
              : rain.isError ? <RetryState onRetry={() => rain.refetch()} /> : <Skeleton className="mx-2 h-48" />}
          </div>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader title="Crops in the field" icon={<Sprout className="h-4 w-4" />}
            subtitle="Current stage from the crop calendar (sample data)" />
          <div className="px-5 pb-5">
            {crops.data?.stages ? <CropStages stages={crops.data.stages} calendar={crops.data.calendar} />
              : crops.isError ? <RetryState onRetry={() => crops.refetch()} /> : <SkeletonLines n={4} />}
          </div>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader title="Advisories for this district" icon={<BellRing className="h-4 w-4" />}
          right={<Link to={`/app/advisories${location.search}`} className="text-[13px] text-accent-700 hover:underline dark:text-accent-400">Open queue →</Link>} />
        <div className="px-5 pb-5">
          {adv.data ? (
            adv.data.advisories.length ? (
              <ul className="divide-y divide-line">
                {adv.data.advisories.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center gap-2 py-2.5 text-sm">
                    <span>{CROP_EMOJI[a.crop]}</span>
                    <Link to={`/app/advisories?id=${a.id}`} className="font-medium hover:underline">{a.title_en}</Link>
                    <SeverityChip severity={a.severity} />
                    <Chip>{a.status}</Chip>
                    <span className="ml-auto text-[12px] text-muted">{titleCase(a.stage)} · {num(a.farmers_targeted)} farmers</span>
                  </li>
                ))}
              </ul>
            ) : <EmptyState title="No advisories drafted for this district and date" />
          ) : <SkeletonLines n={3} />}
        </div>
      </Card>
    </Page>
  );
}

function WeekCard({ w }: { w: ForecastRow }) {
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[12px] font-medium uppercase tracking-wide text-faint">Week {w.lead_week}</p>
          <p className="text-sm text-muted">{range(w.week_start, w.week_end)}</p>
        </div>
        <ConfidenceBadge level={w.confidence} />
      </div>
      <p className="mt-4 text-3xl font-semibold tracking-tight tabular-nums">
        {num(w.q50_mm, w.q50_mm < 10 ? 1 : 0)}<span className="ml-1 text-base font-normal text-muted">mm</span>
      </p>
      <p className="text-[12px] text-muted">median · likely {num(w.q10_mm, 0)}–{num(w.q90_mm, 0)} mm</p>
      <div className="mt-4"><TercileBar row={w} /></div>
      <div className="mt-4 grid grid-cols-2 gap-2 text-[12px]">
        <Stat icon={<CloudLightning className="h-3.5 w-3.5" />} label="Heavy-rain day" value={pct(w.p_heavy)} hot={w.p_heavy >= 0.3} />
        <Stat icon={<SunDim className="h-3.5 w-3.5" />} label="Fully dry week" value={pct(w.p_dry_week)} hot={w.p_dry_week >= 0.4} />
      </div>
    </Card>
  );
}

function Stat({ icon, label, value, hot }: { icon: React.ReactNode; label: string; value: string; hot: boolean }) {
  return (
    <div className={hot ? "rounded-xl bg-amber-50 px-2.5 py-2 text-amber-900 dark:bg-amber-500/10 dark:text-amber-200" : "rounded-xl bg-subtle px-2.5 py-2"}>
      <div className="flex items-center gap-1 text-muted">{icon}{label}</div>
      <div className="mt-0.5 font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function HazardTimeline({ hazards }: { hazards: Hazard[] }) {
  if (!hazards.length) {
    return <EmptyState icon={<Waves className="h-5 w-5" />} title="No hazards for this district" >Rain looks near normal.</EmptyState>;
  }
  const sorted = [...hazards].sort((a, b) => a.lead_week - b.lead_week);
  return (
    <motion.ol initial="hidden" animate="show" variants={stagger} className="relative space-y-4 border-l border-line pl-5">
      {sorted.map((h) => {
        const Icon = HAZARD_ICON[h.hazard_type];
        return (
          <motion.li key={h.id} variants={fadeUp} className="relative">
            <span className="absolute -left-[30px] top-0.5 flex h-5 w-5 items-center justify-center rounded-full border border-line bg-surface">
              <Icon className="h-3 w-3 text-muted" />
            </span>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[12px] font-medium text-faint">{h.lead_week === 0 ? "Now" : `Week ${h.lead_week}`}</span>
              <span className="text-sm font-medium">{HAZARD_LABEL[h.hazard_type]}</span>
              <SeverityChip severity={h.severity} />
              {isObserved(h.basis) && <ObservedBadge />}
            </div>
            <p className="mt-1 text-[13px] leading-relaxed text-muted">{h.why}</p>
          </motion.li>
        );
      })}
    </motion.ol>
  );
}

function CropStages({ stages, calendar }: { stages: CropStage[]; calendar: { crop: string; season: string; district: string; stage_end_day: number }[] }) {
  if (!stages.length) return <EmptyState title="No crop is in the field on this date" />;
  return (
    <motion.ul initial="hidden" animate="show" variants={stagger} className="space-y-3.5">
      {stages.map((s) => {
        const total = Math.max(...calendar.filter((c) => c.crop === s.crop && c.season === s.season &&
          (c.district === s.calendar_district)).map((c) => c.stage_end_day), 1);
        const frac = s.days_after_sowing === null ? 0.02 : Math.min(1, s.days_after_sowing / total);
        return (
          <motion.li key={`${s.crop}-${s.season}`} variants={fadeUp}>
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">{CROP_EMOJI[s.crop]} {titleCase(s.crop)} <span className="font-normal text-faint">· {titleCase(s.season)}</span></span>
              <span className="text-[12px] text-muted">
                {s.stage === "sowing" ? `Sowing window to ${day(s.sowing_window[1])}` : `${titleCase(s.stage)} · day ${s.days_after_sowing}`}
              </span>
            </div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-subtle">
              <motion.div className="h-full rounded-full bg-accent-600" initial={{ width: 0 }} animate={{ width: `${frac * 100}%` }} transition={{ duration: 0.6 }} />
            </div>
          </motion.li>
        );
      })}
    </motion.ul>
  );
}
