"""Deterministic mock forecasts with exactly the Segment 2 ``forecasts`` schema.

MOCK — replaces Segment 2's model output only while FORECAST_SOURCE=mock. Everything
downstream (hazards → advisories → delivery) treats these rows exactly like real ones.

How a value is built, for district *d*, issue date *t*, lead week *k*:

1. **Anomaly signal z** (standardised wet/dry tendency):
   * a smooth random field over Tamil Nadu (a few Gaussian "weather systems" whose centres
     and strengths are seeded by (t, seed)), so neighbouring districts look alike;
   * AR(1)-correlated across lead weeks (a wet week 1 tends to be followed by a wet week 2);
   * a seasonal term: NE monsoon (Oct–Dec) pushes coastal districts wetter, the SW monsoon
     (Jun–Sep) favours the Western Ghats districts;
   * a small per-district term seeded by (district code, t, seed).
2. **Weekly normal** = the district's REAL 1991–2020 climatological 7-day total from
   Segment 1 (``climatology_daily.clim_sum_7d``), so seasonality and geography are real.
3. Tercile probabilities = softmax(−a·z, c, a·z), sharper at short leads; quantiles are a
   log-spread around ``normal × exp(0.55 z)`` (0.85 z when dry); ``p_heavy`` grows with q90 and ``p_dry_week``
   is read off the quantile CDF near zero.
4. Confidence uses the SAME rule as Segment 2's contract with a mock skill table per lead.

Invariants (tested): probabilities in [0.001, 0.999] summing to 1, q10 ≤ q50 ≤ q90,
identical output for identical (district, date, seed), different output for another date.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

import numpy as np
import pandas as pd

MOCK_MODEL_VERSION = "mock-gen-v1"

FORECAST_COLS = [
    "region_id", "issue_date", "lead_week", "week_start", "week_end",
    "p_below", "p_normal", "p_above", "q10_mm", "q50_mm", "q90_mm",
    "p_heavy", "p_dry_week", "confidence", "model_version",
]

# Mock lower-bound tercile RPSS per season and lead week (drives the confidence rule).
MOCK_SKILL = {
    "SWM": {1: 0.12, 2: 0.07, 3: 0.04, 4: 0.02},
    "NEM": {1: 0.14, 2: 0.10, 3: 0.05, 4: 0.02},
}
_SHARPNESS = {1: 1.7, 2: 1.35, 3: 1.05, 4: 0.85}
_WESTERN_GHATS = {"The Nilgiris", "Coimbatore", "Kanniyakumari", "Tenkasi", "Theni", "Dindigul"}

# Tamil Nadu bounding box for placing the random weather systems.
_LON = (76.2, 80.4)
_LAT = (8.0, 13.6)


def _seed(*parts: object) -> int:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "little")


def _rng(*parts: object) -> np.random.Generator:
    return np.random.default_rng(_seed(*parts))


def season_of(d: date) -> str:
    return "NEM" if d.month >= 10 else "SWM"


def confidence_level(skill: float, sharp: float) -> str:
    """Segment 2 contract rule (docs/contracts/segment2_output.md)."""
    if skill >= 0.10 and sharp >= 0.50:
        return "High"
    if (skill >= 0.10 and sharp < 0.50) or (0.03 <= skill < 0.10 and sharp >= 0.45):
        return "Medium"
    return "Low"


def _smooth_field(lon: np.ndarray, lat: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Sum of 4 Gaussian bumps + a weak linear gradient, standardised over the districts."""
    f = np.zeros_like(lon, dtype="float64")
    for _ in range(4):
        cx, cy = rng.uniform(*_LON), rng.uniform(*_LAT)
        sigma = rng.uniform(0.7, 1.6)
        amp = rng.normal(0.0, 1.0)
        f += amp * np.exp(-((lon - cx) ** 2 + (lat - cy) ** 2) / (2 * sigma ** 2))
    f += rng.normal(0, 0.25) * (lon - lon.mean()) + rng.normal(0, 0.25) * (lat - lat.mean())
    sd = f.std()
    return (f - f.mean()) / sd if sd > 1e-9 else f


def _cdf_at(x: float, q10: float, q50: float, q90: float) -> float:
    """Piecewise log-linear CDF through (q10, .1), (q50, .5), (q90, .9)."""
    lx = np.log(max(x, 1e-3))
    pts = [(np.log(max(q10, 1e-3)), 0.1), (np.log(max(q50, 1e-3)), 0.5),
           (np.log(max(q90, 1e-3)), 0.9)]
    if lx <= pts[0][0]:
        return 0.1 * float(np.exp(lx - pts[0][0]))  # decays below q10
    for (x0, p0), (x1, p1) in zip(pts, pts[1:]):
        if lx <= x1:
            return p0 + (p1 - p0) * (lx - x0) / max(x1 - x0, 1e-9)
    return 1.0 - 0.1 * float(np.exp(-(lx - pts[2][0])))


def prob_total_at_least(threshold_mm: float, q10: float, q50: float, q90: float) -> float:
    """P(weekly total ≥ threshold) from the three quantiles (used by the hazard rules too)."""
    return float(np.clip(1.0 - _cdf_at(threshold_mm, q10, q50, q90), 0.0, 1.0))


def finalize(df: pd.DataFrame) -> pd.DataFrame:
    """Enforce the Segment 2 invariants after generation or a scenario override."""
    out = df.copy()
    p = out[["p_below", "p_normal", "p_above"]].to_numpy(dtype="float64")
    p = np.clip(p, 0.001, 0.999)
    p = p / p.sum(axis=1, keepdims=True)
    p = np.round(p, 4)
    p[:, 1] = np.round(1.0 - p[:, 0] - p[:, 2], 4)  # rounding is absorbed by p_normal
    out["p_below"], out["p_normal"], out["p_above"] = p[:, 0], p[:, 1], p[:, 2]
    q = np.sort(np.maximum(out[["q10_mm", "q50_mm", "q90_mm"]].to_numpy(dtype="float64"), 0), axis=1)
    out["q10_mm"], out["q50_mm"], out["q90_mm"] = (np.round(q[:, i], 2) for i in range(3))
    for col in ("p_heavy", "p_dry_week"):
        out[col] = np.round(np.clip(out[col].astype("float64"), 0.001, 0.999), 4)
    return out


def generate(regions: pd.DataFrame, weekly_normals: np.ndarray, issue_date: date,
             seed: int = 42) -> pd.DataFrame:
    """Mock forecasts for every region in ``regions`` (columns: id, code, name, lon, lat,
    coastal) and lead weeks 1–4. ``weekly_normals[i, k-1]`` is region i's climatological
    total (mm) for lead week k. Pure function: no database access."""
    n = len(regions)
    lon = regions["lon"].to_numpy(dtype="float64")
    lat = regions["lat"].to_numpy(dtype="float64")
    coastal = regions["coastal"].to_numpy(dtype=bool)
    ghats = regions["name"].isin(_WESTERN_GHATS).to_numpy()
    season = season_of(issue_date)

    field_rng = _rng("field", issue_date.isoformat(), seed)
    district_noise = np.array([
        _rng("district", code, issue_date.isoformat(), seed).normal(0, 0.18, size=4)
        for code in regions["code"]
    ])  # [n, 4]

    rows = []
    z_prev = _smooth_field(lon, lat, field_rng)
    for k in range(1, 5):
        week_start = issue_date + timedelta(days=7 * (k - 1) + 1)
        week_end = issue_date + timedelta(days=7 * k)
        fresh = _smooth_field(lon, lat, field_rng)
        z = 0.65 * z_prev + 0.76 * fresh if k > 1 else z_prev
        z_prev = z
        zz = 0.8 * z + district_noise[:, k - 1]
        mid_month = week_start.month
        if mid_month >= 10 or (mid_month == 9 and week_start.day >= 25):
            zz = zz + np.where(coastal, 0.45, 0.10)  # NE monsoon: coast wetter
        elif 6 <= mid_month <= 9:
            zz = zz + np.where(ghats, 0.25, -0.05)   # SW monsoon: TN mostly in rain shadow
        zz = zz * (1.0 - 0.12 * (k - 1))            # signal decays with lead

        a = _SHARPNESS[k]
        logits = np.stack([-a * zz, np.full(n, 0.1), a * zz], axis=1)
        e = np.exp(logits - logits.max(axis=1, keepdims=True))
        p = e / e.sum(axis=1, keepdims=True)

        spread_rng = _rng("spread", issue_date.isoformat(), seed, k)
        normal = np.maximum(weekly_normals[:, k - 1], 1.0)
        q50 = normal * np.exp(np.where(zz > 0, 0.55, 0.85) * zz)
        u10 = spread_rng.uniform(2.6, 3.4, size=n) + 0.15 * k
        u90 = spread_rng.uniform(0.95, 1.25, size=n) + 0.05 * k
        q10 = q50 * np.exp(-u10)
        q90 = q50 * np.exp(u90)
        p_heavy = 1.0 - np.exp(-((q90 / 380.0) ** 2.6))
        p_dry = np.array([_cdf_at(5.0, a_, b_, c_) for a_, b_, c_ in zip(q10, q50, q90)])

        for i in range(n):
            rows.append({
                "region_id": int(regions["id"].iloc[i]),
                "issue_date": issue_date, "lead_week": k,
                "week_start": week_start, "week_end": week_end,
                "p_below": p[i, 0], "p_normal": p[i, 1], "p_above": p[i, 2],
                "q10_mm": q10[i], "q50_mm": q50[i], "q90_mm": q90[i],
                "p_heavy": p_heavy[i], "p_dry_week": p_dry[i],
            })
    df = finalize(pd.DataFrame(rows))
    df["confidence"] = assign_confidence(df, season)
    df["model_version"] = MOCK_MODEL_VERSION
    return df[FORECAST_COLS].sort_values(["region_id", "lead_week"]).reset_index(drop=True)


def assign_confidence(df: pd.DataFrame, season: str) -> list[str]:
    sharp = df[["p_below", "p_normal", "p_above"]].max(axis=1).to_numpy()
    return [confidence_level(MOCK_SKILL[season][int(k)], float(s))
            for k, s in zip(df["lead_week"], sharp)]
