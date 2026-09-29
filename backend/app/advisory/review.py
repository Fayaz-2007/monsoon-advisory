"""Human review of drafted advisories: approve / edit / reject, with an audit trail.

Allowed transitions
* approve: draft → approved
* edit:    draft | approved | rejected → draft (edited=true; approved ones need re-approval)
* reject:  draft | approved → rejected
* (broadcast, in app.delivery): approved → sent
"""

from __future__ import annotations

from typing import Any

from app.db import fetch_all, fetch_one, to_json, tx

EDITABLE_FIELDS = ("title_en", "title_ta", "text_en", "text_ta", "action_en", "action_ta",
                   "severity", "tamil_reviewed")


class NotFound(LookupError):
    pass


class InvalidTransition(ValueError):
    pass


def _get_for_update(conn, advisory_id: int) -> dict[str, Any]:
    row = fetch_one("SELECT * FROM advisories WHERE id = :id FOR UPDATE", {"id": advisory_id}, conn)
    if row is None:
        raise NotFound(f"advisory {advisory_id} not found")
    return row


def _event(conn, advisory_id: int, action: str, actor: str | None, note: str | None,
           payload: dict | None = None) -> None:
    fetch_all("INSERT INTO advisory_events (advisory_id, action, actor, note, payload) VALUES "
              "(:a, :act, :actor, :note, CAST(:p AS jsonb)) RETURNING id",
              {"a": advisory_id, "act": action, "actor": actor or "reviewer", "note": note,
               "p": to_json(payload or {})}, conn)


def get_advisory(advisory_id: int) -> dict[str, Any]:
    row = fetch_one("SELECT * FROM advisories WHERE id = :id", {"id": advisory_id})
    if row is None:
        raise NotFound(f"advisory {advisory_id} not found")
    row["events"] = fetch_all("SELECT action, actor, note, payload, at FROM advisory_events "
                              "WHERE advisory_id = :id ORDER BY id", {"id": advisory_id})
    return row


def approve(advisory_id: int, reviewer: str | None = None, note: str | None = None) -> dict[str, Any]:
    with tx() as conn:
        row = _get_for_update(conn, advisory_id)
        if row["status"] != "draft":
            raise InvalidTransition(f"cannot approve an advisory with status '{row['status']}'")
        fetch_all("UPDATE advisories SET status = 'approved', reviewer = :r, review_note = :n, "
                  "approved_at = now(), updated_at = now() WHERE id = :id RETURNING id",
                  {"r": reviewer, "n": note, "id": advisory_id}, conn)
        _event(conn, advisory_id, "approved", reviewer, note)
    return get_advisory(advisory_id)


def edit(advisory_id: int, changes: dict[str, Any], reviewer: str | None = None,
         note: str | None = None) -> dict[str, Any]:
    changes = {k: v for k, v in changes.items() if k in EDITABLE_FIELDS and v is not None}
    if not changes:
        raise InvalidTransition(f"nothing to edit; editable fields: {', '.join(EDITABLE_FIELDS)}")
    if "severity" in changes and changes["severity"] not in ("info", "watch", "warning"):
        raise InvalidTransition("severity must be info, watch or warning")
    with tx() as conn:
        row = _get_for_update(conn, advisory_id)
        if row["status"] not in ("draft", "approved", "rejected"):
            raise InvalidTransition(f"cannot edit an advisory with status '{row['status']}'")
        before = {k: row[k] for k in changes}
        sets = ", ".join(f"{k} = :{k}" for k in changes)
        fetch_all(f"UPDATE advisories SET {sets}, status = 'draft', edited = true, reviewer = :r, "
                  f"approved_at = NULL, updated_at = now() WHERE id = :id RETURNING id",
                  {**changes, "r": reviewer, "id": advisory_id}, conn)
        _event(conn, advisory_id, "edited", reviewer, note,
               {"before": before, "after": changes, "previous_status": row["status"]})
    return get_advisory(advisory_id)


def reject(advisory_id: int, reviewer: str | None = None, reason: str | None = None) -> dict[str, Any]:
    with tx() as conn:
        row = _get_for_update(conn, advisory_id)
        if row["status"] not in ("draft", "approved"):
            raise InvalidTransition(f"cannot reject an advisory with status '{row['status']}'")
        fetch_all("UPDATE advisories SET status = 'rejected', reviewer = :r, review_note = :n, "
                  "updated_at = now() WHERE id = :id RETURNING id",
                  {"r": reviewer, "n": reason, "id": advisory_id}, conn)
        _event(conn, advisory_id, "rejected", reviewer, reason)
    return get_advisory(advisory_id)
