import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from db import get_db
from models import User

logger = logging.getLogger("jwt_auth")

ALGORITHM = "HS256"
ROLES = ("reader", "writer", "moderator")
router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)
# A valid bcrypt hash of a random value, so unknown usernames cost the same time as wrong passwords.
_DUMMY_HASH = bcrypt.hashpw(os.urandom(16).hex().encode(), bcrypt.gensalt()).decode()


class LoginRequest(BaseModel):
    username: str
    password: str


def get_secret() -> str:
    """Return the signing secret from the JWT_SECRET environment variable (never hard-coded)."""
    secret = os.environ.get("JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("Set JWT_SECRET to a random string of at least 32 characters.")
    return secret


def token_minutes() -> int:
    """Return the token lifetime in minutes (JWT_MINUTES, default 30)."""
    return int(os.environ.get("JWT_MINUTES", "30"))


def create_access_token(user: User, minutes: Optional[int] = None) -> str:
    """Create a signed JWT carrying the username, role and expiry for an authenticated user."""
    life = token_minutes() if minutes is None else minutes
    now = datetime.now(timezone.utc)
    claims = {"sub": user.username, "role": user.role, "iat": now, "exp": now + timedelta(minutes=life)}
    return jwt.encode(claims, get_secret(), algorithm=ALGORITHM)


def verify_password(plain: str, stored_hash: str) -> bool:
    """Check a plain password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode(), stored_hash.encode())
    except ValueError:
        return False


@router.post("/login")
def login(payload: LoginRequest, db: OrmSession = Depends(get_db)) -> dict:
    """Return a JWT for valid credentials, or 401 Unauthorized for invalid ones."""
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None:
        verify_password(payload.password, _DUMMY_HASH)
    if user is None or not verify_password(payload.password, user.password_hash):
        logger.info("login failed for username=%s", payload.username)
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    logger.info("login ok for username=%s role=%s", user.username, user.role)
    return {"access_token": create_access_token(user), "token_type": "bearer",
            "expires_in": token_minutes() * 60}


def current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: OrmSession = Depends(get_db),
) -> User:
    """Return the user for a valid bearer token, or raise 401 (missing, invalid or expired token)."""
    challenge = {"WWW-Authenticate": "Bearer"}
    if creds is None:
        raise HTTPException(status_code=401, detail="Missing bearer token.", headers=challenge)
    try:
        claims = jwt.decode(creds.credentials, get_secret(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired.", headers=challenge)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.", headers=challenge)
    user = db.query(User).filter(User.username == claims.get("sub")).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown user.", headers=challenge)
    return user


def require_roles(*allowed: str) -> Callable[..., User]:
    """Build a dependency that returns the user only if their stored role is in `allowed`, else 403."""
    def check(user: User = Depends(current_user)) -> User:
        """Raise 403 Forbidden when the authenticated user's role is not allowed."""
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail=f"Role '{user.role}' may not do this.")
        return user
    return check


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    """Return the authenticated user's identity and role."""
    return {"id": user.id, "username": user.username, "role": user.role}


any_role = require_roles(*ROLES)
writer_or_moderator = require_roles("writer", "moderator")
moderator_only = require_roles("moderator")