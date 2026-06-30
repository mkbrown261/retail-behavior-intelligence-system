"""
Authentication service.

Handles:
  • Password hashing / verification (bcrypt via passlib)
  • JWT access + refresh token creation and verification (HS256 via python-jose)
  • User lookup helpers used by the auth router
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)

# ── Password hashing ────────────────────────────────────────────────────────
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ── JWT helpers ─────────────────────────────────────────────────────────────

def _make_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    """
    Create a signed JWT.
    Payload: sub=<user_id>, type=<access|refresh>, exp=<utc timestamp>
    """
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub":  subject,
        "type": token_type,
        "exp":  expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: str) -> str:
    return _make_token(
        user_id, "access",
        timedelta(minutes=settings.JWT_ACCESS_EXPIRES_M),
    )


def create_refresh_token(user_id: str) -> str:
    return _make_token(
        user_id, "refresh",
        timedelta(days=settings.JWT_REFRESH_EXPIRES_D),
    )


def decode_token(token: str) -> Optional[dict]:
    """
    Decode and validate a JWT.
    Returns the payload dict, or None if invalid/expired.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError as exc:
        logger.debug(f"JWT decode failed: {exc}")
        return None


# ── DB helpers ───────────────────────────────────────────────────────────────

async def get_user_by_id(db: AsyncSession, user_id: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    result = await db.execute(
        select(User).where(User.username == username, User.is_active == True)  # noqa: E712
    )
    return result.scalar_one_or_none()


async def authenticate_user(
    db: AsyncSession, username: str, password: str
) -> Optional[User]:
    """Return the User if credentials are valid, None otherwise."""
    user = await get_user_by_username(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def update_last_login(db: AsyncSession, user_id: str):
    now = datetime.now(timezone.utc)
    await db.execute(
        update(User).where(User.id == user_id).values(last_login=now)
    )
    await db.commit()


async def create_user(
    db: AsyncSession,
    username: str,
    password: str,
    role: str = "SECURITY",
    email: Optional[str] = None,
) -> User:
    """
    Create and persist a new user.  Raises ValueError on duplicate username.
    """
    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        raise ValueError(f"Username '{username}' already exists")

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        role=role,
        is_active=True,
        is_verified=True,  # auto-verify for admin-created users
    )
    db.add(user)
    await db.flush()
    await db.commit()
    await db.refresh(user)
    return user


# ── Role hierarchy ───────────────────────────────────────────────────────────
_ROLE_RANK = {"OWNER": 4, "MANAGER": 3, "SECURITY": 2, "INVESTIGATOR": 1}


def role_has_permission(user_role: str, required_role: str) -> bool:
    """Returns True if user_role meets or exceeds required_role privilege."""
    return _ROLE_RANK.get(user_role, 0) >= _ROLE_RANK.get(required_role, 99)
