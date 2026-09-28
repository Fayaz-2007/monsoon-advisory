"""Small shared helpers: cached downloads, slugs, day-of-year handling."""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from pipeline.config import get_settings

log = logging.getLogger(__name__)


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "unknown"


def normalize_name(value: str) -> str:
    """Case/space/diacritic-insensitive key: 'TAMIL NADU' == 'TamilNadu' == 'Tamil Nādu'."""
    ascii_ = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_.lower())


def download_cached(url: str, dest: Path, max_age_hours: float | None = None,
                    force: bool = False, retries: int = 3) -> Path:
    """Download ``url`` to ``dest`` unless a fresh-enough copy is already cached.

    ``max_age_hours=None`` means a cached file never expires.
    """
    settings = get_settings()
    if dest.exists() and dest.stat().st_size > 0 and not force:
        age_h = (time.time() - dest.stat().st_mtime) / 3600
        if max_age_hours is None or age_h < max_age_hours:
            log.info("Using cached %s (%.1f h old)", dest.name, age_h)
            return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            log.info("Downloading %s", url)
            resp = requests.get(url, timeout=settings.http_timeout_s,
                                headers={"User-Agent": settings.user_agent},
                                proxies=settings.proxies)
            resp.raise_for_status()
            if not resp.content:
                raise ValueError("empty response")
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.write_bytes(resp.content)
            tmp.replace(dest)
            return dest
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            log.warning("Download attempt %d/%d failed for %s: %s", attempt, retries, url, exc)
            time.sleep(2 * attempt)
    if dest.exists() and dest.stat().st_size > 0:
        log.warning("Falling back to stale cached copy of %s", dest.name)
        return dest
    raise RuntimeError(f"Could not download {url}: {last_exc}")


def as_date(value: object) -> date | None:
    """Coerce a DB/pandas scalar (date, datetime, Timestamp, str, NaT/None) to ``date``."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return pd.Timestamp(value).date()


def doy366(dates: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    """Day-of-year on a fixed 366-day calendar.

    Feb 29 is always day 60 and Mar 1 is always day 61, so calendar dates align
    across leap and non-leap years (Dec 31 is always 366).
    """
    idx = pd.DatetimeIndex(dates)
    doy = idx.dayofyear.to_numpy().copy()
    shift = (~idx.is_leap_year) & (idx.month > 2)
    doy[shift] += 1
    return doy
