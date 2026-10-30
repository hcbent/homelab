import hashlib
import secrets
import time
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import SessionRow, User

COOKIE = "ecm_session"
_ph = PasswordHasher()
_failures: dict[str, list[float]] = {}


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sync_admin(db: Session) -> None:
    """Create or update the single admin from environment configuration."""
    s = get_settings()
    h = s.admin_password_hash.get_secret_value()
    if not h:
        return
    user = db.scalar(select(User).where(User.username == s.admin_username))
    if user is None:
        db.add(User(username=s.admin_username, password_hash=h, role="admin"))
    elif user.password_hash != h:
        user.password_hash = h
    db.commit()


def locked_out(key: str) -> bool:
    s = get_settings()
    now = time.monotonic()
    recent = [t for t in _failures.get(key, []) if now - t < s.login_lockout_seconds]
    _failures[key] = recent
    return len(recent) >= s.login_max_failures


def note_failure(key: str) -> None:
    _failures.setdefault(key, []).append(time.monotonic())


def clear_failures(key: str) -> None:
    _failures.pop(key, None)


def verify_password(user: User | None, password: str) -> bool:
    # Hash a dummy when the user is unknown so timing doesn't reveal existence.
    stored = user.password_hash if user else _DUMMY
    try:
        ok = _ph.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return False
    return ok and user is not None


_DUMMY = _ph.hash("not-a-real-password")


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    ttl = timedelta(hours=get_settings().session_ttl_hours)
    db.add(SessionRow(token_hash=_hash_token(token), user_id=user.id,
                      expires_at=datetime.now(UTC) + ttl))
    db.commit()
    return token


def destroy_session(db: Session, token: str) -> None:
    row = db.get(SessionRow, _hash_token(token))
    if row:
        db.delete(row)
        db.commit()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE)
    if token:
        row = db.get(SessionRow, _hash_token(token))
        if row:
            expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
            if expires > datetime.now(UTC):
                user = db.get(User, row.user_id)
                if user:
                    return user
    raise HTTPException(status_code=401, detail="Not authenticated")


def require_csrf_header(request: Request) -> None:
    """Mutating requests need a custom header, which cross-site forms cannot send.
    Combined with SameSite=Strict cookies this blocks CSRF."""
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-ecm-csrf") != "1":
        raise HTTPException(status_code=403, detail="Missing CSRF header")
