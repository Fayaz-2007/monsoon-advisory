"""Pipeline health, model skill, runtime settings and demo scenarios."""

from __future__ import annotations

import collections
import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app import segment1, state
from app.api.common import clean, context_or_error
from app.config import get_app_settings, today
from app.db import APP_TABLES, execute, fetch_all
from app.forecasts import clear_cache, real_issue_dates
from app.hazards.engine import clear_memo, list_hazards
from app.mock.scenarios import SCENARIOS
from pipeline.config import BACKEND_DIR

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/pipeline/health")
def pipeline_health():
    """REAL Segment 1/2 status: table row counts, the latest pipeline_runs, quality summary."""
    counts = segment1.table_counts()
    runs = segment1.recent_runs(10)
    quality = segment1.quality_summary()
    last_rain = segment1.last_rainfall_date()
    lag = (today() - last_rain).days if last_rain else None
    issue_dates = real_issue_dates()
    failed_recent = [r for r in runs[:5] if r["status"] == "failed"]
    status = "ok"
    if quality["summary"]["fail"] or lag is None or lag > 3:
        status = "degraded"
    elif quality["summary"]["warn"] or failed_recent:
        status = "ok_with_warnings"
    return {
        "status": status,
        "table_counts": counts,
        "rainfall": {"last_date": last_rain, "lag_days": lag},
        "forecasts": {"issue_dates": issue_dates[-10:], "latest_issue_date":
                      issue_dates[-1] if issue_dates else None},
        "recent_runs": runs,
        "quality": quality,
    }


@router.get("/model/skill")
def model_skill(model_version: str | None = None,
                target: Literal["tercile", "heavy_day", "dry_week", "weekly_total_mm"] | None = None,
                season: Literal["SWM", "NEM", "ALL"] | None = None,
                lead_week: int | None = Query(None, ge=1, le=4),
                metric: str | None = None, model: str | None = None):
    """REAL Segment 2 validation scores (``model_skill``) with 5–95% bootstrap CIs."""
    version = model_version or get_app_settings().real_model_version
    where, params = ["model_version = :v"], {"v": version}
    for col, val in (("target", target), ("season", season), ("lead_week", lead_week),
                     ("metric", metric), ("model", model)):
        if val is not None:
            where.append(f"{col} = :{col}")
            params[col] = val
    rows = fetch_all(f"SELECT target, lead_week, season, metric, model, value, ci_low, ci_high, "
                     f"n_samples, n_years FROM public.model_skill WHERE {' AND '.join(where)} "
                     f"ORDER BY target, season, lead_week, metric, model", params)
    if not rows and not any(v is not None for v in (target, season, lead_week, metric, model)):
        raise HTTPException(404, f"No model_skill rows for model_version {version!r}")
    headline_metric = {"tercile": "rpss", "heavy_day": "bss", "dry_week": "bss",
                       "weekly_total_mm": "qss"}
    headline = [
        {**{k: r[k] for k in ("target", "lead_week", "season", "value", "ci_low", "ci_high")},
         "metric": r["metric"],
         "skillful": r["ci_low"] is not None and r["ci_low"] > 0}
        for r in rows if r["model"] == "lgbm" and headline_metric.get(r["target"]) == r["metric"]]
    meta, card = {}, None
    art = BACKEND_DIR / "ml" / "artifacts" / version
    if (art / "meta.json").exists():
        m = json.loads((art / "meta.json").read_text(encoding="utf-8"))
        meta = {k: m.get(k) for k in ("model_version", "trained", "train_years", "final_data_end")}
        meta["n_features"] = len(m.get("features", []))
    if (art / "model_card.md").exists():
        card = f"backend/ml/artifacts/{version}/model_card.md"
    return {"model_version": version, "meta": meta, "model_card": card,
            "note": "Skill scores are relative to climatology: > 0 beats climatology. CIs are "
                    "5–95% year-block bootstrap intervals. 'skillful' = CI lower bound > 0.",
            "headline": headline, "count": len(rows), "rows": rows}


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

class SourceBody(BaseModel):
    source: Literal["mock", "real"]


def _source_info() -> dict:
    return {"source": state.get_source(), "available": ["mock", "real"],
            "env_default": get_app_settings().forecast_source,
            "scenario": state.get_scenario(), "real_issue_dates": real_issue_dates()[-10:],
            "demo_mode": get_app_settings().demo_mode}


@router.get("/settings/forecast-source")
def get_forecast_source():
    return _source_info()


@router.post("/settings/forecast-source")
def set_forecast_source(body: SourceBody, date: date | None = None):
    """Switch mock ↔ real at runtime. The whole pipeline (hazards → advisories) is re-run
    for the issue date and the result summarised, so the switch is visible immediately."""
    state.set_source(body.source)
    clear_memo()
    ctx = context_or_error(date)
    hz = list_hazards(ctx.run_id)
    return {**_source_info(), "context": ctx.as_dict(),
            "hazards_by_type": dict(collections.Counter(h["hazard_type"] for h in hz)),
            "hazard_count": len(hz)}


# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------

def _scenario_dict(s) -> dict:
    return {"name": s.name, "title": s.title, "description": s.description,
            "demo_date": s.demo_date or today(), "focus_districts": list(s.focus_districts)}


@router.get("/demo/scenarios", tags=["demo"])
def list_scenarios():
    return {"active": state.get_scenario(), "scenarios": [_scenario_dict(s) for s in SCENARIOS.values()]}


@router.post("/demo/scenario/{name}", tags=["demo"])
def activate_scenario(name: str):
    """Activate a demo scenario (switches the forecast source to mock). Hazards and
    advisories for the scenario's demo date are computed right away."""
    if name not in SCENARIOS:
        raise HTTPException(404, f"Unknown scenario {name!r}; choose from {list(SCENARIOS)}")
    switched = state.get_source() != "mock"
    state.set_source("mock")
    state.set_scenario(name)
    clear_memo()
    ctx = context_or_error(None)
    sc = SCENARIOS[name]
    hz = list_hazards(ctx.run_id)
    focus = [h for h in hz if h["district"] in sc.focus_districts]
    adv = fetch_all("SELECT id, district, crop, stage, hazard_type, severity, title_en, status "
                    "FROM advisories WHERE issue_date = :d AND forecast_source = 'mock' AND "
                    "scenario = :sc AND status <> 'superseded' AND district = ANY(:f) "
                    "ORDER BY CASE severity WHEN 'warning' THEN 0 WHEN 'watch' THEN 1 ELSE 2 END, id",
                    {"d": ctx.issue_date, "sc": name, "f": list(sc.focus_districts) or [""]})
    return {"scenario": _scenario_dict(sc), "switched_source_to_mock": switched,
            "context": ctx.as_dict(), "hazard_count": len(hz),
            "hazards_by_type": dict(collections.Counter(h["hazard_type"] for h in hz)),
            "focus_hazards": focus, "focus_advisories": adv}


@router.post("/demo/reset", tags=["demo"])
def reset_demo(purge: bool = Query(False, description="Also delete all hazards, advisories, "
                                                      "broadcasts and feedback (backend tables only)")):
    """Clear the scenario and return the forecast source to its .env default. With
    ``purge=true`` the backend's workflow tables are emptied too (Segment 1/2 untouched)."""
    state.reset_runtime()
    clear_memo()
    clear_cache()
    purged = []
    if purge:
        for t in APP_TABLES:
            if t != "app_settings":
                execute(f"TRUNCATE {t} RESTART IDENTITY CASCADE")
                purged.append(t)
    ctx = context_or_error(None)
    return {"reset": True, "purged_tables": purged, **_source_info(), "context": ctx.as_dict()}


@router.get("/health", tags=["system"])
def health():
    return {"status": "ok", "demo_mode": get_app_settings().demo_mode,
            "forecast_source": state.get_source(), "scenario": state.get_scenario(),
            "llm_enabled": get_app_settings().llm_enabled, "today": today(),
            "default_date": state.default_date(), "tables": APP_TABLES}
