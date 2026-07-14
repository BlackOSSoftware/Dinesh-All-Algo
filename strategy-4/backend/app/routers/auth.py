from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_utils import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models import User
from app.schemas import LoginBody, TokenResponse, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
LOG = logging.getLogger(__name__)


def _kick_angel_refresh_after_login() -> None:
    """Refresh Angel SmartAPI JWT in background so dashboard/live quotes work after app login."""

    def _run() -> None:
        try:
            from app.services.angel_auto_login_scheduler import trigger_manual_angel_login

            result = trigger_manual_angel_login()
            LOG.info("Angel refresh after app login: %s", result)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Angel refresh after app login failed: %s", exc)

    threading.Thread(target=_run, name="angel-refresh-on-login", daemon=True).start()


@router.post("/register", response_model=UserOut)
def register(body: UserCreate, db: Session = Depends(get_db)):
    existing = db.scalar(select(User).where(User.username == body.username))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )
    user = User(
        username=body.username.strip(),
        password_hash=hash_password(body.password),
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username.strip()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token = create_access_token(
        str(user.id), extra={"username": user.username, "role": user.role}
    )
    _kick_angel_refresh_after_login()
    return TokenResponse(access_token=token)
