"""
CameraManager — orchestrates all CameraStream instances.

Responsibilities
────────────────
• Load camera configs from cameras.yaml / cameras.json at startup
• Assign unique IDs and start a CameraStream per camera
• Expose add_camera() / remove_camera() for runtime hot-swap
• Subscribe to IntentBus events and bridge them to:
    - the AI detection pipeline (FRAME_READY)
    - WebSocket clients     (CAMERA_CONNECTED / DISCONNECTED / ERROR)
• Run ONVIF auto-discovery if requested
• Provide get_all_info() for REST / dashboard listing
• Cleanly shut down all streams on stop()

Intent Layer rules
──────────────────
  • This module ONLY communicates via IntentBus; it never calls other
    services directly (scoring, alerts, storage, etc.).
  • External services subscribe to FRAME_READY / CAMERA_* intents
    through the bus — they never call CameraManager directly.
"""

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from app.camera.camera_stream import CameraConfig, CameraStream, CamType
from app.camera.intent_layer import IntentBus, IntentType, intent_bus

logger = logging.getLogger(__name__)

# ── Default config paths (searched in order) ─────────────────────────────────

# Search relative to the file's location first, then CWD
_HERE = Path(__file__).parent.parent.parent  # backend/
_CONFIG_SEARCH_PATHS = [
    _HERE / "cameras.yaml",
    _HERE / "cameras.json",
    Path("cameras.yaml"),
    Path("cameras.json"),
]


# ── CameraManager ─────────────────────────────────────────────────────────────

class CameraManager:
    """
    Manages the full lifecycle of all camera streams.

    Typical usage (in FastAPI lifespan):

        manager = CameraManager()
        await manager.start()         # loads config, starts streams, attaches bus
        yield
        await manager.stop()          # graceful shutdown
    """

    def __init__(self, config_path: Optional[str] = None):
        self._streams:     Dict[str, CameraStream] = {}
        self._lock         = threading.RLock()
        self._config_path  = config_path
        self._bus:         IntentBus = intent_bus
        self._frame_callbacks: List[Callable] = []  # AI pipeline callbacks

        # Metadata store (set by intent handlers)
        self._camera_meta: Dict[str, Dict] = {}

    # ── External AI pipeline wiring ───────────────────────────────────────────

    def register_frame_callback(self, cb: Callable):
        """
        Register a coroutine to receive every FRAME_READY intent payload.
        The callback signature: async def cb(frame_payload: dict)
        where frame_payload = {camera_id, frame(np.ndarray), sequence, timestamp}
        """
        self._frame_callbacks.append(cb)
        logger.info(f"CameraManager: frame callback registered → {cb.__name__}")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self):
        """Attach IntentBus, load config, start streams."""
        loop = asyncio.get_event_loop()
        self._bus.attach_loop(loop)
        self._subscribe_intents()

        configs = self._load_config()
        if configs:
            logger.info(f"CameraManager: loaded {len(configs)} camera config(s)")
            for cfg_dict in configs:
                try:
                    self._start_from_dict(cfg_dict)
                except Exception as exc:
                    logger.error(f"CameraManager: failed to start camera from config: {exc}")
        else:
            # No config found — start two MOCK cameras so the dashboard has live feeds
            logger.info("CameraManager: no camera config found — starting 2 MOCK cameras")
            self._start_from_dict({"camera_id": "mock_cam_1", "cam_type": "MOCK",
                                   "source": "mock://0", "width": 1280, "height": 720, "fps": 10})
            self._start_from_dict({"camera_id": "mock_cam_2", "cam_type": "MOCK",
                                   "source": "mock://1", "width": 1280, "height": 720, "fps": 10})

        logger.info(f"CameraManager: {len(self._streams)} stream(s) running")

    async def stop(self):
        """Stop all camera streams gracefully."""
        logger.info("CameraManager: stopping all streams...")
        with self._lock:
            ids = list(self._streams.keys())

        for cam_id in ids:
            await self._stop_stream(cam_id, reason="shutdown")

        logger.info("CameraManager: all streams stopped")

    # ── Public API — add / remove ─────────────────────────────────────────────

    async def add_camera(self,
                         camera_id: str,
                         cam_type:  str,
                         source:    Any,
                         width:     int   = 1280,
                         height:    int   = 720,
                         fps:       float = 15.0,
                         username:  str   = "",
                         password:  str   = "",
                         extra:     Dict  = None) -> Dict:
        """
        Add and start a new camera at runtime.
        Returns info dict or raises ValueError if ID already exists.
        """
        with self._lock:
            if camera_id in self._streams:
                raise ValueError(f"Camera '{camera_id}' already exists")

        self._start_from_dict({
            "camera_id": camera_id,
            "cam_type":  cam_type,
            "source":    source,
            "width":     width,
            "height":    height,
            "fps":       fps,
            "username":  username,
            "password":  password,
            "extra":     extra or {},
        })

        logger.info(f"CameraManager: added camera '{camera_id}' ({cam_type})")
        self._emit_list_changed()
        return self.get_camera_info(camera_id)

    async def remove_camera(self, camera_id: str) -> bool:
        """Stop and remove a camera. Returns True if found and removed."""
        with self._lock:
            if camera_id not in self._streams:
                return False

        await self._stop_stream(camera_id, reason="removed by user")
        self._emit_list_changed()
        logger.info(f"CameraManager: removed camera '{camera_id}'")
        return True

    async def restart_camera(self, camera_id: str) -> Optional[Dict]:
        """Restart an existing camera stream."""
        with self._lock:
            stream = self._streams.get(camera_id)
        if stream is None:
            return None

        cfg_dict = {
            "camera_id": stream.cfg.camera_id,
            "cam_type":  stream.cfg.cam_type.value,
            "source":    stream.cfg.source,
            "width":     stream.cfg.width,
            "height":    stream.cfg.height,
            "fps":       stream.cfg.fps,
            # credentials kept internal — not exposed to API layer
            "username":  stream.cfg.username,
            "password":  stream.cfg.password,
            "extra":     stream.cfg.extra,
        }

        await self._stop_stream(camera_id, reason="restart")
        self._start_from_dict(cfg_dict)
        logger.info(f"CameraManager: restarted camera '{camera_id}'")
        return self.get_camera_info(camera_id)

    # ── ONVIF discovery ───────────────────────────────────────────────────────

    async def discover_onvif(self, username: str = "",
                              password: str = "") -> List[Dict]:
        """
        Run ONVIF/WS-Discovery on the local network and add found cameras.
        Returns list of added camera info dicts.
        """
        from app.camera.onvif_discovery import ONVIFDiscovery
        discovery = ONVIFDiscovery(username=username, password=password)
        found = await discovery.discover()

        added = []
        for cfg_dict in found:
            cam_id = cfg_dict["camera_id"]
            if cam_id not in self._streams:
                try:
                    info = await self.add_camera(**cfg_dict)
                    added.append(info)
                except Exception as exc:
                    logger.warning(f"CameraManager: could not add discovered cam {cam_id}: {exc}")
            else:
                logger.debug(f"CameraManager: ONVIF cam {cam_id} already registered")

        logger.info(f"CameraManager: ONVIF discovery added {len(added)} new camera(s)")
        return added

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_camera_info(self, camera_id: str) -> Optional[Dict]:
        with self._lock:
            stream = self._streams.get(camera_id)
        if stream is None:
            return None
        info = stream.info()
        info["meta"] = self._camera_meta.get(camera_id, {})
        return info

    def get_all_info(self) -> List[Dict]:
        with self._lock:
            ids = list(self._streams.keys())
        return [self.get_camera_info(i) for i in ids if self.get_camera_info(i)]

    def get_camera_count(self) -> int:
        with self._lock:
            return len(self._streams)

    def get_stream(self, camera_id: str) -> Optional[CameraStream]:
        """Return raw CameraStream (for direct JPEG/frame access)."""
        with self._lock:
            return self._streams.get(camera_id)

    def get_jpeg(self, camera_id: str, quality: int = 80) -> Optional[bytes]:
        stream = self.get_stream(camera_id)
        return stream.get_jpeg(quality) if stream else None

    def get_jpeg_b64(self, camera_id: str, quality: int = 70) -> Optional[str]:
        stream = self.get_stream(camera_id)
        return stream.get_jpeg_b64(quality) if stream else None

    def get_latest_frame(self, camera_id: str):
        stream = self.get_stream(camera_id)
        return stream.get_latest_frame() if stream else None

    # ── Intent subscriptions ──────────────────────────────────────────────────

    def _subscribe_intents(self):
        """Register all IntentBus handlers."""
        self._bus.subscribe(IntentType.CAMERA_CONNECTED,    self._on_camera_connected)
        self._bus.subscribe(IntentType.CAMERA_DISCONNECTED, self._on_camera_disconnected)
        self._bus.subscribe(IntentType.CAMERA_ERROR,        self._on_camera_error)
        self._bus.subscribe(IntentType.CAMERA_RECONNECTING, self._on_camera_reconnecting)
        self._bus.subscribe(IntentType.FRAME_READY,         self._on_frame_ready)
        logger.debug("CameraManager: intent handlers registered")

    async def _on_camera_connected(self, intent):
        p = intent.payload
        cam_id = p["camera_id"]
        self._camera_meta[cam_id] = {
            "connected_at":  intent.ts_iso(),
            "resolution":    p.get("resolution"),
            "fps":           p.get("fps"),
            "cam_type":      p.get("cam_type"),
        }
        logger.info(
            f"[INTENT] CAMERA_CONNECTED: {cam_id} "
            f"{p.get('resolution')} @ {p.get('fps')} fps"
        )
        await self._ws_broadcast("cameras", {
            "type":       "CAMERA_CONNECTED",
            "camera_id":  cam_id,
            "cam_type":   p.get("cam_type"),
            "resolution": p.get("resolution"),
            "fps":        p.get("fps"),
            "timestamp":  intent.ts_iso(),
        })

    async def _on_camera_disconnected(self, intent):
        p = intent.payload
        cam_id = p["camera_id"]
        logger.info(f"[INTENT] CAMERA_DISCONNECTED: {cam_id} ({p.get('reason','')})")
        await self._ws_broadcast("cameras", {
            "type":      "CAMERA_DISCONNECTED",
            "camera_id": cam_id,
            "reason":    p.get("reason", ""),
            "timestamp": intent.ts_iso(),
        })

    async def _on_camera_error(self, intent):
        p = intent.payload
        logger.warning(f"[INTENT] CAMERA_ERROR: {p['camera_id']} — {p.get('error','')}")
        await self._ws_broadcast("cameras", {
            "type":      "CAMERA_ERROR",
            "camera_id": p["camera_id"],
            "error":     p.get("error", ""),
            "timestamp": intent.ts_iso(),
        })

    async def _on_camera_reconnecting(self, intent):
        p = intent.payload
        logger.info(
            f"[INTENT] CAMERA_RECONNECTING: {p['camera_id']} "
            f"attempt #{p.get('attempt', '?')}"
        )

    async def _on_frame_ready(self, intent):
        """
        Bridge FRAME_READY intent to registered AI pipeline callbacks.
        The frame numpy array is passed directly (in-process, no serialisation).
        """
        if not self._frame_callbacks:
            return
        p = intent.payload
        for cb in self._frame_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(p)
                else:
                    cb(p)
            except Exception as exc:
                logger.error(f"CameraManager: frame callback error: {exc}", exc_info=True)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _start_from_dict(self, d: Dict):
        """Build CameraConfig and start a CameraStream."""
        cam_type_str = str(d.get("cam_type", "MOCK")).upper()
        try:
            cam_type = CamType(cam_type_str)
        except ValueError:
            logger.warning(f"Unknown cam_type '{cam_type_str}' — defaulting to MOCK")
            cam_type = CamType.MOCK

        source = d.get("source", "mock://0")
        # USB: source should be an integer index
        if cam_type == CamType.USB:
            try:
                source = int(source)
            except (TypeError, ValueError):
                pass

        cfg = CameraConfig(
            camera_id = d["camera_id"],
            cam_type  = cam_type,
            source    = source,
            width     = int(d.get("width",  1280)),
            height    = int(d.get("height", 720)),
            fps       = float(d.get("fps",  15.0)),
            username  = d.get("username", ""),
            password  = d.get("password", ""),
            extra     = d.get("extra",    {}),
        )

        stream = CameraStream(cfg)
        with self._lock:
            self._streams[cfg.camera_id] = stream
        stream.start()

    async def _stop_stream(self, camera_id: str, reason: str = ""):
        """Stop and remove a stream. Run stream.stop() in executor (it blocks)."""
        with self._lock:
            stream = self._streams.pop(camera_id, None)
        if stream:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, stream.stop, reason)

    def _emit_list_changed(self):
        self._bus.camera_list_changed(self.get_all_info())

    @staticmethod
    async def _ws_broadcast(topic: str, payload: Dict):
        """Best-effort broadcast to WebSocket clients."""
        try:
            from app.core.websocket import manager as ws_manager
            await ws_manager.broadcast(topic, payload)
        except Exception as exc:
            logger.debug(f"CameraManager: WS broadcast failed: {exc}")

    # ── Config loading ────────────────────────────────────────────────────────

    def _load_config(self) -> List[Dict]:
        """
        Load camera definitions from cameras.yaml or cameras.json.
        Returns empty list if no config found (caller falls back to MOCK).
        """
        # 1. Explicit path
        if self._config_path:
            return self._parse_config_file(Path(self._config_path))

        # 2. Search known paths
        for p in _CONFIG_SEARCH_PATHS:
            if p.exists():
                logger.info(f"CameraManager: using config file: {p}")
                return self._parse_config_file(p)

        # 3. Environment variable
        env_path = os.environ.get("RBIS_CAMERAS_CONFIG")
        if env_path:
            p = Path(env_path)
            if p.exists():
                return self._parse_config_file(p)
            logger.warning(f"CameraManager: RBIS_CAMERAS_CONFIG not found: {env_path}")

        logger.info("CameraManager: no cameras config file found")
        return []

    @staticmethod
    def _parse_config_file(path: Path) -> List[Dict]:
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix.lower() in (".yaml", ".yml"):
                data = yaml.safe_load(text)
            else:
                data = json.loads(text)

            cameras = data.get("cameras", data) if isinstance(data, dict) else data
            if not isinstance(cameras, list):
                logger.warning(f"CameraManager: config root should be a list or dict with 'cameras' key")
                return []

            logger.info(f"CameraManager: parsed {len(cameras)} camera(s) from {path}")
            return cameras
        except Exception as exc:
            logger.error(f"CameraManager: failed to parse {path}: {exc}")
            return []


# ── Module-level singleton ────────────────────────────────────────────────────

camera_manager = CameraManager()
