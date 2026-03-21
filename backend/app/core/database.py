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
    from app.models import person, event, suspicion, media, analytics  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized successfully")
