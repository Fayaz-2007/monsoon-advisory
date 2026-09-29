"""Hazard rules (Segment 3). Pure functions: no database, fully unit-tested.

Inputs per district
* ``obs``: observed daily rain (Segment 1) for the 30 days before the issue date,
  as a list of ``(date, rain_mm)`` sorted by date (``rain_mm`` may be NaN).
* ``fc``: the 4 forecast rows (Segment 2 schema) for lead weeks 1–4.
* ``anom7_pct`` / ``wet_days_7``: Segment 1 features for the last observed day.

Definitions (IMD / agro-met conventions)
* wet day ≥ 2.5 mm, dry day < 2.5 mm; heavy rain ≥ 64.5 mm in a day.
* **onset**: ≥ 20 mm accumulated over 2–3 consecutive days.
* **false onset**: an onset followed by a dry spell of ≥ 7 days within 30 days.
* **dry spell**: 7 (or 14) consecutive days < 2.5 mm/day.
* **active phase**: 7-day rain ≥ 150% of normal with ≥ 4 wet days, or two forecast weeks
  leaning above normal.
* **revival**: useful rain (≥ 20 mm in a week) returning right after a dry spell.

Forecasts are weekly, so daily criteria are evaluated on the week: a forecast "dry spell"
week is Segment 2's ``p_dry_week`` (all 7 days < 2.5 mm, exactly the 7-day criterion);
a forecast "onset" week is P(week total ≥ 20 mm) from the q10/q50/q90 quantiles. Each
hazard records the numbers it used in ``evidence`` and says them in ``why``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

from app.mock.generator import prob_total_at_least

DRY_DAY_MM = 2.5
HEAVY_DAY_MM = 64.5
ONSET_MM = 20.0
ONSET_WINDOWS = (2, 3)
DRY_SPELL_DAYS = 7
LONG_DRY_SPELL_DAYS = 14
FALSE_ONSET_WINDOW_DAYS = 30
RECENT_ONSET_DAYS = 14
RECENT_HEAVY_DAYS = 3
# Observed data must reach at least this close to the issue date to be used (days).
MAX_OBS_LAG_DAYS = 2

# Forecast alert thresholds (probabilities).
P_DRY_WEEK_ALERT = 0.40
P_DRY_14_ALERT = 0.35
P_DRY_WARNING = 0.60
P_HEAVY_ALERT = 0.30
P_HEAVY_WARNING = 0.60
P_ONSET_ALERT = 0.50
P_FALSE_ONSET_ALERT = 0.50
P_FALSE_ONSET_MIN_DRY = 0.50
P_ACTIVE_WEEK1 = 0.50
P_ACTIVE_WEEK2 = 0.45
P_REVIVAL_ALERT = 0.50
# Persistence of dry weeks: P(dry week k+1 | dry week k) = p + RHO·(1 − p). Assumption,
# documented in the why text of 14-day spells.
DRY_PERSISTENCE_RHO = 0.30
ACTIVE_ANOM_PCT = 150.0
ACTIVE_WET_DAYS = 4

HAZARD_TYPES = ("onset", "false_onset", "active_phase", "dry_spell", "heavy_rain", "revival")
SEVERITY_ORDER = {"info": 0, "watch": 1, "warning": 2}


@dataclass
class Hazard:
    hazard_type: str
    probability: float
    lead_week: int                 # 0 = already observed
    confidence: str                # High | Medium | Low
    basis: str                     # observed | forecast | observed+forecast
    severity: str                  # info | watch | warning
    why: str
    subtype: str | None = None
    window_start: date | None = None
    window_end: date | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["probability"] = round(float(self.probability), 4)
        return d


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def fmt_day(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def fmt_range(a: date, b: date) -> str:
    return f"{fmt_day(a)}–{fmt_day(b)}"


def pct(p: float) -> str:
    return f"{round(100 * p)}%"


def _valid(v: float | None) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def _conf_min(*levels: str) -> str:
    order = {"Low": 0, "Medium": 1, "High": 2}
    return min(levels, key=lambda c: order.get(c, 0))


def _soften(severity: str, confidence: str) -> str:
    """Low-confidence forecasts never raise a warning on their own (Segment 2 contract advice)."""
    return "watch" if (severity == "warning" and confidence == "Low") else severity


def find_onset(obs: Sequence[tuple[date, float]]) -> dict[str, Any] | None:
    """The most recent onset event: a 2–3 day window with ≥ ONSET_MM that starts and ends on
    a wet day. Among the qualifying windows of that event (ending within 2 days of the latest
    one) the wettest is reported. Returns start, end, days, total_mm."""
    vals = list(obs)

    def windows_ending(i: int):
        for w in ONSET_WINDOWS:
            win = vals[i - w + 1:i + 1] if i - w + 1 >= 0 else []
            if (len(win) == w and all(_valid(r) for _, r in win)
                    and win[0][1] >= DRY_DAY_MM and win[-1][1] >= DRY_DAY_MM):
                total = sum(r for _, r in win)
                if total >= ONSET_MM:
                    yield total, -w, win

    latest = next((i for i in range(len(vals) - 1, -1, -1) if any(windows_ending(i))), None)
    if latest is None:
        return None
    total, neg_w, win = max((c for i in range(max(0, latest - 2), latest + 1)
                             for c in windows_ending(i)), key=lambda c: (c[0], c[1]))
    return {"start": win[0][0], "end": win[-1][0], "days": -neg_w, "total_mm": round(float(total), 1)}


def is_onset_season(d: date) -> bool:
    """Sowing seasons, when an onset decides whether farmers sow: SW monsoon / kharif
    (1 Jun – 31 Jul) and NE monsoon / rabi (15 Sep – 30 Nov), matching the crop calendar."""
    return d.month in (6, 7) or (d.month == 9 and d.day >= 15) or d.month in (10, 11)


def observed_is_fresh(obs: Sequence[tuple[date, float]], issue_date: date) -> bool:
    return bool(obs) and obs[-1][0] >= issue_date - timedelta(days=MAX_OBS_LAG_DAYS)


def trailing_dry_run(obs: Sequence[tuple[date, float]]) -> int:
    n = 0
    for _, r in reversed(list(obs)):
        if _valid(r) and r < DRY_DAY_MM:
            n += 1
        else:
            break
    return n


def p_onset_week(row: dict[str, Any]) -> float:
    return prob_total_at_least(ONSET_MM, row["q10_mm"], row["q50_mm"], row["q90_mm"])


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------

def rule_onset(obs, fc, issue_date: date, in_season: bool) -> Hazard | None:
    if not in_season:
        return None
    onset = find_onset(obs)
    if onset:
        days_ago = (issue_date - onset["end"]).days
        if days_ago <= RECENT_ONSET_DAYS:
            return Hazard(
                "onset", 1.0, 0, "High", "observed", "info",
                f"Onset rain observed: {onset['total_mm']} mm fell in {onset['days']} days "
                f"({fmt_range(onset['start'], onset['end'])}), above the {ONSET_MM:.0f} mm onset "
                f"threshold.",
                window_start=onset["start"], window_end=onset["end"], evidence={"onset": onset})
        return None  # season already set in; an old onset is not news
    for row in fc[:2]:
        p = p_onset_week(row)
        if p >= P_ONSET_ALERT:
            return Hazard(
                "onset", p, int(row["lead_week"]), row["confidence"], "forecast", "info",
                f"Onset-type rain likely in week {row['lead_week']} "
                f"({fmt_range(row['week_start'], row['week_end'])}): {pct(p)} chance of ≥ "
                f"{ONSET_MM:.0f} mm (median {row['q50_mm']:.0f} mm, range "
                f"{row['q10_mm']:.0f}–{row['q90_mm']:.0f} mm). No onset in the last 30 days.",
                window_start=row["week_start"], window_end=row["week_end"],
                evidence={"p_total_ge_20mm": round(p, 4), "q10_mm": row["q10_mm"],
                          "q50_mm": row["q50_mm"], "q90_mm": row["q90_mm"]})
    return None


def rule_false_onset(obs, fc, issue_date: date, in_season: bool) -> Hazard | None:
    if not in_season:
        return None
    onset = find_onset(obs)
    if onset:
        run = trailing_dry_run(obs)
        run_start = issue_date - timedelta(days=run)
        if (run >= DRY_SPELL_DAYS and run_start > onset["end"]
                and (run_start - onset["end"]).days <= FALSE_ONSET_WINDOW_DAYS):
            # Relief: useful rain in week 1 and no clearly dry week in weeks 1–3.
            relief = p_onset_week(fc[0]) if fc else 0.0
            more_dry = max((r["p_dry_week"] for r in fc[:3]), default=0.0)
            easing = relief >= P_ONSET_ALERT and more_dry < P_FALSE_ONSET_MIN_DRY - 0.15
            return Hazard(
                "false_onset", 1.0, 0, "High", "observed", "watch" if easing else "warning",
                f"False onset under way: {onset['total_mm']} mm fell "
                f"{fmt_range(onset['start'], onset['end'])}, and it has now been dry (< "
                f"{DRY_DAY_MM} mm/day) for {run} days since {fmt_day(run_start)}."
                + (f" Relief likely: {pct(relief)} chance of ≥ {ONSET_MM:.0f} mm in week 1."
                   if easing else ""),
                window_start=onset["start"], window_end=issue_date - timedelta(days=1),
                evidence={"onset": onset, "dry_run_days": run, "p_rain_week1": round(relief, 4),
                          "max_p_dry_weeks_1_3": more_dry})
        p_on, onset_end, onset_desc, on_conf = 1.0, onset["end"], (
            f"{onset['total_mm']} mm fell {fmt_range(onset['start'], onset['end'])} (onset)"), "High"
        first_lead = 1
        basis = "observed+forecast"
    else:
        if not fc:
            return None
        w1 = fc[0]
        p_on = p_onset_week(w1)
        if p_on < P_ONSET_ALERT:
            return None
        onset_end, first_lead = w1["week_end"], 2
        onset_desc = (f"week 1 ({fmt_range(w1['week_start'], w1['week_end'])}) brings onset-type "
                      f"rain ({pct(p_on)} chance of ≥ {ONSET_MM:.0f} mm, median {w1['q50_mm']:.0f} mm)")
        on_conf = w1["confidence"]
        basis = "forecast"
    horizon = onset_end + timedelta(days=FALSE_ONSET_WINDOW_DAYS)
    weeks = [r for r in fc if int(r["lead_week"]) >= first_lead and r["week_start"] <= horizon]
    if not weeks:
        return None
    p_no_dry = 1.0
    for r in weeks:
        p_no_dry *= 1.0 - r["p_dry_week"]
    p_dry_any = 1.0 - p_no_dry
    worst = max(weeks, key=lambda r: r["p_dry_week"])
    if worst["p_dry_week"] < P_FALSE_ONSET_MIN_DRY:
        return None
    p = p_on * p_dry_any
    if p < P_FALSE_ONSET_ALERT:
        return None
    conf = _conf_min(on_conf, worst["confidence"])
    sev = _soften("warning", conf)
    return Hazard(
        "false_onset", p, int(worst["lead_week"]), conf, basis, sev,
        f"False-onset risk {pct(p)}: {onset_desc}, but week {worst['lead_week']} "
        f"({fmt_range(worst['week_start'], worst['week_end'])}) has a {pct(worst['p_dry_week'])} "
        f"chance of a fully dry week (median {worst['q50_mm']:.1f} mm). Seeds sown on the "
        f"first rain may not survive.",
        window_start=worst["week_start"], window_end=worst["week_end"],
        evidence={"p_onset": round(p_on, 4), "p_dry_any_within_30d": round(p_dry_any, 4),
                  "weeks_checked": [int(r["lead_week"]) for r in weeks],
                  "worst_week_p_dry": worst["p_dry_week"]})


def rule_dry_spell(obs, fc, issue_date: date) -> Hazard | None:
    run = trailing_dry_run(obs)
    w1 = fc[0] if fc else None
    # Observed run continuing into week 1 → 14+ days.
    if run >= DRY_SPELL_DAYS and w1 is not None and w1["p_dry_week"] >= P_DRY_WEEK_ALERT:
        p = w1["p_dry_week"]
        return Hazard(
            "dry_spell", p, 1, w1["confidence"], "observed+forecast",
            _soften("warning", w1["confidence"]),
            f"Already {run} dry days (< {DRY_DAY_MM} mm/day) up to {fmt_day(issue_date - timedelta(days=1))}; "
            f"{pct(p)} chance week 1 ({fmt_range(w1['week_start'], w1['week_end'])}) is dry too, "
            f"taking the spell past {run + 7} days.",
            subtype="14d", window_start=issue_date - timedelta(days=run), window_end=w1["week_end"],
            evidence={"observed_dry_days": run, "p_dry_week1": p})
    if run >= LONG_DRY_SPELL_DAYS:
        return Hazard("dry_spell", 1.0, 0, "High", "observed", "warning",
                      f"{run} consecutive dry days observed (< {DRY_DAY_MM} mm/day) up to "
                      f"{fmt_day(issue_date - timedelta(days=1))}.",
                      subtype="14d", window_start=issue_date - timedelta(days=run),
                      window_end=issue_date - timedelta(days=1), evidence={"observed_dry_days": run})
    # Two consecutive forecast dry weeks → 14-day spell.
    for a, b in zip(fc, fc[1:]):
        p_cond = b["p_dry_week"] + DRY_PERSISTENCE_RHO * (1.0 - b["p_dry_week"])
        p14 = a["p_dry_week"] * p_cond
        if p14 >= P_DRY_14_ALERT and a["p_dry_week"] >= P_DRY_WEEK_ALERT:
            conf = _conf_min(a["confidence"], b["confidence"])
            return Hazard(
                "dry_spell", p14, int(a["lead_week"]), conf, "forecast", _soften("warning", conf),
                f"14-day dry spell risk {pct(p14)}: week {a['lead_week']} "
                f"({fmt_range(a['week_start'], a['week_end'])}) is dry with {pct(a['p_dry_week'])} "
                f"chance and week {b['lead_week']} with {pct(b['p_dry_week'])} (dry weeks tend to "
                f"persist; assumed persistence {DRY_PERSISTENCE_RHO}).",
                subtype="14d", window_start=a["week_start"], window_end=b["week_end"],
                evidence={"p_dry_weeks": [a["p_dry_week"], b["p_dry_week"]], "p_14d": round(p14, 4),
                          "persistence_rho": DRY_PERSISTENCE_RHO})
    if run >= DRY_SPELL_DAYS:
        relief = p_onset_week(w1) if w1 is not None else 0.0
        ending = relief >= P_ONSET_ALERT
        return Hazard("dry_spell", 1.0, 0, "High", "observed", "info" if ending else "watch",
                      f"{run} consecutive dry days observed (< {DRY_DAY_MM} mm/day) up to "
                      f"{fmt_day(issue_date - timedelta(days=1))}."
                      + (f" Likely to end: {pct(relief)} chance of ≥ {ONSET_MM:.0f} mm in week 1."
                         if ending else ""),
                      subtype="7d", window_start=issue_date - timedelta(days=run),
                      window_end=issue_date - timedelta(days=1), evidence={"observed_dry_days": run, "p_rain_week1": round(relief, 4)})
    cands = [r for r in fc if r["p_dry_week"] >= P_DRY_WEEK_ALERT]
    if not cands:
        return None
    r = cands[0]  # the nearest week that crosses the threshold
    sev = _soften("warning" if r["p_dry_week"] >= P_DRY_WARNING else "watch", r["confidence"])
    return Hazard(
        "dry_spell", r["p_dry_week"], int(r["lead_week"]), r["confidence"], "forecast", sev,
        f"{pct(r['p_dry_week'])} chance of a 7-day dry spell in week {r['lead_week']} "
        f"({fmt_range(r['week_start'], r['week_end'])}): every day < {DRY_DAY_MM} mm; median week "
        f"total {r['q50_mm']:.1f} mm.",
        subtype="7d", window_start=r["week_start"], window_end=r["week_end"],
        evidence={"p_dry_week": r["p_dry_week"], "q50_mm": r["q50_mm"],
                  "observed_dry_days": run})


def rule_heavy_rain(obs, fc, issue_date: date) -> Hazard | None:
    cands = [r for r in fc if r["p_heavy"] >= P_HEAVY_ALERT]
    if cands:
        r = cands[0]  # the nearest week that crosses the threshold
        sev = _soften("warning" if r["p_heavy"] >= P_HEAVY_WARNING else "watch", r["confidence"])
        very = r["q90_mm"] >= 200
        return Hazard(
            "heavy_rain", r["p_heavy"], int(r["lead_week"]), r["confidence"], "forecast", sev,
            f"{pct(r['p_heavy'])} chance of at least one day ≥ {HEAVY_DAY_MM} mm in week "
            f"{r['lead_week']} ({fmt_range(r['week_start'], r['week_end'])}); week total median "
            f"{r['q50_mm']:.0f} mm, up to {r['q90_mm']:.0f} mm (90th percentile).",
            subtype="very_heavy" if very else "heavy",
            window_start=r["week_start"], window_end=r["week_end"],
            evidence={"p_heavy": r["p_heavy"], "q50_mm": r["q50_mm"], "q90_mm": r["q90_mm"],
                      "weeks_over_threshold": [int(c["lead_week"]) for c in cands]})
    recent = [(d, r) for d, r in obs if d >= issue_date - timedelta(days=RECENT_HEAVY_DAYS)
              and _valid(r) and r >= HEAVY_DAY_MM]
    if recent:
        d, r = max(recent, key=lambda x: x[1])
        return Hazard("heavy_rain", 1.0, 0, "High", "observed", "watch",
                      f"Heavy rain observed: {r:.1f} mm on {fmt_day(d)} (≥ {HEAVY_DAY_MM} mm). "
                      f"Check fields for waterlogging.",
                      subtype="heavy", window_start=d, window_end=d,
                      evidence={"max_rain_mm": round(r, 1), "date": d})
    return None


def rule_active_phase(obs, fc, issue_date: date, anom7_pct: float | None,
                      wet_days_7: int | None) -> Hazard | None:
    obs_active = (_valid(anom7_pct) and _valid(wet_days_7)
                  and anom7_pct >= ACTIVE_ANOM_PCT and wet_days_7 >= ACTIVE_WET_DAYS)
    obs_txt = (f"Last 7 days were {anom7_pct:.0f}% of normal with {int(wet_days_7)} wet days. "
               if obs_active else "")
    if len(fc) >= 2:
        w1, w2 = fc[0], fc[1]
        if (w1["p_above"] >= P_ACTIVE_WEEK1 and w2["p_above"] >= P_ACTIVE_WEEK2
                and w1["p_dry_week"] <= 0.10 and w2["p_dry_week"] <= 0.10):
            p = min(w1["p_above"], w2["p_above"])
            return Hazard(
                "active_phase", p, 1, _conf_min(w1["confidence"], w2["confidence"]),
                "observed+forecast" if obs_active else "forecast", "info",
                f"{obs_txt}Active monsoon phase: above-normal rain favoured in week 1 "
                f"({pct(w1['p_above'])}) and week 2 ({pct(w2['p_above'])}), "
                f"{fmt_range(w1['week_start'], w2['week_end'])}.",
                window_start=w1["week_start"], window_end=w2["week_end"],
                evidence={"p_above": [w1["p_above"], w2["p_above"]], "anomaly_7d_pct": anom7_pct,
                          "wet_days_last_7": wet_days_7})
    if obs_active:
        return Hazard("active_phase", 1.0, 0, "High", "observed", "info",
                      f"Active monsoon phase: {obs_txt.strip()}",
                      window_start=issue_date - timedelta(days=7),
                      window_end=issue_date - timedelta(days=1),
                      evidence={"anomaly_7d_pct": anom7_pct, "wet_days_last_7": wet_days_7})
    return None


def rule_revival(obs, fc, issue_date: date) -> Hazard | None:
    run = trailing_dry_run(obs)
    if run >= DRY_SPELL_DAYS and fc:
        dry_until, j = issue_date - timedelta(days=1), 0
        prior = f"after {run} observed dry days"
    else:
        j = None
        for i, r in enumerate(fc[:-1]):
            if r["p_dry_week"] >= P_DRY_WEEK_ALERT:
                j = i + 1
        if j is None:
            return None
        k = fc[j - 1]
        dry_until = k["week_end"]
        prior = f"after a likely dry week {k['lead_week']} ({pct(k['p_dry_week'])} chance dry)"
    if j >= len(fc):
        return None
    r = fc[j]
    p = p_onset_week(r)
    if p < P_REVIVAL_ALERT or r["p_above"] < 0.40:
        return None
    return Hazard(
        "revival", p, int(r["lead_week"]), r["confidence"],
        "observed+forecast" if j == 0 else "forecast", "info",
        f"Rain revival {prior}: week {r['lead_week']} ({fmt_range(r['week_start'], r['week_end'])}) "
        f"has {pct(p)} chance of ≥ {ONSET_MM:.0f} mm (median {r['q50_mm']:.0f} mm, above-normal "
        f"{pct(r['p_above'])}).",
        window_start=r["week_start"], window_end=r["week_end"],
        evidence={"p_total_ge_20mm": round(p, 4), "p_above": r["p_above"], "dry_until": dry_until})


def detect_all(obs: Sequence[tuple[date, float]], fc: Sequence[dict[str, Any]], issue_date: date,
               anom7_pct: float | None = None, wet_days_7: int | None = None) -> list[Hazard]:
    """Run every rule for one district. ``fc`` must be sorted by lead week."""
    fc = sorted(fc, key=lambda r: int(r["lead_week"]))
    in_season = is_onset_season(issue_date)
    if not observed_is_fresh(obs, issue_date):
        # Observations stop too early (e.g. a future demo date): forecast-only rules, so
        # nothing "ongoing" is inferred from stale data.
        obs, anom7_pct, wet_days_7 = [], None, None
    out = [
        rule_false_onset(obs, fc, issue_date, in_season),
        rule_onset(obs, fc, issue_date, in_season),
        rule_dry_spell(obs, fc, issue_date),
        rule_heavy_rain(obs, fc, issue_date),
        rule_active_phase(obs, fc, issue_date, anom7_pct, wet_days_7),
        rule_revival(obs, fc, issue_date),
    ]
    hazards = [h for h in out if h is not None]
    # A false onset supersedes the plain onset signal it is built on.
    if any(h.hazard_type == "false_onset" for h in hazards):
        hazards = [h for h in hazards if h.hazard_type != "onset"]
    return hazards
