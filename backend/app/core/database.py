from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# ── Engine ─────────────────────────────────────────────────────────────────────
# echo=True logs every SQL statement — only enable in DEBUG mode
_engine_kwargs = dict(
    echo=settings.DEBUG,
    future=True,
)

if settings.is_sqlite:
    # SQLite: single-file, use check_same_thread=False for async access
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL / other: add connection pool settings for production
    _engine_kwargs.update({
        "pool_size":         10,
        "max_overflow":      20,
        "pool_pre_ping":     True,   # validate connections before use
        "pool_recycle":      3600,   # recycle connections every hour
    })

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI dependency: yields a database session with automatic commit/rollback."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    from app.models import person, event, suspicion, media, analytics, sensor  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized successfully")
    # Run lightweight schema migrations to handle column type changes
    # that create_all() won't apply to existing tables.
    await _migrate_schema()


async def _migrate_schema():
    """
    Apply incremental schema fixes to existing databases.
    Safe to call on every startup — each migration is idempotent.
    """
    if not settings.is_sqlite:
        # PostgreSQL: use Alembic for migrations — skip this helper.
        return

    from sqlalchemy import text

    migrations = [
        # Sprint-2: camera_id columns changed from INTEGER to TEXT.
        # SQLite can't ALTER COLUMN type, so we recreate affected tables
        # only if they still have the old INTEGER type.
        ("suspicion_scores", "camera_id"),
        ("alerts",           "camera_id"),
        ("heatmap_points",   "camera_id"),
        ("events",           "camera_id"),
    ]

    # New nullable columns added to an existing table — create_all() only
    # creates missing TABLES, not missing COLUMNS on ones that already exist,
    # so these need an explicit ADD COLUMN (safe/idempotent on SQLite).
    new_columns = [
        ("daily_reports", "event_type_breakdown", "JSON"),
        ("daily_reports", "sensor_events_count",  "INTEGER DEFAULT 0"),
    ]

    async with engine.begin() as conn:
        for table, col, col_type in new_columns:
            rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
            if any(r[1] == col for r in rows):
                continue  # already has it
            try:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                logger.info(f"Migration: added {table}.{col}")
            except Exception as e:
                logger.warning(f"Migration: could not add {table}.{col}: {e}")

        for table, col in migrations:
            # PRAGMA table_info returns: cid, name, type, notnull, dflt, pk
            rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
            col_info = next((r for r in rows if r[1] == col), None)
            if col_info is None:
                continue  # column doesn't exist yet — create_all handles it
            if col_info[2].upper() in ("TEXT", "VARCHAR", "STRING"):
                continue  # already correct type

            # Column is INTEGER — need to migrate.
            # SQLite migration recipe: rename → recreate → copy → drop old.
            logger.info(f"DB migration: converting {table}.{col} INTEGER → TEXT")
            try:
                # Get current CREATE TABLE statement to rebuild without INTEGER
                row = (await conn.execute(
                    text(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
                )).fetchone()
                if row is None:
                    continue
                old_sql: str = row[0]
                # Replace the column type in the CREATE statement
                new_sql = old_sql.replace(
                    f"{col} INTEGER", f"{col} TEXT"
                ).replace(
                    f'"{col}" INTEGER', f'"{col}" TEXT'
                )
                cols_row = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
                col_names = ", ".join(f'"{r[1]}"' for r in cols_row)

                await conn.execute(text(f"ALTER TABLE {table} RENAME TO {table}_old"))
                await conn.execute(text(new_sql))
                await conn.execute(text(
                    f"INSERT INTO {table} ({col_names}) "
                    f"SELECT {col_names} FROM {table}_old"
                ))
                await conn.execute(text(f"DROP TABLE {table}_old"))
                logger.info(f"DB migration: {table}.{col} migration complete")
            except Exception as exc:
                logger.error(f"DB migration failed for {table}.{col}: {exc}", exc_info=True)
