"""MOCK block-level demo: the 13 Community Development blocks of Madurai district.

DEMO DATA. Blocks are ``level='block'`` regions whose parent is Madurai district. They live
here (not in Segment 1's ``regions`` table, which the backend never writes) and use ids from
``BLOCK_ID_BASE`` up, so they can never collide with a district id.

* Block list: Madurai District Administration, "Development Administration" page
  (https://madurai.nic.in/administrative-setup/development-administration/) — 13 blocks.
* Markers sit at each block's headquarters town. Coordinates: OpenStreetMap via Nominatim /
  Photon (see ``coord_source``); Sedapatti has no OSM settlement node, so its point is the
  Wikipedia article's coordinate. Madurai East / West are headquartered inside Madurai city;
  their points are OSM features named for them and are approximate.
* Forecasts: the SAME mock generator as the districts, evaluated at the block HQ inside the
  statewide field, then pulled towards Madurai's own (scenario-adjusted) forecast so blocks
  look like their district and like each other, but not identical.
* Observed rain: Madurai's REAL area-averaged series × a deterministic per-block, per-day
  factor (MOCK), with Madurai's real daily normal.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app import segment1
from app.mock.generator import _rng, assign_confidence, finalize, generate, season_of

BLOCK_ID_BASE = 90000
PARENT_DISTRICT = "Madurai"
DEMO_LABEL = "Block level · demo data"
SOURCE_BLOCKS = ("Madurai District Administration — Development Administration "
                 "(madurai.nic.in/administrative-setup/development-administration/)")


@dataclass(frozen=True)
class Block:
    n: int
    name: str
    name_ta: str
    hq: str
    lat: float
    lon: float
    coord_source: str
    # How hard the false-onset scenario hits this block (1 = exactly Madurai's forecast).
    false_onset_weight: float

    @property
    def id(self) -> int:
        return BLOCK_ID_BASE + self.n

    @property
    def slug(self) -> str:
        return re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")

    @property
    def label(self) -> str:
        return f"{self.name} block, {PARENT_DISTRICT}"


_OSM = "OpenStreetMap (Nominatim)"
_PHOTON = "OpenStreetMap (Photon)"
BLOCKS: tuple[Block, ...] = (
    Block(1, "Madurai East", "மதுரை கிழக்கு", "Madurai (east)", 9.90908, 78.13454,
          f"{_OSM}: 'Madurai East' — approximate, HQ is in Madurai city", 0.2),
    Block(2, "Madurai West", "மதுரை மேற்கு", "Madurai (west)", 9.93756, 78.07533,
          f"{_OSM}: Madurai West taluk office — approximate, HQ is in Madurai city", 0.75),
    Block(3, "Thiruparankundram", "திருப்பரங்குன்றம்", "Thiruparankundram", 9.88078, 78.04999,
          f"{_OSM}: town node", 0.8),
    Block(4, "Melur", "மேலூர்", "Melur", 10.03090, 78.33758, f"{_OSM}: town node", 0.1),
    Block(5, "Kottampatti", "கொட்டாம்பட்டி", "Kottampatti", 10.22159, 78.37392,
          f"{_OSM}: village node", 0.05),
    Block(6, "Vadipatti", "வாடிப்பட்டி", "Vadipatti", 10.08255, 77.96834, f"{_OSM}: town node", 0.6),
    Block(7, "Alanganallur", "அலங்காநல்லூர்", "Alanganallur", 10.04635, 78.08780,
          f"{_OSM}: town node", 0.3),
    Block(8, "Usilampatti", "உசிலம்பட்டி", "Usilampatti", 9.96487, 77.78986, f"{_OSM}: town node", 1.0),
    Block(9, "Chellampatti", "செல்லம்பட்டி", "Chellampatti", 9.94409, 77.89799,
          f"{_OSM}: village node 'Chellampatty'", 0.95),
    Block(10, "T.Kallupatti", "டி.கல்லுப்பட்டி", "T.Kallupatti", 9.72055, 77.85173,
          f"{_OSM}: village node", 0.9),
    Block(11, "Sedapatti", "சேடபட்டி", "Sedapatti", 9.8118, 77.7937,
          "Wikipedia 'Sedapatti' coordinate (no OSM settlement node)", 1.0),
    Block(12, "Thirumangalam", "திருமங்கலம்", "Thirumangalam", 9.79801, 77.92984,
          f"{_OSM}: Thirumangalam", 0.85),
    Block(13, "Kallikudi", "கள்ளிக்குடி", "Kallikudi", 9.69967, 77.96930,
          f"{_PHOTON}: Panchayat Union Office Kallikudi", 0.7),
)
_BY_ID = {b.id: b for b in BLOCKS}
_BY_LABEL = {b.label: b for b in BLOCKS}
TA_LABELS = {b.label: f"{b.name_ta} வட்டாரம், மதுரை" for b in BLOCKS}

# Normal-day pull towards Madurai's forecast (the rest comes from the block's own mock field).
_PARENT_WEIGHT = 0.45


def is_block_id(region_id: int) -> bool:
    return int(region_id) > BLOCK_ID_BASE


def by_id(region_id: int) -> Block | None:
    return _BY_ID.get(int(region_id))


def parent_of_label(label: str) -> str:
    """District name to use for crop calendars etc. (block label → Madurai)."""
    return PARENT_DISTRICT if label in _BY_LABEL else label


def parent_region() -> dict[str, Any]:
    reg = segment1.resolve_district(PARENT_DISTRICT)
    if reg is None:
        raise LookupError("Madurai district is missing from Segment 1 regions")
    return reg


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def resolve_block(key: str | int) -> dict[str, Any] | None:
    k = str(key).strip()
    if k.isdigit():
        b = _BY_ID.get(int(k))
    else:
        n = _norm(k.split("/")[-1])
        b = next((x for x in BLOCKS if n in (_norm(x.slug), _norm(x.name), _norm(x.label))), None)
    return block_dict(b) if b else None


def block_areas() -> dict[int, float]:
    """Mock area per block: Madurai's real area split evenly (used for farmer counts only)."""
    area = float(parent_region()["area_km2"])
    return {b.id: area / len(BLOCKS) for b in BLOCKS}


def block_dict(b: Block) -> dict[str, Any]:
    parent = parent_region()
    return {
        "id": b.id, "code": f"{parent['code']}/{b.slug}", "slug": b.slug, "name": b.name,
        "name_ta": b.name_ta, "label": b.label, "level": "block",
        "parent": {"id": int(parent["id"]), "name": parent["name"], "slug": parent["slug"]},
        "hq": b.hq, "lon": b.lon, "lat": b.lat, "coord_source": b.coord_source,
        "area_km2": round(block_areas()[b.id], 1), "coastal": False,
        "demo": True, "demo_label": DEMO_LABEL,
    }


def blocks_frame() -> pd.DataFrame:
    return pd.DataFrame([{"id": b.id, "code": f"tn/madurai/{b.slug}", "name": b.label,
                          "lon": b.lon, "lat": b.lat, "coastal": False} for b in BLOCKS])


# ---------------------------------------------------------------------------
# Forecasts
# ---------------------------------------------------------------------------

_cache: dict[tuple, pd.DataFrame] = {}
_lock = threading.Lock()


def _block_own_mock(issue_date: date, seed: int) -> pd.DataFrame:
    """The mock generator run over districts + blocks together (so blocks sit in the same
    statewide weather field); only the block rows are kept."""
    regions = segment1.regions()
    parent_id = int(parent_region()["id"])
    blocks = blocks_frame()
    both = pd.concat([regions[["id", "code", "name", "lon", "lat", "coastal"]], blocks],
                     ignore_index=True)
    week_ends = [issue_date + timedelta(days=7 * k) for k in range(1, 5)]
    normals = segment1.weekly_normal_mm(both["id"].to_numpy(), week_ends)
    parent_row = segment1.weekly_normal_mm(np.array([parent_id]), week_ends)[0]
    normals[len(regions):] = parent_row  # blocks share Madurai's real climatology
    df = generate(both, normals, issue_date, seed)
    return df[df["region_id"] > BLOCK_ID_BASE].reset_index(drop=True)


def block_forecasts(issue_date: date, district_fc: pd.DataFrame, scenario: str,
                    seed: int = 42) -> pd.DataFrame:
    """Block forecasts (Segment 2 schema) = blend of the block's own mock and Madurai's row."""
    parent_id = int(parent_region()["id"])
    key = (issue_date, scenario, seed, pd.util.hash_pandas_object(
        district_fc[district_fc["region_id"] == parent_id], index=False).sum())
    with _lock:
        if key in _cache:
            return _cache[key].copy()
    own = _block_own_mock(issue_date, seed)
    parent = district_fc[district_fc["region_id"] == parent_id].set_index("lead_week")
    out = own.copy()
    pinned: list[tuple[int, int, str]] = []
    for i, row in own.iterrows():
        b = _BY_ID[int(row["region_id"])]
        k = int(row["lead_week"])
        if k not in parent.index:
            continue
        p = parent.loc[k]
        w = b.false_onset_weight if scenario == "false_onset_trap" else _PARENT_WEIGHT
        for col in ("p_below", "p_normal", "p_above", "p_heavy", "p_dry_week"):
            out.at[i, col] = w * float(p[col]) + (1 - w) * float(row[col])
        for col in ("q10_mm", "q50_mm", "q90_mm"):  # geometric blend keeps the log-spread
            out.at[i, col] = float(np.exp(w * np.log(max(float(p[col]), 0.05))
                                          + (1 - w) * np.log(max(float(row[col]), 0.05))))
        if w >= 0.7:
            pinned.append((i, k, str(p["confidence"])))
    out = finalize(out)
    out["confidence"] = assign_confidence(out, season_of(issue_date))
    for i, _k, conf in pinned:
        out.at[i, "confidence"] = conf
    out["model_version"] = own["model_version"].iloc[0] + "+block-demo"
    out = out.sort_values(["region_id", "lead_week"]).reset_index(drop=True)
    with _lock:
        _cache[key] = out
    return out.copy()


# ---------------------------------------------------------------------------
# Observed rain (MOCK, derived from Madurai's real series)
# ---------------------------------------------------------------------------

def _block_rain(b: Block, d: date, parent_mm: float) -> float:
    """Deterministic MOCK rain for one block-day: Madurai's value × (fixed block bias × daily
    jitter), plus an occasional local shower, so neighbours stay close but not identical."""
    bias = 0.6 + 0.8 * _rng("block-bias", b.slug).uniform()
    r = _rng("block-rain", b.slug, d.isoformat())
    jitter, u, shower = r.normal(0, 0.35), r.uniform(), r.uniform(2.6, 9.0)
    showery = 0.04 + 0.12 * _rng("block-showery", b.slug).uniform()
    return round(float(parent_mm) * bias * float(np.exp(jitter)) + (shower if u < showery else 0.0), 1)


def observed_daily(issue_date: date, days: int = 30) -> pd.DataFrame:
    """Same columns as :func:`segment1.observed_daily` (region_id, date, rain_mm) for blocks."""
    parent = segment1.observed_daily(issue_date, days, [int(parent_region()["id"])])
    rows = []
    for b in BLOCKS:
        for d, r in zip(parent["date"], parent["rain_mm"]):
            rows.append({"region_id": b.id, "date": d,
                         "rain_mm": _block_rain(b, d, float(r))})
    return pd.DataFrame(rows, columns=["region_id", "date", "rain_mm"])


def rainfall_series(block_id: int, days: int = 30, end: date | None = None) -> pd.DataFrame:
    """Like :func:`segment1.rainfall_series` for a block (MOCK rain, REAL Madurai normal)."""
    b = _BY_ID[block_id]
    df = segment1.rainfall_series(int(parent_region()["id"]), days, end)
    if df.empty:
        return df
    df = df.copy()
    df["rain_mm"] = [_block_rain(b, d, float(r)) for d, r in zip(df["date"], df["rain_mm"])]
    df["source"] = "mock-block"
    df["rain_sum_7d"] = df["rain_mm"].rolling(7, min_periods=1).sum().round(1)
    for col in ("anomaly_7d_pct", "consecutive_dry_days"):
        df[col] = None
    return df


def features_for(obs: pd.DataFrame, parent_feat: pd.Series | None) -> tuple[float | None, int | None]:
    """(7-day anomaly %, wet days in last 7) for one block's observed series, using Madurai's
    real 7-day normal (derived from its real 7-day sum and anomaly)."""
    last7 = obs.sort_values("date").tail(7)
    wet = int((last7["rain_mm"] >= 2.5).sum()) if len(last7) else None
    anom = None
    if parent_feat is not None and pd.notna(parent_feat.get("anomaly_7d_pct")) \
            and pd.notna(parent_feat.get("rain_sum_7d")):
        denom = 1 + float(parent_feat["anomaly_7d_pct"]) / 100
        normal7 = float(parent_feat["rain_sum_7d"]) / denom if denom > 0.01 else None
        if normal7 and normal7 > 0.1:
            anom = (float(last7["rain_mm"].sum()) / normal7 - 1) * 100
    return anom, wet
