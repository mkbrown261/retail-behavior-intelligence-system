"""
cameras.py — WebSocket, Camera Management, and MJPEG streaming endpoints.

Two routers are exported:
  ws_router   — included WITHOUT prefix in main.py  (WebSocket + legacy /cameras/* paths)
  router      — included WITH prefix="/api"          (all REST camera management)

This keeps WebSocket handshakes at /ws/... while REST routes live under /api/cameras/...
"""

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
import re
from pydantic import BaseModel, Field, field_validator

from app.core.websocket import manager as ws_manager
from app.services.video_pipeline import pipeline

logger = logging.getLogger(__name__)

# Router included with prefix="/api" in main.py
router = APIRouter(tags=["Cameras"])

# Router included WITHOUT prefix in main.py (WebSocket + legacy paths)
ws_router = APIRouter(tags=["WebSocket"])


# ── Lazy import helper ────────────────────────────────────────────────────────

def _cam():
    from app.camera.camera_manager import camera_manager
    return camera_manager


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket endpoints  (ws_router — no /api prefix)
# ═══════════════════════════════════════════════════════════════════════════════

@ws_router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await ws_manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "subscribe":
                topics = data.get("topics", ["detections", "alerts", "scores", "cameras"])
                await ws_manager.subscribe(client_id, topics)
                await ws_manager.send_personal(client_id, {
                    "type":   "subscribed",
                    "topics": topics,
                })
    except WebSocketDisconnect:
        await ws_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error [{client_id}]: {e}")
        await ws_manager.disconnect(client_id)


@ws_router.websocket("/ws")
async def websocket_anon(websocket: WebSocket):
    client_id = f"anon_{uuid.uuid4().hex[:8]}"
    await websocket_endpoint(websocket, client_id)


# ── WebSocket status (under /api via main router prefix) ──────────────────────

@router.get("/ws/status")
async def ws_status():
    return {
        "connected_clients": ws_manager.connection_count,
        "pipeline_active":   pipeline._running,
        "active_persons":    pipeline.get_active_count(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Simulated pipeline feeds
# Both paths registered: /api/cameras/feeds (new) + /cameras/feeds (legacy)
# ═══════════════════════════════════════════════════════════════════════════════

async def _camera_feeds_handler():
    sim_feeds = pipeline.get_camera_frames()
    real_cams = _cam().get_all_info()
    return {
        "feeds":          sim_feeds,
        "active_persons": pipeline.get_active_count(),
        "real_cameras":   real_cams,
    }

@router.get("/cameras/feeds")
async def camera_feeds():
    return await _camera_feeds_handler()

@ws_router.get("/cameras/feeds")       # legacy path without /api prefix
async def camera_feeds_legacy():
    return await _camera_feeds_handler()


async def _single_feed_handler(camera_id: int):
    for f in pipeline.get_camera_frames():
        if f["camera_id"] == camera_id:
            return f
    return {"camera_id": camera_id, "persons": [], "person_count": 0}

@router.get("/cameras/{camera_id}/feed")
async def single_camera_feed(camera_id: int):
    return await _single_feed_handler(camera_id)

@ws_router.get("/cameras/{camera_id}/feed")   # legacy path
async def single_camera_feed_legacy(camera_id: int):
    return await _single_feed_handler(camera_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Real camera management  (router — gets /api prefix)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/cameras")
async def list_cameras():
    """List all registered camera streams and their current status."""
    return {
        "cameras": _cam().get_all_info(),
        "total":   _cam().get_camera_count(),
    }


@router.get("/cameras/intent/stats")
async def intent_stats():
    """Return IntentBus dispatch counters per intent type."""
    from app.camera.intent_layer import intent_bus
    return {"intent_stats": intent_bus.stats()}


@router.get("/cameras/{camera_id}")
async def get_camera(camera_id: str):
    """Get status and metadata for a single camera."""
    info = _cam().get_camera_info(camera_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    return info


# Valid camera types
_VALID_CAM_TYPES = {"USB", "RTSP", "HTTP", "ONVIF", "FILE", "MOCK"}
# camera_id: alphanumeric + underscore + hyphen only, max 64 chars
_CAMERA_ID_RE = re.compile(r'^[a-zA-Z0-9_\-]{1,64}$')


class AddCameraRequest(BaseModel):
    camera_id: str   = Field(..., description="Unique camera identifier (alphanumeric, _, -)")
    cam_type:  str   = Field("MOCK", description="USB | RTSP | HTTP | ONVIF | FILE | MOCK")
    source:    Any   = Field(..., description="Device index (USB) or stream URL")
    width:     int   = Field(1280,  ge=160, le=3840)
    height:    int   = Field(720,   ge=120, le=2160)
    fps:       float = Field(15.0,  ge=1,   le=30)
    username:  str   = Field("",    max_length=128)
    password:  str   = Field("",    max_length=128)
    extra:     Dict  = Field(default_factory=dict)

    @field_validator("camera_id")
    @classmethod
    def validate_camera_id(cls, v: str) -> str:
        if not _CAMERA_ID_RE.match(v):
            raise ValueError(
                "camera_id must be 1-64 chars: letters, digits, underscores, hyphens only"
            )
        return v

    @field_validator("cam_type")
    @classmethod
    def validate_cam_type(cls, v: str) -> str:
        upper = v.upper()
        if upper not in _VALID_CAM_TYPES:
            raise ValueError(f"cam_type must be one of: {', '.join(sorted(_VALID_CAM_TYPES))}")
        return upper


@router.post("/cameras")
async def add_camera(req: AddCameraRequest):
    """Dynamically add a new camera stream at runtime."""
    try:
        info = await _cam().add_camera(
            camera_id=req.camera_id,
            cam_type=req.cam_type,
            source=req.source,
            width=req.width,
            height=req.height,
            fps=req.fps,
            username=req.username,
            password=req.password,
            extra=req.extra,
        )
        return {"added": True, "camera": info}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.error(f"add_camera error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/cameras/{camera_id}")
async def remove_camera(camera_id: str):
    """Stop and remove a camera stream at runtime."""
    removed = await _cam().remove_camera(camera_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    return {"removed": True, "camera_id": camera_id}


@router.post("/cameras/{camera_id}/restart")
async def restart_camera(camera_id: str):
    """Restart a camera stream (reconnect)."""
    info = await _cam().restart_camera(camera_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    return {"restarted": True, "camera": info}


# ═══════════════════════════════════════════════════════════════════════════════
# ONVIF auto-discovery
# ═══════════════════════════════════════════════════════════════════════════════

class OnvifDiscoverRequest(BaseModel):
    """Credentials passed in request body — never in query parameters."""
    username: str = Field("", max_length=128, description="ONVIF device username")
    password: str = Field("", max_length=128, description="ONVIF device password")


@router.post("/cameras/discover/onvif")
async def discover_onvif(req: OnvifDiscoverRequest):
    """Run ONVIF WS-Discovery on the local network.
    Credentials are passed in the JSON body, never in query parameters.
    """
    try:
        added = await _cam().discover_onvif(username=req.username, password=req.password)
        return {"discovered": len(added), "cameras": added}
    except Exception as exc:
        logger.error(f"ONVIF discovery error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# MJPEG and snapshot endpoints
# ═══════════════════════════════════════════════════════════════════════════════

MJPEG_BOUNDARY = b"--frame"

async def _mjpeg_generator(camera_id: str, fps: float = 15.0):
    delay = 1.0 / max(1.0, fps)
    cam = _cam()
    while True:
        jpeg = cam.get_jpeg(camera_id, quality=75)
        if jpeg:
            yield (
                MJPEG_BOUNDARY
                + b"\r\nContent-Type: image/jpeg\r\n"
                + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                + jpeg
                + b"\r\n"
            )
        await asyncio.sleep(delay)


@router.get("/cameras/{camera_id}/mjpeg")
async def camera_mjpeg(
    camera_id: str,
    fps: float = Query(default=15.0, ge=1.0, le=30.0),
):
    """MJPEG stream. Open in <img src="/api/cameras/{id}/mjpeg">."""
    if _cam().get_camera_info(camera_id) is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")
    return StreamingResponse(
        _mjpeg_generator(camera_id, fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/cameras/{camera_id}/snapshot")
async def camera_snapshot(camera_id: str, quality: int = Query(default=85, ge=10, le=100)):
    """Single JPEG snapshot of the latest camera frame."""
    jpeg = _cam().get_jpeg(camera_id, quality=quality)
    if jpeg is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found or no frame yet")
    return StreamingResponse(
        iter([jpeg]),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/cameras/{camera_id}/snapshot.b64")
async def camera_snapshot_b64(camera_id: str, quality: int = Query(default=70, ge=10, le=100)):
    """Latest frame as base64-encoded JPEG."""
    b64 = _cam().get_jpeg_b64(camera_id, quality=quality)
    if b64 is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found or no frame yet")
    info = _cam().get_camera_info(camera_id)
    return {
        "camera_id":  camera_id,
        "frame_b64":  b64,
        "resolution": info.get("resolution") if info else None,
        "status":     info.get("status")     if info else None,
    }
