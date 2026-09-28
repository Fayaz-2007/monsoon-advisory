"""Segment 2 tables (``forecasts``, ``model_skill``) and an idempotent upsert.

Plain DDL keeps Segment 2 out of Segment 1's SQLAlchemy metadata while still giving
``forecasts.region_id`` a real foreign key to ``regions``.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from psycopg2.extras import execute_values
from sqlalchemy import text

from pipeline.db import get_engine

DDL = [
    """
    CREATE TABLE IF NOT EXISTS forecasts (
        region_id     integer  NOT NULL REFERENCES regions(id) ON DELETE CASCADE,
        issue_date    date     NOT NULL,
        lead_week     smallint NOT NULL CHECK (lead_week BETWEEN 1 AND 4),
        week_start    date     NOT NULL,
        week_end      date     NOT NULL,
        p_below       real     NOT NULL CHECK (p_below  BETWEEN 0 AND 1),
        p_normal      real     NOT NULL CHECK (p_normal BETWEEN 0 AND 1),
        p_above       real     NOT NULL CHECK (p_above  BETWEEN 0 AND 1),
        q10_mm        real     NOT NULL,
        q50_mm        real     NOT NULL,
        q90_mm        real     NOT NULL,
        p_heavy       real     NOT NULL CHECK (p_heavy    BETWEEN 0 AND 1),
        p_dry_week    real     NOT NULL CHECK (p_dry_week BETWEEN 0 AND 1),
        confidence    text     NOT NULL CHECK (confidence IN ('High', 'Medium', 'Low')),
        model_version text     NOT NULL,
        created_at    timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (region_id, issue_date, lead_week)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_forecasts_issue_date ON forecasts (issue_date)",
    """
    CREATE TABLE IF NOT EXISTS model_skill (
        target        text     NOT NULL,
        lead_week     smallint NOT NULL,
        season        text     NOT NULL,
        metric        text     NOT NULL,
        model         text     NOT NULL,
        model_version text     NOT NULL,
        value         double precision,
        ci_low        double precision,
        ci_high       double precision,
        n_samples     integer,
        n_years       smallint,
        created_at    timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (target, lead_week, season, metric, model, model_version)
    )
    """,
]

FORECAST_COLS = [
    "region_id", "issue_date", "lead_week", "week_start", "week_end",
    "p_below", "p_normal", "p_above", "q10_mm", "q50_mm", "q90_mm",
    "p_heavy", "p_dry_week", "confidence", "model_version",
]
SKILL_COLS = [
    "target", "lead_week", "season", "metric", "model", "model_version",
    "value", "ci_low", "ci_high", "n_samples", "n_years",
]


def init_ml_tables() -> None:
    with get_engine().begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))


def _py(v: object) -> object:
    """numpy/pandas scalars → plain Python (NaN/NaT → None) for psycopg2."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT:
        return None
    if isinstance(v, np.generic):
        v = v.item()
        return None if isinstance(v, float) and np.isnan(v) else v
    if isinstance(v, pd.Timestamp):
        return v.date()
    return v


def upsert_rows(df: pd.DataFrame, table: str, pk_cols: Sequence[str]) -> int:
    """INSERT … ON CONFLICT (pk) DO UPDATE; ``created_at`` is refreshed on update.

    Re-running with the same rows leaves the same row set (idempotent). Returns rows written.
    """
    if df.empty:
        return 0
    df = df.drop_duplicates(subset=list(pk_cols), keep="last")
    cols = list(df.columns)
    updates = [f'"{c}" = EXCLUDED."{c}"' for c in cols if c not in pk_cols]
    updates.append("created_at = now()")
    sql = (f'INSERT INTO "{table}" ({", ".join(chr(34) + c + chr(34) for c in cols)}) VALUES %s '
           f'ON CONFLICT ({", ".join(pk_cols)}) DO UPDATE SET {", ".join(updates)}')
    rows = [tuple(_py(v) for v in rec) for rec in df.itertuples(index=False, name=None)]
    raw = get_engine().raw_connection()
    try:
        cur = raw.cursor()
        execute_values(cur, sql, rows, page_size=5000)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    return len(rows)


def upsert_forecasts(df: pd.DataFrame) -> int:
    return upsert_rows(df[FORECAST_COLS], "forecasts", ["region_id", "issue_date", "lead_week"])


def upsert_skill(df: pd.DataFrame) -> int:
    return upsert_rows(df[SKILL_COLS], "model_skill",
                       ["target", "lead_week", "season", "metric", "model", "model_version"])
