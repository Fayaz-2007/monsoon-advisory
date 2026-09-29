"""Advisory review queue, broadcast and feedback."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.advisory import review
from app.api.common import context_or_error, district_or_404
from app.db import fetch_all, fetch_one
from app.delivery import feedback as fb
from app.delivery import simulator
from app.delivery.channels import CHANNELS, preview

router = APIRouter(prefix="/api", tags=["advisories"])

Status = Literal["draft", "approved", "rejected", "superseded", "sent"]
LIST_COLS = ("id, issue_date, forecast_source, scenario, region_id, district, crop, season, stage, "
             "stage_group, hazard_type, hazard_subtype, hazard_probability, hazard_lead_week, "
             "hazard_confidence, hazard_why, rule_id, severity, title_en, title_ta, text_en, "
             "text_ta, action_en, action_ta, simple_text_en, rephrased_by, tamil_reviewed, "
             "source_note, farmers_targeted, status, edited, reviewer, review_note, created_at, "
             "updated_at, approved_at")


class ApproveBody(BaseModel):
    reviewer: str | None = Field(None, examples=["officer.madurai"])
    note: str | None = None


class EditBody(BaseModel):
    title_en: str | None = None
    title_ta: str | None = None
    text_en: str | None = None
    text_ta: str | None = None
    action_en: str | None = None
    action_ta: str | None = None
    severity: Literal["info", "watch", "warning"] | None = None
    tamil_reviewed: bool | None = None
    reviewer: str | None = None
    note: str | None = None


class RejectBody(BaseModel):
    reviewer: str | None = None
    reason: str | None = Field(None, examples=["Duplicate of yesterday's message"])


class BroadcastBody(BaseModel):
    channels: list[Literal["app", "sms", "whatsapp", "ivr"]] = Field(
        default_factory=lambda: list(CHANNELS))
    reviewer: str | None = None


class FeedbackBody(BaseModel):
    advisory_id: int
    rating: str | int = Field(..., description="'up' / 'down' (or 1 / -1, 👍 / 👎)", examples=["up"])
    comment: str | None = None
    channel: Literal["app", "sms", "whatsapp", "ivr"] | None = None
    broadcast_id: int | None = None


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (review.NotFound, LookupError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except (review.InvalidTransition, simulator.DeliveryError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except fb.FeedbackError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/advisories")
def list_advisories(status: Status | None = None,
                    date: date | None = Query(None, description="Issue date; default current context"),
                    district: str | None = None,
                    crop: str | None = None,
                    severity: Literal["info", "watch", "warning"] | None = None,
                    hazard_type: str | None = None,
                    all_contexts: bool = Query(False, description="Ignore date/source/scenario"),
                    limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """Advisories (Segment 4). Default: the current context, superseded ones hidden unless
    ``status=superseded``. Ordered warning → watch → info, then by farmers reached."""
    where, params = [], {}
    ctx = None
    if not all_contexts:
        ctx = context_or_error(date)
        where += ["issue_date = :d", "forecast_source = :s", "scenario = :sc"]
        params.update(d=ctx.issue_date, s=ctx.source, sc=ctx.scenario)
    if status:
        where.append("status = :status")
        params["status"] = status
    else:
        where.append("status <> 'superseded'")
    if district:
        where.append("region_id = :rid")
        params["rid"] = district_or_404(district)["id"]
    for col, val in (("crop", crop), ("severity", severity), ("hazard_type", hazard_type)):
        if val:
            where.append(f"{col} = :{col}")
            params[col] = val
    w = " AND ".join(where) or "TRUE"
    total = fetch_one(f"SELECT count(*) AS n FROM advisories WHERE {w}", params)["n"]
    counts = fetch_all(f"SELECT status, count(*) AS n FROM advisories WHERE "
                       f"{' AND '.join(x for x in where if not x.startswith('status')) or 'TRUE'} "
                       f"GROUP BY status", params)
    rows = fetch_all(
        f"SELECT {LIST_COLS} FROM advisories WHERE {w} ORDER BY CASE severity WHEN 'warning' "
        f"THEN 0 WHEN 'watch' THEN 1 ELSE 2 END, farmers_targeted DESC, id "
        f"LIMIT :limit OFFSET :offset", {**params, "limit": limit, "offset": offset})
    return {"context": ctx.as_dict() if ctx else None, "total": total, "limit": limit,
            "offset": offset, "status_counts": {r["status"]: r["n"] for r in counts},
            "advisories": rows}


@router.get("/advisories/{advisory_id}")
def get_advisory(advisory_id: int):
    """One advisory with its audit trail, channel previews and broadcasts."""
    adv = _wrap(review.get_advisory, advisory_id)
    adv["channel_preview"] = preview(adv)
    adv["broadcasts"] = fetch_all("SELECT id AS broadcast_id, status, channels, total_recipients, "
                                  "created_at, completed_at FROM broadcasts WHERE advisory_id = :a "
                                  "ORDER BY id", {"a": advisory_id})
    return adv


@router.post("/advisories/{advisory_id}/approve")
def approve_advisory(advisory_id: int, body: ApproveBody | None = None):
    body = body or ApproveBody()
    return _wrap(review.approve, advisory_id, body.reviewer, body.note)


@router.post("/advisories/{advisory_id}/edit")
def edit_advisory(advisory_id: int, body: EditBody):
    changes = body.model_dump(exclude={"reviewer", "note"}, exclude_none=True)
    return _wrap(review.edit, advisory_id, changes, body.reviewer, body.note)


@router.post("/advisories/{advisory_id}/reject")
def reject_advisory(advisory_id: int, body: RejectBody | None = None):
    body = body or RejectBody()
    return _wrap(review.reject, advisory_id, body.reviewer, body.reason)


@router.post("/broadcast/{advisory_id}", tags=["delivery"])
def broadcast(advisory_id: int, body: BroadcastBody | None = None):
    """Send an APPROVED advisory to the chosen channels (SIMULATED gateway). Returns the
    initial status; poll GET /api/broadcast/{id}/status."""
    body = body or BroadcastBody()
    return _wrap(simulator.create_broadcast, advisory_id, list(body.channels), body.reviewer)


@router.get("/broadcast/{broadcast_id}/status", tags=["delivery"])
def broadcast_status(broadcast_id: int):
    return _wrap(simulator.get_status, broadcast_id)


@router.get("/broadcasts", tags=["delivery"])
def list_broadcasts(limit: int = Query(50, ge=1, le=500)):
    return {"broadcasts": simulator.list_broadcasts(limit)}


@router.post("/feedback", tags=["delivery"], status_code=201)
def post_feedback(body: FeedbackBody):
    return _wrap(fb.add_feedback, body.advisory_id, body.rating, body.comment, body.channel,
                 body.broadcast_id)


@router.get("/feedback/summary", tags=["delivery"])
def feedback_summary(advisory_id: int | None = None, include_simulated: bool = True):
    return fb.summary(advisory_id, include_simulated)
