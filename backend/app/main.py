"""
Main FastAPI application entry point.
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.database import init_db
from app.services.video_pipeline import pipeline
from app.services.event_orchestrator import handle_detection
from app.camera.camera_manager import camera_manager
from app.api import persons, alerts, analytics, cameras, events
# cameras module exports two routers:
#   cameras.router    → mounted with prefix="/api"   (REST endpoints)
#   cameras.ws_router → mounted without prefix       (WebSocket + legacy /cameras/*)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 RBIS v2.0 starting up...")

    # Ensure data dirs exist
    for d in ["snapshots", "clips", "reports"]:
        os.makedirs(os.path.join(settings.LOCAL_STORAGE_PATH, d), exist_ok=True)

    # Init DB
    await init_db()

    # ── Camera Manager (Intent Layer) ─────────────────────────────────────────
    # CameraManager attaches the IntentBus to the event loop, loads cameras.yaml,
    # and starts per-camera capture threads. All FRAME_READY intents are bridged
    # to the AI pipeline via the registered callback — no direct coupling.
    camera_manager.register_frame_callback(handle_detection)
    await camera_manager.start()

    # Register pipeline callback and start
    pipeline.register_callback(handle_detection)
    await pipeline.start()

    # Schedule daily report job
    _schedule_reports()

    logger.info("✅ System ready — pipeline running")
    yield

    # Shutdown
    await pipeline.stop()
    await camera_manager.stop()
    logger.info("👋 RBIS shutdown complete")


def _schedule_reports():
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from app.core.database import AsyncSessionLocal
        from app.services.report_service import generate_daily_report

        scheduler = AsyncIOScheduler()

        async def _run_report():
            async with AsyncSessionLocal() as db:
                await generate_daily_report(db)

        scheduler.add_job(
            _run_report,
            "cron",
            hour=settings.REPORT_GENERATION_HOUR,
            minute=settings.REPORT_GENERATION_MINUTE,
            id="daily_report",
        )
        scheduler.start()
        logger.info(
            f"Daily report scheduled at {settings.REPORT_GENERATION_HOUR:02d}:{settings.REPORT_GENERATION_MINUTE:02d} UTC"
        )
    except Exception as e:
        logger.warning(f"Could not schedule reports: {e}")


app = FastAPI(
    title="Retail Behavior Intelligence System",
    description="Phase 2 — Advanced Analytics Platform for Loss Prevention & Business Intelligence",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API Routers ───────────────────────────────────────────────────────────────
app.include_router(persons.router,    prefix="/api")
app.include_router(alerts.router,     prefix="/api")
app.include_router(analytics.router,  prefix="/api")
app.include_router(cameras.router,    prefix="/api")   # REST: /api/cameras/*, /api/ws/status
app.include_router(cameras.ws_router)                   # WS:   /ws/{id}, /ws, /cameras/feeds (legacy)
app.include_router(events.router,     prefix="/api")

# ── Static media files ────────────────────────────────────────────────────────
media_path = settings.LOCAL_STORAGE_PATH
if os.path.exists(media_path):
    app.mount("/media", StaticFiles(directory=media_path), name="media")

# ── Health check ─────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "pipeline_running": pipeline._running,
        "active_persons": pipeline.get_active_count(),
    }


@app.get("/api/system-status")
async def system_status():
    from app.core.websocket import manager
    from app.services.scoring import get_all_live_scores
    return {
        "pipeline_running":   pipeline._running,
        "active_persons":     pipeline.get_active_count(),
        "connected_clients":  manager.connection_count,
        "live_scores":        get_all_live_scores(),
        "cameras": {
            "total":   camera_manager.get_camera_count(),
            "streams": [c["camera_id"] for c in camera_manager.get_all_info()],
        },
    }
