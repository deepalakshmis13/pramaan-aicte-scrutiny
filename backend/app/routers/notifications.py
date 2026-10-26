from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import serialize
from ..db import get_db
from ..models import Notification, User, utcnow
from ..security import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(unread: bool = False, limit: int = 50, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = db.execute(stmt.order_by(Notification.id.desc()).limit(min(limit, 200))).scalars().all()
    n_unread = db.execute(select(func.count(Notification.id)).where(Notification.user_id == user.id, Notification.read_at.is_(None))).scalar()
    return {"unread": n_unread, "items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link_path,
                                           "read": n.read_at is not None, "created_at": serialize.iso(n.created_at)} for n in rows]}


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if not n or n.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    if not n.read_at:
        n.read_at = utcnow()
        db.commit()
    return {"ok": True, "link": n.link_path}


@router.post("/read-all")
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None)).values(read_at=utcnow()))
    db.commit()
    return {"ok": True}
