import { motion } from "framer-motion";
import { Info } from "lucide-react";
import type { Confidence, ForecastRow } from "../api/types";
import { pct } from "../lib/format";
import { cx, Tooltip } from "./ui";

export const CONFIDENCE_HELP =
  "Confidence combines how skilful the model has been for this lead week and season in validation " +
  "(lower 5% bound of its skill vs climatology, 2011–2025) with how decisive this forecast is. " +
  "High: proven skill and a clear signal. Medium: some skill, or a moderately clear signal. " +
  "Low: close to climatology, so treat it as a hint.";

export function ConfidenceBadge({ level, className }: { level: Confidence; className?: string }) {
  const style =
    level === "High" ? "bg-accent-50 text-accent-800 ring-accent-200 dark:bg-accent-500/10 dark:text-accent-400 dark:ring-accent-500/30"
      : level === "Medium" ? "bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-500/30"
        : "bg-subtle text-muted ring-line";
  return (
    <Tooltip content={<><b className="text-fg">{level} confidence.</b> {CONFIDENCE_HELP}</>}>
      <span tabIndex={0} className={cx("inline-flex cursor-help items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset", style, className)}>
        {level} <Info className="h-3 w-3 opacity-60" />
      </span>
    </Tooltip>
  );
}

/** Below / normal / above tercile probabilities as one stacked bar. */
export function TercileBar({ row, compact = false }: { row: Pick<ForecastRow, "p_below" | "p_normal" | "p_above">; compact?: boolean }) {
  const parts = [
    { k: "Below", v: row.p_below, c: "bg-amber-400 dark:bg-amber-500/80" },
    { k: "Normal", v: row.p_normal, c: "bg-zinc-300 dark:bg-zinc-600" },
    { k: "Above", v: row.p_above, c: "bg-accent-600 dark:bg-accent-500" },
  ];
  return (
    <div>
      <div className={cx("flex overflow-hidden rounded-full bg-subtle", compact ? "h-1.5" : "h-2.5")}>
        {parts.map((p) => (
          <motion.div key={p.k} className={p.c} initial={{ width: 0 }} animate={{ width: `${p.v * 100}%` }}
            transition={{ duration: 0.5, ease: "easeOut" }} title={`${p.k} normal: ${pct(p.v)}`} />
        ))}
      </div>
      {!compact && (
        <div className="mt-1.5 flex justify-between text-[11px] text-muted tabular-nums">
          <span>Below {pct(row.p_below)}</span>
          <span>Normal {pct(row.p_normal)}</span>
          <span>Above {pct(row.p_above)}</span>
        </div>
      )}
    </div>
  );
}
