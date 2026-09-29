"""Runtime switches that the API can change without a restart.

* forecast source (mock | real): starts from FORECAST_SOURCE in .env, switchable at runtime
  via POST /api/settings/forecast-source. Also stored in app_settings for visibility.
* active demo scenario: stored in app_settings so it survives a restart.
"""

from __future__ import annotations

import threading
from datetime import date
from typing import Literal

from app.config import get_app_settings, today
from app.db import delete_setting, get_setting, set_setting

Source = Literal["mock", "real"]
_lock = threading.Lock()
_source: Source | None = None
_scenario: str | None = None
_scenario_loaded = False


def get_source() -> Source:
    global _source
    with _lock:
        if _source is None:
            _source = get_app_settings().forecast_source
        return _source


def set_source(source: Source) -> None:
    global _source
    if source not in ("mock", "real"):
        raise ValueError(source)
    with _lock:
        _source = source
    set_setting("forecast_source", source)


def get_scenario() -> str | None:
    global _scenario, _scenario_loaded
    with _lock:
        if not _scenario_loaded:
            val = get_setting("scenario")
            _scenario = val.get("name") if isinstance(val, dict) else None
            _scenario_loaded = True
        return _scenario


def set_scenario(name: str | None) -> None:
    global _scenario, _scenario_loaded
    with _lock:
        _scenario = name
        _scenario_loaded = True
    if name:
        set_setting("scenario", {"name": name})
    else:
        delete_setting("scenario")


def scenario_key() -> str:
    """Scenario label stored with hazards/advisories. Scenarios only apply to mock forecasts."""
    sc = get_scenario()
    return sc if (sc and get_source() == "mock") else "none"


def default_date() -> date:
    """Issue date used when a request has no ?date=: the active scenario's demo date, else today."""
    from app.mock.scenarios import SCENARIOS

    sc = get_scenario()
    if sc and get_source() == "mock" and SCENARIOS[sc].demo_date:
        return SCENARIOS[sc].demo_date  # type: ignore[return-value]
    return today()


def reset_runtime() -> None:
    """Back to .env defaults (used by /api/demo/reset and tests)."""
    global _source
    with _lock:
        _source = get_app_settings().forecast_source
    set_scenario(None)
    delete_setting("forecast_source")
