"""
Storage service — saves snapshots and video clips to local disk (or S3).
"""
import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
import asyncio

from app.core.config import settings

logger = logging.getLogger(__name__)

SNAPSHOT_DIR = os.path.join(settings.LOCAL_STORAGE_PATH, "snapshots")
CLIPS_DIR    = os.path.join(settings.LOCAL_STORAGE_PATH, "clips")

os.makedirs(SNAPSHOT_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)


def _timestamp_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


async def save_snapshot(
    image_bytes: Optional[bytes],
    session_id: str,
    camera_id: int,
    event_type: str = "SNAPSHOT",
) -> str:
    """Save a JPEG snapshot and return its relative path."""
    filename = f"{session_id}_cam{camera_id}_{event_type}_{_timestamp_str()}_{uuid.uuid4().hex[:6]}.jpg"
    filepath = os.path.join(SNAPSHOT_DIR, filename)

    if image_bytes:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write_file, filepath, image_bytes)
    else:
        # Write a placeholder text file as simulated snapshot
        await _write_placeholder(filepath, session_id, camera_id, event_type)

    logger.debug(f"Snapshot saved: {filepath}")
    return os.path.join("snapshots", filename)


async def save_clip(
    video_bytes: Optional[bytes],
    session_id: str,
    camera_id: int,
    duration: float = 20.0,
) -> str:
    """Save a video clip and return its relative path."""
    filename = f"{session_id}_cam{camera_id}_clip_{_timestamp_str()}_{uuid.uuid4().hex[:6]}.mp4"
    filepath = os.path.join(CLIPS_DIR, filename)

    if video_bytes:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write_file, filepath, video_bytes)
    else:
        await _write_placeholder(filepath, session_id, camera_id, "CLIP")

    logger.debug(f"Clip saved: {filepath}")
    return os.path.join("clips", filename)


def _write_file(path: str, data: bytes):
    with open(path, "wb") as f:
        f.write(data)


async def _write_placeholder(filepath: str, session_id: str, camera_id: int, label: str):
    content = (
        f"SIMULATED {label}\n"
        f"Session: {session_id}\n"
        f"Camera: {camera_id}\n"
        f"Time: {datetime.now(timezone.utc).isoformat()}\n"
    )
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _write_file, filepath, content.encode())


def get_file_url(relative_path: str) -> str:
    return f"/media/{relative_path}"
