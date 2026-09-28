"""IMD 0.25° gridded daily rainfall via ``imdlib``.

* Final (quality-controlled) data: one binary ``.grd`` per year, published with
  roughly a year's lag. Cached in data/raw/imd/grd/rain/<year>.grd.
* Real-time (provisional) data: one ``.grd`` per day, used for dates the final
  product does not cover yet. Cached in data/raw/imd/realtime/.
* Both are cropped to the configured bounding box and saved as small NetCDFs
  (data/raw/imd/cropped/), which are what the aggregation stage reads.
"""

from __future__ import annotations

import contextlib
import io
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import imdlib
import numpy as np
import pandas as pd
import requests
import xarray as xr

from pipeline.config import get_settings

log = logging.getLogger(__name__)

IMD_NLAT, IMD_NLON = 129, 135
BYTES_PER_DAY = IMD_NLAT * IMD_NLON * 4
DOWNLOAD_RETRIES = 3


def _grd_dir() -> Path:
    return get_settings().imd_dir / "grd"


def _realtime_dir() -> Path:
    return get_settings().imd_dir / "realtime"


def _cropped_dir() -> Path:
    return get_settings().imd_dir / "cropped"


def final_nc_path(year: int) -> Path:
    return _cropped_dir() / f"rain_final_{year}.nc"


def realtime_nc_path(day: date) -> Path:
    return _cropped_dir() / "realtime" / f"rain_rt_{day:%Y-%m-%d}.nc"


def _days_in_year(year: int) -> int:
    return 366 if pd.Timestamp(year, 12, 31).dayofyear == 366 else 365


def _quiet(fn: Callable[..., object], *args: object, **kwargs: object) -> object:
    """Call an imdlib function, routing its print() output to the debug log."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            return fn(*args, **kwargs)
    finally:
        for line in buf.getvalue().splitlines():
            if line.strip():
                log.debug("imdlib: %s", line.strip())


def crop_to_bbox(ds: xr.Dataset | xr.DataArray) -> xr.DataArray:
    s = get_settings()
    da = ds["rain"] if isinstance(ds, xr.Dataset) else ds
    da = da.sel(lat=slice(s.bbox_lat_min, s.bbox_lat_max), lon=slice(s.bbox_lon_min, s.bbox_lon_max))
    da = da.where(da >= -1.0)  # IMD sentinels (-999 etc.) → NaN
    return da.astype("float32")


def _save(da: xr.DataArray, path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ds = da.to_dataset(name="rain")
    ds.attrs.update({"source": source, "units": "mm/day", "crs": "EPSG:4326"})
    tmp = path.with_suffix(".nc.part")
    ds.to_netcdf(tmp, encoding={"rain": {"zlib": True, "complevel": 4, "dtype": "float32"}})
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Final yearly data
# ---------------------------------------------------------------------------


def download_final_year(year: int, force: bool = False) -> Path | None:
    """Download one year's final gridded file. Returns path or None if unavailable."""
    settings = get_settings()
    rain_dir = _grd_dir() / "rain"
    rain_dir.mkdir(parents=True, exist_ok=True)
    path = rain_dir / f"{year}.grd"
    expected = _days_in_year(year) * BYTES_PER_DAY
    if path.exists() and (force or path.stat().st_size != expected):
        path.unlink()
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        if path.exists() and path.stat().st_size == expected:
            break
        path.unlink(missing_ok=True)  # imdlib skips any existing file >= 1 KB
        log.info("Downloading IMD final rainfall for %d (attempt %d/%d)", year, attempt,
                 DOWNLOAD_RETRIES)
        try:
            _quiet(imdlib.get_data, "rain", year, year, fn_format="yearwise",
                   file_dir=str(_grd_dir()), proxies=settings.proxies)
        except Exception as exc:  # noqa: BLE001 - imdlib raises bare Exceptions
            log.debug("imdlib.get_data(%d) raised: %s", year, exc)
        if not (path.exists() and path.stat().st_size == expected) and attempt < DOWNLOAD_RETRIES:
            time.sleep(10 * attempt)  # IMD server intermittently returns empty bodies
    if not path.exists() or path.stat().st_size != expected:
        size = path.stat().st_size if path.exists() else 0
        log.warning("IMD final rainfall for %d not available (got %d bytes, expected %d)",
                    year, size, expected)
        path.unlink(missing_ok=True)
        return None
    return path


def crop_final_year(year: int) -> Path:
    data = _quiet(imdlib.open_data, "rain", year, year, fn_format="yearwise",
                  file_dir=str(_grd_dir()))
    da = crop_to_bbox(data.get_xarray())  # type: ignore[union-attr]
    out = final_nc_path(year)
    _save(da, out, "IMD 0.25deg gridded rainfall (final)")
    if not get_settings().imd_keep_grd:
        (_grd_dir() / "rain" / f"{year}.grd").unlink(missing_ok=True)
    return out


def ensure_final_year(year: int, force: bool = False) -> bool:
    """Make sure the cropped NetCDF for ``year`` exists. Returns False if IMD lacks it."""
    out = final_nc_path(year)
    if out.exists() and not force:
        return True
    if download_final_year(year, force=force) is None:
        return False
    crop_final_year(year)
    log.info("Cropped IMD %d -> %s", year, out.name)
    return True


# ---------------------------------------------------------------------------
# Real-time daily data
# ---------------------------------------------------------------------------


def _realtime_grd(day: date) -> Path:
    return _realtime_dir() / f"rain_ind0.25_{day:%y_%m_%d}.grd"


def _download_realtime_grd(day: date, force: bool = False) -> bool:
    """Download one real-time .grd (thread-safe; plain requests, same endpoint as imdlib).

    The IMD server is slow (10-30 s per request) and intermittently returns empty
    bodies, so each day is retried with backoff.
    """
    settings = get_settings()
    grd = _realtime_grd(day)
    if grd.exists() and grd.stat().st_size == BYTES_PER_DAY and not force:
        return True
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            resp = requests.post(settings.imd_realtime_url, data={"rain": f"{day:%d%m%Y}"},
                                 timeout=settings.http_timeout_s, proxies=settings.proxies,
                                 headers={"User-Agent": settings.user_agent})
            resp.raise_for_status()
            if len(resp.content) == BYTES_PER_DAY:
                tmp = grd.with_suffix(".grd.part")
                tmp.write_bytes(resp.content)
                tmp.replace(grd)
                return True
            log.debug("IMD real-time %s attempt %d: %d bytes", day, attempt, len(resp.content))
        except requests.RequestException as exc:
            log.debug("IMD real-time %s attempt %d failed: %s", day, attempt, exc)
        if attempt < DOWNLOAD_RETRIES:
            time.sleep(5 * attempt)
    return False


def _crop_realtime_day(day: date) -> None:
    iso = day.isoformat()
    data = imdlib.open_real_data("rain", iso, iso, file_dir=str(_realtime_dir()))
    _save(crop_to_bbox(data.get_xarray()), realtime_nc_path(day),
          "IMD 0.25deg real-time rainfall (provisional)")


def fetch_realtime_days(days: list[date], force: bool = False,
                        progress: Callable[[str], None] | None = None) -> tuple[list[date], list[date]]:
    """Download (in parallel) and crop real-time days. Returns (available, unavailable)."""
    settings = get_settings()
    _realtime_dir().mkdir(parents=True, exist_ok=True)
    todo = [d for d in days if force or not realtime_nc_path(d).exists()]
    ok = [d for d in days if d not in todo]
    missing: list[date] = []
    if todo:
        log.info("Fetching %d IMD real-time day(s) with %d parallel downloads",
                 len(todo), settings.imd_realtime_workers)
    with ThreadPoolExecutor(max_workers=settings.imd_realtime_workers) as pool:
        futures = {pool.submit(_download_realtime_grd, d, force): d for d in todo}
        for i, fut in enumerate(as_completed(futures), start=1):
            if progress:
                progress(f"IMD real-time {i}/{len(todo)}")
            d = futures[fut]
            if fut.result():
                _crop_realtime_day(d)  # netCDF/HDF5 writes stay on this thread
                ok.append(d)
            else:
                missing.append(d)
    if missing:
        log.warning("IMD real-time rainfall unavailable for %d day(s): %s", len(missing),
                    ", ".join(str(d) for d in sorted(missing)[:15]))
    return sorted(ok), sorted(missing)


def ensure_realtime_day(day: date, force: bool = False) -> bool:
    """Fetch + crop one real-time (provisional) day. Returns False if unavailable."""
    ok, _ = fetch_realtime_days([day], force=force)
    return bool(ok)


# ---------------------------------------------------------------------------
# Stage + reader
# ---------------------------------------------------------------------------


def run_rainfall(start: date, end: date, force: bool = False,
                 progress: Callable[[str], None] | None = None) -> tuple[int, list[str]]:
    """Ensure cropped NetCDFs exist for [start, end]. Returns (days_available, notes)."""
    settings = get_settings()
    settings.ensure_dirs()
    yesterday = date.today() - timedelta(days=1)
    end = min(end, yesterday)
    notes: list[str] = []
    days_ok = 0
    missing_years: list[int] = []
    for year in range(start.year, end.year + 1):
        if progress:
            progress(f"IMD {year}")
        # IMD never publishes the final file for the current year; don't waste retries on it.
        if year < date.today().year and ensure_final_year(year, force=force):
            y0, y1 = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
            days_ok += (y1 - y0).days + 1
        else:
            missing_years.append(year)

    # Real-time fallback for recent years that have no final file yet.
    for year in missing_years:
        if year < date.today().year - 1:
            notes.append(f"final {year} unavailable")
            continue
        d0, d1 = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
        log.info("Using IMD real-time data for %s -> %s", d0, d1)
        wanted = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
        ok, missing = fetch_realtime_days(wanted, force=force, progress=progress)
        days_ok += len(ok)
        notes.append(f"{year}: real-time used ({len(missing)} days unavailable)")
    if missing_years:
        log.warning("Final IMD data missing for years: %s", missing_years)
    return days_ok, notes


def refresh_realtime(days_back: int) -> list[date]:
    """Re-fetch the last ``days_back`` days of real-time data (provisional values get revised)."""
    today = date.today()
    days = [today - timedelta(days=i) for i in range(days_back, 0, -1)]
    days = [d for d in days if not final_nc_path(d.year).exists()]
    fetched, _ = fetch_realtime_days(days, force=True)
    return fetched


def load_rain(start: date, end: date) -> tuple[xr.DataArray, pd.Series]:
    """Load cropped rainfall for [start, end] → (DataArray[time, lat, lon], source per day).

    Final data takes precedence over real-time for any date covered by both.
    """
    pieces: list[xr.DataArray] = []
    sources: list[pd.Series] = []
    final_years: set[int] = set()
    for year in range(start.year, end.year + 1):
        p = final_nc_path(year)
        if p.exists():
            with xr.open_dataset(p) as ds:
                da = ds["rain"].sel(time=slice(str(start), str(end))).load()
            if da.sizes["time"]:
                pieces.append(da)
                sources.append(pd.Series("imd_final", index=pd.DatetimeIndex(da["time"].values)))
                final_years.add(year)
    rt_dir = _cropped_dir() / "realtime"
    if rt_dir.exists():
        for p in sorted(rt_dir.glob("rain_rt_*.nc")):
            day = date.fromisoformat(p.stem.removeprefix("rain_rt_"))
            if not (start <= day <= end) or day.year in final_years:
                continue
            with xr.open_dataset(p) as ds:
                pieces.append(ds["rain"].load())
            sources.append(pd.Series("imd_realtime", index=pd.DatetimeIndex([pd.Timestamp(day)])))
    if not pieces:
        raise FileNotFoundError(
            f"No cropped IMD rainfall between {start} and {end}. Run --stage rainfall first."
        )
    da = xr.concat(pieces, dim="time").sortby("time")
    _, idx = np.unique(da["time"].values, return_index=True)
    da = da.isel(time=np.sort(idx))
    src = pd.concat(sources)
    src = src[~src.index.duplicated(keep="first")].sort_index()
    return da, src
