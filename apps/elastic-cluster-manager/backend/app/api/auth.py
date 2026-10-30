from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, auth
from app.config import get_settings
from app.db import get_db
from app.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Login(BaseModel):
    username: str
    password: str


@router.post("/login", dependencies=[Depends(auth.require_csrf_header)])
def login(body: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    key = f"{request.client.host if request.client else '?'}:{body.username}"
    if auth.locked_out(key):
        raise HTTPException(429, "Too many failed attempts; try again later")
    user = db.scalar(select(User).where(User.username == body.username))
    if not auth.verify_password(user, body.password):
        auth.note_failure(key)
        audit.record(db, body.username[:100], "auth.login_failed")
        raise HTTPException(401, "Invalid credentials")
    auth.clear_failures(key)
    token = auth.create_session(db, user)
    s = get_settings()
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="strict",
                        secure=s.secure_cookies, max_age=s.session_ttl_hours * 3600, path="/")
    audit.record(db, user.username, "auth.login")
    return {"username": user.username, "role": user.role}


@router.post("/logout", dependencies=[Depends(auth.require_csrf_header)])
def logout(request: Request, response: Response, db: Session = Depends(get_db),
           user: User = Depends(auth.current_user)):
    token = request.cookies.get(auth.COOKIE)
    if token:
        auth.destroy_session(db, token)
    response.delete_cookie(auth.COOKIE, path="/")
    audit.record(db, user.username, "auth.logout")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(auth.current_user)):
    return {"username": user.username, "role": user.role}
