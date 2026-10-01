"""Districts, forecasts, hazards, overview and observed rainfall."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app import blocks, segment1
from app.advisory.stages import current_stages
from app.api.common import clean, context_or_error, district_or_404, forecast_rows, records
from app.api.overview import build_overview, district_risk
from app.db import fetch_all
from app.hazards.engine import list_hazards

router = APIRouter(prefix="/api", tags=["data"])

DateQ = Query(None, description="Issue date (YYYY-MM-DD). Default: the active scenario's demo "
                                "date, else today.")


@router.get("/context")
def get_context(date: date | None = DateQ):
    """The context every other endpoint uses: issue date, forecast source, scenario."""
    return context_or_error(date).as_dict()


@router.get("/districts")
def get_districts(date: date | None = DateQ,
                  tolerance: float = Query(0.005, ge=0, le=0.1,
                                           description="Geometry simplification (degrees)")):
    """GeoJSON FeatureCollection of the 38 districts (Segment 1 boundaries), with each
    district's current risk in ``properties.risk``."""
    ctx = context_or_error(date)
    gj = segment1.districts_geojson(tolerance)
    risk = district_risk(list_hazards(ctx.run_id))
    for f in gj["features"]:
        f["properties"]["risk"] = risk.get(f["id"], {"severity": "none", "top_hazard": None,
                                                     "top_probability": None, "hazard_types": []})
    gj["context"] = clean(ctx.as_dict())
    return gj


@router.get("/forecasts")
def get_all_forecasts(date: date | None = DateQ,
                      lead_week: int | None = Query(None, ge=1, le=4)):
    """Forecast rows for every district (Segment 2 schema) — handy for map layers."""
    ctx = context_or_error(date)
    df = ctx.forecasts
    if lead_week:
        df = df[df["lead_week"] == lead_week]
    names = dict(zip(segment1.regions()["id"], segment1.regions()["name"]))
    rows = records(df)
    for r in rows:
        r["district"] = names.get(r["region_id"])
    return {"context": ctx.as_dict(), "count": len(rows), "forecasts": rows}


@router.get("/forecast/{district}")
def get_forecast(district: str, date: date | None = DateQ):
    """4-week forecast for one district plus its hazards, crop stages and recent rain."""
    reg = district_or_404(district)
    ctx = context_or_error(date)
    is_block = reg.get("level") == "block"
    if is_block:
        obs = blocks.observed_daily(ctx.issue_date, 30)
        obs = obs[obs["region_id"] == reg["id"]]
    else:
        obs = segment1.observed_daily(ctx.issue_date, 30, [reg["id"]])
    last7 = obs[obs["date"] >= ctx.issue_date - timedelta(days=7)]
    info = {k: reg[k] for k in ("id", "code", "slug", "name", "area_km2", "lon", "lat", "coastal")}
    if is_block:
        info.update({k: reg[k] for k in ("level", "label", "name_ta", "parent", "hq", "demo",
                                         "demo_label", "coord_source")})
    return {
        "context": ctx.as_dict(),
        "district": info,
        "forecast": forecast_rows(ctx, reg["id"]),
        "hazards": list_hazards(ctx.run_id, reg["id"]),
        "crop_stages": [s.as_dict() for s in current_stages(
            reg["parent"]["name"] if is_block else reg["name"], ctx.issue_date)],
        "observed": {
            "through": clean(obs["date"].max()) if not obs.empty else None,
            "last_7_days_mm": round(float(last7["rain_mm"].sum()), 1) if not last7.empty else None,
            "last_30_days_mm": round(float(obs["rain_mm"].sum()), 1) if not obs.empty else None,
            "source": ("MOCK block rain: Madurai's IMD series x per-block factor (demo)" if is_block
                       else "Segment 1 rainfall_daily (IMD gridded, area-weighted)"),
        },
    }


@router.get("/blocks", tags=["blocks"])
def get_blocks(district: str = Query("madurai", description="Parent district (only Madurai has "
                                                             "block-level demo data)"),
               date: date | None = DateQ):
    """MOCK block-level demo data: the CD blocks of a district with each block's current risk.
    Only Madurai (13 blocks) has them; other districts return an empty list."""
    parent = district_or_404(district)
    ctx = context_or_error(date)
    is_madurai = parent.get("level") != "block" and parent["name"] == blocks.PARENT_DISTRICT
    risk = district_risk(list_hazards(ctx.run_id, level="block")) if is_madurai else {}
    none = {"severity": "none", "top_hazard": None, "top_probability": None, "hazard_types": []}
    items = ([{**blocks.block_dict(b), "risk": risk.get(b.id, none)} for b in blocks.BLOCKS]
             if is_madurai else [])
    return {"context": ctx.as_dict(),
            "district": {"id": parent["id"], "name": parent["name"], "slug": parent["slug"]},
            "level": "block", "demo": True, "demo_label": blocks.DEMO_LABEL,
            "sources": {"block_list": blocks.SOURCE_BLOCKS,
                        "coordinates": "OpenStreetMap (Nominatim/Photon); Sedapatti: Wikipedia",
                        "data": "MOCK generator (same as districts), blended with the parent district"},
            "count": len(items), "blocks": items}


@router.get("/blocks/{block}", tags=["blocks"])
def get_block(block: str, date: date | None = DateQ):
    """One block's forecast, hazards, crop stages and recent (MOCK) rain — same shape as
    GET /api/forecast/{district}."""
    reg = blocks.resolve_block(block)
    if reg is None:
        raise HTTPException(404, f"Unknown block {block!r}. See GET /api/blocks?district=madurai.")
    return get_forecast(str(reg["id"]), date)


@router.get("/hazards")
def get_hazards(date: date | None = DateQ,
                district: str | None = Query(None, description="Name, slug or id"),
                type: str | None = Query(None, description="onset | false_onset | active_phase | "
                                                           "dry_spell | heavy_rain | revival"),
                severity: Literal["info", "watch", "warning"] | None = None,
                min_severity: Literal["info", "watch", "warning"] | None = None,
                level: Literal["district", "block", "all"] = Query(
                    "district", description="district (the 38 districts) | block (MOCK Madurai "
                                            "blocks, demo) | all")):
    """Hazards detected for the issue date (Segment 3), most severe first."""
    ctx = context_or_error(date)
    rid = district_or_404(district)["id"] if district else None
    rows = list_hazards(ctx.run_id, rid, type, level)
    order = {"info": 0, "watch": 1, "warning": 2}
    if severity:
        rows = [h for h in rows if h["severity"] == severity]
    if min_severity:
        rows = [h for h in rows if order[h["severity"]] >= order[min_severity]]
    return {"context": ctx.as_dict(), "count": len(rows), "hazards": rows}


@router.get("/overview")
def get_overview(date: date | None = DateQ):
    """Headline KPIs for the dashboard."""
    return build_overview(context_or_error(date))


@router.get("/rainfall/{district}")
def get_rainfall(district: str, days: int = Query(30, ge=1, le=366),
                 end: date | None = Query(None, description="Last day (default: latest data)")):
    """REAL observed daily rainfall (Segment 1) with the 1991–2020 daily normal."""
    reg = district_or_404(district)
    is_block = reg.get("level") == "block"
    df = (blocks.rainfall_series(reg["id"], days, end) if is_block
          else segment1.rainfall_series(reg["id"], days, end))
    if df.empty:
        raise HTTPException(404, f"No rainfall data for {reg['name']} in the requested window")
    rows = records(df)
    total = float(df["rain_mm"].sum())
    normal = float(df["normal_mm"].sum())
    return {
        "district": {"id": reg["id"], "name": reg["name"], "slug": reg["slug"]},
        "days": len(rows), "start": rows[0]["date"], "end": rows[-1]["date"],
        "total_mm": round(total, 1), "normal_mm": round(normal, 1),
        "percent_of_normal": round(100 * total / normal, 1) if normal > 0 else None,
        "wet_days": int((df["rain_mm"] >= 2.5).sum()),
        "max_day_mm": round(float(df["rain_mm"].max()), 1),
        "source": ("MOCK block rain (demo): Madurai's IMD series x per-block factor; normal = "
                   "Madurai climatology 1991–2020") if is_block else
                  ("Segment 1 rainfall_daily (IMD 0.25° gridded, area-weighted); normal = "
                   "climatology_daily.rain_mean 1991–2020"),
        "demo": is_block,
        "series": rows,
    }


@router.get("/crop-calendar")
def get_crop_calendar(district: str | None = None, date: date | None = DateQ):
    """Segment 1 crop calendar, and (with ``district``) the crop stages on the issue date."""
    rows = fetch_all("SELECT crop, season, district, sowing_start_doy, sowing_end_doy, stage_name, "
                     "stage_start_day, stage_end_day, is_sample FROM crop_calendar "
                     "ORDER BY crop, season, district, stage_start_day")
    out = {"calendar": rows}
    if district:
        reg = district_or_404(district)
        ctx = context_or_error(date)
        name = reg["parent"]["name"] if reg.get("level") == "block" else reg["name"]
        out["stages"] = [s.as_dict() for s in current_stages(name, ctx.issue_date)]
        out["issue_date"] = ctx.issue_date
    return out
