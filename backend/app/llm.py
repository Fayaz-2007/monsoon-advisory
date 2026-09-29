"""Optional Claude integration (LLM_API_KEY). Every caller has a template fallback, so the
backend behaves the same without a key, when the API errors, or when it times out."""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import AsyncIterator

from app.config import get_app_settings

log = logging.getLogger(__name__)

REPHRASE_SYSTEM = (
    "You rewrite crop advisories for smallholder farmers in Tamil Nadu. Rewrite the advisory "
    "in plain, friendly English a farmer with basic schooling understands, in at most 60 words. "
    "Keep every number, date, percentage, district and crop name exactly as given. Do not add "
    "advice, facts or numbers that are not in the original. Reply with the rewritten text only."
)

_cache: dict[str, str] = {}
_cache_lock = threading.Lock()


def enabled() -> bool:
    return get_app_settings().llm_enabled


def _client():
    import anthropic

    s = get_app_settings()
    return anthropic.Anthropic(api_key=s.llm_api_key, timeout=s.llm_timeout_s, max_retries=0)


def _async_client():
    import anthropic

    s = get_app_settings()
    return anthropic.AsyncAnthropic(api_key=s.llm_api_key, timeout=s.llm_timeout_s, max_retries=0)


def rephrase(text: str) -> str | None:
    """Simpler farmer-language version of ``text``, or None (caller keeps the template)."""
    if not enabled():
        return None
    key = hashlib.sha256(text.encode()).hexdigest()
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    try:
        s = get_app_settings()
        resp = _client().messages.create(
            model=s.llm_model, max_tokens=1024, system=REPHRASE_SYSTEM,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": text}],
        )
        if resp.stop_reason == "refusal":
            return None
        out = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not out or len(out) > 2 * len(text) + 200:
            return None
    except Exception as exc:  # noqa: BLE001 — any failure falls back to the template
        log.warning("LLM rephrase failed, using template: %s", exc)
        return None
    with _cache_lock:
        _cache[key] = out
    return out


async def stream_answer(system: str, question: str) -> AsyncIterator[str]:
    """Stream Claude's answer text. Raises on failure so the caller can fall back."""
    s = get_app_settings()
    async with _async_client().messages.stream(
        model=s.llm_model, max_tokens=4096, system=system,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": question}],
    ) as stream:
        async for text in stream.text_stream:
            yield text
