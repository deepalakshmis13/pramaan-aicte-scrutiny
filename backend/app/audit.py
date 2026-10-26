"""Append-only audit events with a hash chain.

Each event hashes its canonical content together with the previous event's hash,
so modification or deletion of an earlier row is detectable by `verify_chain`.
This is an integrity check for the prototype; it is not a claim of tamper-proofing
(a database superuser could rewrite the whole chain).
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import AuditEvent, User, utcnow

_SENSITIVE_KEYS = {"password", "password_hash", "token", "secret", "api_key"}


def _scrub(details: dict) -> dict:
    return {k: ("[redacted]" if k.lower() in _SENSITIVE_KEYS else v) for k, v in (details or {}).items()}


def _digest(ev: AuditEvent) -> str:
    payload = json.dumps(
        {
            "at": ev.created_at.isoformat(),
            "actor": ev.actor_id,
            "action": ev.action,
            "entity": f"{ev.entity_type}:{ev.entity_id}",
            "app": ev.application_id,
            "summary": ev.summary,
            "details": ev.details,
            "prev": ev.prev_hash,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def record(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: str | int = "",
    *,
    actor: User | None = None,
    application_id: int | None = None,
    summary: str = "",
    details: dict | None = None,
    ip: str = "",
) -> AuditEvent:
    # Serialise chain appends across concurrent transactions.
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(7311)"))
    prev = db.execute(select(AuditEvent.hash).order_by(AuditEvent.id.desc()).limit(1)).scalar()
    ev = AuditEvent(
        created_at=utcnow(),
        actor_id=actor.id if actor else None,
        actor_label=actor.full_name if actor else "system",
        actor_role=actor.role if actor else "system",
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        application_id=application_id,
        summary=summary,
        details=_scrub(details or {}),
        ip_address=ip,
        prev_hash=prev or "",
    )
    ev.hash = _digest(ev)
    db.add(ev)
    db.flush()
    return ev


def verify_chain(db: Session) -> dict:
    prev = ""
    count = 0
    for ev in db.execute(select(AuditEvent).order_by(AuditEvent.id).execution_options(populate_existing=True)).scalars():
        count += 1
        if ev.prev_hash != prev or _digest(ev) != ev.hash:
            return {"ok": False, "checked": count, "broken_at_event_id": ev.id}
        prev = ev.hash
    return {"ok": True, "checked": count, "broken_at_event_id": None}
