"""
Intent Layer — the ONLY communication channel between the camera system
and the rest of the pipeline (AI, dashboard, storage).

Rules:
  • Camera code fires intents; it NEVER calls other services directly.
  • Consumers register handlers; they NEVER call camera code directly.
  • All payloads are plain dicts → serializable, loggable, testable.

Intent types
────────────
  CAMERA_CONNECTED    camera_id, cam_type, resolution, fps, timestamp
  CAMERA_DISCONNECTED camera_id, timestamp, reason
  CAMERA_ERROR        camera_id, error, timestamp
  CAMERA_RECONNECTING camera_id, attempt, timestamp
  FRAME_READY         camera_id, frame(np.ndarray), timestamp, sequence
  FRAME_DROPPED       camera_id, timestamp, reason
  CAMERA_LIST_CHANGED cameras (list of summaries)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ── Intent type constants ──────────────────────────────────────────────────────

class IntentType(str, Enum):
    CAMERA_CONNECTED    = "CAMERA_CONNECTED"
    CAMERA_DISCONNECTED = "CAMERA_DISCONNECTED"
    CAMERA_ERROR        = "CAMERA_ERROR"
    CAMERA_RECONNECTING = "CAMERA_RECONNECTING"
    FRAME_READY         = "FRAME_READY"
    FRAME_DROPPED       = "FRAME_DROPPED"
    CAMERA_LIST_CHANGED = "CAMERA_LIST_CHANGED"


@dataclass
class Intent:
    """Immutable intent envelope."""
    type: IntentType
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)

    def ts_iso(self) -> str:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat()

    def __repr__(self):
        cam = self.payload.get("camera_id", "?")
        return f"<Intent {self.type.value} cam={cam} ts={self.timestamp:.3f}>"


# ── Handler types ──────────────────────────────────────────────────────────────

SyncHandler  = Callable[[Intent], None]
AsyncHandler = Callable[[Intent], Coroutine]
Handler      = SyncHandler | AsyncHandler


# ── Intent Bus ────────────────────────────────────────────────────────────────

class IntentBus:
    """
    Lightweight publish/subscribe bus.
    • Handlers can be sync or async coroutines.
    • Wildcard subscription via subscribe("*").
    • Dispatch is always async (call from event loop).
    • Thread-safe: fire_from_thread() posts to the loop.
    """

    def __init__(self):
        self._handlers: Dict[str, List[Handler]] = {}   # type → [handler]
        self._loop:     Optional[asyncio.AbstractEventLoop] = None
        self._queue:    asyncio.Queue = None             # set in attach_loop
        self._stats:    Dict[str, int] = {}              # type → fire count

    # ── Setup ─────────────────────────────────────────────────────────────────

    def attach_loop(self, loop: asyncio.AbstractEventLoop):
        """Call once after the event loop is running."""
        self._loop  = loop
        self._queue = asyncio.Queue()
        logger.info("IntentBus: attached to event loop — ready")

    # ── Subscribe ─────────────────────────────────────────────────────────────

    def subscribe(self, intent_type: str | IntentType, handler: Handler):
        """
        Register a handler for an intent type.
        Use "*" to receive every intent.
        """
        key = intent_type.value if isinstance(intent_type, IntentType) else intent_type
        self._handlers.setdefault(key, []).append(handler)
        logger.debug(f"IntentBus: subscribed {handler.__name__} → {key}")

    def unsubscribe(self, intent_type: str | IntentType, handler: Handler):
        key = intent_type.value if isinstance(intent_type, IntentType) else intent_type
        handlers = self._handlers.get(key, [])
        if handler in handlers:
            handlers.remove(handler)

    # ── Fire (async, from event loop) ─────────────────────────────────────────

    async def fire(self, intent: Intent):
        """Dispatch intent to all registered handlers immediately."""
        self._stats[intent.type.value] = self._stats.get(intent.type.value, 0) + 1

        # Collect handlers: exact match + wildcard
        handlers: List[Handler] = (
            list(self._handlers.get(intent.type.value, []))
            + list(self._handlers.get("*", []))
        )

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(intent)
                else:
                    handler(intent)
            except Exception as exc:
                logger.error(
                    f"IntentBus: handler {getattr(handler, '__name__', handler)} "
                    f"failed for {intent}: {exc}",
                    exc_info=True,
                )

    # ── Fire (thread-safe, from background threads) ───────────────────────────

    def fire_from_thread(self, intent: Intent):
        """
        Thread-safe: enqueue an intent to be dispatched on the event loop.
        Call from non-async camera capture threads.
        """
        if self._loop is None:
            logger.warning(f"IntentBus: no loop — dropping {intent}")
            return
        asyncio.run_coroutine_threadsafe(self.fire(intent), self._loop)

    # ── Convenience constructors ──────────────────────────────────────────────

    def camera_connected(self, camera_id: str, cam_type: str,
                         resolution: tuple, fps: float, extra: Dict = None):
        self.fire_from_thread(Intent(
            type=IntentType.CAMERA_CONNECTED,
            payload={
                "camera_id":  camera_id,
                "cam_type":   cam_type,
                "resolution": list(resolution),
                "fps":        fps,
                **(extra or {}),
            }
        ))

    def camera_disconnected(self, camera_id: str, reason: str = ""):
        self.fire_from_thread(Intent(
            type=IntentType.CAMERA_DISCONNECTED,
            payload={"camera_id": camera_id, "reason": reason}
        ))

    def camera_error(self, camera_id: str, error: str):
        self.fire_from_thread(Intent(
            type=IntentType.CAMERA_ERROR,
            payload={"camera_id": camera_id, "error": error}
        ))

    def camera_reconnecting(self, camera_id: str, attempt: int):
        self.fire_from_thread(Intent(
            type=IntentType.CAMERA_RECONNECTING,
            payload={"camera_id": camera_id, "attempt": attempt}
        ))

    def frame_ready(self, camera_id: str, frame, sequence: int):
        """Called from capture thread — low overhead path."""
        self.fire_from_thread(Intent(
            type=IntentType.FRAME_READY,
            payload={
                "camera_id": camera_id,
                "frame":     frame,
                "sequence":  sequence,
            }
        ))

    def frame_dropped(self, camera_id: str, reason: str):
        self.fire_from_thread(Intent(
            type=IntentType.FRAME_DROPPED,
            payload={"camera_id": camera_id, "reason": reason}
        ))

    def camera_list_changed(self, cameras: List[Dict]):
        self.fire_from_thread(Intent(
            type=IntentType.CAMERA_LIST_CHANGED,
            payload={"cameras": cameras}
        ))

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, int]:
        return dict(self._stats)


# ── Singleton bus ─────────────────────────────────────────────────────────────

intent_bus = IntentBus()
