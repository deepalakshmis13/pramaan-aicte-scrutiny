from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, serialize
from ..config import settings
from ..db import get_db
from ..enums import APPLICATION_STATUSES, DECISION_OUTCOMES, DOCUMENT_TYPES, FINDING_CATEGORIES, NOTICE_STATUSES, RESULT_STATES
from ..models import ApplicationCategory, User, utcnow
from ..security import COOKIE_NAME, client_ip, create_token, get_current_user, login_limiter, verify_password

router = APIRouter(prefix="/api", tags=["auth"])


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    if not login_limiter.check(f"login:{ip}", settings.login_rate_limit_per_minute):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts. Wait a minute and try again.")
    user = db.execute(select(User).where(func.lower(User.email) == body.email.strip().lower())).scalar_one_or_none()
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        audit.record(db, "auth.login_failed", "user", user.id if user else "", summary="Failed sign-in attempt",
                     details={"email": body.email.strip().lower()[:80]}, ip=ip)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect")
    user.last_login_at = utcnow()
    audit.record(db, "auth.login", "user", user.id, actor=user, summary=f"{user.full_name} signed in", ip=ip)
    db.commit()
    response.set_cookie(COOKIE_NAME, create_token(user), httponly=True, samesite="lax", secure=settings.cookie_secure,
                        max_age=settings.token_minutes * 60, path="/")
    return {"user": serialize.user(user)}


@router.post("/auth/logout")
def logout(request: Request, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    audit.record(db, "auth.logout", "user", user.id, actor=user, summary=f"{user.full_name} signed out", ip=client_ip(request))
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request, db: Session = Depends(get_db)):
    """Session probe: returns user=null (200) when signed out, so the login page has no error noise."""
    from ..security import decode_token

    payload = decode_token(request.cookies.get(COOKIE_NAME, "") or "")
    user = db.get(User, int(payload["sub"])) if payload else None
    if not user or not user.is_active:
        return {"user": None, "session_minutes": settings.token_minutes}
    return {"user": serialize.user(user), "session_minutes": settings.token_minutes}


@router.get("/meta")
def meta(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cats = db.execute(select(ApplicationCategory).order_by(ApplicationCategory.id)).scalars().all()
    return {
        "application_statuses": APPLICATION_STATUSES, "result_states": RESULT_STATES, "finding_categories": FINDING_CATEGORIES,
        "document_types": DOCUMENT_TYPES, "notice_statuses": NOTICE_STATUSES, "decision_outcomes": DECISION_OUTCOMES,
        "categories": [{"id": c.id, "code": c.code, "name": c.name} for c in cats],
        "environment": settings.env,
    }
