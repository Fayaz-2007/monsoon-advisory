"""Inputs (via Segment 1's ``load_features`` and existing tables) and the cached dataset."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from ml.config import CFG, WORK_DIR
from ml.features import STATE_COLS, build_issue_frame, monthly_indices
from ml.targets import build_targets
from pipeline import load_features
from pipeline.db import read_df

DAILY_COLS = ["region_id", "date", "rain_mm", *STATE_COLS, "mjo_source"]
ISSUE_FILE = WORK_DIR / "issue_dataset.parquet"
RAIN_FILE = WORK_DIR / "rain_final.parquet"


def load_region_meta() -> pd.DataFrame:
    """Active regions with centroid lat/lon (from the existing ``regions`` table)."""
    return read_df(
        "SELECT id AS region_id, code, name, ST_Y(ST_Centroid(geom)) AS lat, "
        "ST_X(ST_Centroid(geom)) AS lon FROM regions WHERE active ORDER BY id")


def load_monthly_indices() -> pd.DataFrame:
    return monthly_indices(read_df("SELECT date, oni, dmi FROM climate_indices_daily"))


def final_data_end() -> date:
    """Last day of IMD *final* rainfall; later days are provisional (real-time)."""
    return pd.Timestamp(read_df(
        "SELECT max(date) AS d FROM rainfall_daily WHERE source = 'imd_final'")["d"].iloc[0]).date()


def issue_dates_for_years(years: range | list[int]) -> pd.DatetimeIndex:
    parts = [pd.date_range(f"{y}-{CFG.issue_start_month:02d}-01", f"{y}-12-31", freq="D")
             for y in years]
    return pd.DatetimeIndex(pd.Index([]).append(parts)) if parts else pd.DatetimeIndex([])


def rain_wide(daily: pd.DataFrame, region_ids: list[int], end: date | None = None) -> pd.DataFrame:
    w = daily.pivot(index="date", columns="region_id", values="rain_mm").astype(float)
    w = w.reindex(columns=region_ids).asfreq("D")
    return w.loc[: pd.Timestamp(end)] if end is not None else w


@dataclass
class Dataset:
    issue: pd.DataFrame      # features + per-lead targets, one row per (region, issue date)
    rain: pd.DataFrame       # wide daily FINAL rainfall (for fold climatology)
    final_end: date


def build_dataset(progress=lambda msg: None) -> Dataset:
    progress("loading features_daily")
    daily = load_features()[DAILY_COLS]
    meta = load_region_meta()
    daily = daily[daily["region_id"].isin(meta["region_id"])]
    monthly = load_monthly_indices()
    final_end = final_data_end()
    region_ids = meta["region_id"].astype(int).tolist()

    years = range(CFG.first_year, final_end.year + 1)
    issue_dates = issue_dates_for_years(years)
    issue_dates = issue_dates[issue_dates <= pd.Timestamp(final_end)]
    progress(f"features for {len(issue_dates):,} issue dates × {len(region_ids)} regions")
    issue = build_issue_frame(daily, monthly, meta, issue_dates)

    progress("targets (final data only)")
    rain = rain_wide(daily, region_ids, final_end)
    issue = build_targets(rain, issue)
    issue["year"] = pd.DatetimeIndex(issue["issue_date"]).year
    return Dataset(issue=issue, rain=rain, final_end=final_end)


def save_dataset(ds: Dataset) -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    ds.issue.to_parquet(ISSUE_FILE, index=False)
    r = ds.rain.copy()
    r.columns = [str(c) for c in r.columns]
    r.to_parquet(RAIN_FILE)


def load_dataset() -> Dataset:
    if not ISSUE_FILE.exists() or not RAIN_FILE.exists():
        raise RuntimeError("No cached dataset. Run: python -m ml.run --stage build-targets")
    issue = pd.read_parquet(ISSUE_FILE)
    rain = pd.read_parquet(RAIN_FILE)
    rain.columns = [int(c) for c in rain.columns]
    rain.index = pd.DatetimeIndex(rain.index)
    rain = rain.asfreq("D")
    return Dataset(issue=issue, rain=rain, final_end=rain.index.max().date())
