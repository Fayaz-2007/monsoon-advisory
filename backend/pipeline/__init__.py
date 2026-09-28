"""Segment 1 — data pipeline for the Hyperlocal Monsoon Onset & Break Prediction System.

Segment 2 (ML) should consume data through :func:`load_features`::

    from pipeline import load_features
    df = load_features(region_ids=[12, 13], start="2015-01-01", end="2024-12-31")

See docs/contracts/segment1_output.md for the schema.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import pandas as pd

__all__ = ["load_features", "load_regions"]


def load_features(
    region_ids: Iterable[int] | None = None,
    start: str | date | None = None,
    end: str | date | None = None,
) -> pd.DataFrame:
    """Return rows of ``features_daily`` as a DataFrame sorted by (region_id, date).

    Args:
        region_ids: restrict to these ``regions.id`` values (default: all active regions).
        start, end: inclusive date bounds (ISO string or ``date``); ``None`` = unbounded.

    The ``date`` column is returned as ``datetime64[ns]``. Only *active* regions
    (the current boundary level) are returned unless ``region_ids`` is given.
    """
    from pipeline.db import read_df  # local import keeps `import pipeline` lightweight

    where: list[str] = []
    params: dict[str, object] = {}
    if region_ids is not None:
        ids = [int(r) for r in region_ids]
        if not ids:
            return pd.DataFrame()
        where.append("f.region_id = ANY(:ids)")
        params["ids"] = ids
    else:
        where.append("r.active")
    if start is not None:
        where.append("f.date >= :start")
        params["start"] = pd.Timestamp(start).date()
    if end is not None:
        where.append("f.date <= :end")
        params["end"] = pd.Timestamp(end).date()

    sql = (
        "SELECT f.* FROM features_daily f JOIN regions r ON r.id = f.region_id "
        f"WHERE {' AND '.join(where)} ORDER BY f.region_id, f.date"
    )
    df = read_df(sql, params).drop(columns=["updated_at"], errors="ignore")
    return _apply_feature_dtypes(df)


# Stable dtypes regardless of which rows are selected (pandas would otherwise infer
# int64 vs float64 depending on NULLs, and object for all-NULL columns like ERA5).
_INT_COLS = ("consecutive_dry_days", "wet_days_last_7", "wet_days_last_14", "mjo_phase")


def _apply_feature_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["region_id"] = out["region_id"].astype("int64")
    out["date"] = pd.to_datetime(out["date"]).astype("datetime64[ns]")
    for col in out.columns:
        if col in ("region_id", "date"):
            continue
        if col in _INT_COLS:
            out[col] = pd.to_numeric(out[col]).astype("Int64")
        elif col == "mjo_source":
            out[col] = out[col].astype("string")
        elif col == "is_monsoon_season":
            out[col] = out[col].astype("bool")
        else:
            out[col] = pd.to_numeric(out[col]).astype("float64")
    return out


def load_regions(active_only: bool = True) -> pd.DataFrame:
    """Return region metadata (no geometry): id, code, name, district, level, state, area_km2."""
    from pipeline.db import read_df

    sql = "SELECT id, code, name, district, level, state, area_km2, active FROM regions"
    if active_only:
        sql += " WHERE active"
    return read_df(sql + " ORDER BY id")
