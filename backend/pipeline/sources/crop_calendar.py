"""Load the crop-calendar seed CSV into the ``crop_calendar`` table."""

from __future__ import annotations

import logging

import pandas as pd

from pipeline.config import get_settings
from pipeline.db import upsert_df

log = logging.getLogger(__name__)

REQUIRED_COLS = ["district", "crop", "season", "sowing_start_doy", "sowing_end_doy",
                 "stage_name", "stage_start_day", "stage_end_day"]


def read_crop_calendar() -> pd.DataFrame:
    settings = get_settings()
    path = settings.raw_dir / settings.crop_calendar_file
    if not path.exists():
        raise FileNotFoundError(f"Crop calendar seed not found: {path}")
    text_head = path.read_text(encoding="utf-8")[:500].upper()
    df = pd.read_csv(path, comment="#", skipinitialspace=True)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name} is missing columns: {missing}")
    df = df[REQUIRED_COLS].copy()
    for c in ("district", "crop", "season", "stage_name"):
        df[c] = df[c].astype(str).str.strip()
    for c in ("sowing_start_doy", "sowing_end_doy"):
        bad = ~df[c].between(1, 366)
        if bad.any():
            raise ValueError(f"{path.name}: {c} outside 1..366 in rows {list(df.index[bad])}")
    bad = df["stage_end_day"] < df["stage_start_day"]
    if bad.any():
        raise ValueError(f"{path.name}: stage_end_day < stage_start_day in rows {list(df.index[bad])}")
    df["state"] = settings.state_name
    df["is_sample"] = "SAMPLE" in text_head
    df["source"] = path.name
    return df


def load_crop_calendar() -> int:
    df = read_crop_calendar()
    if df["is_sample"].all():
        log.warning("Crop calendar %s is SAMPLE data - verify with State Agriculture Dept "
                    "before using in advisories", get_settings().crop_calendar_file)
    n = upsert_df(df, "crop_calendar",
                  pk_cols=["state", "district", "crop", "season", "stage_name"])
    log.info("Upserted %d crop-calendar rows", n)
    return n
