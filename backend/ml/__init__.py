"""Segment 2 — ML prediction engine for the Hyperlocal Monsoon Onset & Break Prediction System.

Segment 3 reads forecasts through :func:`load_forecasts`::

    from ml import load_forecasts
    df = load_forecasts(issue_date="2026-09-28")

See docs/contracts/segment2_output.md for the schema and the confidence rule.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import pandas as pd

__all__ = ["load_forecasts"]

_FLOAT_COLS = ("p_below", "p_normal", "p_above", "q10_mm", "q50_mm", "q90_mm",
               "p_heavy", "p_dry_week")


def load_forecasts(region_ids: Iterable[int] | None = None,
                   issue_date: str | date | None = None) -> pd.DataFrame:
    """Rows of ``forecasts`` sorted by (region_id, issue_date, lead_week).

    Args:
        region_ids: restrict to these ``regions.id`` values (default: all).
        issue_date: one issue date (default: every issue date stored).

    Dtypes: region_id int64, lead_week int64, issue_date/week_start/week_end
    datetime64[ns], probabilities and quantiles float64, confidence/model_version string.
    """
    from pipeline.db import read_df

    where, params = ["TRUE"], {}
    if region_ids is not None:
        ids = [int(r) for r in region_ids]
        if not ids:
            return pd.DataFrame()
        where.append("region_id = ANY(:ids)")
        params["ids"] = ids
    if issue_date is not None:
        where.append("issue_date = :d")
        params["d"] = pd.Timestamp(issue_date).date()
    df = read_df(f"SELECT * FROM forecasts WHERE {' AND '.join(where)} "
                 "ORDER BY region_id, issue_date, lead_week", params)
    df["region_id"] = df["region_id"].astype("int64")
    df["lead_week"] = df["lead_week"].astype("int64")
    for col in ("issue_date", "week_start", "week_end"):
        df[col] = pd.to_datetime(df[col]).astype("datetime64[ns]")
    for col in _FLOAT_COLS:
        df[col] = pd.to_numeric(df[col]).astype("float64")
    for col in ("confidence", "model_version"):
        df[col] = df[col].astype("string")
    return df
