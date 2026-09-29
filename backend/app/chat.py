"""Grounded Q&A over the current forecasts, hazards and advisories.

``build_facts`` collects the numbers the answer may use (from the same functions the API
endpoints use). Without LLM_API_KEY the answer is a template filled with those facts; with
a key, Claude answers from the facts only, and any error falls back to the template.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any

from app import segment1
from app.advisory.stages import current_stages
from app.db import fetch_all, to_json
from app.hazards.engine import Context, list_hazards
from app.hazards.rules import SEVERITY_ORDER, fmt_range, pct

INTENTS = {
    "sowing": r"\b(sow|sowing|seed|plant|planting|விதை)",
    "heavy": r"\b(heavy|flood|cyclone|storm|downpour|கனமழை)",
    "dry": r"\b(dry|drought|no rain|break|irrigat|வறட்சி)",
    "advisory": r"\b(advis|advice|recommend|what should|ஆலோசனை)",
    "statewide": r"\b(which districts|where|statewide|state|all districts|tamil nadu|alerts?)\b",
    "forecast": r"\b(rain|forecast|weather|week|மழை)",
}


def detect_intent(message: str) -> str:
    m = message.lower()
    for name, pat in INTENTS.items():
        if re.search(pat, m):
            return name
    return "summary"


def find_district(message: str) -> dict[str, Any] | None:
    m = message.lower()
    regs = segment1.regions()
    best = None
    for r in regs.itertuples():
        for key in {r.name.lower(), r.slug.replace("-", " "), r.name.lower().replace("the ", "")}:
            if key and re.search(rf"\b{re.escape(key)}\b", m):
                if best is None or len(key) > best[0]:
                    best = (len(key), r)
    return segment1.resolve_district(best[1].id) if best else None


def build_facts(ctx: Context, district: dict[str, Any] | None) -> dict[str, Any]:
    facts: dict[str, Any] = {"context": ctx.as_dict()}
    hz_all = list_hazards(ctx.run_id)
    if district:
        rid = int(district["id"])
        fc = ctx.forecasts[ctx.forecasts["region_id"] == rid].sort_values("lead_week")
        obs = segment1.observed_daily(ctx.issue_date, 30, [rid])
        last7 = obs[obs["date"] >= ctx.issue_date - timedelta(days=7)]
        facts["district"] = district["name"]
        facts["forecast"] = [
            {"lead_week": int(r.lead_week), "window": fmt_range(r.week_start, r.week_end),
             "median_mm": round(float(r.q50_mm), 1), "range_mm": [round(float(r.q10_mm), 1),
                                                                  round(float(r.q90_mm), 1)],
             "p_below": float(r.p_below), "p_normal": float(r.p_normal), "p_above": float(r.p_above),
             "p_heavy": float(r.p_heavy), "p_dry_week": float(r.p_dry_week),
             "confidence": r.confidence} for r in fc.itertuples()]
        facts["hazards"] = [{k: h[k] for k in ("hazard_type", "severity", "probability",
                                               "lead_week", "confidence", "why")}
                            for h in hz_all if h["region_id"] == rid]
        facts["observed"] = {"through": obs["date"].max() if not obs.empty else None,
                             "last_7_days_mm": round(float(last7["rain_mm"].sum()), 1) if not last7.empty else None,
                             "last_30_days_mm": round(float(obs["rain_mm"].sum()), 1) if not obs.empty else None}
        facts["crop_stages"] = [{"crop": s.crop, "season": s.season, "stage": s.stage}
                                for s in current_stages(district["name"], ctx.issue_date)]
        facts["advisories"] = fetch_all(
            "SELECT id, crop, stage, hazard_type, severity, title_en, action_en, status "
            "FROM advisories WHERE issue_date = :d AND forecast_source = :s AND scenario = :sc "
            "AND region_id = :r AND status <> 'superseded' ORDER BY CASE severity WHEN 'warning' "
            "THEN 0 WHEN 'watch' THEN 1 ELSE 2 END LIMIT 6",
            {"d": ctx.issue_date, "s": ctx.source, "sc": ctx.scenario, "r": rid})
    alerts = [h for h in hz_all if h["severity"] in ("watch", "warning")]
    alerts.sort(key=lambda h: (-SEVERITY_ORDER[h["severity"]], -h["probability"]))
    facts["statewide"] = {
        "districts_with_alerts": len({h["district"] for h in alerts}),
        "top_alerts": [{k: h[k] for k in ("district", "hazard_type", "severity", "probability",
                                          "lead_week", "why")} for h in alerts[:6]],
    }
    return facts


def _src_line(facts: dict[str, Any]) -> str:
    c = facts["context"]
    src = "MOCK forecast" if c["forecast_source"] == "mock" else f"model {c['model_version']}"
    return (f"(Source: {src} issued {c['forecast_issue_date']}; observed rain from IMD data "
            f"through {c['observed_through']}.)")


def _week_line(f: dict[str, Any]) -> str:
    lean = max(("below", f["p_below"]), ("normal", f["p_normal"]), ("above", f["p_above"]),
               key=lambda x: x[1])
    return (f"Week {f['lead_week']} ({f['window']}): median {f['median_mm']} mm "
            f"(range {f['range_mm'][0]}–{f['range_mm'][1]} mm), {pct(lean[1])} chance of "
            f"{lean[0]}-normal rain, heavy-rain day {pct(f['p_heavy'])}, fully dry week "
            f"{pct(f['p_dry_week'])} [{f['confidence']} confidence].")


def template_answer(message: str, facts: dict[str, Any]) -> str:
    intent = detect_intent(message)
    d = facts.get("district")
    sw = facts["statewide"]
    if not d or intent == "statewide":
        if not sw["top_alerts"]:
            return ("No watch or warning alerts are active in Tamil Nadu for this forecast. "
                    + _src_line(facts))
        lines = [f"{sw['districts_with_alerts']} district(s) have alerts. The most serious:"]
        lines += [f"• {a['district']}: {a['hazard_type'].replace('_', ' ')} ({a['severity']}, "
                  f"{pct(a['probability'])}) — {a['why']}" for a in sw["top_alerts"]]
        if not d:
            lines.append("Ask about a district by name (e.g. 'Will it rain in Madurai?') for details.")
        return "\n".join(lines + [_src_line(facts)])

    hz = facts["hazards"]
    fc = facts["forecast"]
    obs = facts["observed"]
    obs_line = (f"Observed: {obs['last_7_days_mm']} mm in the last 7 days and "
                f"{obs['last_30_days_mm']} mm in the last 30 days (to {obs['through']})."
                if obs["last_7_days_mm"] is not None else "No recent observed rainfall available.")

    def hazards_of(*types: str) -> list[dict[str, Any]]:
        return [h for h in hz if h["hazard_type"] in types]

    if intent == "sowing":
        bad = hazards_of("false_onset", "dry_spell", "heavy_rain")
        good = hazards_of("onset", "active_phase", "revival")
        sowing = [s["crop"] for s in facts["crop_stages"] if s["stage"] == "sowing"]
        head = (f"{d}: crops in their sowing window now: {', '.join(sowing)}. " if sowing
                else f"{d}: no crop in the calendar is in its sowing window right now. ")
        if any(h["hazard_type"] == "false_onset" for h in bad):
            h = next(h for h in bad if h["hazard_type"] == "false_onset")
            verdict = f"Don't sow yet. {h['why']}"
        elif bad:
            verdict = "Hold off on sowing. " + " ".join(h["why"] for h in bad[:2])
        elif good:
            verdict = "Conditions look favourable. " + good[0]["why"]
        else:
            verdict = "No sowing-related hazard is flagged. " + _week_line(fc[0])
        return f"{head}{verdict}\n{obs_line}\n{_src_line(facts)}"
    if intent in ("heavy", "dry"):
        types = ("heavy_rain",) if intent == "heavy" else ("dry_spell", "false_onset")
        found = hazards_of(*types)
        key = "p_heavy" if intent == "heavy" else "p_dry_week"
        label = "a heavy-rain day (≥ 64.5 mm)" if intent == "heavy" else "a fully dry week"
        probs = "; ".join(f"week {f['lead_week']} ({f['window']}) {pct(f[key])}" for f in fc)
        lead = " ".join(h["why"] for h in found) if found else f"No {intent} alert for {d}."
        return f"{d}: {lead}\nChance of {label}: {probs}.\n{obs_line}\n{_src_line(facts)}"
    if intent == "advisory":
        adv = facts["advisories"]
        if not adv:
            return f"{d}: no advisories are drafted for this forecast. {_src_line(facts)}"
        lines = [f"{d}: {len(adv)} advisory(ies):"]
        lines += [f"• {a['crop']} ({a['stage'].replace('_', ' ')}), {a['severity']}, {a['status']}: "
                  f"{a['title_en']} — {a['action_en']}" for a in adv]
        return "\n".join(lines + [_src_line(facts)])
    # forecast / summary
    lines = [f"Rain outlook for {d}:"] + [_week_line(f) for f in fc]
    if hz:
        lines.append("Hazards: " + " ".join(f"[{h['severity']}] {h['why']}" for h in hz[:3]))
    lines += [obs_line, _src_line(facts)]
    return "\n".join(lines)


LLM_SYSTEM = """You are AgriVarsha's assistant for agricultural officers and farmers in Tamil Nadu.
Answer ONLY from the JSON facts below. Quote the exact numbers (mm, %, dates, confidence) from
the facts. If the facts do not contain the answer, say so. Keep answers under 150 words, plain
language, no markdown headings. End with one line naming the forecast source and issue date.
Probabilities in the facts are fractions (0.72 = 72%).

FACTS:
"""


def llm_system(facts: dict[str, Any]) -> str:
    return LLM_SYSTEM + json.dumps(json.loads(to_json(facts)), ensure_ascii=False, indent=1)


def facts_sources(facts: dict[str, Any]) -> list[str]:
    src = ["/api/hazards", "/api/overview"]
    if facts.get("district"):
        slug = facts["district"].lower().replace(" ", "-")
        src = [f"/api/forecast/{slug}", f"/api/rainfall/{slug}",
               f"/api/advisories?district={slug}"] + src
    return src

