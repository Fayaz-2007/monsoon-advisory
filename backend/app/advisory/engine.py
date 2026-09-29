"""Advisory engine: hazards × current crop stage → rule → drafted advisory (status=draft).

Called by the hazard engine whenever the stored hazard set for a context changes:

* one advisory per (district, crop, season): the most severe / most relevant hazard wins
  (see ``resolve_conflicts``), so farmers never get contradictory messages;
* new (district, crop, season, hazard) → insert a draft;
* an existing unedited draft → refreshed with the new numbers;
* an edited draft, or an approved/rejected/sent advisory → left alone (human decisions win);
* drafts whose hazard disappeared → ``superseded``.
Every change is written to ``advisory_events`` (the audit trail).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import TYPE_CHECKING, Any

from app import llm, segment1
from app.config import get_app_settings
from app.advisory.rules import (CROP_NAMES, SOURCE_NOTE, STAGE_NAMES, TA_DISTRICTS, AdviceRule,
                                select_rule)
from app.advisory.stages import CropStage, current_stages
from app.db import fetch_all, fetch_one, to_json, tx
from app.hazards.rules import SEVERITY_ORDER, fmt_range, pct
from app.mock.farmers import farmer_counts

if TYPE_CHECKING:
    from app.hazards.engine import Context

log = logging.getLogger(__name__)

CONTENT_FIELDS = ("title_en", "title_ta", "text_en", "text_ta", "action_en", "action_ta")


def _min_severity(a: str, b: str) -> str:
    return a if SEVERITY_ORDER[a] <= SEVERITY_ORDER[b] else b


TA_MONTHS = ["ஜன.", "பிப்.", "மார்ச்", "ஏப்.", "மே", "ஜூன்", "ஜூலை", "ஆக.", "செப்.", "அக்.",
             "நவ.", "டிச."]


def _fmt_ta(d: date) -> str:
    return f"{d.day} {TA_MONTHS[d.month - 1]}"


def render(rule: AdviceRule, hazard: dict[str, Any], cs: CropStage) -> dict[str, str]:
    """Fill a rule's templates with the hazard's real numbers (pure; tested).

    Observed hazards (lead week 0) are already happening, so they read "high chance … in
    the coming days" instead of quoting 100% for a window in the past."""
    crop_en, crop_ta = CROP_NAMES.get(cs.crop, (cs.crop, cs.crop))
    stage_en, stage_ta = STAGE_NAMES.get(cs.stage, (cs.stage.replace("_", " "), cs.stage))
    ws, we = hazard.get("window_start"), hazard.get("window_end")
    observed = int(hazard.get("lead_week", 1)) == 0
    if observed or not (ws and we):
        window_en, window_ta = "the coming days", "வரும் நாட்களில்"
        prob_en, prob_ta = "a high", "அதிக"
    else:
        window_en, window_ta = fmt_range(ws, we), f"{_fmt_ta(ws)}–{_fmt_ta(we)}"
        prob_en = prob_ta = pct(float(hazard["probability"]))
    common = {"district": hazard["district"],
              "district_ta": TA_DISTRICTS.get(hazard["district"], hazard["district"])}
    en = {**common, "crop": crop_en, "crop_ta": crop_ta, "stage": stage_en, "stage_ta": stage_ta,
          "window": window_en, "prob": prob_en}
    ta = {**en, "window": window_ta, "prob": prob_ta, "crop": crop_ta, "stage": stage_ta}
    out = {f: getattr(rule, f).format(**(ta if f.endswith("_ta") else en)) for f in CONTENT_FIELDS}
    # "a high chance" reads right; "a 72% chance" too — but templates say "{prob} chance",
    # so drop the article where it is not needed.
    for f in ("text_en", "action_en", "title_en"):
        out[f] = out[f].replace("a a high", "a high").replace("(a high chance)", "(high chance)")
    for f in ("text_ta", "action_ta", "title_ta"):
        out[f] = out[f].replace("வரும் நாட்களில் காலத்தில்", "வரும் நாட்களில்")
    return out


def build_drafts(ctx_date: date, hazards: list[dict[str, Any]],
                 stages_by_district: dict[str, list[CropStage]]) -> list[dict[str, Any]]:
    """Pure core: one draft per (district, crop, season, hazard type) with a matching rule."""
    area = dict(zip(segment1.regions()["name"], segment1.regions()["area_km2"])) if hazards else {}
    drafts = []
    for h in hazards:
        for cs in stages_by_district.get(h["district"], []):
            rule = select_rule(cs.crop, cs.stage, cs.stage_group, h["hazard_type"], h.get("subtype"))
            if rule is None:
                continue
            d = render(rule, h, cs)
            d.update(
                region_id=h["region_id"], district=h["district"], crop=cs.crop, season=cs.season,
                stage=cs.stage, stage_group=cs.stage_group, hazard_type=h["hazard_type"],
                hazard_subtype=h.get("subtype"), hazard_probability=float(h["probability"]),
                hazard_lead_week=int(h["lead_week"]), hazard_confidence=h["confidence"],
                hazard_why=h["why"], rule_id=rule.rule_id,
                severity=_min_severity(rule.severity, h["severity"]),
                source_note=SOURCE_NOTE,
                farmers_targeted=farmer_counts(h["district"], float(area.get(h["district"], 0)), cs.crop),
            )
            drafts.append(d)
    return resolve_conflicts(drafts)


# When several hazards hit the same crop, farmers get ONE message: the most severe, then
# the most decision-relevant hazard type, then the most probable.
HAZARD_PRIORITY = {"false_onset": 0, "heavy_rain": 1, "dry_spell": 2, "onset": 3,
                   "active_phase": 4, "revival": 5}


def resolve_conflicts(drafts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one draft per (district, crop, season) (pure; tested)."""
    best: dict[tuple, dict[str, Any]] = {}
    for d in drafts:
        k = (d["region_id"], d["crop"], d["season"])
        rank = (-SEVERITY_ORDER[d["severity"]], HAZARD_PRIORITY.get(d["hazard_type"], 9),
                -d["hazard_probability"])
        if k not in best or rank < best[k][0]:
            best[k] = (rank, d)
    return [v[1] for v in best.values()]


def _dedupe_key(ctx: "Context", d: dict[str, Any]) -> str:
    return (f"{ctx.issue_date}|{ctx.source}|{ctx.scenario}|{d['region_id']}|{d['crop']}|"
            f"{d['season']}|{d['hazard_type']}")


def _log_event(conn, advisory_id: int, action: str, actor: str = "system",
               note: str | None = None, payload: dict | None = None) -> None:
    fetch_all("INSERT INTO advisory_events (advisory_id, action, actor, note, payload) "
              "VALUES (:a, :act, :actor, :note, CAST(:p AS jsonb)) RETURNING id",
              {"a": advisory_id, "act": action, "actor": actor, "note": note,
               "p": to_json(payload or {})}, conn)


def _rephrase_many(texts: dict[int, str]) -> dict[int, str]:
    if not texts or not llm.enabled():
        return {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = dict(zip(texts.keys(), ex.map(llm.rephrase, texts.values())))
    return {k: v for k, v in results.items() if v}


def draft_advisories(ctx: "Context") -> dict[str, int]:
    """Sync the advisories of one context with its current hazards."""
    from app.hazards.engine import list_hazards

    hazards = list_hazards(ctx.run_id)
    districts = {h["district"] for h in hazards}
    stages = {d: current_stages(d, ctx.issue_date) for d in districts}
    drafts = build_drafts(ctx.issue_date, hazards, stages)
    stats = {"inserted": 0, "updated": 0, "superseded": 0, "kept": 0}
    to_rephrase: dict[int, str] = {}
    with tx() as conn:
        live = {r["dedupe_key"]: r for r in fetch_all(
            "SELECT * FROM advisories WHERE issue_date = :d AND forecast_source = :s AND "
            "scenario = :sc AND status <> 'superseded' FOR UPDATE",
            {"d": ctx.issue_date, "s": ctx.source, "sc": ctx.scenario}, conn)}
        seen = set()
        for d in drafts:
            key = _dedupe_key(ctx, d)
            if key in seen:
                continue
            seen.add(key)
            cur = live.get(key)
            cols = {k: v for k, v in d.items()}
            if cur is None:
                row = fetch_one(
                    "INSERT INTO advisories (issue_date, forecast_source, scenario, dedupe_key, "
                    + ", ".join(cols) + ") VALUES (:issue_date, :source, :scenario, :key, "
                    + ", ".join(f":{c}" for c in cols) + ") RETURNING id",
                    {**cols, "issue_date": ctx.issue_date, "source": ctx.source,
                     "scenario": ctx.scenario, "key": key}, conn)
                _log_event(conn, row["id"], "drafted", payload={"rule_id": d["rule_id"],
                                                                "hazard_run_id": ctx.run_id})
                to_rephrase[row["id"]] = d["text_en"] + " " + d["action_en"]
                stats["inserted"] += 1
            elif cur["status"] == "draft" and not cur["edited"]:
                changed = any(cur.get(c) != v for c, v in cols.items()
                              if c not in ("hazard_probability",)) or \
                    round(cur["hazard_probability"] or 0, 3) != round(d["hazard_probability"], 3)
                if changed:
                    fetch_all("UPDATE advisories SET " + ", ".join(f"{c} = :{c}" for c in cols)
                              + ", updated_at = now() WHERE id = :id RETURNING id",
                              {**cols, "id": cur["id"]}, conn)
                    _log_event(conn, cur["id"], "redrafted", note="hazard changed",
                               payload={"rule_id": d["rule_id"], "hazard_run_id": ctx.run_id})
                    to_rephrase[cur["id"]] = d["text_en"] + " " + d["action_en"]
                    stats["updated"] += 1
                else:
                    stats["kept"] += 1
            else:
                stats["kept"] += 1
        for key, cur in live.items():
            if key not in seen and cur["status"] == "draft":
                fetch_all("UPDATE advisories SET status = 'superseded', updated_at = now() "
                          "WHERE id = :id RETURNING id", {"id": cur["id"]}, conn)
                _log_event(conn, cur["id"], "superseded", note="hazard no longer present")
                stats["superseded"] += 1
    simple = _rephrase_many(to_rephrase)
    if simple:
        with tx() as conn:
            for aid, text in simple.items():
                fetch_all("UPDATE advisories SET simple_text_en = :t, rephrased_by = :by "
                          "WHERE id = :id RETURNING id",
                          {"t": text, "by": f"llm:{get_app_settings().llm_model}", "id": aid}, conn)
    log.info("advisories for %s/%s/%s: %s", ctx.issue_date, ctx.source, ctx.scenario, stats)
    return stats
