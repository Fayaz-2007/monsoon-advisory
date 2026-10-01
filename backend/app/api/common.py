"""Shared helpers for the API routers."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException

from app import segment1
from app.forecasts import NoForecastError
from app.hazards.engine import Context, ensure_context


def clean(v: Any) -> Any:
    """numpy / pandas values → JSON-friendly Python (NaN → None)."""
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.date() if v.hour == 0 and v.minute == 0 else v.to_pydatetime()
    return v


def records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [clean(r) for r in df.to_dict("records")]


def context_or_error(d: date | None) -> Context:
    try:
        return ensure_context(d)
    except NoForecastError as exc:
        raise HTTPException(404, str(exc)) from exc


def district_or_404(key: str) -> dict[str, Any]:
    from app.blocks import resolve_block

    reg = segment1.resolve_district(key)
    if reg is None:
        reg = resolve_block(key)  # MOCK Madurai blocks (demo)
    if reg is None:
        raise HTTPException(404, f"Unknown district {key!r}. Use a name, slug (e.g. 'chennai') "
                                 "or id from GET /api/districts.")
    return clean(reg)


FORECAST_FIELDS = ["lead_week", "week_start", "week_end", "p_below", "p_normal", "p_above",
                   "q10_mm", "q50_mm", "q90_mm", "p_heavy", "p_dry_week", "confidence",
                   "model_version"]


def forecast_rows(ctx: Context, region_id: int) -> list[dict[str, Any]]:
    from app.blocks import is_block_id

    src = ctx.block_forecasts if is_block_id(region_id) else ctx.forecasts
    if src.empty:
        return []
    df = src[src["region_id"] == region_id].sort_values("lead_week")
    return records(df[FORECAST_FIELDS])
