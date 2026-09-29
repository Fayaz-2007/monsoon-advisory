# AgriVarsha backend — Segments 3 (hazards), 4 (advisories), 5 (API), 7 (delivery)

FastAPI service on top of Segment 1 (`pipeline/`, observed data) and Segment 2 (`ml/`,
forecasts). The frontend contract is [`docs/contracts/api.md`](../../docs/contracts/api.md).

```bash
cd backend
python -m app.seed               # create backend tables, draft today's advisories
python -m app.seed --scenarios   # also precompute the 4 demo scenarios
uvicorn app.main:app --reload    # http://127.0.0.1:8000/docs
pytest tests -k app_             # backend tests (DB tests use a throwaway schema)
```

## What is real and what is mocked

| Part | Status | Switch |
| --- | --- | --- |
| Districts, boundaries, observed rainfall, climatology, crop calendar | **real** (Segment 1) | — |
| Model skill, pipeline runs, quality report | **real** (Segment 1/2) | — |
| Forecasts | mock generator by default, or Segment 2 `forecasts` | `FORECAST_SOURCE=mock\|real`, `POST /api/settings/forecast-source` |
| Hazard rules, advisory rules, review workflow, audit trail, API | **real logic** | — |
| Farmer counts per district × crop | mock (`app/mock/farmers.py`) | `FARMER_COUNT_SOURCE=mock` |
| SMS / WhatsApp / IVR gateway, farmer responses | simulated (`app/delivery/simulator.py`) | `DELIVERY_MODE=simulated` |
| Plain-language rephrasing, chat answers | templates; Claude when `LLM_API_KEY` is set | `LLM_API_KEY` |

## Layout

```
app/
  config.py, state.py      settings (.env) and runtime switches (source, scenario)
  db.py                    engine (search_path <APP_DB_SCHEMA>,public), backend DDL
  segment1.py              read-only access to Segment 1 tables
  forecasts.py             mock | real forecast switch (same schema)
  mock/                    generator.py, scenarios.py, farmers.py   (MOCK)
  hazards/                 rules.py (pure, unit-tested), engine.py (→ hazards table)
  advisory/                stages.py, rules.py (EN+TA table), engine.py (auto-draft), review.py
  delivery/                channels.py, simulator.py (SIMULATED), feedback.py
  api/                     routers; chat.py + llm.py for /api/chat
  seed.py, main.py
```

## Backend tables (never touches Segment 1/2 tables)

`app_settings`, `hazard_runs`, `hazards`, `advisories`, `advisory_events` (audit trail),
`broadcasts`, `broadcast_channels`, `feedback`.

## Data flow

`ensure_context(date)` = forecasts (mock/real) + last 30 days of observed rain → hazard
rules → `hazards` (fingerprinted). When the fingerprint changes, advisories are auto-drafted
(`status=draft`): crop stage from `crop_calendar` × hazard → rule → EN/TA text with the
hazard's numbers; one advisory per district × crop (the most severe hazard wins). A human
approves / edits / rejects; approved advisories are broadcast (simulated) and farmers' 👍/👎
land in `feedback`.
