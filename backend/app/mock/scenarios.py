"""Demo scenarios: deterministic overrides applied on top of the mock forecasts.

MOCK — scenarios only apply while FORECAST_SOURCE=mock (activating one switches the
source to mock). Each scenario edits forecast rows only; the hazard, advisory and delivery
engines then react to those rows exactly as they would to a real forecast.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from app.mock.generator import assign_confidence, finalize, season_of

Override = dict[str, float | str]


@dataclass(frozen=True)
class Scenario:
    name: str
    title: str
    description: str
    demo_date: date | None           # suggested issue date (None = today)
    focus_districts: tuple[str, ...]
    apply: Callable[[pd.DataFrame, pd.DataFrame], pd.DataFrame]


def _ids(regions: pd.DataFrame, names: tuple[str, ...] | list[str]) -> dict[str, int]:
    m = dict(zip(regions["name"], regions["id"]))
    return {n: int(m[n]) for n in names if n in m}


def _set(df: pd.DataFrame, region_id: int, lead: int, values: Override) -> None:
    mask = (df["region_id"] == region_id) & (df["lead_week"] == lead)
    for col, v in values.items():
        df.loc[mask, col] = v


def _finish(df: pd.DataFrame, pinned_conf: dict[tuple[int, int], str]) -> pd.DataFrame:
    season = season_of(pd.Timestamp(df["issue_date"].iloc[0]).date())
    out = finalize(df)
    out["confidence"] = assign_confidence(out, season)
    for (rid, lead), conf in pinned_conf.items():
        out.loc[(out["region_id"] == rid) & (out["lead_week"] == lead), "confidence"] = conf
    return out


# ---------------------------------------------------------------------------
# 1. False onset trap — Madurai
# ---------------------------------------------------------------------------

def _false_onset_trap(df: pd.DataFrame, regions: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    pinned: dict[tuple[int, int], str] = {}
    core = _ids(regions, ["Madurai"])
    ring = _ids(regions, ["Dindigul", "Theni", "Sivaganga", "Virudhunagar"])
    weeks: dict[int, Override] = {
        1: dict(p_below=0.05, p_normal=0.15, p_above=0.80, q10_mm=18, q50_mm=52, q90_mm=115,
                p_heavy=0.45, p_dry_week=0.01),
        2: dict(p_below=0.78, p_normal=0.18, p_above=0.04, q10_mm=0.0, q50_mm=1.2, q90_mm=6,
                p_heavy=0.01, p_dry_week=0.80),
        3: dict(p_below=0.62, p_normal=0.28, p_above=0.10, q10_mm=0.2, q50_mm=3.5, q90_mm=18,
                p_heavy=0.02, p_dry_week=0.55),
        4: dict(p_below=0.40, p_normal=0.35, p_above=0.25, q10_mm=1.0, q50_mm=12, q90_mm=45,
                p_heavy=0.05, p_dry_week=0.25),
    }
    for rid in core.values():
        for k, v in weeks.items():
            _set(df, rid, k, v)
        pinned.update({(rid, 1): "High", (rid, 2): "High", (rid, 3): "Medium"})
    ring_weeks: dict[int, Override] = {
        1: dict(p_below=0.15, p_normal=0.30, p_above=0.55, q10_mm=6, q50_mm=28, q90_mm=70,
                p_heavy=0.18, p_dry_week=0.05),
        2: dict(p_below=0.55, p_normal=0.30, p_above=0.15, q10_mm=0.3, q50_mm=5, q90_mm=22,
                p_heavy=0.03, p_dry_week=0.42),
    }
    for rid in ring.values():
        for k, v in ring_weeks.items():
            _set(df, rid, k, v)
    return _finish(df, pinned)


# ---------------------------------------------------------------------------
# 2. NE monsoon surge — Chennai, Cuddalore, Nagapattinam
# ---------------------------------------------------------------------------

def _ne_monsoon_surge(df: pd.DataFrame, regions: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    pinned: dict[tuple[int, int], str] = {}
    core = _ids(regions, ["Chennai", "Cuddalore", "Nagapattinam"])
    ring = _ids(regions, ["Thiruvallur", "Chengalputtu", "Kancheepuram", "Viluppuram",
                          "Mayiladuthurai", "Thiruvarur"])
    # Calm the rest of the state so the alerts are clearly the surge districts.
    others = ~df["region_id"].isin(list(core.values()))
    df.loc[others, "p_heavy"] = np.minimum(df.loc[others, "p_heavy"], 0.25)
    weeks: dict[int, Override] = {
        1: dict(p_below=0.04, p_normal=0.14, p_above=0.82, q10_mm=45, q50_mm=140, q90_mm=320,
                p_heavy=0.85, p_dry_week=0.005),
        2: dict(p_below=0.08, p_normal=0.22, p_above=0.70, q10_mm=25, q50_mm=95, q90_mm=240,
                p_heavy=0.62, p_dry_week=0.01),
        3: dict(p_below=0.20, p_normal=0.35, p_above=0.45, q10_mm=10, q50_mm=55, q90_mm=150,
                p_heavy=0.30, p_dry_week=0.05),
    }
    for rid in core.values():
        for k, v in weeks.items():
            _set(df, rid, k, v)
        pinned.update({(rid, 1): "High", (rid, 2): "High", (rid, 3): "Medium"})
    for rid in ring.values():
        _set(df, rid, 1, dict(p_below=0.10, p_normal=0.30, p_above=0.60, q10_mm=15, q50_mm=70,
                              q90_mm=150, p_heavy=0.22, p_dry_week=0.02))
        _set(df, rid, 2, dict(p_below=0.15, p_normal=0.33, p_above=0.52, q10_mm=10, q50_mm=50,
                              q90_mm=130, p_heavy=0.18, p_dry_week=0.03))
    return _finish(df, pinned)


# ---------------------------------------------------------------------------
# 3. Mid-season break — groundnut belt during flowering/pegging
# ---------------------------------------------------------------------------

GROUNDNUT_BELT = ("Tiruvannamalai", "Viluppuram", "Vellore", "Ranipet", "Kallakurichi",
                  "Salem", "Namakkal", "Pudukkottai", "Krishnagiri", "Dharmapuri")


def _mid_season_break(df: pd.DataFrame, regions: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    pinned: dict[tuple[int, int], str] = {}
    weeks: dict[int, Override] = {
        1: dict(p_below=0.72, p_normal=0.22, p_above=0.06, q10_mm=0.0, q50_mm=1.5, q90_mm=9,
                p_heavy=0.01, p_dry_week=0.70),
        2: dict(p_below=0.65, p_normal=0.25, p_above=0.10, q10_mm=0.1, q50_mm=2.5, q90_mm=14,
                p_heavy=0.02, p_dry_week=0.62),
        3: dict(p_below=0.12, p_normal=0.33, p_above=0.55, q10_mm=8, q50_mm=35, q90_mm=85,
                p_heavy=0.12, p_dry_week=0.06),
    }
    for rid in _ids(regions, GROUNDNUT_BELT).values():
        for k, v in weeks.items():
            _set(df, rid, k, v)
        pinned.update({(rid, 1): "High", (rid, 2): "Medium"})
    return _finish(df, pinned)


# ---------------------------------------------------------------------------
# 4. Normal season — mostly calm
# ---------------------------------------------------------------------------

def _normal_season(df: pd.DataFrame, regions: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    third = 1.0 / 3.0
    for col in ("p_below", "p_normal", "p_above"):
        df[col] = 0.35 * df[col] + 0.65 * third
    df["p_heavy"] = np.minimum(df["p_heavy"], 0.12)
    df["p_dry_week"] = np.minimum(df["p_dry_week"], 0.18)
    # Pull the quantile spread in towards the median.
    q50 = df["q50_mm"].astype("float64")
    df["q10_mm"] = q50 * 0.35
    df["q90_mm"] = np.minimum(df["q90_mm"], q50 * 2.2)
    return _finish(df, {})


SCENARIOS: dict[str, Scenario] = {
    s.name: s for s in [
        Scenario("false_onset_trap", "False onset trap",
                 "Heavy early rain in Madurai next week, then a ~10-day dry spell. Early "
                 "sowing would fail, so the advice is: don't sow yet.",
                 None, ("Madurai",), _false_onset_trap),
        Scenario("ne_monsoon_surge", "NE monsoon surge",
                 "A strong northeast-monsoon pulse brings heavy-rain alerts to Chennai, "
                 "Cuddalore and Nagapattinam in weeks 1–2.",
                 date(2026, 10, 20), ("Chennai", "Cuddalore", "Nagapattinam"), _ne_monsoon_surge),
        Scenario("mid_season_break", "Mid-season break",
                 "A two-week dry spell over the groundnut belt during flowering/pegging, "
                 "with rain returning in week 3.",
                 date(2026, 8, 14), GROUNDNUT_BELT, _mid_season_break),
        Scenario("normal_season", "Normal season",
                 "Near-normal rainfall everywhere; few or no alerts.",
                 None, (), _normal_season),
    ]
}


def apply_scenario(df: pd.DataFrame, regions: pd.DataFrame, name: str | None) -> pd.DataFrame:
    if not name or name == "none":
        return df
    if name not in SCENARIOS:
        raise KeyError(name)
    return SCENARIOS[name].apply(df, regions)
