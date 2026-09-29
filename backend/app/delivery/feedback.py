"""Farmer feedback store: 👍 / 👎 with an optional comment, per advisory."""

from __future__ import annotations

from typing import Any

from app.db import fetch_all, fetch_one, tx


class FeedbackError(ValueError):
    pass


def parse_rating(rating: Any) -> int:
    r = str(rating).strip().lower()
    if r in ("up", "1", "+1", "👍", "thumbs_up", "yes", "true"):
        return 1
    if r in ("down", "-1", "👎", "thumbs_down", "no", "false"):
        return -1
    raise FeedbackError("rating must be 'up' or 'down' (or 1 / -1)")


def add_feedback(advisory_id: int, rating: Any, comment: str | None = None,
                 channel: str | None = None, broadcast_id: int | None = None) -> dict[str, Any]:
    r = parse_rating(rating)
    adv = fetch_one("SELECT id, region_id FROM advisories WHERE id = :id", {"id": advisory_id})
    if adv is None:
        raise LookupError(f"advisory {advisory_id} not found")
    comment = (comment or "").strip()[:1000] or None
    with tx() as conn:
        return fetch_one(
            "INSERT INTO feedback (advisory_id, broadcast_id, region_id, channel, rating, comment) "
            "VALUES (:a, :b, :r, :ch, :rt, :c) RETURNING id, advisory_id, broadcast_id, channel, "
            "rating, comment, simulated, created_at",
            {"a": advisory_id, "b": broadcast_id, "r": adv["region_id"], "ch": channel, "rt": r,
             "c": comment}, conn)


def _agg(group_sql: str, where: str, params: dict) -> list[dict[str, Any]]:
    return fetch_all(
        f"SELECT {group_sql} AS key, count(*) AS total, "
        f"count(*) FILTER (WHERE f.rating = 1) AS up, count(*) FILTER (WHERE f.rating = -1) AS down, "
        f"round(avg((f.rating + 1) / 2.0), 3) AS positive_rate "
        f"FROM feedback f JOIN advisories a ON a.id = f.advisory_id WHERE {where} "
        f"GROUP BY 1 ORDER BY total DESC", params)


def summary(advisory_id: int | None = None, include_simulated: bool = True) -> dict[str, Any]:
    where, params = ["TRUE"], {}
    if advisory_id is not None:
        where.append("f.advisory_id = :a")
        params["a"] = advisory_id
    if not include_simulated:
        where.append("NOT f.simulated")
    w = " AND ".join(where)
    tot = fetch_one(
        f"SELECT count(*) AS total, count(*) FILTER (WHERE rating = 1) AS up, "
        f"count(*) FILTER (WHERE rating = -1) AS down, "
        f"count(*) FILTER (WHERE simulated) AS simulated, "
        f"count(*) FILTER (WHERE NOT simulated) AS \"real\", "
        f"count(*) FILTER (WHERE comment IS NOT NULL) AS with_comment "
        f"FROM feedback f WHERE {w}", params)
    tot["positive_rate"] = round(tot["up"] / tot["total"], 3) if tot["total"] else None
    recent = fetch_all(
        f"SELECT f.id, f.advisory_id, a.district, a.crop, a.hazard_type, f.channel, f.rating, "
        f"f.comment, f.simulated, f.created_at FROM feedback f JOIN advisories a ON "
        f"a.id = f.advisory_id WHERE {w} AND f.comment IS NOT NULL ORDER BY f.id DESC LIMIT 10",
        params)
    return {
        "totals": tot,
        "by_hazard_type": _agg("a.hazard_type", w, params),
        "by_district": _agg("a.district", w, params),
        "by_channel": _agg("coalesce(f.channel, 'unknown')", w, params),
        "by_advisory": _agg("a.id", w, params)[:20],
        "recent_comments": recent,
        "note": "Rows with simulated=true come from the delivery simulator (MOCK farmer responses).",
    }
