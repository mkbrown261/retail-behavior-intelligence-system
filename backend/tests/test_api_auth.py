"""
Tests for the JWT authentication API.

Covers:
  POST /api/auth/login        – success, wrong password, unknown user
  POST /api/auth/refresh      – valid + invalid refresh token
  POST /api/auth/logout       – stateless hint
  GET  /api/auth/me           – requires auth
  POST /api/auth/users        – create user (OWNER only)
  GET  /api/auth/users        – list users (MANAGER+)
"""
import pytest
from httpx import AsyncClient

from app.services.auth_service import create_user, hash_password
from app.models.user import User


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _make_owner(db) -> tuple[str, str]:
    """Create an OWNER user and return (username, password)."""
    await create_user(db, "admin_owner", "ownerpass123", role="OWNER")
    return "admin_owner", "ownerpass123"


async def _make_security(db) -> tuple[str, str]:
    await create_user(db, "sec_user", "secpass456", role="SECURITY")
    return "sec_user", "secpass456"


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    r = await client.post("/api/auth/login", json={"username": username, "password": password})
    return r


# ── Login ─────────────────────────────────────────────────────────────────────

async def test_login_success(client, db):
    username, password = await _make_owner(db)
    r = await _login(client, username, password)
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    assert body["role"] == "OWNER"
    assert body["username"] == username


async def test_login_wrong_password(client, db):
    await _make_owner(db)
    r = await _login(client, "admin_owner", "wrongpassword")
    assert r.status_code == 401


async def test_login_unknown_user(client):
    r = await _login(client, "ghost_user", "doesntmatter")
    assert r.status_code == 401


async def test_login_missing_fields(client):
    r = await client.post("/api/auth/login", json={"username": "admin_owner"})
    assert r.status_code == 422


async def test_login_empty_username(client):
    r = await client.post("/api/auth/login", json={"username": "", "password": "pass"})
    assert r.status_code == 422


# ── Refresh ───────────────────────────────────────────────────────────────────

async def test_refresh_valid_token(client, db):
    await _make_owner(db)
    login_r = await _login(client, "admin_owner", "ownerpass123")
    refresh_token = login_r.json()["refresh_token"]

    r = await client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


async def test_refresh_invalid_token(client):
    r = await client.post("/api/auth/refresh", json={"refresh_token": "not.a.real.token"})
    assert r.status_code == 401


async def test_refresh_access_token_rejected(client, db):
    """Passing an access token to /refresh must be rejected."""
    await _make_owner(db)
    login_r = await _login(client, "admin_owner", "ownerpass123")
    access_token = login_r.json()["access_token"]

    r = await client.post("/api/auth/refresh", json={"refresh_token": access_token})
    assert r.status_code == 401


# ── Logout ────────────────────────────────────────────────────────────────────

async def test_logout_returns_200(client):
    r = await client.post("/api/auth/logout")
    assert r.status_code == 200


# ── /me ───────────────────────────────────────────────────────────────────────

async def test_me_with_valid_token(client, db):
    await _make_owner(db)
    login_r = await _login(client, "admin_owner", "ownerpass123")
    token = login_r.json()["access_token"]

    r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "admin_owner"
    assert body["role"] == "OWNER"
    assert "hashed_password" not in body


async def test_me_without_token(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


async def test_me_with_bad_token(client):
    r = await client.get("/api/auth/me", headers={"Authorization": "Bearer bad.token.here"})
    assert r.status_code == 401


# ── Create user ───────────────────────────────────────────────────────────────

async def test_create_user_as_owner(client, db):
    await _make_owner(db)
    login_r = await _login(client, "admin_owner", "ownerpass123")
    token = login_r.json()["access_token"]

    r = await client.post(
        "/api/auth/users",
        json={"username": "new_manager", "password": "manpass789", "role": "MANAGER"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "new_manager"
    assert body["role"] == "MANAGER"
    assert "hashed_password" not in body


async def test_create_user_security_forbidden(client, db):
    """SECURITY role cannot create users."""
    await _make_security(db)
    login_r = await _login(client, "sec_user", "secpass456")
    token = login_r.json()["access_token"]

    r = await client.post(
        "/api/auth/users",
        json={"username": "another", "password": "anotherpass", "role": "SECURITY"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


async def test_create_user_duplicate_username(client, db):
    await _make_owner(db)
    login_r = await _login(client, "admin_owner", "ownerpass123")
    token = login_r.json()["access_token"]

    # First creation succeeds
    await client.post(
        "/api/auth/users",
        json={"username": "dup_user", "password": "pass12345", "role": "SECURITY"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # Second creation with same username → 409
    r = await client.post(
        "/api/auth/users",
        json={"username": "dup_user", "password": "different", "role": "SECURITY"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 409


async def test_create_user_invalid_role(client, db):
    await _make_owner(db)
    login_r = await _login(client, "admin_owner", "ownerpass123")
    token = login_r.json()["access_token"]

    r = await client.post(
        "/api/auth/users",
        json={"username": "bad_role_user", "password": "pass12345", "role": "SUPERHERO"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


async def test_create_user_password_too_short(client, db):
    await _make_owner(db)
    login_r = await _login(client, "admin_owner", "ownerpass123")
    token = login_r.json()["access_token"]

    r = await client.post(
        "/api/auth/users",
        json={"username": "shortpass", "password": "abc", "role": "SECURITY"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


# ── List users ────────────────────────────────────────────────────────────────

async def test_list_users_as_manager(client, db):
    """MANAGER can list users."""
    # Create an owner to use for creating the manager
    await _make_owner(db)
    owner_login = await _login(client, "admin_owner", "ownerpass123")
    owner_token = owner_login.json()["access_token"]

    # Create a manager
    await client.post(
        "/api/auth/users",
        json={"username": "list_manager", "password": "mgrpass789", "role": "MANAGER"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    mgr_login = await _login(client, "list_manager", "mgrpass789")
    mgr_token = mgr_login.json()["access_token"]

    r = await client.get("/api/auth/users", headers={"Authorization": f"Bearer {mgr_token}"})
    assert r.status_code == 200
    users = r.json()
    assert isinstance(users, list)
    assert len(users) >= 2  # admin_owner + list_manager


async def test_list_users_as_investigator_forbidden(client, db):
    """INVESTIGATOR rank is too low for /users list."""
    await create_user(db, "investigator1", "invpass123", role="INVESTIGATOR")
    await db.commit()
    login_r = await _login(client, "investigator1", "invpass123")
    token = login_r.json()["access_token"]

    r = await client.get("/api/auth/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


async def test_list_users_unauthenticated(client):
    r = await client.get("/api/auth/users")
    assert r.status_code == 401
