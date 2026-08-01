"""
Main FastAPI application entry point.
"""
import asyncio
import logging
import os
import socket
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import settings
from app.core.database import init_db
from app.services.video_pipeline import pipeline
from app.services.event_orchestrator import handle_detection
from app.camera.camera_manager import camera_manager
from app.api import persons, alerts, analytics, cameras, events, sensors, admin
from app.api import auth


logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ── Suppress noisy loggers in production ──────────────────────────────────────
if not settings.DEBUG:
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 RBIS v2.0 starting up...")

    # Ensure data dirs exist
    for d in ["snapshots", "clips", "reports"]:
        os.makedirs(os.path.join(settings.LOCAL_STORAGE_PATH, d), exist_ok=True)

    # Init DB
    await init_db()

    # ── Load YOLOv8-nano model (non-blocking — runs in executor) ─────────────
    # Model is ~6MB and loads in ~1s. We do it at startup so first-frame
    # latency is zero rather than stalling the first real detection.
    if settings.AI_ENABLED:
        try:
            from app.services.ai_inference import YOLOInferenceEngine
            loop = asyncio.get_event_loop()
            loaded = await loop.run_in_executor(
                None, YOLOInferenceEngine.ensure_loaded, settings.YOLO_MODEL_PATH or None
            )
            if loaded:
                logger.info("✅ YOLOv8-nano ready for real camera detection")
            else:
                logger.warning("⚠️  YOLOv8 model not loaded — falling back to simulation")
        except Exception as e:
            logger.warning(f"⚠️  YOLOv8 load failed ({e}) — simulation mode active")

    # ── Camera Manager (Intent Layer) ─────────────────────────────────────────
    # Wire the AI frame callback BEFORE starting streams so no frames are missed.
    if settings.AI_ENABLED:
        _wire_ai_to_camera_manager()

    await camera_manager.start()

    # ── Simulation pipeline ───────────────────────────────────────────────────
    # Only runs when AI is disabled (demo/dev mode).
    # When AI_ENABLED=true, real camera frames drive detections instead.
    if not settings.AI_ENABLED:
        pipeline.register_callback(handle_detection)
        await pipeline.start()
        logger.info("✅ System ready — simulation mode")
    else:
        logger.info("✅ System ready — AI=true, using real camera feeds")

    # ── Startup diagnostic summary ────────────────────────────────────────────
    _print_startup_summary()

    # Schedule daily report job
    _schedule_reports()
    _schedule_retention()
    yield

    # Shutdown
    if not settings.AI_ENABLED:
        await pipeline.stop()
    await camera_manager.stop()
    logger.info("👋 RBIS shutdown complete")


def _print_startup_summary():
    """Print a clear startup diagnostic so the user knows exactly what's running."""
    from app.services.ai_inference import is_model_loaded, YOLOInferenceEngine
    cam_count = camera_manager.get_camera_count()
    cam_infos = camera_manager.get_all_info()

    logger.info("=" * 60)
    logger.info("🔍 RBIS STARTUP DIAGNOSTIC")
    logger.info(f"  AI_ENABLED:       {settings.AI_ENABLED}")
    logger.info(f"  YOLO loaded:      {is_model_loaded()}")
    logger.info(f"  YOLO model path:  {YOLOInferenceEngine._model_path}")
    logger.info(f"  Cameras started:  {cam_count}")
    for c in cam_infos:
        logger.info(
            f"    [{c['camera_id']}] type={c['cam_type']} "
            f"status={c['status']} source={c.get('source','?')}"
        )
    if not cam_infos:
        logger.error("  ❌ NO CAMERAS — check cameras.yaml!")
    if not is_model_loaded() and settings.AI_ENABLED:
        logger.error("  ❌ YOLO NOT LOADED — detections will NOT fire!")
        logger.error("     Fix: run:  python3 -c \"from ultralytics import YOLO; YOLO('yolov8n.pt')\"")
    logger.info(f"  Pipeline mode:    {'AI/real camera' if settings.AI_ENABLED else 'SIMULATION'}")
    logger.info(f"  Sim running:      {pipeline._running}")
    logger.info("=" * 60)
    logger.info("📡 Debug endpoint: GET /api/debug/ai  (shows live YOLO + frame stats)")
    logger.info("=" * 60)


def _wire_ai_to_camera_manager():
    """
    Register an async frame callback on CameraManager so every FRAME_READY
    intent from a real camera flows through YOLOv8 → behavior analyzer
    → handle_detection → scoring / alerts / WebSocket.
    """
    from app.services.ai_inference import get_or_create_processor, ZoneConfig
    from collections import defaultdict

    # Per-camera, not global — with multiple cameras a single flat counter
    # would only ever log "first 3 frames" for whichever camera happens to
    # fire first, leaving every other camera's startup silent.
    _callback_fire_count = defaultdict(int)

    async def _ai_frame_callback(frame_payload: dict):
        """
        Called by CameraManager._on_frame_ready() for every real camera frame.
        frame_payload = {camera_id: str, frame: np.ndarray, sequence: int}
        """
        camera_id = frame_payload.get("camera_id", "unknown")
        frame     = frame_payload.get("frame")
        if frame is None:
            logger.warning(f"[{camera_id}] _ai_frame_callback: frame is None in payload!")
            return

        _callback_fire_count[camera_id] += 1
        n = _callback_fire_count[camera_id]

        # Log the first 3 frames per camera so we know data is flowing from EACH one
        if n <= 3:
            logger.info(
                f"📡 AI frame callback firing (#{n}): camera={camera_id} "
                f"frame_shape={frame.shape if hasattr(frame, 'shape') else 'unknown'}"
            )

        # Per-camera zone thresholds — configured in cameras.yaml under
        # `extra: {zones: {...}}`. Falls back to store-layout defaults.
        stream = camera_manager.get_stream(camera_id)
        zones_dict = (stream.cfg.extra or {}).get("zones") if stream else None
        zones = ZoneConfig.from_dict(zones_dict)
        if n == 1 and zones_dict:
            logger.info(f"[{camera_id}] Using custom zone config: {zones_dict}")

        processor = get_or_create_processor(camera_id, handle_detection, zones)
        await processor.on_frame(frame)

    camera_manager.register_frame_callback(_ai_frame_callback)
    logger.info("✅ AI frame callback registered on CameraManager — frames will flow to YOLO")


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
            f"Daily report scheduled at "
            f"{settings.REPORT_GENERATION_HOUR:02d}:{settings.REPORT_GENERATION_MINUTE:02d} UTC"
        )
    except Exception as e:
        logger.warning(f"Could not schedule reports: {e}")


def _schedule_retention():
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from app.core.database import AsyncSessionLocal
        from app.services.retention import purge_expired_data

        scheduler = AsyncIOScheduler()

        async def _run_purge():
            async with AsyncSessionLocal() as db:
                await purge_expired_data(db)

        scheduler.add_job(
            _run_purge,
            "cron",
            hour=settings.RETENTION_PURGE_HOUR,
            minute=settings.RETENTION_PURGE_MINUTE,
            id="data_retention_purge",
        )
        scheduler.start()
        logger.info(
            f"Data retention purge scheduled daily at "
            f"{settings.RETENTION_PURGE_HOUR:02d}:{settings.RETENTION_PURGE_MINUTE:02d} UTC "
            f"(tracking data: {settings.DATA_RETENTION_DAYS}d, alerts: {settings.ALERT_RETENTION_DAYS}d)"
        )
    except Exception as e:
        logger.warning(f"Could not schedule retention purge: {e}")


# ── App factory ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Retail Behavior Intelligence System",
    description="Behavior-based analytics for loss prevention.",
    version="2.0.0",
    lifespan=lifespan,
    # Lock down docs to DEBUG mode only — never expose in production
    docs_url="/api/docs"    if settings.DEBUG else None,
    redoc_url="/api/redoc"  if settings.DEBUG else None,
    openapi_url="/api/openapi.json" if settings.DEBUG else None,
)


# ── Security headers middleware ────────────────────────────────────────────────
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"]    = "nosniff"
    response.headers["X-Frame-Options"]            = "DENY"
    response.headers["X-XSS-Protection"]           = "1; mode=block"
    response.headers["Referrer-Policy"]            = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]         = "camera=(), microphone=(), geolocation=()"
    # Only add HSTS in production (not on http://localhost)
    if not settings.DEBUG:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Server fingerprinting header is suppressed via uvicorn --no-server-header flag
    # (set in ecosystem.config.cjs). The header cannot be removed here because
    # uvicorn adds it after the middleware chain completes.
    return response


# ── Simple in-memory rate limiter ──────────────────────────────────────────────
_rate_counters: dict = defaultdict(lambda: {"count": 0, "window_start": 0.0})
_RATE_WINDOW = 60.0  # 1 minute window

@app.middleware("http")
async def rate_limit(request: Request, call_next):
    # Skip rate limiting for static assets
    path = request.url.path
    if path.startswith("/assets") or path.startswith("/media"):
        return await call_next(request)

    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    bucket = _rate_counters[ip]

    # Reset window if expired
    if now - bucket["window_start"] > _RATE_WINDOW:
        bucket["count"] = 0
        bucket["window_start"] = now

    bucket["count"] += 1

    if bucket["count"] > settings.RATE_LIMIT_PER_MINUTE:
        logger.warning(f"Rate limit exceeded: {ip} ({bucket['count']} req/min)")
        return JSONResponse(
            {"detail": "Too many requests. Please slow down."},
            status_code=429,
            headers={"Retry-After": "60"},
        )

    return await call_next(request)


# ── CORS ───────────────────────────────────────────────────────────────────────
# Uses ALLOWED_ORIGINS from settings (set in .env, NOT hardcoded to "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)


# ── API Routers ────────────────────────────────────────────────────────────────
app.include_router(persons.router,    prefix="/api")
app.include_router(alerts.router,     prefix="/api")
app.include_router(analytics.router,  prefix="/api")
app.include_router(cameras.router,    prefix="/api")
app.include_router(cameras.ws_router)
app.include_router(events.router,     prefix="/api")
app.include_router(sensors.router,    prefix="/api")
app.include_router(admin.router,      prefix="/api")
app.include_router(auth.router,       prefix="/api")


# ── Static media files ─────────────────────────────────────────────────────────
media_path = settings.LOCAL_STORAGE_PATH
if os.path.exists(media_path):
    app.mount("/media", StaticFiles(directory=media_path), name="media")


# ── Global exception handler — never leak tracebacks to clients ───────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url}: {exc}", exc_info=True)
    # Return generic message — no internal details exposed to client
    return JSONResponse(
        {"detail": "An internal error occurred. Please try again."},
        status_code=500,
    )


# ── Health check ───────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    ai_running = settings.AI_ENABLED and camera_manager.get_camera_count() > 0
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "pipeline_running": pipeline._running or ai_running,
        "active_persons":   pipeline.get_active_count(),
    }


@app.get("/api/system-status")
async def system_status():
    from app.core.websocket import manager
    from app.services.scoring import get_all_live_scores
    from app.services.ai_inference import get_active_person_count, is_model_loaded
    ai_running = settings.AI_ENABLED and camera_manager.get_camera_count() > 0
    active = get_active_person_count() if ai_running else pipeline.get_active_count()
    return {
        "pipeline_running":  pipeline._running or ai_running,
        "active_persons":    active,
        "connected_clients": manager.connection_count,
        "live_scores":       get_all_live_scores(),
        "ai_enabled":        settings.AI_ENABLED,
        "ai_model_loaded":   is_model_loaded(),
        "cameras": {
            "total":   camera_manager.get_camera_count(),
            "streams": [c["camera_id"] for c in camera_manager.get_all_info()],
        },
    }


@app.get("/api/network-info")
async def network_info():
    """Return local IPs so the UI can display the QR-code URL."""
    ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ":" not in ip:
                if ip not in ips:
                    ips.append(ip)
    except Exception:
        pass
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
            s.close()
        except Exception:
            ips.append("127.0.0.1")
    port = int(os.environ.get("PORT", 8000))
    return {
        "ips":  ips,
        "port": port,
        "urls": [f"http://{ip}:{port}" for ip in ips],
    }


# ── Serve built frontend (self-hosted mode) ────────────────────────────────────
_UI_DIR = Path(__file__).parent.parent / "static" / "ui"

if _UI_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_UI_DIR / "assets")), name="ui-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """Catch-all: serve index.html for React SPA routing. Never serves arbitrary files."""
        if (
            full_path.startswith("api/")
            or full_path.startswith("media/")
            or full_path.startswith("ws")
            or full_path.startswith("assets/")
        ):
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        index = _UI_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"detail": "UI not found"}, status_code=404)
