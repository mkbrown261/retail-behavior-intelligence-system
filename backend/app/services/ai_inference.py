"""
ai_inference.py — YOLOv8-nano person detection + behavior analysis engine.

Architecture (Hybrid Option C):
  • YOLOv8-nano runs 100% locally — zero cost per inference
  • Per-person state machine derives behavior events from bbox sequences
  • LLM (Claude / Grok / Llama) called ONLY for high-suspicion alert explanations
    (wired in Sprint 3 — stub here returns a plain description)

Detection → Behavior pipeline
──────────────────────────────
  1. YOLO detects all persons in a frame → list of bboxes + confidence
  2. Simple IoU tracker assigns track IDs across frames (no DeepSORT dep)
  3. Per-track BehaviorAnalyzer watches bbox velocity/dwell → emits events:
       ENTER_STORE, PICK_ITEM, HOLD_ITEM, LOITER, RAPID_MOVEMENT,
       BYPASS_REGISTER, APPROACH_REGISTER, EXIT_STORE
  4. Each event becomes a detection dict → handle_detection() in orchestrator

Performance targets (MacBook Air M-series CPU):
  • YOLOv8-nano: ~8–15ms/frame at 640px (well under 30fps budget)
  • Behavior logic: <1ms/frame (pure Python, no GPU needed)
  • Total overhead: <20ms/frame → safe at 10fps processing
"""

import logging
import os
import time
import threading
import urllib.request
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ── Model configuration ────────────────────────────────────────────────────────

# yolov8n.pt — 6 MB, person detection class 0, ~8ms/frame on CPU
MODEL_URLS = [
    "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt",
]
# Default model path — configurable via env var YOLO_MODEL_PATH
DEFAULT_MODEL_PATH = os.environ.get(
    "YOLO_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "yolov8n.pt")
)

PERSON_CLASS_ID   = 0       # COCO class 0 = person
CONFIDENCE_THRESH = 0.40    # min detection confidence
NMS_IOU_THRESH    = 0.45    # NMS IoU threshold
INFERENCE_SIZE    = 640     # input resolution for YOLO (square)

# ── Tracker configuration ──────────────────────────────────────────────────────

IOU_MATCH_THRESH  = 0.30    # min IoU to match track across frames
MAX_MISSED_FRAMES = 15      # frames before track is dropped
MIN_CONFIRM_HITS  = 2       # frames before track is "confirmed" (avoids noise)

# ── Behavior thresholds ────────────────────────────────────────────────────────

LOITER_FRAMES        = 25   # frames stationary in same zone → LOITER event
RAPID_MOVE_THRESH    = 0.12 # normalized position delta/frame → RAPID_MOVEMENT
PICK_ITEM_DWELL      = 8    # frames bbox overlaps "shelf zone" → PICK_ITEM
BYPASS_ZONE_THRESH   = 0.75 # x > 75% of frame without register zone → BYPASS
HOLD_ITEM_INTERVAL   = 30   # emit HOLD_ITEM every N frames while holding
EXIT_ZONE_X          = 0.85 # x > 85% = near exit
REGISTER_ZONE_X      = (0.15, 0.55)  # x range of register zone


# ── IoU helper ────────────────────────────────────────────────────────────────

def _iou(a: List[float], b: List[float]) -> float:
    """Compute intersection-over-union of two [x1,y1,x2,y2] boxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1); iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2); iy2 = min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter == 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / (area_a + area_b - inter)


def _bbox_center(box: List[float]) -> Tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _dominant_color_from_bbox(
    frame: np.ndarray, box: List[float]
) -> str:
    """Extract dominant BGR color from the torso region of a bounding box."""
    h, w = frame.shape[:2]
    x1 = int(box[0] * w); y1 = int(box[1] * h)
    x2 = int(box[2] * w); y2 = int(box[3] * h)
    # Torso: middle third vertically, middle half horizontally
    ty1 = y1 + (y2 - y1) // 3
    ty2 = y1 + 2 * (y2 - y1) // 3
    tx1 = x1 + (x2 - x1) // 4
    tx2 = x2 - (x2 - x1) // 4
    roi = frame[ty1:ty2, tx1:tx2]
    if roi.size == 0:
        return "#888888"
    # Mean BGR → hex
    mean_bgr = roi.reshape(-1, 3).mean(axis=0).astype(int)
    b, g, r = int(mean_bgr[0]), int(mean_bgr[1]), int(mean_bgr[2])
    return f"#{r:02X}{g:02X}{b:02X}"


# ── Per-track behavior state machine ──────────────────────────────────────────

@dataclass
class TrackState:
    track_id:       int
    session_id:     str
    camera_id:      str
    confirmed:      bool  = False
    hits:           int   = 0
    missed:         int   = 0
    age:            int   = 0   # total frames seen

    bbox:           List[float] = field(default_factory=lambda: [0,0,0,0])
    prev_center:    Optional[Tuple[float,float]] = None

    # Behavior counters
    stationary_frames:  int   = 0
    shelf_dwell_frames: int   = 0
    holding_frames:     int   = 0
    hold_event_emitted: int   = 0  # how many HOLD_ITEM events emitted
    items_held:         int   = 0
    visited_register:   bool  = False
    entered_store:      bool  = False
    exited:             bool  = False

    # Dominant color (updated periodically)
    dominant_color: str = "#888888"

    # Position history for velocity calc
    center_history: deque = field(default_factory=lambda: deque(maxlen=10))


class BehaviorAnalyzer:
    """
    Converts raw bbox observations into semantic retail behavior events.
    One instance per active track.
    """

    def __init__(self, state: TrackState):
        self.s = state

    def update(
        self,
        bbox: List[float],
        frame: np.ndarray,
        frame_w: int,
        frame_h: int,
    ) -> List[Dict]:
        """
        Feed new bbox observation; return list of event dicts to emit.
        All bbox coords are normalized [0,1].
        """
        s = self.s
        s.bbox = bbox
        cx, cy = _bbox_center(bbox)
        s.center_history.append((cx, cy))
        s.hits   += 1
        s.missed  = 0
        s.age    += 1

        # Confirm track after MIN_CONFIRM_HITS
        if not s.confirmed and s.hits >= MIN_CONFIRM_HITS:
            s.confirmed = True

        if not s.confirmed:
            return []

        events = []

        # ── ENTER_STORE (once, first confirmed frame) ──────────────────────
        if not s.entered_store:
            s.entered_store = True
            # Sample dominant color
            s.dominant_color = _dominant_color_from_bbox(frame, bbox)
            events.append(self._make_event("ENTER_STORE", bbox, cx, cy, frame_w, frame_h))
            return events  # nothing else on entry frame

        # ── Update dominant color every 30 frames ─────────────────────────
        if s.age % 30 == 0:
            s.dominant_color = _dominant_color_from_bbox(frame, bbox)

        # ── Velocity (normalized per frame) ───────────────────────────────
        velocity = 0.0
        if s.prev_center:
            dx = cx - s.prev_center[0]
            dy = cy - s.prev_center[1]
            velocity = (dx**2 + dy**2) ** 0.5
        s.prev_center = (cx, cy)

        # ── Zone detection ────────────────────────────────────────────────
        in_shelf_zone = (0.15 < cx < 0.75) and (cy < 0.75)  # not near exit/checkout
        in_register_zone = REGISTER_ZONE_X[0] < cx < REGISTER_ZONE_X[1] and cy > 0.65
        near_exit = cx > EXIT_ZONE_X

        # ── RAPID_MOVEMENT ────────────────────────────────────────────────
        if velocity > RAPID_MOVE_THRESH:
            s.stationary_frames = 0
            events.append(self._make_event(
                "RAPID_MOVEMENT", bbox, cx, cy, frame_w, frame_h,
                extra={"velocity": round(velocity, 4)}
            ))

        # ── LOITER (stationary in shelf zone) ────────────────────────────
        elif velocity < 0.008 and in_shelf_zone:
            s.stationary_frames += 1
            if s.stationary_frames == LOITER_FRAMES:
                events.append(self._make_event(
                    "LOITER", bbox, cx, cy, frame_w, frame_h,
                    extra={"dwell_frames": s.stationary_frames}
                ))
        else:
            s.stationary_frames = max(0, s.stationary_frames - 1)

        # ── PICK_ITEM (dwell near shelves) ────────────────────────────────
        if in_shelf_zone and velocity < 0.015:
            s.shelf_dwell_frames += 1
            if s.shelf_dwell_frames == PICK_ITEM_DWELL:
                s.items_held += 1
                s.holding_frames = 0
                s.hold_event_emitted = 0
                events.append(self._make_event(
                    "PICK_ITEM", bbox, cx, cy, frame_w, frame_h
                ))
        else:
            s.shelf_dwell_frames = max(0, s.shelf_dwell_frames - 3)

        # ── HOLD_ITEM (still carrying after pick) ────────────────────────
        if s.items_held > 0:
            s.holding_frames += 1
            hold_threshold = HOLD_ITEM_INTERVAL * (s.hold_event_emitted + 1)
            if s.holding_frames >= hold_threshold:
                s.hold_event_emitted += 1
                duration_seconds = s.holding_frames / 10.0  # ~10fps
                events.append(self._make_event(
                    "HOLD_ITEM", bbox, cx, cy, frame_w, frame_h,
                    extra={"duration_seconds": round(duration_seconds, 1)}
                ))

        # ── APPROACH_REGISTER ────────────────────────────────────────────
        if in_register_zone and not s.visited_register:
            s.visited_register = True
            events.append(self._make_event(
                "APPROACH_REGISTER", bbox, cx, cy, frame_w, frame_h
            ))

        # ── BYPASS_REGISTER (has items, passes register zone x-range) ────
        if (s.items_held > 0
                and not s.visited_register
                and cx > REGISTER_ZONE_X[1] + 0.05
                and near_exit):
            events.append(self._make_event(
                "BYPASS_REGISTER", bbox, cx, cy, frame_w, frame_h
            ))

        # ── EXIT_STORE ────────────────────────────────────────────────────
        if near_exit and not s.exited:
            s.exited = True
            events.append(self._make_event(
                "EXIT_STORE", bbox, cx, cy, frame_w, frame_h
            ))

        return events

    def _make_event(
        self,
        event_type: str,
        bbox: List[float],
        cx: float, cy: float,
        frame_w: int, frame_h: int,
        extra: Dict = None,
    ) -> Dict:
        s = self.s
        det = {
            "session_id":     s.session_id,
            "event_type":     event_type,
            "camera_id":      s.camera_id,   # STRING — matches cameras.yaml
            "bounding_box":   [round(v, 4) for v in bbox],
            "position_x":     round(cx, 4),
            "position_y":     round(cy, 4),
            "confidence":     0.90,          # behavior confidence (not YOLO conf)
            "zone":           _cx_to_zone(cx, cy),
            "dominant_color": s.dominant_color,
            "is_staff":       False,         # staff detection: Sprint 3
            "timestamp":      datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            det.update(extra)
        return det


def _cx_to_zone(cx: float, cy: float) -> str:
    """Map normalized centroid to store zone name."""
    if cx < 0.15:
        return "ENTRANCE"
    if cy > 0.70 and 0.15 < cx < 0.80:
        return "CHECKOUT"
    if cx > 0.82:
        return "EXIT"
    if cx < 0.35:
        return "AISLE_A"
    if cx < 0.58:
        return "AISLE_B"
    return "AISLE_C"


# ── Simple IoU tracker ────────────────────────────────────────────────────────

class IoUTracker:
    """
    Lightweight multi-object tracker using IoU matching.
    No external dependencies (no DeepSORT / ByteTrack install needed).
    Sufficient for store-scale scenes (<15 persons simultaneously).
    """

    def __init__(self, camera_id: str):
        self.camera_id   = camera_id
        self._next_id    = 1
        self._tracks:    Dict[int, TrackState] = {}
        self._analyzers: Dict[int, BehaviorAnalyzer] = {}

    def update(
        self,
        detections: List[Tuple[List[float], float]],  # [(bbox_norm, conf), ...]
        frame: np.ndarray,
        frame_w: int,
        frame_h: int,
    ) -> List[Dict]:
        """
        Match detections to existing tracks via IoU greedy matching.
        Returns list of behavior event dicts to pass to handle_detection().
        """
        events = []

        # ── Mark all tracks as "not matched yet" ──────────────────────────
        unmatched_tracks = set(self._tracks.keys())

        matched_pairs = []  # (track_id, det_idx)

        # Greedy IoU matching
        for det_idx, (det_box, det_conf) in enumerate(detections):
            best_iou   = IOU_MATCH_THRESH
            best_track = None
            for tid in list(unmatched_tracks):
                iou = _iou(self._tracks[tid].bbox, det_box)
                if iou > best_iou:
                    best_iou   = iou
                    best_track = tid
            if best_track is not None:
                matched_pairs.append((best_track, det_idx))
                unmatched_tracks.discard(best_track)

        # ── Update matched tracks ──────────────────────────────────────────
        matched_det_indices = set()
        for tid, det_idx in matched_pairs:
            bbox, conf = detections[det_idx]
            evts = self._analyzers[tid].update(bbox, frame, frame_w, frame_h)
            events.extend(evts)
            self._tracks[tid].missed = 0
            matched_det_indices.add(det_idx)

        # ── Increment missed counter for unmatched tracks ──────────────────
        for tid in unmatched_tracks:
            self._tracks[tid].missed += 1
            self._tracks[tid].age    += 1

        # ── Create new tracks for unmatched detections ────────────────────
        for det_idx, (det_box, det_conf) in enumerate(detections):
            if det_idx in matched_det_indices:
                continue
            tid        = self._next_id
            self._next_id += 1
            session_id = f"CAM{self.camera_id[-4:] if len(self.camera_id) > 4 else self.camera_id}_T{tid:04d}"
            state      = TrackState(
                track_id=tid,
                session_id=session_id,
                camera_id=self.camera_id,
                bbox=det_box,
            )
            self._tracks[tid]    = state
            self._analyzers[tid] = BehaviorAnalyzer(state)

        # ── Drop stale tracks & emit EXIT_STORE if needed ─────────────────
        stale = [
            tid for tid, t in self._tracks.items()
            if t.missed > MAX_MISSED_FRAMES
        ]
        for tid in stale:
            state = self._tracks[tid]
            if state.confirmed and state.entered_store and not state.exited:
                # Person left field of view without EXIT_STORE → emit it
                cx, cy = _bbox_center(state.bbox)
                events.append(
                    self._analyzers[tid]._make_event(
                        "EXIT_STORE", state.bbox, cx, cy, frame_w, frame_h
                    )
                )
            del self._tracks[tid]
            del self._analyzers[tid]

        return events

    def active_count(self) -> int:
        return sum(1 for t in self._tracks.values() if t.confirmed)


# ── YOLOv8 Inference Engine ───────────────────────────────────────────────────

class YOLOInferenceEngine:
    """
    Wraps YOLOv8-nano for person detection.
    Lazy-loads the model on first use; thread-safe singleton per camera.

    Usage:
        engine = YOLOInferenceEngine()
        engine.ensure_loaded()                    # call once at startup
        detections = engine.detect(frame)         # returns [(bbox_norm, conf), ...]
    """

    _instance_lock = threading.Lock()
    _model         = None     # shared across all cameras (model is thread-safe for inference)
    _model_path    = None

    @classmethod
    def ensure_loaded(cls, model_path: Optional[str] = None) -> bool:
        """Load (or download) the YOLO model. Returns True on success."""
        with cls._instance_lock:
            if cls._model is not None:
                return True

            path = model_path or DEFAULT_MODEL_PATH
            os.makedirs(os.path.dirname(path), exist_ok=True)

            # Download if missing
            if not os.path.exists(path):
                logger.info(f"YOLOv8n model not found at {path} — downloading (~6 MB)...")
                for url in MODEL_URLS:
                    try:
                        urllib.request.urlretrieve(url, path)
                        logger.info(f"Downloaded YOLOv8n → {path}")
                        break
                    except Exception as e:
                        logger.warning(f"Download from {url} failed: {e}")

            if not os.path.exists(path):
                logger.error("YOLOv8n model could not be downloaded — AI detection disabled")
                return False

            try:
                from ultralytics import YOLO
                cls._model      = YOLO(path)
                cls._model_path = path
                # Warm up with a blank frame to pre-compile
                warm = np.zeros((INFERENCE_SIZE, INFERENCE_SIZE, 3), dtype=np.uint8)
                cls._model(warm, verbose=False, classes=[PERSON_CLASS_ID])
                logger.info(f"✅ YOLOv8n loaded and warmed up from {path}")
                return True
            except Exception as e:
                logger.error(f"Failed to load YOLO model: {e}", exc_info=True)
                return False

    @classmethod
    def detect(cls, frame: np.ndarray) -> List[Tuple[List[float], float]]:
        """
        Run YOLOv8 inference on a BGR frame.
        Returns list of (bbox_normalized [x1,y1,x2,y2], confidence) for persons only.
        bbox coords are normalized to [0,1] relative to frame size.
        """
        if cls._model is None:
            return []

        h, w = frame.shape[:2]
        try:
            results = cls._model(
                frame,
                verbose=False,
                conf=CONFIDENCE_THRESH,
                iou=NMS_IOU_THRESH,
                classes=[PERSON_CLASS_ID],
                imgsz=INFERENCE_SIZE,
            )
            detections = []
            for r in results:
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf[0])
                    # Normalize
                    bbox_norm = [
                        round(x1 / w, 4), round(y1 / h, 4),
                        round(x2 / w, 4), round(y2 / h, 4),
                    ]
                    detections.append((bbox_norm, conf))
            return detections
        except Exception as e:
            logger.error(f"YOLO inference error: {e}")
            return []


# ── Per-camera AI processor ───────────────────────────────────────────────────

class CameraAIProcessor:
    """
    One instance per active camera.
    Receives raw numpy frames, runs YOLO + tracker + behavior analyzer,
    calls back with detection dicts for the event orchestrator.
    """

    def __init__(self, camera_id: str, callback):
        self.camera_id = camera_id
        self._callback  = callback
        self._tracker   = IoUTracker(camera_id)
        self._frame_count = 0
        # Process every Nth frame to reduce CPU load (10fps effective at 30fps input)
        self._process_every = int(os.environ.get("RBIS_AI_FRAME_SKIP", "3"))
        logger.info(f"CameraAIProcessor ready for {camera_id} (skip={self._process_every})")

    async def on_frame(self, frame: np.ndarray):
        """Called for every frame from CameraStream. Skips frames per config."""
        self._frame_count += 1
        if self._frame_count % self._process_every != 0:
            return

        h, w = frame.shape[:2]
        detections = YOLOInferenceEngine.detect(frame)
        events     = self._tracker.update(detections, frame, w, h)

        for evt in events:
            try:
                await self._callback(evt)
            except Exception as e:
                logger.error(f"AI callback error [{self.camera_id}]: {e}", exc_info=True)

    def active_persons(self) -> int:
        return self._tracker.active_count()


# ── Global registry of per-camera processors ─────────────────────────────────

_processors: Dict[str, CameraAIProcessor] = {}
_registry_lock = threading.Lock()


def get_or_create_processor(camera_id: str, callback) -> CameraAIProcessor:
    with _registry_lock:
        if camera_id not in _processors:
            _processors[camera_id] = CameraAIProcessor(camera_id, callback)
        return _processors[camera_id]


def remove_processor(camera_id: str):
    with _registry_lock:
        _processors.pop(camera_id, None)


def get_active_person_count() -> int:
    with _registry_lock:
        return sum(p.active_persons() for p in _processors.values())


def is_model_loaded() -> bool:
    return YOLOInferenceEngine._model is not None
