"""
CameraStream — per-camera capture thread.

Each instance owns:
  • One background thread running _capture_loop()
  • A lock-protected latest_frame slot (numpy array or None)
  • A shared frame_event so consumers can block-wait for new frames
  • Full Intent Layer integration (CAMERA_CONNECTED, FRAME_READY, etc.)

Supported source types
──────────────────────
  USB    — OpenCV VideoCapture(int index)
  RTSP   — OpenCV VideoCapture("rtsp://...") or PyAV fallback
  HTTP   — OpenCV VideoCapture("http://...") MJPEG
  ONVIF  — Resolved to RTSP URL before passing here
  FILE   — VideoCapture("path/to/file.mp4") for testing
  MOCK   — Synthetic colour-fill frames (no hardware required)
"""

import logging
import threading
import time
import base64
import queue
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from app.camera.intent_layer import intent_bus

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_WIDTH   = 1280
DEFAULT_HEIGHT  = 720
DEFAULT_FPS_CAP = 30          # Maximum frames to publish per second
RECONNECT_DELAY = 5.0         # Seconds between reconnection attempts
MAX_RECONNECT   = 0           # 0 = infinite retries
FRAME_QUEUE_SZ  = 4           # Deep = latency; Shallow = drops. 4 is good balance.
RTSP_BUFFER_SZ  = 1           # Keep only the latest RTSP frame in OpenCV buffer


class CamType(str, Enum):
    USB   = "USB"
    RTSP  = "RTSP"
    HTTP  = "HTTP"
    ONVIF = "ONVIF"   # Resolved to RTSP before capture
    FILE  = "FILE"
    MOCK  = "MOCK"


class StreamStatus(str, Enum):
    IDLE          = "IDLE"
    CONNECTING    = "CONNECTING"
    CONNECTED     = "CONNECTED"
    RECONNECTING  = "RECONNECTING"
    DISCONNECTED  = "DISCONNECTED"
    STOPPED       = "STOPPED"
    ERROR         = "ERROR"


# ── Placeholder frame (used when no frame available) ──────────────────────────

def _make_placeholder(width: int = DEFAULT_WIDTH,
                      height: int = DEFAULT_HEIGHT,
                      camera_id: str = "") -> np.ndarray:
    """Grey frame with camera ID text overlay."""
    frame = np.full((height, width, 3), 40, dtype=np.uint8)
    # Grid lines
    for x in range(0, width, 80):
        cv2.line(frame, (x, 0), (x, height), (55, 55, 55), 1)
    for y in range(0, height, 60):
        cv2.line(frame, (0, y), (width, y), (55, 55, 55), 1)
    # Label
    cv2.putText(frame, f"CAM: {camera_id}", (20, height // 2 - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (120, 120, 120), 2)
    cv2.putText(frame, "NO SIGNAL", (20, height // 2 + 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 80, 80), 1)
    return frame


# ── MOCK frame generator ──────────────────────────────────────────────────────

_MOCK_COLORS = [
    (180, 60, 60), (60, 180, 60), (60, 60, 180),
    (180, 180, 60), (60, 180, 180), (180, 60, 180),
]
_mock_color_idx = 0

def _make_mock_frame(camera_id: str, sequence: int,
                     width: int = DEFAULT_WIDTH,
                     height: int = DEFAULT_HEIGHT) -> np.ndarray:
    global _mock_color_idx
    color = _MOCK_COLORS[_mock_color_idx % len(_MOCK_COLORS)]
    frame = np.full((height, width, 3), color, dtype=np.uint8)
    # Animated bar
    bar_x = int((sequence * 4) % width)
    cv2.rectangle(frame, (bar_x - 10, 0), (bar_x + 10, height), (255, 255, 255), -1)
    # Labels
    ts = datetime.now(tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3]
    cv2.putText(frame, f"MOCK | {camera_id}", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
    cv2.putText(frame, f"#{sequence}  {ts}", (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 1)
    _mock_color_idx += 1
    return frame


# ── CameraStream ──────────────────────────────────────────────────────────────

@dataclass
class CameraConfig:
    camera_id:  str
    cam_type:   CamType
    source:     str | int       # int for USB index, str for URL/path
    width:      int  = DEFAULT_WIDTH
    height:     int  = DEFAULT_HEIGHT
    fps:        float = DEFAULT_FPS_CAP
    username:   str  = ""
    password:   str  = ""
    extra:      Dict = field(default_factory=dict)

    # Convenience: inject credentials into RTSP URL
    def resolved_url(self) -> str:
        url = str(self.source)
        if self.username and "rtsp://" in url and "@" not in url:
            url = url.replace("rtsp://", f"rtsp://{self.username}:{self.password}@")
        return url


class CameraStream:
    """
    One camera, one thread.

    The thread runs _capture_loop() which:
      1. Opens the source (with retry on failure)
      2. Reads frames at up to cfg.fps
      3. Normalises each frame (resize + BGR check)
      4. Stores in self.latest_frame (thread-safe via RLock)
      5. Fires FRAME_READY via IntentBus
      6. On error, fires CAMERA_ERROR + retries after RECONNECT_DELAY
    """

    def __init__(self, cfg: CameraConfig):
        self.cfg    = cfg
        self.id     = cfg.camera_id

        # State
        self.status:    StreamStatus = StreamStatus.IDLE
        self._sequence: int          = 0
        self._reconnect_count: int   = 0
        self._last_frame_ts: float   = 0.0
        self._fps_actual: float      = 0.0

        # Frame storage
        self._lock       = threading.RLock()
        self.latest_frame: Optional[np.ndarray] = None
        self.frame_event = threading.Event()   # set whenever a new frame arrives

        # Control
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Stats
        self._frames_total:   int = 0
        self._frames_dropped: int = 0
        self._errors_total:   int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        """Start the capture thread."""
        if self._thread and self._thread.is_alive():
            logger.warning(f"[{self.id}] already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            name=f"cam-{self.id}",
            daemon=True,
        )
        self.status = StreamStatus.CONNECTING
        self._thread.start()
        logger.info(f"[{self.id}] capture thread started ({self.cfg.cam_type})")

    def stop(self, reason: str = "stopped"):
        """Signal the capture thread to stop and wait for it to exit."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=8.0)
        self.status = StreamStatus.STOPPED
        intent_bus.camera_disconnected(self.id, reason)
        logger.info(f"[{self.id}] stopped — {reason}")

    def get_latest_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def get_jpeg(self, quality: int = 80) -> Optional[bytes]:
        """Return latest frame encoded as JPEG bytes (for MJPEG / REST)."""
        frame = self.get_latest_frame()
        if frame is None:
            frame = _make_placeholder(self.cfg.width, self.cfg.height, self.id)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes() if ok else None

    def get_jpeg_b64(self, quality: int = 70) -> Optional[str]:
        """Return latest frame as base64-encoded JPEG (for WebSocket JSON)."""
        raw = self.get_jpeg(quality)
        return base64.b64encode(raw).decode() if raw else None

    def info(self) -> Dict:
        cap_w = self.cfg.width
        cap_h = self.cfg.height
        return {
            "camera_id":        self.id,
            "cam_type":         self.cfg.cam_type.value,
            "source":           str(self.cfg.source),
            "status":           self.status.value,
            "resolution":       [cap_w, cap_h],
            "fps_target":       self.cfg.fps,
            "fps_actual":       round(self._fps_actual, 1),
            "frames_total":     self._frames_total,
            "frames_dropped":   self._frames_dropped,
            "errors_total":     self._errors_total,
            "reconnect_count":  self._reconnect_count,
            "last_frame_ts":    self._last_frame_ts,
            "has_frame":        self.latest_frame is not None,
        }

    # ── Capture loop ──────────────────────────────────────────────────────────

    def _capture_loop(self):
        while not self._stop_event.is_set():
            cap = self._open_source()
            if cap is None:
                # Could not open — retry
                continue
            # Opened successfully
            self.status = StreamStatus.CONNECTED
            self._reconnect_count = 0
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)  or self.cfg.width)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or self.cfg.height)
            fps = cap.get(cv2.CAP_PROP_FPS) or self.cfg.fps
            intent_bus.camera_connected(
                self.id, self.cfg.cam_type.value,
                (w, h), fps,
                extra={"source": str(self.cfg.source)},
            )
            logger.info(f"[{self.id}] connected {w}×{h} @ {fps:.1f} fps")

            frame_interval = 1.0 / max(1.0, self.cfg.fps)
            last_frame_time = 0.0
            fps_bucket_start = time.monotonic()
            fps_bucket_count = 0

            while not self._stop_event.is_set():
                now = time.monotonic()
                elapsed = now - last_frame_time

                # Throttle to target FPS
                if elapsed < frame_interval:
                    time.sleep(frame_interval - elapsed)
                    continue

                ok, raw = cap.read()
                if not ok or raw is None:
                    logger.warning(f"[{self.id}] read failed — reconnecting")
                    self._frames_dropped += 1
                    intent_bus.camera_error(self.id, "read failure — reconnecting")
                    break   # Break inner loop → reconnect outer loop

                # Normalise
                frame = self._normalise(raw)
                ts = time.time()

                # Store
                with self._lock:
                    self.latest_frame = frame
                self.frame_event.set()
                self.frame_event.clear()

                # Emit intent
                self._sequence     += 1
                self._frames_total += 1
                self._last_frame_ts = ts
                last_frame_time     = now
                intent_bus.frame_ready(self.id, frame, self._sequence)

                # Rolling FPS measurement
                fps_bucket_count += 1
                bucket_elapsed = time.monotonic() - fps_bucket_start
                if bucket_elapsed >= 2.0:
                    self._fps_actual    = fps_bucket_count / bucket_elapsed
                    fps_bucket_count    = 0
                    fps_bucket_start    = time.monotonic()

            cap.release()
            if not self._stop_event.is_set():
                self.status = StreamStatus.RECONNECTING
                self._reconnect_count += 1
                intent_bus.camera_reconnecting(self.id, self._reconnect_count)
                logger.info(
                    f"[{self.id}] reconnect #{self._reconnect_count} "
                    f"in {RECONNECT_DELAY}s"
                )
                self._stop_event.wait(timeout=RECONNECT_DELAY)

        self.status = StreamStatus.STOPPED
        logger.info(f"[{self.id}] capture loop exited")

    def _open_source(self) -> Optional[cv2.VideoCapture]:
        """Open the camera source with retries. Returns None if stop requested."""

        # MOCK — synthetic frames, no hardware
        if self.cfg.cam_type == CamType.MOCK:
            return _MockCapture(self.cfg, self)     # type: ignore[return-value]

        self.status = StreamStatus.CONNECTING
        while not self._stop_event.is_set():
            try:
                src = (self.cfg.source
                       if self.cfg.cam_type == CamType.USB
                       else self.cfg.resolved_url())

                logger.info(f"[{self.id}] opening: {src}")
                cap = cv2.VideoCapture(src)

                # RTSP optimisation: minimal buffer → low latency
                if self.cfg.cam_type in (CamType.RTSP, CamType.ONVIF, CamType.HTTP):
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, RTSP_BUFFER_SZ)
                    # Prefer TCP for RTSP (more stable than UDP on lossy networks)
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"H264"))

                if cap.isOpened():
                    # Set desired resolution
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.cfg.width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
                    return cap

                cap.release()
                logger.warning(
                    f"[{self.id}] could not open source — retry in {RECONNECT_DELAY}s"
                )
                intent_bus.camera_error(self.id, f"could not open: {src}")

            except Exception as exc:
                self._errors_total += 1
                logger.error(f"[{self.id}] open error: {exc}")
                intent_bus.camera_error(self.id, str(exc))

            self._reconnect_count += 1
            intent_bus.camera_reconnecting(self.id, self._reconnect_count)
            self._stop_event.wait(timeout=RECONNECT_DELAY)

        return None

    def _normalise(self, frame: np.ndarray) -> np.ndarray:
        """Resize to target resolution and ensure 3-channel BGR."""
        h, w = frame.shape[:2]
        target_w, target_h = self.cfg.width, self.cfg.height

        # Resize only if needed (avoid unnecessary copy)
        if w != target_w or h != target_h:
            frame = cv2.resize(
                frame, (target_w, target_h),
                interpolation=cv2.INTER_LINEAR
            )

        # Ensure 3-channel BGR
        if len(frame.shape) == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        return frame


# ── MOCK capture (no hardware) ────────────────────────────────────────────────

class _MockCapture:
    """Quacks like cv2.VideoCapture but generates synthetic frames."""

    def __init__(self, cfg: CameraConfig, stream: CameraStream):
        self._cfg    = cfg
        self._stream = stream
        self._seq    = 0
        self._opened = True

    def isOpened(self) -> bool:
        return self._opened

    def get(self, prop_id: int) -> float:
        if prop_id == cv2.CAP_PROP_FRAME_WIDTH:  return float(self._cfg.width)
        if prop_id == cv2.CAP_PROP_FRAME_HEIGHT: return float(self._cfg.height)
        if prop_id == cv2.CAP_PROP_FPS:          return float(self._cfg.fps)
        return 0.0

    def set(self, *args):
        return True

    def read(self):
        self._seq += 1
        frame = _make_mock_frame(
            self._cfg.camera_id, self._seq,
            self._cfg.width, self._cfg.height
        )
        return True, frame

    def release(self):
        self._opened = False
