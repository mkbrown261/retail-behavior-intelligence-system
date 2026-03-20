"""
RBIS Camera Module

Exports:
  camera_manager  — singleton CameraManager (lifecycle + stream registry)
  intent_bus      — singleton IntentBus (pub/sub for all camera events)
  CameraStream    — per-camera capture thread
  CameraConfig    — camera configuration dataclass
  CamType         — camera type enum (USB, RTSP, HTTP, ONVIF, FILE, MOCK)
  IntentType      — intent type enum
  ONVIFDiscovery  — ONVIF/WS-Discovery helper
"""

from app.camera.camera_manager  import camera_manager          # noqa: F401
from app.camera.intent_layer    import intent_bus, IntentType  # noqa: F401
from app.camera.camera_stream   import (                        # noqa: F401
    CameraStream, CameraConfig, CamType,
)
from app.camera.onvif_discovery import ONVIFDiscovery           # noqa: F401

__all__ = [
    "camera_manager",
    "intent_bus",
    "IntentType",
    "CameraStream",
    "CameraConfig",
    "CamType",
    "ONVIFDiscovery",
]
