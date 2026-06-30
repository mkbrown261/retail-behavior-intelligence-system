"""
Alembic environment — configured for RBIS async SQLite / PostgreSQL.
Supports both sync (offline SQL generation) and async (online migration) modes.
"""
import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Make sure backend package is importable ───────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Import all models so Alembic can see their metadata ──────────────────────
from app.core.database import Base  # noqa: F401
import app.models.person       # noqa: F401
import app.models.event        # noqa: F401
import app.models.suspicion    # noqa: F401
import app.models.media        # noqa: F401
import app.models.analytics    # noqa: F401

# ── Alembic config ────────────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# ── Database URL: prefer environment variable, fall back to alembic.ini ──────
def get_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url:
        # Alembic needs a sync driver for migrations — swap async driver
        url = url.replace("sqlite+aiosqlite", "sqlite")
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    else:
        url = config.get_main_option("sqlalchemy.url", "sqlite:///./data/rbis.db")
    return url


def run_migrations_offline() -> None:
    """Offline mode: emit SQL to stdout without connecting to the DB."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,   # required for SQLite column alterations
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,   # required for SQLite column alterations
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Online mode: connect to the DB and run migrations."""
    # Build a sync-compatible URL from the async one
    sync_url = get_url()

    from sqlalchemy import create_engine
    engine = create_engine(
        sync_url,
        connect_args={"check_same_thread": False} if "sqlite" in sync_url else {},
        poolclass=pool.NullPool,
    )

    with engine.connect() as connection:
        do_run_migrations(connection)

    engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
