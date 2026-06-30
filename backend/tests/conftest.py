"""
conftest.py — Shared pytest fixtures for the RBIS test suite.

Uses a separate file-based SQLite test database (test_rbis.db) so tests
are completely isolated from the production database. A file-based DB is
used instead of :memory: to avoid StaticPool concurrency issues when
background tasks (asyncio.create_task) open their own DB connections.

The test DB is created fresh at the start of each test session.
"""
import asyncio
import os
import sys

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# ── Make sure the backend package is importable ──────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Use a dedicated test DB file — never the production DB ───────────────────
_TEST_DB_FILE = os.path.join(os.path.dirname(__file__), "test_rbis.db")
_TEST_DB_URL = f"sqlite+aiosqlite:///{_TEST_DB_FILE}"

# Set env var BEFORE any app modules load so settings picks it up
os.environ["DATABASE_URL"] = _TEST_DB_URL

# ── App imports (after DATABASE_URL env var is set) ───────────────────────────
from app.core.config import settings  # noqa: E402

from app.core.database import Base  # noqa: E402
import app.models.person      # noqa: F401, E402
import app.models.event       # noqa: F401, E402
import app.models.suspicion   # noqa: F401, E402
import app.models.media       # noqa: F401, E402
import app.models.analytics   # noqa: F401, E402
import app.models.user        # noqa: F401, E402


# ── Test engine / session factory ─────────────────────────────────────────────
_test_engine = create_async_engine(
    _TEST_DB_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

TestSessionLocal = async_sessionmaker(
    _test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    """
    Create all tables at the start of the test session.
    Since the app's engine also points at the test DB file (env var set above),
    all sessions (including background tasks) share the same tables.
    """
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Drop and delete test DB file after session
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _test_engine.dispose()
    if os.path.exists(_TEST_DB_FILE):
        os.remove(_TEST_DB_FILE)


@pytest_asyncio.fixture(autouse=True)
async def clean_tables():
    """Truncate all tables before each test for isolation."""
    yield
    async with _test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    """Yield a live DB session backed by the in-memory engine."""
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db) -> AsyncClient:
    """
    HTTPX AsyncClient wired to the FastAPI app.
    The app's get_db dependency is overridden to use the test session.
    """
    # Import here to avoid circular issues with the env var override above
    from app.main import app
    from app.core.database import get_db

    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db

    # Use lifespan=False so we don't start the video pipeline / camera manager
    # during unit tests — those are integration-test concerns.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
