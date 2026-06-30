"""
Authentication API router.

Endpoints:
  POST /api/auth/login        – username + password → access + refresh tokens
  POST /api/auth/refresh      – refresh token → new access token
  POST /api/auth/logout       – client-side token invalidation (stateless hint)
  GET  /api/auth/me           – return current user profile
  POST /api/auth/users        – create user (OWNER only)
  GET  /api/auth/users        – list users  (MANAGER+)

FastAPI dependency for protected routes:
  from app.api.auth import require_role, get_current_user
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.services.auth_service import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    create_user,
    decode_token,
    get_user_by_id,
    role_has_permission,
    update_last_login,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


# ── Pydantic schemas ─────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    role:          str
    username:      str
    user_id:       str


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=8)
    role:     str = Field("SECURITY", pattern="^(OWNER|MANAGER|SECURITY|INVESTIGATOR)$")
    email:    Optional[str] = None


# ── Auth dependency ──────────────────────────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency — extracts and validates Bearer JWT, returns User.
    Raises HTTP 401 if token is missing, invalid, or expired.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await get_user_by_id(db, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_role(minimum_role: str):
    """
    Dependency factory — enforces a minimum role level.

    Usage:
        @router.get("/admin")
        async def admin_only(user = Depends(require_role("MANAGER"))):
            ...
    """
    async def _check(current_user: User = Depends(get_current_user)) -> User:
        if not role_has_permission(current_user.role, minimum_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {minimum_role} role or higher",
            )
        return current_user
    return _check


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Exchange username + password for JWT access + refresh tokens.
    Returns HTTP 401 on invalid credentials (no username enumeration).
    """
    user = await authenticate_user(db, body.username, body.password)
    if not user:
        # Constant-time-ish rejection — no enumeration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token  = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    # Fire-and-forget last_login update
    import asyncio
    asyncio.create_task(update_last_login(db, user.id))

    logger.info(f"User logged in: {user.username} (role={user.role})")
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        role=user.role,
        username=user.username,
        user_id=user.id,
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh token for a new access token."""
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = await get_user_by_id(db, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    return AccessTokenResponse(access_token=create_access_token(user.id))


@router.post("/logout")
async def logout():
    """
    Stateless logout hint (client must discard tokens).
    Full token blacklisting requires Redis; deferred to Sprint 3.
    """
    return {"detail": "Logged out. Please discard your tokens on the client."}


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return current_user.to_dict()


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_new_user(
    body: CreateUserRequest,
    current_user: User = Depends(require_role("OWNER")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user account. Requires OWNER role."""
    try:
        user = await create_user(
            db,
            username=body.username,
            password=body.password,
            role=body.role,
            email=body.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    logger.info(
        f"User created: {user.username} (role={user.role}) "
        f"by {current_user.username}"
    )
    return user.to_dict()


@router.get("/users")
async def list_users(
    current_user: User = Depends(require_role("MANAGER")),
    db: AsyncSession = Depends(get_db),
):
    """List all users. Requires MANAGER role or higher."""
    from sqlalchemy import select
    result = await db.execute(
        select(User).where(User.is_active == True).order_by(User.created_at)  # noqa: E712
    )
    users = result.scalars().all()
    return [u.to_dict() for u in users]
