"""KPI aggregation for GET /api/overview."""

from __future__ import annotations

from typing import Any

from app import segment1
from app.db import fetch_all, fetch_one
from app.hazards.engine import Context, list_hazards
from app.hazards.rules import SEVERITY_ORDER
from app.mock.farmers import district_total


def district_risk(hazards: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Per district: worst severity, its hazard, and all hazard types present."""
    out: dict[int, dict[str, Any]] = {}
    for h in hazards:
        cur = out.get(h["region_id"])
        key = (SEVERITY_ORDER[h["severity"]], h["probability"])
        if cur is None:
            out[h["region_id"]] = cur = {"severity": h["severity"], "top_hazard": h["hazard_type"],
                                         "top_probability": h["probability"],
                                         "hazard_types": [], "_key": key}
        elif key > cur["_key"]:
            cur.update(severity=h["severity"], top_hazard=h["hazard_type"],
                       top_probability=h["probability"], _key=key)
        if h["hazard_type"] not in cur["hazard_types"]:
            cur["hazard_types"].append(h["hazard_type"])
    for v in out.values():
        v.pop("_key")
    return out


def build_overview(ctx: Context) -> dict[str, Any]:
    regions = segment1.regions()
    hazards = list_hazards(ctx.run_id)
    risk = district_risk(hazards)
    alerts = {rid: r for rid, r in risk.items() if r["severity"] in ("watch", "warning")}
    by_type: dict[str, dict[str, int]] = {}
    for h in hazards:
        t = by_type.setdefault(h["hazard_type"], {"districts": 0, "info": 0, "watch": 0, "warning": 0})
        t["districts"] += 1
        t[h["severity"]] += 1

    adv = fetch_all(
        "SELECT status, count(*) AS n, coalesce(sum(farmers_targeted), 0) AS farmers "
        "FROM advisories WHERE issue_date = :d AND forecast_source = :s AND scenario = :sc "
        "GROUP BY status", {"d": ctx.issue_date, "s": ctx.source, "sc": ctx.scenario})
    adv_counts = {r["status"]: int(r["n"]) for r in adv}
    adv_farmers = {r["status"]: int(r["farmers"]) for r in adv}
    sev = fetch_all(
        "SELECT severity, count(*) AS n FROM advisories WHERE issue_date = :d AND "
        "forecast_source = :s AND scenario = :sc AND status <> 'superseded' GROUP BY severity",
        {"d": ctx.issue_date, "s": ctx.source, "sc": ctx.scenario})

    deliv = fetch_one(
        "SELECT count(DISTINCT b.id) AS broadcasts, coalesce(sum(c.recipients), 0) AS recipients, "
        "coalesce(sum(c.sent), 0) AS sent, coalesce(sum(c.delivered), 0) AS delivered, "
        "coalesce(sum(c.read), 0) AS read FROM broadcasts b "
        "JOIN broadcast_channels c ON c.broadcast_id = b.id "
        "JOIN advisories a ON a.id = b.advisory_id "
        "WHERE a.issue_date = :d AND a.forecast_source = :s AND a.scenario = :sc",
        {"d": ctx.issue_date, "s": ctx.source, "sc": ctx.scenario})
    fb = fetch_one("SELECT count(*) AS total, count(*) FILTER (WHERE rating = 1) AS up "
                   "FROM feedback")

    fc = ctx.forecasts
    w1 = fc[fc["lead_week"] == 1]
    farmers_total = sum(district_total(n, a) for n, a in zip(regions["name"], regions["area_km2"]))
    farmers_at_risk = sum(district_total(n, a) for n, a, rid in
                          zip(regions["name"], regions["area_km2"], regions["id"]) if rid in alerts)
    last_rain = segment1.last_rainfall_date()
    names = dict(zip(regions["id"], regions["name"]))
    top = sorted(alerts.items(), key=lambda kv: (-SEVERITY_ORDER[kv[1]["severity"]],
                                                  -kv[1]["top_probability"]))[:8]
    return {
        "context": ctx.as_dict(),
        "districts": {"total": len(regions), "with_alerts": len(alerts),
                      "warning": sum(r["severity"] == "warning" for r in risk.values()),
                      "watch": sum(r["severity"] == "watch" for r in risk.values()),
                      "info_only": sum(r["severity"] == "info" for r in risk.values())},
        "hazards": {"total": len(hazards), "by_type": by_type},
        "advisories": {
            "by_status": {s: adv_counts.get(s, 0) for s in ("draft", "approved", "rejected", "sent", "superseded")},
            "pending_review": adv_counts.get("draft", 0),
            "by_severity": {r["severity"]: int(r["n"]) for r in sev},
            "farmers_covered_by_sent": adv_farmers.get("sent", 0),
        },
        "farmers": {"registered_total": farmers_total, "in_alert_districts": farmers_at_risk,
                    "source": "mock"},
        "delivery": {
            "broadcasts": int(deliv["broadcasts"]), "recipients": int(deliv["recipients"]),
            "sent": int(deliv["sent"]), "delivered": int(deliv["delivered"]), "read": int(deliv["read"]),
            "delivery_rate": round(deliv["delivered"] / deliv["recipients"], 3) if deliv["recipients"] else None,
            "read_rate": round(deliv["read"] / deliv["delivered"], 3) if deliv["delivered"] else None,
            "mode": "simulated",
        },
        "feedback": {"total": int(fb["total"]), "positive_rate":
                     round(fb["up"] / fb["total"], 3) if fb["total"] else None},
        "forecast_week1": {
            "mean_q50_mm": round(float(w1["q50_mm"].mean()), 1) if len(w1) else None,
            "districts_above_normal_favoured": int((w1["p_above"] >= 0.5).sum()),
            "districts_below_normal_favoured": int((w1["p_below"] >= 0.5).sum()),
            "confidence_counts": {k: int(v) for k, v in fc["confidence"].value_counts().items()},
        },
        "data_freshness": {"last_rainfall_date": last_rain,
                           "rainfall_lag_days": (ctx.issue_date - last_rain).days if last_rain else None,
                           "observed_through": ctx.observed_through},
        "top_risk_districts": [
            {"region_id": rid, "district": names[rid], **r} for rid, r in top],
    }
