"""
Video processing simulation pipeline.
In production this would hook into real RTSP streams + YOLOv8 + DeepSORT.
Here we generate realistic synthetic tracking data so the full system runs
without requiring GPU / camera hardware.
"""
import asyncio
import random
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)

# ── Store zones ───────────────────────────────────────────────────────────────
STORE_ZONES = {
    "ENTRANCE":  [(0.0, 0.0), (0.2, 1.0)],
    "AISLE_A":   [(0.2, 0.0), (0.4, 0.7)],
    "AISLE_B":   [(0.4, 0.0), (0.6, 0.7)],
    "AISLE_C":   [(0.6, 0.0), (0.8, 0.7)],
    "CHECKOUT":  [(0.2, 0.7), (0.8, 1.0)],
    "EXIT":      [(0.8, 0.0), (1.0, 1.0)],
}

CAMERA_ZONES = {
    0: ["ENTRANCE"],
    1: ["AISLE_A"],
    2: ["AISLE_B"],
    3: ["AISLE_C"],
    4: ["CHECKOUT", "EXIT"],
}

EVENT_SEQUENCE_NORMAL = [
    "ENTER_STORE", "PICK_ITEM", "HOLD_ITEM", "RETURN_ITEM",
    "PICK_ITEM", "APPROACH_REGISTER", "COMPLETE_CHECKOUT", "EXIT_STORE"
]
EVENT_SEQUENCE_SUSPICIOUS = [
    "ENTER_STORE", "PICK_ITEM", "HOLD_ITEM", "PICK_ITEM",
    "BYPASS_REGISTER", "EXIT_STORE"
]
EVENT_SEQUENCE_STAFF = [
    "ENTER_STORE", "ENTER_STORE", "ENTER_STORE"  # just walks around
]

COLORS = ["#E53935", "#8E24AA", "#1E88E5", "#43A047", "#FB8C00",
          "#6D4C41", "#00ACC1", "#F4511E", "#7CB342", "#3949AB"]

_session_counter = 0
_counter_lock = asyncio.Lock()


async def _next_session_id() -> str:
    global _session_counter
    async with _counter_lock:
        _session_counter += 1
        return f"Person_{_session_counter:03d}"


def _random_bbox(cam_id: int) -> List[float]:
    """Return a plausible normalised bounding box [x1,y1,x2,y2]."""
    x1 = round(random.uniform(0.05, 0.85), 3)
    y1 = round(random.uniform(0.1, 0.75), 3)
    w  = round(random.uniform(0.07, 0.15), 3)
    h  = round(random.uniform(0.25, 0.45), 3)
    return [x1, y1, min(x1 + w, 1.0), min(y1 + h, 1.0)]


def _random_position(zone: str) -> Tuple[float, float]:
    bounds = STORE_ZONES.get(zone, [(0.0, 0.0), (1.0, 1.0)])
    x = round(random.uniform(bounds[0][0], bounds[1][0]), 3)
    y = round(random.uniform(bounds[0][1], bounds[1][1]), 3)
    return x, y


def _choose_camera(zone: str) -> int:
    for cam, zones in CAMERA_ZONES.items():
        if zone in zones:
            return cam
    return random.randint(0, 4)


class SimulatedPerson:
    def __init__(self, session_id: str, is_staff: bool = False, is_suspicious: bool = False):
        self.session_id = session_id
        self.is_staff = is_staff
        self.is_suspicious = is_suspicious
        self.dominant_color = random.choice(COLORS)
        self.events_planned = (
            EVENT_SEQUENCE_STAFF if is_staff
            else EVENT_SEQUENCE_SUSPICIOUS if is_suspicious
            else EVENT_SEQUENCE_NORMAL
        )
        self.event_index = 0
        self.current_zone = "ENTRANCE"
        self.current_camera = 0
        self.bbox = _random_bbox(0)

    def next_detection(self) -> Optional[Dict]:
        if self.event_index >= len(self.events_planned):
            return None
        event = self.events_planned[self.event_index]
        self.event_index += 1

        # Advance zone
        zone_sequence = list(STORE_ZONES.keys())
        zone_idx = zone_sequence.index(self.current_zone) if self.current_zone in zone_sequence else 0
        if event not in ("ENTER_STORE",) and zone_idx < len(zone_sequence) - 1:
            self.current_zone = zone_sequence[min(zone_idx + 1, len(zone_sequence) - 1)]

        cam = _choose_camera(self.current_zone)
        self.current_camera = cam
        self.bbox = _random_bbox(cam)
        px, py = _random_position(self.current_zone)

        hold_duration = None
        if event == "HOLD_ITEM":
            hold_duration = round(random.uniform(8, 45), 1)

        return {
            "session_id": self.session_id,
            "event_type": event,
            "camera_id": cam,
            "zone": self.current_zone,
            "bounding_box": self.bbox,
            "position_x": px,
            "position_y": py,
            "confidence": round(random.uniform(0.72, 0.99), 3),
            "dominant_color": self.dominant_color,
            "is_staff": self.is_staff,
            "duration_seconds": hold_duration,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class VideoProcessingPipeline:
    """
    Simulated multi-camera processing pipeline.
    Emits detection frames at configurable FPS.
    In production: replace _generate_frame() with actual YOLO+DeepSORT output.
    """

    def __init__(self):
        self._running = False
        self._active_persons: Dict[str, SimulatedPerson] = {}
        self._event_callbacks = []
        self._frame_interval = 1.0 / 5  # 5 FPS processing
        self._spawn_interval = 8        # seconds between new person spawns

    def register_callback(self, cb):
        self._event_callbacks.append(cb)

    async def start(self):
        if self._running:
            return
        self._running = True
        asyncio.create_task(self._spawn_loop())
        asyncio.create_task(self._detection_loop())
        logger.info("Video pipeline started (simulation mode)")

    async def stop(self):
        self._running = False
        logger.info("Video pipeline stopped")

    async def _spawn_loop(self):
        while self._running:
            await asyncio.sleep(self._spawn_interval)
            if len(self._active_persons) < 12:
                await self._spawn_person()

    async def _spawn_person(self):
        session_id = await _next_session_id()
        is_staff = random.random() < 0.15
        is_suspicious = (not is_staff) and (random.random() < 0.25)
        person = SimulatedPerson(session_id, is_staff, is_suspicious)
        self._active_persons[session_id] = person
        logger.debug(f"Spawned {session_id} (staff={is_staff}, suspicious={is_suspicious})")

    async def _detection_loop(self):
        # Pre-spawn a few people
        for _ in range(3):
            await self._spawn_person()

        while self._running:
            start = time.monotonic()
            await self._process_frame()
            elapsed = time.monotonic() - start
            sleep_time = max(0.0, self._frame_interval - elapsed)
            await asyncio.sleep(sleep_time)

    async def _process_frame(self):
        to_remove = []
        for session_id, person in list(self._active_persons.items()):
            detection = person.next_detection()
            if detection is None:
                to_remove.append(session_id)
                continue
            for cb in self._event_callbacks:
                try:
                    await cb(detection)
                except Exception as e:
                    logger.error(f"Callback error: {e}")

        for sid in to_remove:
            self._active_persons.pop(sid, None)

    def get_active_count(self) -> int:
        return len(self._active_persons)

    def get_camera_frames(self) -> List[Dict]:
        """Return one synthetic frame per camera for the live grid."""
        frames = []
        for cam_id in range(5):
            persons_in_cam = [
                {
                    "session_id": p.session_id,
                    "bbox": p.bbox,
                    "zone": p.current_zone,
                    "color": p.dominant_color,
                    "is_staff": p.is_staff,
                }
                for p in self._active_persons.values()
                if p.current_camera == cam_id
            ]
            frames.append({
                "camera_id": cam_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "person_count": len(persons_in_cam),
                "persons": persons_in_cam,
                "width": 1280,
                "height": 720,
            })
        return frames


# Global pipeline instance
pipeline = VideoProcessingPipeline()
