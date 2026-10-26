"""Authentication, session cookies, CSRF guard, rate limiting and authorization helpers."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Application, User

COOKIE_NAME = "pramaan_session"
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.token_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


class RateLimiter:
    """Sliding-window in-memory limiter (per process). Adequate for the prototype."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_s: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = RateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account unavailable")
    # CSRF mitigation: state-changing requests must carry a custom header that
    # cross-site forms cannot set (cookie is also SameSite=Lax).
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.headers.get("x-requested-with") != "pramaan":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing request header")
    request.state.user = user
    return user


def require_roles(*roles: str):
    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role does not permit this action")
        return user

    return dep


require_reviewer = require_roles("reviewer")
require_institution = require_roles("institution")
require_admin = require_roles("admin")


def reviewer_can_access(user: User, app: Application) -> bool:
    """Scrutiny officers can access every submitted application; drafts belong to the institution until submitted."""
    return user.role == "reviewer" and app.status != "draft"


def get_application_for_reviewer(application_id: int, user: User, db: Session) -> Application:
    app = db.get(Application, application_id)
    if not app:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    if not reviewer_can_access(user, app):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return app


def get_application_for_institution(application_id: int, user: User, db: Session) -> Application:
    app = db.get(Application, application_id)
    # Do not reveal existence of other institutions' records.
    if not app or app.institution_id != user.institution_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return app
