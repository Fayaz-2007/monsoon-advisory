"""API flow tests against the local PostgreSQL (Segment 1/2 tables read-only).

The backend's own tables go to a throwaway schema (APP_DB_SCHEMA=agrivarsha_test) that is
dropped afterwards, so the demo data in ``public`` is never touched. Skipped when the
database is unreachable.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date

import pytest

TEST_SCHEMA = "agrivarsha_test"


@pytest.fixture(scope="module")
def client():
    os.environ["APP_DB_SCHEMA"] = TEST_SCHEMA
    os.environ["FORECAST_SOURCE"] = "mock"
    os.environ["DELIVERY_SIM_SECONDS"] = "1.5"
    os.environ["LLM_API_KEY"] = ""
    from app.config import get_app_settings

    get_app_settings.cache_clear()
    from sqlalchemy import text

    from app import db, state
    try:
        with db.get_engine().connect() as conn:
            conn.execute(text("SELECT 1 FROM public.regions LIMIT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unavailable: {exc}")
    with db.get_engine().begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
    db.init_app_tables()
    state.reset_runtime()
    from fastapi.testclient import TestClient

    from app.hazards.engine import clear_memo
    from app.main import app
    clear_memo()
    with TestClient(app) as c:
        yield c
    state.reset_runtime()
    clear_memo()
    with db.get_engine().begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
    for k in ("APP_DB_SCHEMA", "FORECAST_SOURCE", "DELIVERY_SIM_SECONDS", "LLM_API_KEY"):
        os.environ.pop(k, None)
    get_app_settings.cache_clear()


def test_tables_live_in_test_schema(client):
    from app.db import fetch_one
    row = fetch_one("SELECT count(*) AS n FROM information_schema.tables WHERE table_schema = :s "
                    "AND table_name = 'advisories'", {"s": TEST_SCHEMA})
    assert row["n"] == 1


def test_districts_geojson_real_boundaries(client):
    r = client.get("/api/districts", params={"tolerance": 0.02})
    assert r.status_code == 200
    gj = r.json()
    assert gj["type"] == "FeatureCollection" and len(gj["features"]) == 38
    f = gj["features"][0]
    assert f["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert {"name", "slug", "risk", "centroid"} <= set(f["properties"])


def test_rainfall_is_real_segment1_data(client):
    r = client.get("/api/rainfall/chennai", params={"days": 10, "end": "2026-09-28"})
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 10 and body["end"] == "2026-09-28"
    from app.db import fetch_one
    row = fetch_one("SELECT round(sum(rain_mm)::numeric, 1) AS s FROM rainfall_daily WHERE "
                    "region_id = 3 AND date BETWEEN '2026-09-19' AND '2026-09-28'")
    assert body["total_mm"] == pytest.approx(float(row["s"]), abs=0.15)


def test_forecast_hazards_overview(client):
    r = client.get("/api/forecast/madurai", params={"date": "2026-09-29"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["forecast"]) == 4 and body["context"]["forecast_source"] == "mock"
    assert client.get("/api/forecast/atlantis").status_code == 404
    hz = client.get("/api/hazards", params={"date": "2026-09-29"}).json()
    assert hz["count"] > 0 and all(h["why"] for h in hz["hazards"])
    ov = client.get("/api/overview", params={"date": "2026-09-29"}).json()
    assert ov["districts"]["total"] == 38 and ov["advisories"]["pending_review"] > 0


def test_approval_broadcast_feedback_flow(client):
    adv = client.get("/api/advisories", params={"status": "draft", "date": "2026-09-29",
                                                "limit": 5}).json()["advisories"]
    assert adv, "expected auto-drafted advisories"
    a = adv[0]
    assert a["tamil_reviewed"] is False and "SAMPLE" in a["source_note"]
    aid = a["id"]
    # broadcasting a draft is refused
    assert client.post(f"/api/broadcast/{aid}").status_code == 409
    # edit keeps it a draft and records the change
    r = client.post(f"/api/advisories/{aid}/edit", json={"action_en": "Edited action.",
                                                         "reviewer": "tester"})
    assert r.status_code == 200 and r.json()["edited"] is True and r.json()["status"] == "draft"
    r = client.post(f"/api/advisories/{aid}/approve", json={"reviewer": "tester"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert client.post(f"/api/advisories/{aid}/approve").status_code == 409
    r = client.post(f"/api/broadcast/{aid}", json={"channels": ["sms", "whatsapp", "ivr", "app"]})
    assert r.status_code == 200
    b = r.json()
    bid = b["broadcast_id"]
    assert b["status"] == "in_progress" and b["total_recipients"] > 0
    sms = next(c for c in b["channels"] if c["channel"] == "sms")
    assert sms["chars_en"] <= 160 and "Edited action." in sms["content_en"]
    time.sleep(1.8)
    done = client.get(f"/api/broadcast/{bid}/status").json()
    assert done["status"] == "completed"
    t = done["totals"]
    assert t["queued"] >= t["sent"] >= t["delivered"] >= t["read"] > 0
    assert t["failed"] == t["queued"] - t["delivered"]
    assert client.get(f"/api/advisories/{aid}").json()["status"] == "sent"
    events = [e["action"] for e in client.get(f"/api/advisories/{aid}").json()["events"]]
    assert events[:1] == ["drafted"] and {"edited", "approved", "broadcast"} <= set(events)
    # farmer feedback
    r = client.post("/api/feedback", json={"advisory_id": aid, "rating": "up", "comment": "Useful",
                                           "channel": "whatsapp"})
    assert r.status_code == 201 and r.json()["rating"] == 1
    assert client.post("/api/feedback", json={"advisory_id": aid, "rating": "meh"}).status_code == 422
    s = client.get("/api/feedback/summary", params={"advisory_id": aid}).json()
    assert s["totals"]["real"] == 1 and s["totals"]["simulated"] > 0
    real_only = client.get("/api/feedback/summary",
                           params={"advisory_id": aid, "include_simulated": False}).json()
    assert real_only["totals"]["total"] == 1


def test_reject_flow(client):
    adv = client.get("/api/advisories", params={"status": "draft", "date": "2026-09-29",
                                                "limit": 1}).json()["advisories"][0]
    r = client.post(f"/api/advisories/{adv['id']}/reject", json={"reason": "not relevant"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert client.post(f"/api/advisories/{adv['id']}/approve").status_code == 409
    assert client.post("/api/advisories/999999/approve").status_code == 404


def test_scenarios_drive_the_pipeline(client):
    r = client.post("/api/demo/scenario/false_onset_trap")
    assert r.status_code == 200
    body = r.json()
    types = {(h["district"], h["hazard_type"]) for h in body["focus_hazards"]}
    assert ("Madurai", "false_onset") in types
    titles = [a["title_en"] for a in body["focus_advisories"]]
    assert any(t.startswith("Don't sow") for t in titles)

    body = client.post("/api/demo/scenario/ne_monsoon_surge").json()
    heavy = {h["district"] for h in body["focus_hazards"]
             if h["hazard_type"] == "heavy_rain" and h["severity"] == "warning"}
    assert heavy == {"Chennai", "Cuddalore", "Nagapattinam"}

    body = client.post("/api/demo/scenario/mid_season_break").json()
    assert body["context"]["issue_date"] == "2026-08-14"
    gn = [a for a in body["focus_advisories"] if a["crop"] == "groundnut"]
    assert gn and all(a["stage"] == "flowering_pegging" for a in gn)
    assert any(a["hazard_type"] == "dry_spell" and a["severity"] == "warning" for a in gn)

    body = client.post("/api/demo/scenario/normal_season").json()
    forecast_alerts = [h for h in client.get("/api/hazards").json()["hazards"]
                       if h["basis"] == "forecast" and h["severity"] != "info"]
    assert forecast_alerts == []

    assert client.post("/api/demo/scenario/zombie_apocalypse").status_code == 404
    r = client.post("/api/demo/reset").json()
    assert r["scenario"] is None and r["source"] == "mock"


def test_forecast_source_switch_end_to_end(client):
    r = client.post("/api/settings/forecast-source", json={"source": "real"},
                    params={"date": "2026-09-29"})
    assert r.status_code == 200
    body = r.json()
    ctx = body["context"]
    assert body["source"] == "real" and ctx["forecast_source"] == "real"
    assert ctx["model_version"] == "s2-lgbm-20260929-0304"
    assert ctx["forecast_issue_date"] == "2026-09-28"  # latest Segment 2 run ≤ requested date
    fc = client.get("/api/forecast/chennai", params={"date": "2026-09-29"}).json()
    w1 = fc["forecast"][0]
    assert w1["model_version"] == "s2-lgbm-20260929-0304"
    assert w1["p_below"] == pytest.approx(0.3933, abs=1e-4)  # contract example row
    adv = client.get("/api/advisories", params={"date": "2026-09-29"}).json()
    assert adv["context"]["forecast_source"] == "real"
    assert all(a["forecast_source"] == "real" for a in adv["advisories"])
    # a scenario forces mock again
    assert client.post("/api/demo/scenario/normal_season").json()["switched_source_to_mock"] is True
    client.post("/api/demo/reset")
    r = client.post("/api/settings/forecast-source", json={"source": "sideways"})
    assert r.status_code == 422


def test_pipeline_health_and_model_skill(client):
    h = client.get("/api/pipeline/health").json()
    assert h["table_counts"]["regions"] == 38 and h["table_counts"]["rainfall_daily"] > 400000
    assert h["recent_runs"] and h["quality"]["summary"]["pass"] >= 1
    s = client.get("/api/model/skill", params={"target": "tercile", "season": "ALL"}).json()
    assert s["model_version"] == "s2-lgbm-20260929-0304"
    row = next(r for r in s["rows"] if r["lead_week"] == 1 and r["metric"] == "rpss"
               and r["model"] == "lgbm")
    assert row["ci_low"] < row["value"] < row["ci_high"]


def _sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_chat_streams_grounded_answer(client):
    r = client.post("/api/chat", json={"message": "Will it rain in Madurai next week?",
                                       "date": "2026-09-29"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = _sse(r.text)
    assert events[0][0] == "meta" and events[0][1]["district"] == "Madurai"
    assert events[0][1]["mode"] == "template"
    assert events[-1][0] == "done"
    answer = "".join(d["text"] for e, d in events if e == "token")
    assert answer == events[-1][1]["answer"]
    fc = client.get("/api/forecast/madurai", params={"date": "2026-09-29"}).json()["forecast"]
    assert f"median {round(fc[0]['q50_mm'], 1)} mm" in answer  # quotes the API's numbers
    r = client.post("/api/chat", json={"message": "Which districts have alerts?"})
    assert "district(s) have alerts" in _sse(r.text)[-1][1]["answer"] or \
        "No watch or warning" in _sse(r.text)[-1][1]["answer"]


def test_mock_is_deterministic_through_api(client):
    a = client.get("/api/forecast/salem", params={"date": "2026-10-05"}).json()["forecast"]
    b = client.get("/api/forecast/salem", params={"date": "2026-10-05"}).json()["forecast"]
    c = client.get("/api/forecast/salem", params={"date": "2026-10-06"}).json()["forecast"]
    assert a == b and a != c
    assert date.fromisoformat(a[0]["week_start"]) == date(2026, 10, 6)
