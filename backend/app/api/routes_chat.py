"""POST /api/chat — Server-Sent Events stream of a grounded answer."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import chat, llm
from app.api.common import context_or_error, district_or_404
from app.db import to_json

router = APIRouter(prefix="/api", tags=["chat"])
log = logging.getLogger(__name__)


class ChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000,
                         examples=["Should I sow groundnut in Madurai this week?"])
    district: str | None = Field(None, description="Optional; otherwise detected in the message")
    date: dt.date | None = None


def sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {to_json(data) if not isinstance(data, str) else json.dumps(data)}\n\n"


async def _answer_stream(body: ChatBody) -> AsyncIterator[str]:
    def prepare():
        ctx = context_or_error(body.date)
        district = district_or_404(body.district) if body.district else chat.find_district(body.message)
        return ctx, district, chat.build_facts(ctx, district)

    try:
        ctx, district, facts = await run_in_threadpool(prepare)
    except Exception as exc:  # noqa: BLE001 — report as an SSE error event
        yield sse("error", {"detail": getattr(exc, "detail", str(exc))})
        return
    mode = "llm" if llm.enabled() else "template"
    yield sse("meta", {"mode": mode, "intent": chat.detect_intent(body.message),
                       "district": district["name"] if district else None,
                       "context": ctx.as_dict(), "sources": chat.facts_sources(facts)})
    if mode == "llm":
        sent_any = False
        try:
            async for text in llm.stream_answer(chat.llm_system(facts), body.message):
                sent_any = True
                yield sse("token", {"text": text})
            yield sse("done", {"mode": "llm"})
            return
        except Exception as exc:  # noqa: BLE001 — fall back to the template answer
            log.warning("chat LLM failed, using template: %s", exc)
            if sent_any:
                yield sse("token", {"text": "\n\n[Model unavailable; showing the standard answer]\n"})
            mode = "template_fallback"
    answer = chat.template_answer(body.message, facts)
    for piece in re.findall(r"\S+\s*", answer):
        yield sse("token", {"text": piece})
        await asyncio.sleep(0.008)
    yield sse("done", {"mode": mode, "answer": answer})


@router.post("/chat")
async def chat_endpoint(body: ChatBody):
    """Streams ``text/event-stream`` events: ``meta`` (context, sources, mode), then
    ``token`` chunks (``{"text": ...}``), then ``done``. ``error`` on failure."""
    return StreamingResponse(_answer_stream(body), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
