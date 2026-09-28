"""Climate indices: ONI (ENSO), DMI (IOD) and MJO (RMM, with ROMI fallback).

Sources (URLs configurable in config.py / .env):
* ONI  — NOAA CPC ``oni.ascii.txt``: 3-month running seasons, anomaly column used.
         Each season is assigned to its centre month (DJF 1991 → Jan 1991).
* DMI  — NOAA PSL ``dmi.had.long.data``: monthly HadISST Dipole Mode Index.
* RMM  — BoM ``rmm.74toRealtime.txt``: daily Wheeler–Hendon RMM1/RMM2/phase/amplitude.
         NOTE: BoM stopped updating this file in Feb 2024.
* ROMI — NOAA PSL ``romi.cpcolr.1x.txt``: real-time OLR MJO index, updated daily.
         Mapped to RMM phase space as (PC2, -PC1) (Kiladis et al. 2014), then rotated by
         ROMI_ROTATION_DEG (default -30°, fitted on the 1991–2024 RMM overlap: raises
         component correlation from ~0.64 to ~0.73; 94% of strong-MJO days within ±1 phase).

Monthly indices are forward-filled to daily; see ``to_daily``.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from pipeline.config import get_settings
from pipeline.db import upsert_df
from pipeline.utils import download_cached

log = logging.getLogger(__name__)

ONI_SEASON_CENTER_MONTH: dict[str, int] = {
    "DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
    "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12,
}
MISSING_ABS = 999.0  # |value| >= this is treated as missing (RMM uses 999 and 1e36)


# ---------------------------------------------------------------------------
# Parsers (pure functions — unit tested)
# ---------------------------------------------------------------------------


def parse_oni(text: str) -> pd.DataFrame:
    """Parse CPC ``oni.ascii.txt`` → DataFrame[date (month start), oni]."""
    rows: list[tuple[pd.Timestamp, float]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0].upper() not in ONI_SEASON_CENTER_MONTH:
            continue
        try:
            year = int(parts[1])
            anom = float(parts[3])
        except ValueError:
            continue
        if abs(anom) >= 99:
            continue
        rows.append((pd.Timestamp(year, ONI_SEASON_CENTER_MONTH[parts[0].upper()], 1), anom))
    df = pd.DataFrame(rows, columns=["date", "oni"])
    return df.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def parse_dmi(text: str) -> pd.DataFrame:
    """Parse PSL ``dmi.had.long.data`` → DataFrame[date (month start), dmi].

    Format: first line "<start_year> <end_year>", then one row per year with 12
    monthly values, then a missing-value line (-9999) and free-text footer.
    """
    lines = text.splitlines()
    header = lines[0].split()
    y0, y1 = int(header[0]), int(header[1])
    rows: list[tuple[pd.Timestamp, float]] = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) != 13:
            if parts and parts[0].lstrip("-").isdigit() and len(parts) == 1:
                break  # missing-value sentinel line → footer follows
            continue
        try:
            year = int(parts[0])
        except ValueError:
            continue
        if not (y0 <= year <= y1):
            continue
        for month, token in enumerate(parts[1:], start=1):
            value = float(token)
            if value <= -999:
                continue
            rows.append((pd.Timestamp(year, month, 1), value))
    df = pd.DataFrame(rows, columns=["date", "dmi"])
    return df.sort_values("date").reset_index(drop=True)


def mjo_phase(rmm1: np.ndarray | pd.Series, rmm2: np.ndarray | pd.Series) -> np.ndarray:
    """Wheeler–Hendon phase (1..8) from RMM1/RMM2; NaN where inputs are missing."""
    x = np.asarray(rmm1, dtype=float)
    y = np.asarray(rmm2, dtype=float)
    angle = np.arctan2(y, x)  # (-pi, pi]
    phase = np.floor((angle + np.pi) / (np.pi / 4)) + 1
    phase = np.clip(phase, 1, 8)
    phase[np.isnan(x) | np.isnan(y)] = np.nan
    return phase


def parse_rmm(text: str) -> pd.DataFrame:
    """Parse BoM ``rmm.74toRealtime.txt`` → DataFrame[date, rmm1, rmm2, mjo_phase, mjo_amplitude]."""
    rows: list[tuple[pd.Timestamp, float, float, float, float]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 7:
            continue
        try:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            r1, r2, ph, amp = (float(p) for p in parts[3:7])
        except ValueError:
            continue
        vals = [np.nan if abs(v) >= MISSING_ABS else v for v in (r1, r2, ph, amp)]
        rows.append((pd.Timestamp(y, m, d), *vals))
    df = pd.DataFrame(rows, columns=["date", "rmm1", "rmm2", "mjo_phase", "mjo_amplitude"])
    bad_phase = ~df["mjo_phase"].between(1, 8)
    df.loc[bad_phase, "mjo_phase"] = np.nan
    return df.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def parse_romi(text: str, rotation_deg: float = 0.0) -> pd.DataFrame:
    """Parse PSL ROMI (year month day hour PC1 PC2 amplitude) into RMM-equivalent columns.

    ``rotation_deg`` rotates the (PC2, -PC1) phase-space vector anticlockwise.
    """
    rows: list[tuple[pd.Timestamp, float, float, float]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 7:
            continue
        try:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            pc1, pc2, amp = float(parts[4]), float(parts[5]), float(parts[6])
        except ValueError:
            continue
        if max(abs(pc1), abs(pc2), abs(amp)) >= MISSING_ABS:
            continue
        rows.append((pd.Timestamp(y, m, d), pc2, -pc1, amp))
    df = pd.DataFrame(rows, columns=["date", "rmm1", "rmm2", "mjo_amplitude"])
    if rotation_deg:
        t = np.radians(rotation_deg)
        x, y = df["rmm1"].to_numpy(), df["rmm2"].to_numpy()
        df["rmm1"] = x * np.cos(t) - y * np.sin(t)
        df["rmm2"] = x * np.sin(t) + y * np.cos(t)
    df["mjo_phase"] = mjo_phase(df["rmm1"], df["rmm2"])
    return df.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def combine_mjo(rmm: pd.DataFrame | None, romi: pd.DataFrame | None, mode: str) -> pd.DataFrame:
    """Merge RMM and ROMI according to ``mode``; adds an ``mjo_source`` column."""
    cols = ["date", "rmm1", "rmm2", "mjo_phase", "mjo_amplitude", "mjo_source"]
    parts: list[pd.DataFrame] = []
    if mode in ("rmm_then_romi", "rmm_only") and rmm is not None and not rmm.empty:
        r = rmm.dropna(subset=["rmm1", "rmm2"]).assign(mjo_source="rmm")
        parts.append(r)
    if mode in ("rmm_then_romi", "romi_only") and romi is not None and not romi.empty:
        o = romi.assign(mjo_source="romi")
        if parts:
            o = o[~o["date"].isin(parts[0]["date"])]
        parts.append(o)
    if not parts:
        return pd.DataFrame(columns=cols)
    return pd.concat(parts)[cols].sort_values("date").reset_index(drop=True)


def to_daily(oni: pd.DataFrame, dmi: pd.DataFrame, mjo: pd.DataFrame,
             start: date, end: date, monthly_ffill_days: int,
             daily_ffill_days: int) -> pd.DataFrame:
    """Expand to one row per day between ``start`` and ``end`` (trailing all-NaN days trimmed).

    Monthly values apply to every day of their month and are then forward-filled
    for at most ``monthly_ffill_days`` beyond the last month that has data. Daily
    MJO values are forward-filled across gaps of up to ``daily_ffill_days``.
    """
    days = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    out = pd.DataFrame({"date": days})
    month_start = days.to_period("M").to_timestamp()

    for name, frame in (("oni", oni), ("dmi", dmi)):
        s = frame.set_index("date")[name] if not frame.empty else pd.Series(dtype=float)
        vals = pd.Series(month_start.map(s), index=days, dtype=float)
        # Forward fill counts days since the last day with a value (end of last known month).
        out[name] = vals.ffill(limit=monthly_ffill_days).to_numpy()

    m = mjo.set_index("date").reindex(days) if not mjo.empty else pd.DataFrame(index=days)
    for col in ("rmm1", "rmm2", "mjo_phase", "mjo_amplitude", "mjo_source"):
        series = m[col] if col in m else pd.Series(np.nan, index=days)
        out[col] = series.ffill(limit=daily_ffill_days).to_numpy()

    value_cols = ["oni", "dmi", "rmm1", "rmm2"]
    has_any = out[value_cols].notna().any(axis=1)
    if has_any.any():
        out = out.loc[: has_any[has_any].index.max()]
    else:
        out = out.iloc[0:0]
    out["mjo_phase"] = pd.to_numeric(out["mjo_phase"]).round().astype("Int64")
    out["mjo_source"] = out["mjo_source"].astype("object").where(out["mjo_source"].notna(), None)
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Stage
# ---------------------------------------------------------------------------


def _fetch_text(url: str, force: bool) -> str | None:
    settings = get_settings()
    filename = url.rstrip("/").rsplit("/", 1)[-1]
    try:
        path = download_cached(url, settings.indices_dir / filename,
                               max_age_hours=settings.index_refresh_hours, force=force)
    except RuntimeError as exc:
        log.error("%s", exc)
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def run_indices(start: date | None = None, end: date | None = None,
                force: bool = False) -> tuple[int, list[str]]:
    """Download, parse and upsert climate_indices_daily. Returns (rows, notes)."""
    settings = get_settings()
    start = min(start or settings.indices_start_date, settings.indices_start_date)
    end = end or date.today()
    notes: list[str] = []

    parsed: dict[str, pd.DataFrame | None] = {}
    for key, url, parser in (("oni", settings.oni_url, parse_oni),
                             ("dmi", settings.dmi_url, parse_dmi),
                             ("rmm", settings.rmm_url, parse_rmm),
                             ("romi", settings.romi_url,
                              lambda t: parse_romi(t, settings.romi_rotation_deg))):
        if key == "rmm" and settings.mjo_source_mode == "romi_only":
            continue
        if key == "romi" and settings.mjo_source_mode == "rmm_only":
            continue
        text = _fetch_text(url, force)
        if text is None:
            parsed[key] = None
            notes.append(f"{key}: download failed")
            continue
        df = parser(text)
        parsed[key] = df
        last = df["date"].max().date() if not df.empty else None
        log.info("%-4s parsed %6d rows, %s -> %s", key.upper(), len(df),
                 df["date"].min().date() if not df.empty else "-", last)
        notes.append(f"{key}: {len(df)} rows to {last}")

    if parsed.get("oni") is None and parsed.get("dmi") is None and \
            parsed.get("rmm") is None and parsed.get("romi") is None:
        raise RuntimeError("All climate-index downloads failed and no cache is available")

    rmm = parsed.get("rmm")
    if rmm is not None and not rmm.empty and settings.mjo_source_mode != "romi_only":
        gap = (pd.Timestamp(end) - rmm["date"].max()).days
        if gap > 30:
            log.warning("BoM RMM ends %s (%d days before end date); ROMI fills later dates "
                        "(mode=%s)", rmm["date"].max().date(), gap, settings.mjo_source_mode)

    mjo = combine_mjo(rmm, parsed.get("romi"), settings.mjo_source_mode)
    empty_monthly = pd.DataFrame(columns=["date"])
    daily = to_daily(
        parsed.get("oni") if parsed.get("oni") is not None else empty_monthly.assign(oni=[]),
        parsed.get("dmi") if parsed.get("dmi") is not None else empty_monthly.assign(dmi=[]),
        mjo, start, end, settings.monthly_index_ffill_days, settings.daily_index_ffill_days,
    )
    n = upsert_df(daily, "climate_indices_daily", pk_cols=["date"])
    log.info("Upserted %d climate_indices_daily rows (%s -> %s)", n,
             daily["date"].min().date() if not daily.empty else "-",
             daily["date"].max().date() if not daily.empty else "-")
    return n, notes
