"""Read-only access to Segment 1 tables (regions, rainfall, climatology, crop calendar, runs).

Districts, boundaries and observed rainfall ALWAYS come from here, whatever FORECAST_SOURCE says.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.db import fetch_all, fetch_one, read_df
from pipeline.config import BACKEND_DIR
from pipeline.utils import doy366

QUALITY_REPORT = BACKEND_DIR / "data" / "processed" / "quality_report.md"

SEGMENT1_TABLES = ["regions", "region_grid_weights", "rainfall_daily", "climate_indices_daily",
                   "era5_daily", "climatology_daily", "features_daily", "crop_calendar",
                   "pipeline_runs"]

# Districts on the Bay of Bengal coast (by name): the NE monsoon hits these hardest.
COASTAL_DISTRICTS = {
    "Chennai", "Thiruvallur", "Chengalputtu", "Kancheepuram", "Viluppuram", "Cuddalore",
    "Mayiladuthurai", "Nagapattinam", "Thiruvarur", "Thanjavur", "Pudukkottai",
    "Ramanathapuram", "Thoothukkudi", "Tirunelveli", "Kanniyakumari",
}


def doy_of(d: date) -> int:
    """Segment 1's 366-day calendar day of year (Feb 29 = 60, Mar 1 = 61 every year)."""
    return int(doy366(pd.DatetimeIndex([pd.Timestamp(d)]))[0])


@lru_cache(maxsize=1)
def _regions_cached() -> pd.DataFrame:
    df = read_df(
        "SELECT id, code, name, district, area_km2, "
        "ST_X(ST_Centroid(geom)) AS lon, ST_Y(ST_Centroid(geom)) AS lat "
        "FROM regions WHERE active ORDER BY id")
    df["slug"] = df["code"].str.split("/").str[-1]
    df["coastal"] = df["name"].isin(COASTAL_DISTRICTS)
    return df


def regions() -> pd.DataFrame:
    """Active regions: id, code, slug, name, district, area_km2, lon, lat, coastal."""
    return _regions_cached().copy()


def clear_caches() -> None:
    _regions_cached.cache_clear()
    _crop_calendar_cached.cache_clear()
    _climatology_cached.cache_clear()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def resolve_district(key: str | int) -> dict[str, Any] | None:
    """Find a district by id, slug (``chennai``), code (``tn/chennai``) or name (any case)."""
    df = _regions_cached()
    k = str(key).strip()
    if k.isdigit():
        hit = df[df["id"] == int(k)]
    else:
        n = _norm(k)
        hit = df[(df["slug"].map(_norm) == n) | (df["name"].map(_norm) == n)
                 | (df["code"].map(_norm) == n)]
    return None if hit.empty else hit.iloc[0].to_dict()


def districts_geojson(tolerance: float = 0.005) -> dict[str, Any]:
    rows = fetch_all(
        "SELECT id, code, name, district, area_km2, "
        "ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, :tol), 5) AS geometry, "
        "ST_X(ST_Centroid(geom)) AS lon, ST_Y(ST_Centroid(geom)) AS lat "
        "FROM regions WHERE active ORDER BY id", {"tol": tolerance})
    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "id": r["id"],
            "geometry": json.loads(r["geometry"]),
            "properties": {
                "id": r["id"], "code": r["code"], "slug": r["code"].split("/")[-1],
                "name": r["name"], "area_km2": round(r["area_km2"], 1),
                "centroid": [round(r["lon"], 4), round(r["lat"], 4)],
                "coastal": r["name"] in COASTAL_DISTRICTS,
            },
        })
    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# Rainfall
# ---------------------------------------------------------------------------


def last_rainfall_date() -> date | None:
    row = fetch_one("SELECT max(date) AS d FROM rainfall_daily")
    return row["d"] if row else None


def observed_daily(issue_date: date, days: int = 30,
                   region_ids: list[int] | None = None) -> pd.DataFrame:
    """Observed daily rain for the ``days`` days before ``issue_date`` (issue date excluded,
    matching Segment 2's information cut-off). Columns: region_id, date, rain_mm."""
    start = issue_date - timedelta(days=days)
    end = issue_date - timedelta(days=1)
    where = "date BETWEEN :s AND :e"
    params: dict[str, Any] = {"s": start, "e": end}
    if region_ids is not None:
        where += " AND region_id = ANY(:ids)"
        params["ids"] = [int(i) for i in region_ids]
    df = read_df(f"SELECT region_id, date, rain_mm FROM rainfall_daily WHERE {where} "
                 "ORDER BY region_id, date", params)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["rain_mm"] = pd.to_numeric(df["rain_mm"]).astype("float64")
    return df


def latest_features(on_or_before: date) -> pd.DataFrame:
    """features_daily row per region for the last day ≤ ``on_or_before``."""
    return read_df(
        "SELECT DISTINCT ON (region_id) region_id, date, rain_sum_7d, rain_sum_30d, "
        "anomaly_7d_pct, anomaly_30d_pct, consecutive_dry_days, wet_days_last_7 "
        "FROM features_daily WHERE date <= :d AND date > :d - 10 "
        "ORDER BY region_id, date DESC", {"d": on_or_before})


def rainfall_series(region_id: int, days: int = 30, end: date | None = None) -> pd.DataFrame:
    """Observed daily rain with the day's climatological mean and trailing-sum features."""
    if end is None:
        end = last_rainfall_date() or date.today()
    start = end - timedelta(days=days - 1)
    df = read_df(
        "SELECT r.date, r.rain_mm, r.source, f.rain_sum_7d, f.anomaly_7d_pct, "
        "f.consecutive_dry_days "
        "FROM rainfall_daily r LEFT JOIN features_daily f "
        "  ON f.region_id = r.region_id AND f.date = r.date "
        "WHERE r.region_id = :rid AND r.date BETWEEN :s AND :e ORDER BY r.date",
        {"rid": region_id, "s": start, "e": end})
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    clim = _climatology_cached()
    doys = doy366(pd.DatetimeIndex(df["date"]))
    sub = clim[clim["region_id"] == region_id].set_index("doy")
    df["normal_mm"] = sub.reindex(doys)["rain_mean"].to_numpy()
    df["date"] = df["date"].dt.date
    return df


@lru_cache(maxsize=1)
def _climatology_cached() -> pd.DataFrame:
    return read_df("SELECT region_id, doy, rain_mean, rain_p90, clim_sum_7d FROM climatology_daily")


def weekly_normal_mm(region_ids: np.ndarray, week_ends: list[date]) -> np.ndarray:
    """Climatological 7-day total (mm) ending on each week_end, shape [n_regions, n_weeks]."""
    clim = _climatology_cached().pivot(index="region_id", columns="doy", values="clim_sum_7d")
    doys = [doy_of(d) for d in week_ends]
    out = clim.reindex(index=region_ids, columns=doys).to_numpy(dtype="float64")
    return np.nan_to_num(out, nan=10.0)


# ---------------------------------------------------------------------------
# Crop calendar
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _crop_calendar_cached() -> pd.DataFrame:
    return read_df(
        "SELECT crop, season, district, sowing_start_doy, sowing_end_doy, stage_name, "
        "stage_start_day, stage_end_day, is_sample, source FROM crop_calendar "
        "ORDER BY crop, season, district, stage_start_day")


def crop_calendar() -> pd.DataFrame:
    return _crop_calendar_cached().copy()


# ---------------------------------------------------------------------------
# Pipeline health
# ---------------------------------------------------------------------------


def table_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for t in SEGMENT1_TABLES + ["forecasts", "model_skill"]:
        try:
            row = fetch_one(f'SELECT count(*) AS n FROM public."{t}"')
            out[t] = int(row["n"]) if row else 0
        except Exception:  # noqa: BLE001 — a missing table is reported as -1, not an error
            out[t] = -1
    return out


def recent_runs(limit: int = 10) -> list[dict[str, Any]]:
    return fetch_all(
        "SELECT id, stage, status, started_at, finished_at, rows_written, message, "
        "EXTRACT(EPOCH FROM (finished_at - started_at)) AS duration_s "
        "FROM pipeline_runs ORDER BY id DESC LIMIT :n", {"n": limit})


def quality_summary() -> dict[str, Any]:
    """Parse Segment 1's quality report (checks table) plus the latest quality run."""
    run = fetch_one("SELECT id, stage, status, finished_at, message FROM pipeline_runs "
                    "WHERE stage LIKE '%quality' ORDER BY id DESC LIMIT 1")
    checks: list[dict[str, str]] = []
    generated = None
    path = Path(QUALITY_REPORT)
    if path.exists():
        text = path.read_text(encoding="utf-8")
        m = re.search(r"Generated ([0-9-]+ [0-9:]+)", text)
        generated = m.group(1) if m else None
        in_table = False
        for line in text.splitlines():
            if line.startswith("| Check |"):
                in_table = True
                continue
            if in_table:
                if not line.startswith("|"):
                    break
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) == 3 and cells[1] in {"PASS", "WARN", "FAIL"}:
                    checks.append({"check": cells[0], "status": cells[1], "detail": cells[2]})
    counts = {s: sum(c["status"] == s for c in checks) for s in ("PASS", "WARN", "FAIL")}
    return {
        "report_generated": generated,
        "report_path": "backend/data/processed/quality_report.md",
        "summary": {"pass": counts["PASS"], "warn": counts["WARN"], "fail": counts["FAIL"]},
        "checks": checks,
        "latest_quality_run": run,
    }
