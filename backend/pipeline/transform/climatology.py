"""Daily rainfall climatology per region (default base period 1991–2020).

For each day-of-year *d* (366-day calendar, see ``utils.doy366``) all days within
±``clim_window_days`` of *d* across all base years are pooled. From that pool:

* rain_mean, rain_p50, rain_p90 — statistics of daily rainfall (mm/day)
* clim_sum_7d, clim_sum_30d — mean of trailing 7-/30-day rainfall sums (mm),
  used as the "normal" for the rolling-sum anomalies in features_daily.
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


def window_mask(doys: np.ndarray, half_window: int) -> np.ndarray:
    """Boolean [366, n_days]: True where a day's doy is within ±half_window of each target doy
    (circular on a 366-day year)."""
    targets = np.arange(1, 367)[:, None]
    diff = np.abs(targets - doys[None, :])
    circ = np.minimum(diff, 366 - diff)
    return circ <= half_window


def _pooled_mean(mask: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Mean over pooled days, ignoring NaN. values: [n_days, n_regions] → [366, n_regions]."""
    valid = ~np.isnan(values)
    m = mask.astype(np.float64)
    num = m @ np.where(valid, values, 0.0)
    den = m @ valid.astype(np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def compute_climatology(wide: pd.DataFrame, half_window: int,
                        base_start: pd.Timestamp | None = None) -> pd.DataFrame:
    """Compute climatology from a wide frame (index = daily dates, columns = region ids).

    Rows before ``base_start`` (if given) are used only to complete the rolling sums
    at the beginning of the base period.
    """
    wide = wide.sort_index().asfreq("D")
    sum7 = wide.rolling(7, min_periods=7).sum()
    sum30 = wide.rolling(30, min_periods=30).sum()
    if base_start is not None:
        keep = wide.index >= base_start
        wide, sum7, sum30 = wide[keep], sum7[keep], sum30[keep]

    doys = doy366(wide.index)
    mask = window_mask(doys, half_window)
    vals = wide.to_numpy(dtype=np.float64)

    mean = _pooled_mean(mask, vals)
    c7 = _pooled_mean(mask, sum7.to_numpy(dtype=np.float64))
    c30 = _pooled_mean(mask, sum30.to_numpy(dtype=np.float64))
    p50 = np.full_like(mean, np.nan)
    p90 = np.full_like(mean, np.nan)
    for d in range(366):
        pool = vals[mask[d]]
        if pool.size and not np.isnan(pool).all():
            with np.errstate(all="ignore"):
                p50[d], p90[d] = np.nanpercentile(pool, [50, 90], axis=0)
    years = pd.DataFrame(~np.isnan(vals), index=wide.index).groupby(wide.index.year).any().sum()

    regions = list(wide.columns)
    n_reg = len(regions)
    return pd.DataFrame({
        "region_id": np.tile(np.asarray(regions, dtype=np.int64), 366),
        "doy": np.repeat(np.arange(1, 367), n_reg),
        "rain_mean": mean.reshape(-1),
        "rain_p50": p50.reshape(-1),
        "rain_p90": p90.reshape(-1),
        "clim_sum_7d": c7.reshape(-1),
        "clim_sum_30d": c30.reshape(-1),
        "n_years": np.tile(years.to_numpy(), 366),
    })


def run_climatology(progress: Callable[[str], None] | None = None,
                    batch_size: int = 100) -> tuple[int, list[str]]:
    s = get_settings()
    base_start = date(s.clim_start_year, 1, 1)
    base_end = date(s.clim_end_year, 12, 31)
    ids = read_df("SELECT id FROM regions WHERE active AND state = :s ORDER BY id",
                  {"s": s.state_name})["id"].tolist()
    if not ids:
        raise RuntimeError("No active regions. Run --stage boundaries first.")
    span = read_df("SELECT min(date) AS lo, max(date) AS hi FROM rainfall_daily "
                   "WHERE date BETWEEN :a AND :b", {"a": base_start, "b": base_end})
    lo, hi = as_date(span["lo"].iloc[0]), as_date(span["hi"].iloc[0])
    if lo is None or hi is None:
        raise RuntimeError(f"No rainfall_daily rows in base period {base_start}–{base_end}. "
                           "Run --stage rainfall and --stage aggregate first.")
    notes = [f"base period {s.clim_start_year}-{s.clim_end_year}, data {lo} to {hi}"]
    if (hi - lo).days < 365 * 25:
        msg = f"Climatology built from only {(hi - lo).days / 365.25:.1f} years ({lo}–{hi})"
        log.warning(msg)
        notes.append(msg)

    total = 0
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        if progress:
            progress(f"regions {i + 1}-{i + len(batch)} of {len(ids)}")
        df = read_df("SELECT region_id, date, rain_mm FROM rainfall_daily "
                     "WHERE region_id = ANY(:ids) AND date BETWEEN :a AND :b",
                     {"ids": batch, "a": base_start - timedelta(days=30), "b": base_end})
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"])
        wide = df.pivot(index="date", columns="region_id", values="rain_mm").astype(float)
        clim = compute_climatology(wide, s.clim_window_days, pd.Timestamp(base_start))
        total += upsert_df(clim.round(4), "climatology_daily", pk_cols=["region_id", "doy"])
    log.info("Upserted %d climatology_daily rows", total)
    return total, notes
