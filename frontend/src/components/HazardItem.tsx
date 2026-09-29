import { motion } from "framer-motion";
import { CloudDrizzle, CloudLightning, CloudRain, CloudSun, Sprout, SunDim } from "lucide-react";
import type { Hazard, HazardType } from "../api/types";
import { HAZARD_LABEL, isObserved, pct, range } from "../lib/format";
import { Chip, fadeUp, ObservedBadge, SeverityChip } from "./ui";

export const HAZARD_ICON: Record<HazardType, typeof CloudRain> = {
  onset: Sprout,
  false_onset: CloudSun,
  active_phase: CloudRain,
  dry_spell: SunDim,
  heavy_rain: CloudLightning,
  revival: CloudDrizzle,
};

export function HazardItem({ h, showDistrict = true, onClick }: {
  h: Hazard; showDistrict?: boolean; onClick?: () => void;
}) {
  const Icon = HAZARD_ICON[h.hazard_type];
  return (
    <motion.li variants={fadeUp} layout="position">
      <button onClick={onClick} disabled={!onClick}
        className="flex w-full gap-3 rounded-xl px-3 py-3 text-left transition-colors enabled:hover:bg-subtle">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-subtle text-muted">
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-sm font-medium">
              {showDistrict && <>{h.district} · </>}{HAZARD_LABEL[h.hazard_type]}
              {h.subtype === "14d" && " (14-day)"}{h.subtype === "very_heavy" && " (very heavy)"}
            </span>
            <SeverityChip severity={h.severity} />
            {isObserved(h.basis) && <ObservedBadge />}
          </div>
          <p className="mt-1 text-[13px] leading-relaxed text-muted">{h.why}</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <Chip>{h.lead_week === 0 ? "Observed" : `Week ${h.lead_week}`}</Chip>
            {h.lead_week > 0 && <Chip>{pct(h.probability)} chance</Chip>}
            {h.window_start && <Chip>{range(h.window_start, h.window_end)}</Chip>}
            <Chip>{h.confidence} confidence</Chip>
          </div>
        </div>
      </button>
    </motion.li>
  );
}
