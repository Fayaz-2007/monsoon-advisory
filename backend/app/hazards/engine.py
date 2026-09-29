"""Hazard engine: observed rain (Segment 1) + forecasts (mock or Segment 2) → ``hazards`` table.

``ensure_context(date)`` is the single entry point used by the API and the seed script. It
computes hazards for (issue date, forecast source, scenario), stores them, and — when the
hazard set differs from what was stored — triggers advisory auto-drafting.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app import segment1, state
from app.db import execute, fetch_all, fetch_one, to_json, tx
from app.forecasts import ForecastMeta, get_forecasts
from app.hazards.rules import SEVERITY_ORDER, Hazard, detect_all

OBS_DAYS = 30
_MEMO_TTL_S = 30.0


@dataclass
class Context:
    issue_date: date
    source: str
    scenario: str
    run_id: int
    meta: ForecastMeta
    observed_through: date | None
    forecasts: pd.DataFrame
    changed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "issue_date": self.issue_date, "forecast_source": self.source,
            "scenario": self.scenario, "forecast_issue_date": self.meta.forecast_issue_date,
            "model_version": self.meta.model_version, "observed_through": self.observed_through,
            "note": self.meta.note, "hazard_run_id": self.run_id,
        }


_lock = threading.RLock()
_memo: dict[tuple, tuple[float, Context]] = {}


def _clean(v: Any) -> Any:
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, pd.Timestamp):
        return v.date()
    return v


def compute_hazards(issue_date: date, forecasts: pd.DataFrame) -> tuple[list[dict[str, Any]], date | None]:
    """Run the rules for every district. Returns hazard dicts (with region info) and the last
    observed date used."""
    regions = segment1.regions()
    obs = segment1.observed_daily(issue_date, OBS_DAYS)
    feats = segment1.latest_features(issue_date - timedelta(days=1)).set_index("region_id")
    observed_through = obs["date"].max() if not obs.empty else None
    obs_by_region = {rid: list(zip(g["date"], g["rain_mm"])) for rid, g in obs.groupby("region_id")}
    fc_by_region = {rid: [{k: _clean(v) for k, v in row.items()} for row in g.to_dict("records")]
                    for rid, g in forecasts.groupby("region_id")}
    out: list[dict[str, Any]] = []
    for reg in regions.itertuples():
        f = feats.loc[reg.id] if reg.id in feats.index else None
        anom = float(f["anomaly_7d_pct"]) if f is not None and pd.notna(f["anomaly_7d_pct"]) else None
        wet = int(f["wet_days_last_7"]) if f is not None and pd.notna(f["wet_days_last_7"]) else None
        hz = detect_all(obs_by_region.get(reg.id, []), fc_by_region.get(reg.id, []), issue_date,
                        anom, wet)
        for h in hz:
            d = h.as_dict()
            d.update(region_id=int(reg.id), district=reg.name)
            out.append(d)
    out.sort(key=lambda h: (-SEVERITY_ORDER[h["severity"]], -h["probability"], h["district"]))
    return out, observed_through


def fingerprint(hazards: list[dict[str, Any]]) -> str:
    keys = sorted(f"{h['region_id']}|{h['hazard_type']}|{h['subtype']}|{h['lead_week']}|"
                  f"{h['severity']}|{round(h['probability'], 2)}|{h['confidence']}" for h in hazards)
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()[:16]


def _store(issue_date: date, source: str, scenario: str, meta: ForecastMeta,
           observed_through: date | None, hazards: list[dict[str, Any]]) -> tuple[int, bool]:
    fp = fingerprint(hazards)
    with tx() as conn:
        prev = fetch_one("SELECT id, fingerprint FROM hazard_runs WHERE issue_date = :d AND "
                         "forecast_source = :s AND scenario = :sc FOR UPDATE",
                         {"d": issue_date, "s": source, "sc": scenario}, conn)
        if prev and prev["fingerprint"] == fp:
            return prev["id"], False
        if prev:
            run_id = prev["id"]
            execute("DELETE FROM hazards WHERE run_id = :r", {"r": run_id}, conn)
            fetch_all("UPDATE hazard_runs SET fingerprint = :fp, n_hazards = :n, "
                      "forecast_issue_date = :fid, model_version = :mv, observed_through = :ot, "
                      "computed_at = now() WHERE id = :id RETURNING id",
                      {"fp": fp, "n": len(hazards), "fid": meta.forecast_issue_date,
                       "mv": meta.model_version, "ot": observed_through, "id": run_id}, conn)
        else:
            run_id = fetch_one(
                "INSERT INTO hazard_runs (issue_date, forecast_source, scenario, forecast_issue_date, "
                "model_version, observed_through, fingerprint, n_hazards) VALUES "
                "(:d, :s, :sc, :fid, :mv, :ot, :fp, :n) RETURNING id",
                {"d": issue_date, "s": source, "sc": scenario, "fid": meta.forecast_issue_date,
                 "mv": meta.model_version, "ot": observed_through, "fp": fp, "n": len(hazards)},
                conn)["id"]
        for h in hazards:
            fetch_all(
                "INSERT INTO hazards (run_id, region_id, district, hazard_type, subtype, severity, "
                "probability, lead_week, window_start, window_end, confidence, basis, why, evidence) "
                "VALUES (:run, :rid, :district, :type, :subtype, :sev, :p, :lead, :ws, :we, :conf, "
                ":basis, :why, CAST(:ev AS jsonb)) RETURNING id",
                {"run": run_id, "rid": h["region_id"], "district": h["district"],
                 "type": h["hazard_type"], "subtype": h["subtype"], "sev": h["severity"],
                 "p": h["probability"], "lead": h["lead_week"], "ws": h["window_start"],
                 "we": h["window_end"], "conf": h["confidence"], "basis": h["basis"],
                 "why": h["why"], "ev": to_json(h["evidence"])}, conn)
    return run_id, True


def ensure_context(issue_date: date | None = None, force: bool = False) -> Context:
    """Compute (or reuse) hazards for the current source/scenario and auto-draft advisories."""
    issue_date = issue_date or state.default_date()
    source = state.get_source()
    scenario = state.scenario_key()
    key = (issue_date, source, scenario)
    with _lock:
        hit = _memo.get(key)
        if hit and not force and time.monotonic() - hit[0] < _MEMO_TTL_S:
            return hit[1]
        forecasts, meta = get_forecasts(issue_date, source, scenario)
        hazards, observed_through = compute_hazards(issue_date, forecasts)
        run_id, changed = _store(issue_date, source, scenario, meta, observed_through, hazards)
        ctx = Context(issue_date, source, scenario, run_id, meta, observed_through, forecasts, changed)
        if changed:
            from app.advisory.engine import draft_advisories
            draft_advisories(ctx)
        _memo[key] = (time.monotonic(), ctx)
        return ctx


def clear_memo() -> None:
    with _lock:
        _memo.clear()


def list_hazards(run_id: int, district_id: int | None = None,
                 hazard_type: str | None = None) -> list[dict[str, Any]]:
    where, params = ["run_id = :r"], {"r": run_id}
    if district_id is not None:
        where.append("region_id = :rid")
        params["rid"] = district_id
    if hazard_type:
        where.append("hazard_type = :t")
        params["t"] = hazard_type
    return fetch_all(
        f"SELECT id, region_id, district, hazard_type, subtype, severity, probability, lead_week, "
        f"window_start, window_end, confidence, basis, why, evidence FROM hazards "
        f"WHERE {' AND '.join(where)} ORDER BY CASE severity WHEN 'warning' THEN 0 "
        f"WHEN 'watch' THEN 1 ELSE 2 END, probability DESC, district", params)
