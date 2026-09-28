"""Feature engineering → ``features_daily`` (the table Segment 2 consumes).

Pure feature functions live at the top of this module and are unit-tested; the
DB orchestration (:func:`run_features`) is at the bottom. No targets/labels are
created here — Segment 2 owns those.

Null rules: a rolling feature is NULL unless every day in its window has rainfall.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta

import numpy as np
import pandas as pd

from pipeline.config import get_settings
from pipeline.db import read_df, upsert_df
from pipeline.utils import as_date, doy366

log = logging.getLogger(__name__)

INDEX_COLS = ["oni", "dmi", "rmm1", "rmm2", "mjo_phase", "mjo_amplitude", "mjo_source"]
ERA5_COLS = ["u850", "v850", "tcwv", "olr"]
FEATURE_COLS = [
    "rain_mm", "rain_sum_3d", "rain_sum_7d", "rain_sum_14d", "rain_sum_30d",
    "anomaly_7d_mm", "anomaly_7d_pct", "anomaly_30d_mm", "anomaly_30d_pct",
    "consecutive_dry_days", "wet_days_last_7", "wet_days_last_14", "max_1day_rain_last_7",
    "doy_sin", "doy_cos", "oni", "oni_lag30", "dmi", "dmi_lag30",
    "rmm1", "rmm2", "mjo_phase", "mjo_amplitude", "mjo_source", *ERA5_COLS, "is_monsoon_season",
]


# ---------------------------------------------------------------------------
# Pure feature functions
# ---------------------------------------------------------------------------


def rolling_sum(rain: pd.Series, window: int) -> pd.Series:
    """Trailing sum over ``window`` days including today; NULL if any day is missing."""
    return rain.rolling(window, min_periods=window).sum()


def rolling_max(rain: pd.Series, window: int) -> pd.Series:
    return rain.rolling(window, min_periods=window).max()


def wet_day_count(rain: pd.Series, window: int, threshold: float) -> pd.Series:
    """Number of days with rain ≥ threshold in the trailing window (NULL if any day missing)."""
    wet = (rain >= threshold).astype(float).where(rain.notna())
    return wet.rolling(window, min_periods=window).sum()


def consecutive_dry_days(rain: pd.Series, threshold: float, initial: int = 0) -> pd.Series:
    """Length of the dry run (rain < threshold) ending on each day; 0 on a wet day.

    ``initial`` is the count on the day *before* the series starts, so incremental
    runs continue long dry spells correctly. A missing day yields NULL and
    restarts the count from 0 afterwards.
    """
    known = rain.notna()
    dry = (rain < threshold) & known
    breaks = (~dry).cumsum()
    count = dry.astype(int).groupby(breaks).cumsum()
    leading = breaks == 0  # dry run that starts at the first row continues the seed
    count = count.where(~leading, count + int(initial))
    return count.where(known).astype("float")


def doy_cyclic(dates: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """sin/cos encoding of the (366-day calendar) day of year."""
    angle = 2 * np.pi * (doy366(dates) - 1) / 366.0
    return np.sin(angle), np.cos(angle)


def season_flag(dates: pd.DatetimeIndex, start_month: int, end_month: int) -> np.ndarray:
    """True inside [start_month, end_month]; handles windows that wrap the year end."""
    m = dates.month
    if start_month <= end_month:
        return np.asarray((m >= start_month) & (m <= end_month))
    return np.asarray((m >= start_month) | (m <= end_month))


def percent_of_normal(actual: pd.Series, normal: np.ndarray, min_normal: float) -> np.ndarray:
    normal = np.asarray(normal, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        pct = 100.0 * actual.to_numpy(dtype=float) / normal
    pct[~(normal >= min_normal)] = np.nan
    return pct


def compute_region_features(
    rain: pd.Series,
    clim: pd.DataFrame | None,
    indices: pd.DataFrame,
    era5: pd.DataFrame | None = None,
    *,
    dry_threshold: float = 2.5,
    season: tuple[int, int] = (6, 12),
    min_clim_mm: float = 1.0,
    cdd_seed: int = 0,
) -> pd.DataFrame:
    """Build all features for one region.

    Args:
        rain: daily rainfall (mm) indexed by a *continuous* DatetimeIndex.
        clim: climatology indexed by doy (1..366) with clim_sum_7d / clim_sum_30d.
        indices: daily climate indices indexed by date (may extend beyond ``rain``).
        era5: optional daily ERA5 fields indexed by date.
    """
    dates = pd.DatetimeIndex(rain.index)
    out = pd.DataFrame(index=dates)
    out["rain_mm"] = rain.to_numpy(dtype=float)
    for w in (3, 7, 14, 30):
        out[f"rain_sum_{w}d"] = rolling_sum(rain, w).to_numpy()

    doy = doy366(dates)
    for w in (7, 30):
        if clim is not None and not clim.empty:
            normal = clim[f"clim_sum_{w}d"].reindex(doy).to_numpy(dtype=float)
        else:
            normal = np.full(len(dates), np.nan)
        out[f"anomaly_{w}d_mm"] = out[f"rain_sum_{w}d"].to_numpy() - normal
        out[f"anomaly_{w}d_pct"] = percent_of_normal(out[f"rain_sum_{w}d"], normal, min_clim_mm)

    out["consecutive_dry_days"] = consecutive_dry_days(rain, dry_threshold, cdd_seed).to_numpy()
    out["wet_days_last_7"] = wet_day_count(rain, 7, dry_threshold).to_numpy()
    out["wet_days_last_14"] = wet_day_count(rain, 14, dry_threshold).to_numpy()
    out["max_1day_rain_last_7"] = rolling_max(rain, 7).to_numpy()
    out["doy_sin"], out["doy_cos"] = doy_cyclic(dates)

    idx = indices.reindex(dates)
    for col in INDEX_COLS:
        out[col] = idx[col].to_numpy() if col in idx else np.nan
    lag = indices.reindex(dates - pd.Timedelta(days=30))
    out["oni_lag30"] = lag["oni"].to_numpy() if "oni" in lag else np.nan
    out["dmi_lag30"] = lag["dmi"].to_numpy() if "dmi" in lag else np.nan

    e = era5.reindex(dates) if era5 is not None else pd.DataFrame(index=dates)
    for col in ERA5_COLS:
        out[col] = e[col].to_numpy() if col in e else np.nan

    out["is_monsoon_season"] = season_flag(dates, *season)
    out.index.name = "date"
    return out[FEATURE_COLS]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _load_indices(start: date, end: date) -> pd.DataFrame:
    df = read_df("SELECT * FROM climate_indices_daily WHERE date BETWEEN :a AND :b",
                 {"a": start, "b": end})
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def run_features(start: date, end: date, progress: Callable[[str], None] | None = None,
                 batch_size: int = 25) -> tuple[int, list[str]]:
    """Compute and upsert features_daily for all active regions over [start, end]."""
    s = get_settings()
    ids = read_df("SELECT id FROM regions WHERE active AND state = :s ORDER BY id",
                  {"s": s.state_name})["id"].tolist()
    if not ids:
        raise RuntimeError("No active regions. Run --stage boundaries first.")
    last_rain = as_date(read_df("SELECT max(date) AS d FROM rainfall_daily")["d"].iloc[0])
    if last_rain is None:
        raise RuntimeError("rainfall_daily is empty. Run --stage aggregate first.")
    end = min(end, last_rain)
    if start > end:
        return 0, [f"nothing to do: start {start} after last rainfall date {end}"]
    load_start = start - timedelta(days=s.feature_lookback_days)
    notes: list[str] = []

    indices = _load_indices(load_start - timedelta(days=31), end)
    if indices.empty:
        log.warning("climate_indices_daily is empty - index features will be NULL")
        notes.append("no climate indices")
    clim_all = read_df("SELECT region_id, doy, clim_sum_7d, clim_sum_30d FROM climatology_daily")
    if clim_all.empty:
        log.warning("climatology_daily is empty - anomaly features will be NULL")
        notes.append("no climatology")
    clim_by_region = {rid: g.set_index("doy") for rid, g in clim_all.groupby("region_id")}
    days = pd.date_range(load_start, end, freq="D")

    total = 0
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        if progress:
            progress(f"regions {i + 1}-{i + len(batch)} of {len(ids)}")
        rain_df = read_df("SELECT region_id, date, rain_mm FROM rainfall_daily "
                          "WHERE region_id = ANY(:ids) AND date BETWEEN :a AND :b",
                          {"ids": batch, "a": load_start, "b": end})
        rain_df["date"] = pd.to_datetime(rain_df["date"])
        era5_df = read_df("SELECT * FROM era5_daily WHERE region_id = ANY(:ids) "
                          "AND date BETWEEN :a AND :b", {"ids": batch, "a": load_start, "b": end})
        era5_df["date"] = pd.to_datetime(era5_df["date"])
        seeds = read_df("SELECT region_id, consecutive_dry_days FROM features_daily "
                        "WHERE region_id = ANY(:ids) AND date = :d",
                        {"ids": batch, "d": load_start - timedelta(days=1)})
        seed_map = dict(zip(seeds["region_id"], seeds["consecutive_dry_days"].fillna(0),
                            strict=True))

        frames: list[pd.DataFrame] = []
        for rid in batch:
            r = rain_df[rain_df["region_id"] == rid].set_index("date")["rain_mm"]
            if r.empty:
                continue
            r = r.astype(float).reindex(days)
            e = era5_df[era5_df["region_id"] == rid].set_index("date")
            feats = compute_region_features(
                r, clim_by_region.get(rid), indices, e if not e.empty else None,
                dry_threshold=s.dry_day_threshold_mm,
                season=(s.monsoon_season_start_month, s.monsoon_season_end_month),
                min_clim_mm=s.anomaly_pct_min_clim_mm,
                cdd_seed=int(seed_map.get(rid, 0)),
            )
            feats = feats[feats.index >= pd.Timestamp(start)]
            frames.append(feats.reset_index().assign(region_id=rid))
        if not frames:
            continue
        batch_df = pd.concat(frames, ignore_index=True)
        float_cols = [c for c in FEATURE_COLS
                      if c not in ("mjo_source", "is_monsoon_season", "mjo_phase")]
        batch_df[float_cols] = batch_df[float_cols].astype(float).round(4)
        total += upsert_df(batch_df, "features_daily", pk_cols=["region_id", "date"],
                           touch_updated_at=True)
    log.info("Upserted %d features_daily rows (%s to %s)", total, start, end)
    notes.append(f"{total} rows {start} to {end}")
    return total, notes
