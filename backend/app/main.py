"""AgriVarsha backend — FastAPI app (Segments 3, 4, 5, 7).

Run from backend/:  uvicorn app.main:app --reload     (docs at http://127.0.0.1:8000/docs)
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import state
from app.api import routes_advisories, routes_chat, routes_data, routes_system
from app.config import APP_VERSION, get_app_settings
from app.db import init_app_tables

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


def _warm_up() -> None:
    try:
        from app.hazards.engine import ensure_context

        ctx = ensure_context()
        log.info("warm-up done: %s", ctx.as_dict())
    except Exception as exc:  # noqa: BLE001 — warm-up is best effort
        log.warning("warm-up failed (requests will compute on demand): %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        init_app_tables()
    except Exception as exc:  # noqa: BLE001 — re-raised with a hint
        raise RuntimeError("Cannot reach the database. Is PostgreSQL running (start_db.bat) "
                           "and DATABASE_URL in backend/.env correct?") from exc
    s = get_app_settings()
    # Warm the connection pool, caches and today's hazards/advisories in the background so
    # the first request does not pay for them.
    threading.Thread(target=_warm_up, name="warm-up", daemon=True).start()
    log.info("AgriVarsha backend up: DEMO_MODE=%s FORECAST_SOURCE=%s scenario=%s LLM=%s",
             s.demo_mode, state.get_source(), state.get_scenario(),
             "on" if s.llm_enabled else "off (templates)")
    yield


app = FastAPI(
    title="AgriVarsha API",
    version=APP_VERSION,
    description="Monsoon hazard detection, crop advisories and (simulated) delivery for 38 "
                "Tamil Nadu districts. Mocks are labelled; see docs/contracts/api.md.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_app_settings().cors_origin_list,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (routes_data, routes_advisories, routes_system, routes_chat):
    app.include_router(r.router)


@app.get("/", include_in_schema=False)
def root():
    return {"name": "AgriVarsha API", "version": APP_VERSION, "docs": "/docs",
            "contract": "docs/contracts/api.md"}
