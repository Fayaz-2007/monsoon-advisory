"""Database engine, sessions, PostGIS setup, bulk upserts and run tracking."""

from __future__ import annotations

import io
import json
import logging
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import Boolean, Date, Integer, SmallInteger

from pipeline.config import get_settings
from pipeline.models import Base

log = logging.getLogger(__name__)

COPY_CHUNK_ROWS = 250_000


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True, future=True)


def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create the PostGIS extension and all tables (idempotent)."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.create_all(engine)
    log.debug("Database schema ensured")


def _safe_url() -> str:
    """DATABASE_URL with the password masked, for log/error messages."""
    return get_engine().url.render_as_string(hide_password=True)


def check_connection() -> None:
    """Raise a friendly error if the database is unreachable."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — re-raised with context
        raise RuntimeError(
            f"Cannot connect to the database at {_safe_url()}. Is PostgreSQL running and "
            "is DATABASE_URL in backend/.env correct? (Windows: run start_db.bat)"
        ) from exc


def _prepare_frame(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    """Coerce dtypes so the CSV COPY stream is accepted by PostgreSQL."""
    table = Base.metadata.tables[table_name]
    out = df.copy()
    for col in out.columns:
        coltype = table.c[col].type
        if isinstance(coltype, Date):
            out[col] = pd.to_datetime(out[col]).dt.strftime("%Y-%m-%d")
        elif isinstance(coltype, (Integer, SmallInteger)):
            out[col] = pd.array(np.round(pd.to_numeric(out[col])), dtype="Int64")
        elif isinstance(coltype, Boolean):
            out[col] = out[col].map({True: "t", False: "f"}).astype("object")
    return out


def upsert_df(
    df: pd.DataFrame,
    table_name: str,
    pk_cols: Sequence[str],
    update_cols: Sequence[str] | None = None,
    touch_updated_at: bool = False,
) -> int:
    """Idempotent bulk upsert: COPY into a temp table, then INSERT … ON CONFLICT DO UPDATE.

    Returns the number of rows written (inserted or updated).
    """
    if df.empty:
        return 0
    df = df.drop_duplicates(subset=list(pk_cols), keep="last")
    cols = list(df.columns)
    update_cols = [c for c in (update_cols or cols) if c not in pk_cols]
    col_list = ", ".join(f'"{c}"' for c in cols)
    set_parts = [f'"{c}" = EXCLUDED."{c}"' for c in update_cols]
    if touch_updated_at:
        set_parts.append("updated_at = now()")
    conflict = ", ".join(f'"{c}"' for c in pk_cols)
    action = f"DO UPDATE SET {', '.join(set_parts)}" if set_parts else "DO NOTHING"

    total = 0
    raw = get_engine().raw_connection()
    try:
        cur = raw.cursor()
        for start in range(0, len(df), COPY_CHUNK_ROWS):
            chunk = _prepare_frame(df.iloc[start:start + COPY_CHUNK_ROWS], table_name)
            tmp = f"tmp_{table_name}_{uuid.uuid4().hex[:8]}"
            cur.execute(
                f'CREATE TEMP TABLE {tmp} AS SELECT {col_list} FROM "{table_name}" WITH NO DATA'
            )
            buf = io.StringIO()
            chunk.to_csv(buf, index=False, header=False, na_rep="")
            buf.seek(0)
            cur.copy_expert(f"COPY {tmp} ({col_list}) FROM STDIN WITH (FORMAT csv, NULL '')", buf)
            cur.execute(
                f'INSERT INTO "{table_name}" ({col_list}) SELECT {col_list} FROM {tmp} '
                f"ON CONFLICT ({conflict}) {action}"
            )
            total += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            cur.execute(f"DROP TABLE {tmp}")
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    return total


def read_df(sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


# ---------------------------------------------------------------------------
# pipeline_runs tracking
# ---------------------------------------------------------------------------


def mark_stale_runs(max_age_hours: int = 2) -> int:
    """Mark 'running' rows older than ``max_age_hours`` as 'interrupted' (killed/crashed runs)."""
    with get_engine().begin() as conn:
        n = conn.execute(text(
            "UPDATE pipeline_runs SET status = 'interrupted', finished_at = now(), "
            "message = coalesce(message || ' | ', '') || 'process ended without finishing' "
            "WHERE status = 'running' AND started_at < now() - make_interval(hours => :h)"),
            {"h": max_age_hours}).rowcount
    if n:
        log.warning("Marked %d stale pipeline_runs row(s) as interrupted", n)
    return n


class StageSkipped(Exception):
    """Raise inside a tracked stage to record status='skipped' without failing the run."""


@dataclass
class RunHandle:
    id: int
    stage: str
    rows_written: int = 0
    messages: list[str] = field(default_factory=list)
    status: str = "success"

    def add_rows(self, n: int) -> None:
        self.rows_written += int(n)

    def note(self, msg: str) -> None:
        self.messages.append(msg)


def _json_default(o: object) -> str:
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return str(o)


@contextmanager
def track_run(stage: str, params: dict[str, Any] | None = None) -> Iterator[RunHandle]:
    """Record a stage in pipeline_runs: running → success | skipped | failed."""
    engine = get_engine()
    with engine.begin() as conn:
        run_id = conn.execute(
            text("INSERT INTO pipeline_runs (stage, status, params) "
                 "VALUES (:s, 'running', CAST(:p AS JSONB)) RETURNING id"),
            {"s": stage, "p": json.dumps(params or {}, default=_json_default)},
        ).scalar_one()
    handle = RunHandle(id=run_id, stage=stage)

    def _finish(status: str, message: str) -> None:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE pipeline_runs SET finished_at = now(), status = :st, "
                     "rows_written = :n, message = :m WHERE id = :id"),
                {"st": status, "n": handle.rows_written, "m": message[:4000], "id": run_id},
            )

    try:
        yield handle
    except StageSkipped as exc:
        handle.note(str(exc))
        _finish("skipped", " | ".join(handle.messages))
        log.warning("[%s] skipped: %s", stage, exc)
        return
    except BaseException as exc:
        handle.note(f"{type(exc).__name__}: {exc}")
        _finish("failed", " | ".join(handle.messages))
        raise
    _finish(handle.status, " | ".join(handle.messages))
