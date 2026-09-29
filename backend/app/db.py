"""Database access for the backend: one engine, the backend's own tables, small helpers.

The engine uses the same DATABASE_URL as Segment 1. Its ``search_path`` is
``<APP_DB_SCHEMA>, public``: backend tables are created in APP_DB_SCHEMA (default
``public``; tests use a throwaway schema) while Segment 1/2 tables are found in ``public``.
The backend never writes to Segment 1/2 tables.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

import pandas as pd
from sqlalchemy import Connection, Engine, create_engine, make_url, text

from app.config import get_app_settings

_SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

DDL = [
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        key        text PRIMARY KEY,
        value      jsonb NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    # One row per computed context (issue date × forecast source × scenario).
    """
    CREATE TABLE IF NOT EXISTS hazard_runs (
        id                  serial PRIMARY KEY,
        issue_date          date NOT NULL,
        forecast_source     text NOT NULL,
        scenario            text NOT NULL DEFAULT 'none',
        forecast_issue_date date,
        model_version       text,
        observed_through    date,
        fingerprint         text NOT NULL,
        n_hazards           integer NOT NULL DEFAULT 0,
        computed_at         timestamptz NOT NULL DEFAULT now(),
        UNIQUE (issue_date, forecast_source, scenario)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hazards (
        id           serial PRIMARY KEY,
        run_id       integer NOT NULL REFERENCES hazard_runs(id) ON DELETE CASCADE,
        region_id    integer NOT NULL,
        district     text NOT NULL,
        hazard_type  text NOT NULL,
        subtype      text,
        severity     text NOT NULL CHECK (severity IN ('info', 'watch', 'warning')),
        probability  real NOT NULL CHECK (probability BETWEEN 0 AND 1),
        lead_week    smallint NOT NULL CHECK (lead_week BETWEEN 0 AND 4),
        window_start date,
        window_end   date,
        confidence   text NOT NULL,
        basis        text NOT NULL,
        why          text NOT NULL,
        evidence     jsonb NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_hazards_run ON hazards (run_id)",
    """
    CREATE TABLE IF NOT EXISTS advisories (
        id                 serial PRIMARY KEY,
        issue_date         date NOT NULL,
        forecast_source    text NOT NULL,
        scenario           text NOT NULL DEFAULT 'none',
        dedupe_key         text NOT NULL,
        region_id          integer NOT NULL,
        district           text NOT NULL,
        crop               text NOT NULL,
        season             text NOT NULL,
        stage              text NOT NULL,
        stage_group        text NOT NULL,
        hazard_type        text NOT NULL,
        hazard_subtype     text,
        hazard_probability real,
        hazard_lead_week   smallint,
        hazard_confidence  text,
        hazard_why         text,
        rule_id            text NOT NULL,
        severity           text NOT NULL CHECK (severity IN ('info', 'watch', 'warning')),
        title_en           text NOT NULL,
        title_ta           text NOT NULL,
        text_en            text NOT NULL,
        text_ta            text NOT NULL,
        action_en          text NOT NULL,
        action_ta          text NOT NULL,
        simple_text_en     text,
        rephrased_by       text NOT NULL DEFAULT 'template',
        tamil_reviewed     boolean NOT NULL DEFAULT false,
        source_note        text NOT NULL,
        farmers_targeted   integer NOT NULL DEFAULT 0,
        status             text NOT NULL DEFAULT 'draft'
                           CHECK (status IN ('draft', 'approved', 'rejected', 'superseded', 'sent')),
        edited             boolean NOT NULL DEFAULT false,
        reviewer           text,
        review_note        text,
        created_at         timestamptz NOT NULL DEFAULT now(),
        updated_at         timestamptz NOT NULL DEFAULT now(),
        approved_at        timestamptz
    )
    """,
    # At most one live (non-superseded) advisory per key.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_advisories_live ON advisories (dedupe_key) "
    "WHERE status <> 'superseded'",
    "CREATE INDEX IF NOT EXISTS ix_advisories_ctx ON advisories (issue_date, forecast_source, scenario)",
    "CREATE INDEX IF NOT EXISTS ix_advisories_status ON advisories (status)",
    """
    CREATE TABLE IF NOT EXISTS advisory_events (
        id          serial PRIMARY KEY,
        advisory_id integer NOT NULL REFERENCES advisories(id) ON DELETE CASCADE,
        action      text NOT NULL,
        actor       text,
        note        text,
        payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
        at          timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS broadcasts (
        id               serial PRIMARY KEY,
        advisory_id      integer NOT NULL REFERENCES advisories(id) ON DELETE CASCADE,
        channels         text[] NOT NULL,
        delivery_mode    text NOT NULL,
        status           text NOT NULL DEFAULT 'in_progress'
                         CHECK (status IN ('in_progress', 'completed')),
        total_recipients integer NOT NULL DEFAULT 0,
        duration_s       real NOT NULL,
        created_at       timestamptz NOT NULL DEFAULT now(),
        completed_at     timestamptz
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS broadcast_channels (
        id               serial PRIMARY KEY,
        broadcast_id     integer NOT NULL REFERENCES broadcasts(id) ON DELETE CASCADE,
        channel          text NOT NULL CHECK (channel IN ('app', 'sms', 'whatsapp', 'ivr')),
        content_en       text NOT NULL,
        content_ta       text NOT NULL,
        recipients       integer NOT NULL,
        target_sent      integer NOT NULL,
        target_delivered integer NOT NULL,
        target_read      integer NOT NULL,
        queued           integer NOT NULL,
        sent             integer NOT NULL DEFAULT 0,
        delivered        integer NOT NULL DEFAULT 0,
        read             integer NOT NULL DEFAULT 0,
        failed           integer NOT NULL DEFAULT 0,
        status           text NOT NULL DEFAULT 'queued'
                         CHECK (status IN ('queued', 'sending', 'delivering', 'reading', 'completed')),
        updated_at       timestamptz NOT NULL DEFAULT now(),
        UNIQUE (broadcast_id, channel)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS feedback (
        id           serial PRIMARY KEY,
        advisory_id  integer NOT NULL REFERENCES advisories(id) ON DELETE CASCADE,
        broadcast_id integer REFERENCES broadcasts(id) ON DELETE SET NULL,
        region_id    integer,
        channel      text,
        rating       smallint NOT NULL CHECK (rating IN (-1, 1)),
        comment      text,
        simulated    boolean NOT NULL DEFAULT false,
        created_at   timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_feedback_advisory ON feedback (advisory_id)",
]

APP_TABLES = ["feedback", "broadcast_channels", "broadcasts", "advisory_events", "advisories",
              "hazards", "hazard_runs", "app_settings"]


def app_schema() -> str:
    schema = get_app_settings().app_db_schema
    if not _SCHEMA_RE.match(schema):
        raise ValueError(f"APP_DB_SCHEMA {schema!r} is not a plain lower-case identifier")
    return schema


@lru_cache(maxsize=4)
def _engine_for(url: str, schema: str) -> Engine:
    search_path = f"{schema},public" if schema != "public" else "public"
    u = make_url(url)
    if u.host == "localhost":
        # On Windows "localhost" tries IPv6 first and costs seconds per new connection.
        u = u.set(host="127.0.0.1")
    return create_engine(u, pool_pre_ping=True, future=True, pool_size=10, max_overflow=10,
                         connect_args={"options": f"-csearch_path={search_path}"})


def get_engine() -> Engine:
    return _engine_for(get_app_settings().database_url, app_schema())


def init_app_tables() -> None:
    """Create the backend's schema and tables (idempotent). Never touches Segment 1/2 tables."""
    schema = app_schema()
    with get_engine().begin() as conn:
        if schema != "public":
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        for stmt in DDL:
            conn.execute(text(stmt))


@contextmanager
def tx() -> Iterator[Connection]:
    with get_engine().begin() as conn:
        yield conn


def _plain(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    return v


def fetch_all(sql: str, params: dict[str, Any] | None = None,
              conn: Connection | None = None) -> list[dict[str, Any]]:
    def run(c: Connection) -> list[dict[str, Any]]:
        res = c.execute(text(sql), params or {})
        return [{k: _plain(v) for k, v in row.items()} for row in res.mappings()]
    if conn is not None:
        return run(conn)
    with get_engine().connect() as c:
        return run(c)


def fetch_one(sql: str, params: dict[str, Any] | None = None,
              conn: Connection | None = None) -> dict[str, Any] | None:
    rows = fetch_all(sql, params, conn)
    return rows[0] if rows else None


def read_df(sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def execute(sql: str, params: dict[str, Any] | None = None,
            conn: Connection | None = None) -> Any:
    if conn is not None:
        return conn.execute(text(sql), params or {})
    with get_engine().begin() as c:
        return c.execute(text(sql), params or {})


def _json_default(o: object) -> Any:
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if hasattr(o, "item"):
        return o.item()
    return str(o)


def to_json(value: Any) -> str:
    return json.dumps(value, default=_json_default, ensure_ascii=False)


def get_setting(key: str, default: Any = None) -> Any:
    row = fetch_one("SELECT value FROM app_settings WHERE key = :k", {"k": key})
    return row["value"] if row else default


def set_setting(key: str, value: Any) -> None:
    execute("INSERT INTO app_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
            {"k": key, "v": to_json(value)})


def delete_setting(key: str) -> None:
    execute("DELETE FROM app_settings WHERE key = :k", {"k": key})
