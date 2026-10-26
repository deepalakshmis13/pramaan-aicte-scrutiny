from __future__ import annotations

from sqlalchemy import and_, not_, or_, select

from ..models import Application, Finding, User

OPEN_ISSUE = and_(Finding.is_issue.is_(True), Finding.status.notin_(["resolved", "verified"]), Finding.review_state != "dismissed")


def accessible_apps(user: User):
    """All submitted applications (drafts stay private to the institution)."""
    return select(Application).where(Application.status != "draft")


def has_filter(kind: str):
    sub = select(Finding.id).where(Finding.application_id == Application.id)
    m = {
        "missing": and_(OPEN_ISSUE, Finding.status == "missing"),
        "expired": and_(OPEN_ISSUE, Finding.status == "expired"),
        "mismatch": and_(OPEN_ISSUE, Finding.status == "mismatch"),
        "manual_review": and_(OPEN_ISSUE, Finding.status == "manual_review"),
        "pending_source": Finding.status.in_(["source_unavailable", "pending", "simulated"]),
        "anomaly": and_(OPEN_ISSUE, Finding.category.in_(["anomaly", "duplicate"])),
        "unreviewed": and_(OPEN_ISSUE, Finding.review_state == "unreviewed"),
    }
    cond = m.get(kind)
    if cond is None:
        return None
    return sub.where(cond).exists()


def search_cond(q: str):
    like = f"%{q.strip()}%"
    from ..models import Institution

    return or_(Application.reference.ilike(like), Application.institution.has(or_(Institution.name.ilike(like), Institution.permanent_id.ilike(like))))


__all__ = ["OPEN_ISSUE", "accessible_apps", "has_filter", "search_cond", "not_"]
