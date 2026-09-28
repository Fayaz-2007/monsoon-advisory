"""OPTIONAL ERA5 predictors via the Copernicus CDS API (``cdsapi``).

Variables (daily means of 00/06/12/18 UTC):
* u850, v850 — 850 hPa wind components (m/s)
* tcwv       — total column water vapour (kg/m²)
* olr        — outgoing long-wave radiation proxy, W/m² = -ttr / 3600
                (ttr = hourly-accumulated top net thermal radiation, J/m²)

If CDS_API_KEY is not set the stage is *skipped* (never failed). Monthly files are
cached in data/raw/era5/; only complete months (≥ 6 days old) are requested.
"""

from __future__ import annotations

import calendar
import logging
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import xarray as xr

from pipeline.config import get_settings
from pipeline.db import StageSkipped

log = logging.getLogger(__name__)

ERA5_LAG_DAYS = 6
HOURS = ["00:00", "06:00", "12:00", "18:00"]


def daily_nc_path(year: int, month: int) -> Path:
    return get_settings().era5_dir / f"era5_daily_{year}_{month:02d}.nc"


def _area() -> list[float]:
    s = get_settings()
    return [s.bbox_lat_max, s.bbox_lon_min, s.bbox_lat_min, s.bbox_lon_max]  # N, W, S, E


def _months(start: date, end: date) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _standardize(ds: xr.Dataset) -> xr.Dataset:
    ren = {k: v for k, v in {"valid_time": "time", "latitude": "lat", "longitude": "lon"}.items()
           if k in ds.dims or k in ds.coords}
    ds = ds.rename(ren)
    drop = [d for d in ("pressure_level", "level") if d in ds.dims]
    if drop:
        ds = ds.squeeze(drop, drop=True)
    return ds.sortby("lat")


def _download_month(client: object, year: int, month: int) -> Path:
    s = get_settings()
    ndays = calendar.monthrange(year, month)[1]
    base = {
        "product_type": ["reanalysis"],
        "year": [str(year)], "month": [f"{month:02d}"],
        "day": [f"{d:02d}" for d in range(1, ndays + 1)],
        "time": HOURS, "area": _area(),
        "data_format": "netcdf", "download_format": "unarchived",
    }
    tmp_pl = s.era5_dir / f"_pl_{year}_{month:02d}.nc"
    tmp_sl = s.era5_dir / f"_sl_{year}_{month:02d}.nc"
    client.retrieve("reanalysis-era5-pressure-levels",  # type: ignore[attr-defined]
                    {**base, "variable": ["u_component_of_wind", "v_component_of_wind"],
                     "pressure_level": ["850"]}, str(tmp_pl))
    client.retrieve("reanalysis-era5-single-levels",  # type: ignore[attr-defined]
                    {**base, "variable": ["total_column_water_vapour",
                                          "top_net_thermal_radiation"]}, str(tmp_sl))
    with xr.open_dataset(tmp_pl) as pl, xr.open_dataset(tmp_sl) as sl:
        pl, sl = _standardize(pl.load()), _standardize(sl.load())
        daily = xr.Dataset({
            "u850": pl["u"].resample(time="1D").mean(),
            "v850": pl["v"].resample(time="1D").mean(),
            "tcwv": sl["tcwv"].resample(time="1D").mean(),
            "olr": (-sl["ttr"] / 3600.0).resample(time="1D").mean(),
        })
    out = daily_nc_path(year, month)
    daily.astype("float32").to_netcdf(out)
    tmp_pl.unlink(missing_ok=True)
    tmp_sl.unlink(missing_ok=True)
    return out


def run_era5(start: date, end: date, force: bool = False,
             progress: Callable[[str], None] | None = None) -> tuple[int, list[str]]:
    """Download ERA5 months in [max(start, ERA5_START_DATE), end]. Returns (months, notes)."""
    s = get_settings()
    if not s.cds_api_key:
        raise StageSkipped("CDS_API_KEY not set — ERA5 features will be NULL")
    try:
        import cdsapi  # noqa: PLC0415 — optional dependency
    except ImportError as exc:
        raise StageSkipped(f"cdsapi not installed ({exc})") from exc

    s.era5_dir.mkdir(parents=True, exist_ok=True)
    start = max(start, s.era5_start_date)
    last_complete = (date.today() - timedelta(days=ERA5_LAG_DAYS)).replace(day=1) - timedelta(days=1)
    end = min(end, last_complete)
    if start > end:
        raise StageSkipped(f"No complete ERA5 months in range (start {start}, end {end})")

    client = cdsapi.Client(url=s.cds_api_url, key=s.cds_api_key, quiet=True, progress=False)
    done, failed = 0, []
    for year, month in _months(start, end):
        if daily_nc_path(year, month).exists() and not force:
            done += 1
            continue
        if progress:
            progress(f"ERA5 {year}-{month:02d}")
        try:
            _download_month(client, year, month)
            done += 1
        except Exception as exc:  # noqa: BLE001 — optional source must never fail the run
            log.warning("ERA5 %d-%02d failed: %s", year, month, exc)
            failed.append(f"{year}-{month:02d}")
    notes = [f"{done} months available"] + ([f"failed: {', '.join(failed[:12])}"] if failed else [])
    return done, notes


def load_era5(start: date, end: date) -> xr.Dataset | None:
    """Daily ERA5 fields for [start, end], or None if nothing is cached."""
    files = [daily_nc_path(y, m) for y, m in _months(start, end)]
    files = [f for f in files if f.exists()]
    if not files:
        return None
    ds = xr.concat([xr.open_dataset(f).load() for f in files], dim="time").sortby("time")
    ds = ds.sel(time=slice(str(start), str(end)))
    _, idx = np.unique(ds["time"].values, return_index=True)
    return ds.isel(time=np.sort(idx))
