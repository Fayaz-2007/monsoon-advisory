"""Grid → region aggregation (area-weighted zonal mean) for IMD rainfall and ERA5."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date

import numpy as np
import pandas as pd
import xarray as xr
from sqlalchemy import text

from pipeline.config import get_settings
from pipeline.db import get_engine, read_df, upsert_df
from pipeline.sources.boundaries import load_regions_gdf
from pipeline.sources.era5 import load_era5
from pipeline.sources.imd_rainfall import final_nc_path, load_rain
from pipeline.transform.weights import aggregate_grid, compute_weights, weight_matrix

log = logging.getLogger(__name__)

IMD_GRID = "imd025"
ERA5_GRID = "era5"
ERA5_VARS = ["u850", "v850", "tcwv", "olr"]


def reference_valid_mask(sample: xr.DataArray) -> np.ndarray:
    """Cells with real data: non-NaN at least once and not identically zero across all
    available final years (IMD reports some no-station boundary cells as 0.0)."""
    lats, lons = sample["lat"].values, sample["lon"].values
    ever = np.zeros((len(lats), len(lons)), dtype=bool)
    nonzero = np.zeros_like(ever)
    n_years = 0
    for p in sorted(final_nc_path(0).parent.glob("rain_final_*.nc")):
        with xr.open_dataset(p) as ds:
            da = ds["rain"].reindex(lat=lats, lon=lons, method="nearest", tolerance=1e-3)
            v = da.values
        ever |= ~np.isnan(v).all(axis=0)
        nonzero |= (np.nan_to_num(v) != 0).any(axis=0)
        n_years += 1
    if n_years == 0:  # only real-time data available
        v = sample.values
        return ~np.isnan(v).all(axis=0)
    return ever & nonzero


def _store_weights(grid: str, weights: pd.DataFrame) -> int:
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM region_grid_weights WHERE grid = :g"), {"g": grid})
    return upsert_df(weights.assign(grid=grid), "region_grid_weights",
                     pk_cols=["region_id", "grid", "lat", "lon"])


def get_weights(grid: str, regions: pd.DataFrame, lats: np.ndarray, lons: np.ndarray,
                res: float, valid_mask: Callable[[], np.ndarray | None], recompute: bool
                ) -> pd.DataFrame:
    """Load stored weights, or (re)compute them when asked or when regions are missing.

    ``valid_mask`` is called only when weights are actually (re)computed (it is slow).
    """
    stored = read_df("SELECT region_id, lat, lon, weight, method FROM region_grid_weights "
                     "WHERE grid = :g", {"g": grid})
    if not recompute and not stored.empty and set(regions["id"]) <= set(stored["region_id"]):
        return stored[stored["region_id"].isin(regions["id"])]
    log.info("Computing %s area weights for %d regions", grid, len(regions))
    weights = compute_weights(regions, lats, lons, res, get_settings().equal_area_crs,
                              valid_mask())
    _store_weights(grid, weights)
    n_nearest = int((weights.groupby("region_id")["method"].first() == "nearest").sum())
    log.info("Stored %d %s weight rows (%d regions via nearest-cell fallback)",
             len(weights), grid, n_nearest)
    return weights


def _long_frame(values: np.ndarray, dates: pd.DatetimeIndex, region_ids: list[int],
                name: str) -> pd.DataFrame:
    return pd.DataFrame({
        "region_id": np.tile(np.asarray(region_ids, dtype=np.int64), len(dates)),
        "date": np.repeat(dates.values, len(region_ids)),
        name: values.reshape(-1),
    })


def run_aggregate(start: date, end: date, recompute_weights: bool = True,
                  progress: Callable[[str], None] | None = None) -> tuple[int, list[str]]:
    """Aggregate rainfall (and ERA5 if cached) to regions for [start, end]."""
    settings = get_settings()
    regions = load_regions_gdf()
    if regions.empty:
        raise RuntimeError("No active regions. Run --stage boundaries first.")
    region_ids = regions["id"].astype(int).tolist()
    notes: list[str] = []

    rain, source = load_rain(start, end)
    lats, lons = rain["lat"].values, rain["lon"].values
    weights = get_weights(IMD_GRID, regions, lats, lons, settings.imd_grid_res,
                          lambda: reference_valid_mask(rain), recompute_weights)
    w = weight_matrix(weights, lats, lons, region_ids)

    total = 0
    times = pd.DatetimeIndex(rain["time"].values)
    for year in sorted(set(times.year)):
        if progress:
            progress(f"rainfall {year}")
        sel = times.year == year
        mean, n_cells = aggregate_grid(rain.values[sel], w)
        dates = times[sel]
        df = _long_frame(np.round(mean, 3), dates, region_ids, "rain_mm")
        df["n_cells"] = n_cells.reshape(-1)
        df["source"] = np.repeat(source.reindex(dates).fillna("imd_final").to_numpy(),
                                 len(region_ids))
        total += upsert_df(df, "rainfall_daily", pk_cols=["region_id", "date"])
    notes.append(f"rainfall_daily: {total} rows, {times.min().date()} to {times.max().date()}")
    log.info("Upserted %d rainfall_daily rows", total)

    era5_rows = aggregate_era5(regions, region_ids, start, end, recompute_weights)
    if era5_rows is not None:
        total += era5_rows
        notes.append(f"era5_daily: {era5_rows} rows")
    return total, notes


def aggregate_era5(regions: pd.DataFrame, region_ids: list[int], start: date, end: date,
                   recompute_weights: bool) -> int | None:
    settings = get_settings()
    ds = load_era5(max(start, settings.era5_start_date), end)
    if ds is None or ds.sizes.get("time", 0) == 0:
        log.info("No cached ERA5 data for this range - era5_daily not updated")
        return None
    lats, lons = ds["lat"].values, ds["lon"].values
    weights = get_weights(ERA5_GRID, regions, lats, lons, settings.era5_grid_res,
                          lambda: None, recompute_weights)
    w = weight_matrix(weights, lats, lons, region_ids)
    dates = pd.DatetimeIndex(ds["time"].values).normalize()
    frame: pd.DataFrame | None = None
    for var in ERA5_VARS:
        mean, _ = aggregate_grid(ds[var].transpose("time", "lat", "lon").values, w)
        part = _long_frame(np.round(mean, 3), dates, region_ids, var)
        frame = part if frame is None else frame.assign(**{var: part[var].to_numpy()})
    assert frame is not None
    n = upsert_df(frame, "era5_daily", pk_cols=["region_id", "date"])
    log.info("Upserted %d era5_daily rows", n)
    return n
