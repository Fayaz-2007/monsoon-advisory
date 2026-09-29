"""The forecast source switch. Both sources return the SAME DataFrame schema (Segment 2's
``forecasts`` table), so hazards → advisories → delivery never know which one ran.

* ``mock``: :mod:`app.mock.generator` (+ the active demo scenario).
* ``real``: Segment 2's table through ``ml.load_forecasts``. If the requested issue date has
  no rows, the latest issue date on or before it is used and reported as
  ``forecast_issue_date`` (the model runs daily; the demo database holds 2026-09-28).
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import date

import pandas as pd

from app import segment1
from app.config import get_app_settings
from app.db import fetch_all
from app.mock.generator import FORECAST_COLS, MOCK_MODEL_VERSION, generate
from app.mock.scenarios import apply_scenario


class NoForecastError(LookupError):
    pass


@dataclass
class ForecastMeta:
    source: str
    requested_date: date
    forecast_issue_date: date
    model_version: str
    scenario: str
    note: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


_cache: dict[tuple, pd.DataFrame] = {}
_cache_lock = threading.Lock()


def mock_forecasts(issue_date: date, scenario: str | None = None,
                   seed: int | None = None) -> pd.DataFrame:
    seed = get_app_settings().mock_seed if seed is None else seed
    key = ("mock", issue_date, scenario or "none", seed)
    with _cache_lock:
        if key in _cache:
            return _cache[key].copy()
    regions = segment1.regions()
    week_ends = [issue_date + pd.Timedelta(days=7 * k).to_pytimedelta() for k in range(1, 5)]
    normals = segment1.weekly_normal_mm(regions["id"].to_numpy(), week_ends)
    df = generate(regions, normals, issue_date, seed)
    df = apply_scenario(df, regions, scenario)
    with _cache_lock:
        _cache[key] = df
    return df.copy()


def real_issue_dates() -> list[date]:
    return [r["issue_date"] for r in
            fetch_all("SELECT DISTINCT issue_date FROM forecasts ORDER BY issue_date")]


def real_forecasts(issue_date: date) -> tuple[pd.DataFrame, date]:
    from ml import load_forecasts

    dates = [d for d in real_issue_dates() if d <= issue_date]
    if not dates:
        raise NoForecastError(
            f"No Segment 2 forecasts on or before {issue_date}. Available issue dates: "
            f"{[d.isoformat() for d in real_issue_dates()] or 'none'}. Run "
            "`python -m ml.run predict --date <date>` or switch FORECAST_SOURCE to mock.")
    used = dates[-1]
    df = load_forecasts(issue_date=used)
    for col in ("issue_date", "week_start", "week_end"):
        df[col] = pd.to_datetime(df[col]).dt.date
    df["confidence"] = df["confidence"].astype(str)
    df["model_version"] = df["model_version"].astype(str)
    return df[FORECAST_COLS].reset_index(drop=True), used


def get_forecasts(issue_date: date, source: str, scenario: str = "none") -> tuple[pd.DataFrame, ForecastMeta]:
    if source == "mock":
        df = mock_forecasts(issue_date, None if scenario == "none" else scenario)
        return df, ForecastMeta("mock", issue_date, issue_date, MOCK_MODEL_VERSION, scenario,
                                "MOCK forecasts (deterministic generator)")
    if source == "real":
        df, used = real_forecasts(issue_date)
        note = None
        if used != issue_date:
            note = (f"No Segment 2 run for {issue_date}; using the latest run, issued {used} "
                    f"({(issue_date - used).days} day(s) earlier).")
        version = str(df["model_version"].iloc[0]) if not df.empty else get_app_settings().real_model_version
        return df, ForecastMeta("real", issue_date, used, version, "none", note)
    raise ValueError(f"unknown forecast source {source!r}")


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
