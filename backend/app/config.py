"""Backend settings (Segments 3, 4, 5, 7).

Values come from environment variables or ``backend/.env`` (same file as Segment 1).
Every mock sits behind one of the switches below, so a real source can replace it later:

* ``FORECAST_SOURCE``   mock | real  — forecasts from the mock generator or Segment 2's table
* ``FARMER_COUNT_SOURCE`` mock       — farmer registry (only mock exists today)
* ``DELIVERY_MODE``     simulated    — SMS / WhatsApp / IVR gateway (only simulated exists today)
* ``LLM_API_KEY``       optional     — rephrasing and chat; templates are used without it
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from pipeline.config import BACKEND_DIR

APP_VERSION = "0.1.0"
REAL_MODEL_VERSION = "s2-lgbm-20260929-0304"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str = "postgresql+psycopg2://monsoon_app@localhost:5432/monsoon"
    # Schema for the backend's own tables. Segment 1/2 tables are always read from `public`.
    app_db_schema: str = "public"

    demo_mode: bool = True
    # Pin "today" for a reproducible demo (blank = the real current date).
    demo_today: date | None = None

    forecast_source: Literal["mock", "real"] = "mock"
    mock_seed: int = 42
    farmer_count_source: Literal["mock"] = "mock"
    delivery_mode: Literal["simulated"] = "simulated"
    # Seconds a simulated broadcast takes to go queued → sent → delivered → read.
    delivery_sim_seconds: float = 8.0

    llm_api_key: str | None = None
    llm_model: str = "claude-opus-5-5"
    llm_timeout_s: float = 20.0

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Real model version to report when the forecasts table has none.
    real_model_version: str = REAL_MODEL_VERSION

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key and self.llm_api_key.strip())


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    return AppSettings()


def today() -> date:
    s = get_app_settings()
    return s.demo_today or date.today()
