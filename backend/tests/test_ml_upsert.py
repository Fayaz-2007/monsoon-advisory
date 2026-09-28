"""Forecast upserts are idempotent (needs the local database; skipped when it is down).

Uses issue date 1900-01-01 and model_version 'pytest' so real forecasts are never touched,
and deletes its rows afterwards.
"""

import pandas as pd
import pytest

from ml.schema import FORECAST_COLS, init_ml_tables, upsert_forecasts

TEST_DATE = pd.Timestamp("1900-01-01").date()


@pytest.fixture(scope="module")
def db():
    try:
        from pipeline.db import check_connection, read_df
        check_connection()
        init_ml_tables()
        rid = int(read_df("SELECT min(id) AS r FROM regions")["r"].iloc[0])
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database not available: {exc}")
    yield rid
    from pipeline.db import get_engine
    from sqlalchemy import text
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM forecasts WHERE issue_date = :d"), {"d": TEST_DATE})


def _rows(rid, p_below):
    rows = []
    for lead in (1, 2, 3, 4):
        start = pd.Timestamp(TEST_DATE) + pd.Timedelta(days=7 * (lead - 1) + 1)
        rows.append({"region_id": rid, "issue_date": TEST_DATE, "lead_week": lead,
                     "week_start": start.date(), "week_end": (start + pd.Timedelta(days=6)).date(),
                     "p_below": p_below, "p_normal": 0.3, "p_above": 0.7 - p_below,
                     "q10_mm": 0.0, "q50_mm": 5.0, "q90_mm": 30.0, "p_heavy": 0.02,
                     "p_dry_week": 0.4, "confidence": "Low", "model_version": "pytest"})
    return pd.DataFrame(rows)[FORECAST_COLS]


def _stored():
    from ml import load_forecasts
    return load_forecasts(issue_date=TEST_DATE)


def test_upsert_is_idempotent(db):
    df = _rows(db, 0.2)
    assert upsert_forecasts(df) == 4
    first = _stored()
    assert upsert_forecasts(df) == 4
    second = _stored()
    assert len(first) == len(second) == 4
    cols = [c for c in FORECAST_COLS if c != "created_at"]
    pd.testing.assert_frame_equal(first[cols], second[cols])


def test_upsert_updates_in_place(db):
    upsert_forecasts(_rows(db, 0.2))
    upsert_forecasts(_rows(db, 0.5))
    got = _stored()
    assert len(got) == 4
    assert (got["p_below"] == 0.5).all()
    assert got["region_id"].dtype == "int64" and str(got["issue_date"].dtype) == "datetime64[ns]"
