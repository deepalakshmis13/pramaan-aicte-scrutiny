from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Notification, User


def send(db: Session, user_id: int, kind: str, title: str, body: str, link: str, application_id: int | None = None) -> None:
    db.add(Notification(user_id=user_id, kind=kind, title=title, body=body, link_path=link, application_id=application_id))


def to_institution(db: Session, institution_id: int, kind: str, title: str, body: str, link: str, application_id: int) -> None:
    for u in db.execute(select(User).where(User.institution_id == institution_id, User.role == "institution", User.is_active)).scalars():
        send(db, u.id, kind, title, body, link, application_id)


def to_officers(db: Session, app, kind: str, title: str, body: str, link: str) -> None:
    """Notify the assigned officer, or every active scrutiny officer when none is assigned yet."""
    if app.assigned_reviewer_id:
        send(db, app.assigned_reviewer_id, kind, title, body, link, app.id)
        return
    for u in db.execute(select(User).where(User.role == "reviewer", User.is_active)).scalars():
        send(db, u.id, kind, title, body, link, app.id)
