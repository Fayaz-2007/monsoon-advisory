"""SIMULATED delivery gateway (DELIVERY_MODE=simulated).

A broadcast stores one row per channel with the real formatted message and seeded target
counts for each funnel step (sent → delivered → read, with realistic drop-off). Progress is
a deterministic function of the time since the broadcast was created: every status read
advances the stored counters, so the DB always holds the latest state and a restart loses
nothing. To go live, replace ``_targets`` and ``progress`` with gateway callbacks
(SMS/WhatsApp delivery receipts, IVR call records) writing the same columns.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from app.config import get_app_settings
from app.db import fetch_all, fetch_one, to_json, tx
from app.delivery.channels import CHANNELS, format_message, sms_segments
from app.mock.farmers import CHANNEL_REACH

# Funnel rates per channel (MOCK): (sent | queued, delivered | sent, read | delivered).
# For IVR, "delivered" = call answered and "read" = listened to the end.
FUNNEL = {
    "app":      ((0.985, 0.998), (0.93, 0.97), (0.35, 0.50)),
    "sms":      ((0.970, 0.995), (0.90, 0.95), (0.50, 0.62)),
    "whatsapp": ((0.975, 0.995), (0.85, 0.92), (0.68, 0.80)),
    "ivr":      ((0.960, 0.990), (0.55, 0.68), (0.70, 0.82)),
}
# Fraction of the broadcast duration over which each step ramps up.
PHASES = {"sent": (0.05, 0.35), "delivered": (0.20, 0.65), "read": (0.45, 1.00)}

SIM_COMMENTS = {
    1: ["Very useful, thank you", "Delayed sowing as advised", "Clear message",
        "Drained the field in time", "Good to get this in Tamil", "Will follow this"],
    -1: ["Too late for my field", "Rain did not come here", "Need more detail for my village",
         "Could not understand the voice call"],
}


class DeliveryError(ValueError):
    pass


def _targets(recipients: int, channel: str, rng: random.Random) -> tuple[int, int, int]:
    (s0, s1), (d0, d1), (r0, r1) = FUNNEL[channel]
    sent = round(recipients * rng.uniform(s0, s1))
    delivered = round(sent * rng.uniform(d0, d1))
    read = round(delivered * rng.uniform(r0, r1))
    return sent, delivered, read


def _ramp(f: float, a: float, b: float) -> float:
    if f <= a:
        return 0.0
    if f >= b:
        return 1.0
    x = (f - a) / (b - a)
    return x * x * (3 - 2 * x)  # smoothstep


def progress(fraction: float, recipients: int, targets: tuple[int, int, int]) -> dict[str, Any]:
    """Counters at ``fraction`` (0 = just queued, ≥ 1 = finished) of the broadcast (pure)."""
    t_sent, t_del, t_read = targets
    sent = round(t_sent * _ramp(fraction, *PHASES["sent"]))
    delivered = min(sent, round(t_del * _ramp(fraction, *PHASES["delivered"])))
    read = min(delivered, round(t_read * _ramp(fraction, *PHASES["read"])))
    done = fraction >= 1.0
    failed = recipients - t_del if done else 0
    if done:
        status = "completed"
    elif fraction < PHASES["sent"][0]:
        status = "queued"
    elif fraction < PHASES["delivered"][0]:
        status = "sending"
    elif fraction < PHASES["read"][0]:
        status = "delivering"
    else:
        status = "reading"
    return {"queued": recipients, "sent": sent, "delivered": delivered, "read": read,
            "failed": failed, "status": status}


def create_broadcast(advisory_id: int, channels: list[str] | None = None,
                     actor: str | None = None) -> dict[str, Any]:
    channels = list(dict.fromkeys(channels or list(CHANNELS)))
    bad = [c for c in channels if c not in CHANNELS]
    if bad:
        raise DeliveryError(f"unknown channel(s) {bad}; use {list(CHANNELS)}")
    settings = get_app_settings()
    with tx() as conn:
        adv = fetch_one("SELECT * FROM advisories WHERE id = :id FOR UPDATE", {"id": advisory_id}, conn)
        if adv is None:
            raise LookupError(f"advisory {advisory_id} not found")
        if adv["status"] != "approved":
            raise DeliveryError(f"only approved advisories can be broadcast (status is "
                                f"'{adv['status']}')")
        bid = fetch_one(
            "INSERT INTO broadcasts (advisory_id, channels, delivery_mode, duration_s) "
            "VALUES (:a, :ch, :mode, :dur) RETURNING id",
            {"a": advisory_id, "ch": channels, "mode": settings.delivery_mode,
             "dur": settings.delivery_sim_seconds}, conn)["id"]
        total = 0
        for ch in channels:
            rng = random.Random(f"{advisory_id}|{bid}|{ch}")
            recipients = round(adv["farmers_targeted"] * CHANNEL_REACH[ch])
            t_sent, t_del, t_read = _targets(recipients, ch, rng)
            en, ta = format_message(adv, ch)
            fetch_all(
                "INSERT INTO broadcast_channels (broadcast_id, channel, content_en, content_ta, "
                "recipients, target_sent, target_delivered, target_read, queued) VALUES "
                "(:b, :ch, :en, :ta, :n, :ts, :td, :tr, :n) RETURNING id",
                {"b": bid, "ch": ch, "en": en, "ta": ta, "n": recipients, "ts": t_sent,
                 "td": t_del, "tr": t_read}, conn)
            total += recipients
        fetch_all("UPDATE broadcasts SET total_recipients = :t WHERE id = :id RETURNING id",
                  {"t": total, "id": bid}, conn)
        fetch_all("UPDATE advisories SET status = 'sent', updated_at = now() WHERE id = :id "
                  "RETURNING id", {"id": advisory_id}, conn)
        fetch_all("INSERT INTO advisory_events (advisory_id, action, actor, payload) VALUES "
                  "(:a, 'broadcast', :actor, CAST(:p AS jsonb)) RETURNING id",
                  {"a": advisory_id, "actor": actor or "reviewer",
                   "p": to_json({"broadcast_id": bid, "channels": channels,
                                 "recipients": total})}, conn)
    return get_status(bid)


def _simulated_feedback(conn, bc: dict[str, Any], adv: dict[str, Any], read_total: int) -> None:
    rng = random.Random(f"feedback|{bc['id']}")
    n = min(25, max(3, read_total // 200))
    p_up = 0.82 if adv["severity"] != "info" else 0.74
    chans = [c for c in bc["channels"] if c in ("whatsapp", "ivr", "app")] or bc["channels"]
    for _ in range(n):
        rating = 1 if rng.random() < p_up else -1
        comment = rng.choice(SIM_COMMENTS[rating]) if rng.random() < 0.4 else None
        fetch_all("INSERT INTO feedback (advisory_id, broadcast_id, region_id, channel, rating, "
                  "comment, simulated) VALUES (:a, :b, :r, :ch, :rt, :c, true) RETURNING id",
                  {"a": adv["id"], "b": bc["id"], "r": adv["region_id"], "ch": rng.choice(chans),
                   "rt": rating, "c": comment}, conn)


def get_status(broadcast_id: int) -> dict[str, Any]:
    """Advance the simulated counters to now, persist them, and return the broadcast state."""
    with tx() as conn:
        bc = fetch_one("SELECT *, EXTRACT(EPOCH FROM (now() - created_at)) AS elapsed_s "
                       "FROM broadcasts WHERE id = :id FOR UPDATE", {"id": broadcast_id}, conn)
        if bc is None:
            raise LookupError(f"broadcast {broadcast_id} not found")
        rows = fetch_all("SELECT * FROM broadcast_channels WHERE broadcast_id = :id ORDER BY id",
                         {"id": broadcast_id}, conn)
        fraction = float(bc["elapsed_s"]) / max(float(bc["duration_s"]), 0.1)
        if bc["status"] != "completed":
            for r in rows:
                p = progress(fraction, r["recipients"],
                             (r["target_sent"], r["target_delivered"], r["target_read"]))
                fetch_all("UPDATE broadcast_channels SET sent = :sent, delivered = :delivered, "
                          "read = :read, failed = :failed, status = :status, updated_at = now() "
                          "WHERE id = :id RETURNING id", {**p, "id": r["id"]}, conn)
                r.update(p)
            if fraction >= 1.0:
                fetch_all("UPDATE broadcasts SET status = 'completed', completed_at = now() "
                          "WHERE id = :id RETURNING id", {"id": broadcast_id}, conn)
                bc["status"] = "completed"
                adv = fetch_one("SELECT * FROM advisories WHERE id = :id", {"id": bc["advisory_id"]}, conn)
                _simulated_feedback(conn, bc, adv, sum(r["read"] for r in rows))
    totals = {k: sum(r[k] for r in rows) for k in ("queued", "sent", "delivered", "read", "failed")}
    channels = []
    for r in rows:
        channels.append({
            "channel": r["channel"], "status": r["status"], "recipients": r["recipients"],
            "sent": r["sent"], "delivered": r["delivered"], "read": r["read"], "failed": r["failed"],
            "delivery_rate": round(r["delivered"] / r["recipients"], 3) if r["recipients"] else 0.0,
            "read_rate": round(r["read"] / r["delivered"], 3) if r["delivered"] else 0.0,
            "content_en": r["content_en"], "content_ta": r["content_ta"],
            "chars_en": len(r["content_en"]), "chars_ta": len(r["content_ta"]),
            **({"sms_segments_en": sms_segments(r["content_en"]),
                "sms_segments_ta": sms_segments(r["content_ta"])} if r["channel"] == "sms" else {}),
        })
    return {
        "broadcast_id": bc["id"], "advisory_id": bc["advisory_id"], "status": bc["status"],
        "delivery_mode": bc["delivery_mode"], "created_at": bc["created_at"],
        "completed_at": bc.get("completed_at"),
        "progress": round(min(fraction, 1.0), 3), "duration_s": bc["duration_s"],
        "total_recipients": bc["total_recipients"], "totals": totals, "channels": channels,
        "as_of": datetime.now(timezone.utc),
    }


def list_broadcasts(limit: int = 50) -> list[dict[str, Any]]:
    return fetch_all(
        "SELECT b.id AS broadcast_id, b.advisory_id, b.status, b.channels, b.total_recipients, "
        "b.created_at, b.completed_at, a.district, a.crop, a.title_en, a.severity "
        "FROM broadcasts b JOIN advisories a ON a.id = b.advisory_id ORDER BY b.id DESC LIMIT :n",
        {"n": limit})
