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

import asyncio
import logging
import os
import time
import threading
import urllib.request
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Unique per backend process start. Without this, track IDs reset to 1 on
# every restart and the resulting session_id ("CAMbcam_T0001") collides with
# whatever old Person row already has that session_id in the DB — silently
# merging today's fresh test data with hours-old history from prior runs.
_RUN_ID = uuid.uuid4().hex[:6]

# ── Model configuration ────────────────────────────────────────────────────────

# yolov8n-pose.pt — 6.5 MB, person detection + 17 COCO keypoints, ~10-15ms/frame on CPU.
# Keypoints let us reason about actual hand position relative to the body
# (reach-and-retract, hand-near-hip) instead of only where the body is on screen.
MODEL_URLS = [
    "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8n-pose.pt",
]
# Default model path — configurable via env var YOLO_MODEL_PATH
DEFAULT_MODEL_PATH = os.environ.get(
    "YOLO_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "yolov8n-pose.pt")
)

PERSON_CLASS_ID   = 0       # COCO class 0 = person
CONFIDENCE_THRESH = 0.40    # min detection confidence
NMS_IOU_THRESH    = 0.45    # NMS IoU threshold
INFERENCE_SIZE    = 640     # input resolution for YOLO (square)

# ── COCO keypoint indices (from yolov8-pose, 17 keypoints per person) ──────────
KP_L_SHOULDER, KP_R_SHOULDER = 5, 6
KP_L_ELBOW,    KP_R_ELBOW    = 7, 8
KP_L_WRIST,    KP_R_WRIST    = 9, 10
KP_L_HIP,      KP_R_HIP      = 11, 12
KP_CONF_THRESH = 0.35   # min per-keypoint confidence to trust it

# ── Kinematic hand-behavior thresholds ─────────────────────────────────────────
# Wrist-to-torso distance is normalized by torso scale (shoulder-to-hip length)
# so it works regardless of how close the person is to the camera.
REACH_THRESH          = 1.35  # wrist distance/torso_scale above this = arm extended (reaching)
REACH_MIN_FRAMES      = 2     # reach must sustain this many frames before a retract counts as a pick
                               # (filters single-frame pose jitter from ordinary gestures)
RETRACT_THRESH        = 0.75  # wrist distance/torso_scale below this = arm pulled back to body
REACH_TIMEOUT_FRAMES  = 40    # must retract within this many processed frames of reaching, or reset

# CONCEALMENT fires on a quick, deep retract of the wrist toward the torso
# shortly after a pick — not on sustained stillness. Real pocketing is a fast
# transient motion (hand dips in, comes back out), not a still hold, so
# requiring low velocity + a long dwell (the original design) almost never
# fires on a real "grab and pocket" — it fires more reliably on someone
# standing still holding an item at chest height, which is the opposite of
# what we want to flag.
CONCEALMENT_RATIO_THRESH  = 0.50  # deeper retract than RETRACT_THRESH — hand pulled in close to torso/waist
# Real behavior isn't "conceal once, done" — someone can pull the item back
# out to look at it, then re-pocket it, and that second concealment is just
# as real as the first. CONCEALMENT is a re-fireable exposed<->concealed
# state machine, not a one-shot flag. RE_EXPOSE_THRESH sits well above the
# conceal threshold (hysteresis) so the wrist hovering right at the boundary
# can't rapidly toggle and spam re-fires.
CONCEALMENT_RE_EXPOSE_THRESH = 0.80

# ── Color-disappearance signal ──────────────────────────────────────────────
# Corroborating signal, independent of hand kinematics: sample the color at
# the wrist right before a reach (empty-hand baseline) and right after a pick
# completes (held-item color). If the wrist patch later drifts back toward
# the baseline and away from the held color, the item's visual signature has
# disappeared from view — self-normalizing ratio (see _color_disappearance_ratio).
#
# The CONTRAST FLOOR and RATIO THRESHOLD below are lighting-adaptive, not
# fixed constants — a dim store, glare, or a cheap webcam sensor all shift
# how much natural color jitter exists frame-to-frame even when nothing is
# happening. Each track measures its OWN noise floor (from idle-frame color
# samples, before any reach starts) and scales both thresholds off that
# measurement, so the same code doesn't need per-camera recalibration the way
# a fixed absolute threshold would. STREAK/WINDOW stay fixed — they're about
# how fast a real event unfolds in time, not about lighting.
COLOR_NOISE_SAMPLES       = 6     # rolling idle-frame samples used to estimate this track's noise floor
COLOR_NOISE_DEFAULT       = 6.0   # assumed noise floor until enough idle samples are collected
COLOR_MIN_CONTRAST_FLOOR  = 8.0   # absolute floor under the adaptive contrast requirement (never goes below this)
COLOR_NOISE_MULTIPLIER    = 3.0   # required contrast = max(floor, this * measured noise)
COLOR_RATIO_MIN           = 0.55  # adaptive ratio threshold never goes below this (clean signal, most sensitive)
COLOR_RATIO_MAX           = 0.85  # adaptive ratio threshold never exceeds this (noisy signal, most conservative)
COLOR_RATIO_NOISE_MARGIN  = 0.35  # how strongly noise-to-contrast ratio pushes the threshold toward MAX
COLOR_DISAPPEAR_STREAK    = 3     # consecutive qualifying frames required (denoise single-frame misreads)
# Like CONCEALMENT, this is a re-fireable visible<->hidden state machine —
# take the item out to look at it, put it back, and that second disappearance
# is real too. COLOR_REAPPEAR_RATIO sits well below the disappear ratio
# thresholds (hysteresis) so a borderline reading can't rapidly toggle state.
COLOR_REAPPEAR_RATIO      = 0.30

# ── Phase 2: navigation pattern thresholds ──────────────────────────────────
# SHELF_REVISIT — returning to a zone already visited (not just passing
# through once) — a real "browsing/scanning the same area repeatedly"
# signal, independent of the pose-kinematic pick/conceal work.
REVISIT_MIN_VISITS      = 2    # 2nd+ entry into a zone counts as a revisit
# EXTENDED_DWELL — cumulative time (across possibly multiple visits) spent in
# one zone crossing a threshold — distinct from LOITER, which only fires on
# one continuous still burst.
EXTENDED_DWELL_FRAMES    = 150  # cumulative processed frames in one zone (~30s at 5fps)
# _cx_to_zone() divides the frame into fixed AISLE_A/B/C/etc. percentages —
# unlike shelf/register/exit zones, this is NOT wired to the Zone Editor's
# per-camera calibration. On a close-up camera, normal body sway crosses
# these fixed boundaries constantly. Require a zone to be the stable read for
# several consecutive frames before counting it as a real transition, so
# boundary flicker can't fire a SHELF_REVISIT on every step.
ZONE_STABILITY_FRAMES    = 6    # ~1.2s at 5fps — filters boundary oscillation from a single instant crossing

# ── Tracker configuration ──────────────────────────────────────────────────────

IOU_MATCH_THRESH  = 0.30    # min IoU to match track across frames
MAX_MISSED_FRAMES = 15      # frames before track is dropped
MIN_CONFIRM_HITS  = 2       # frames before track is "confirmed" (avoids noise)

# ── Behavior thresholds ────────────────────────────────────────────────────────
# Defaults assume a real store layout (entrance/aisles/register/exit mapped
# left-to-right across the frame). Override per-camera via cameras.yaml:
#   cameras:
#     - camera_id: webcam
#       extra:
#         zones:
#           register_zone_x: [0.15, 0.55]
#           exit_zone_x: 0.85
#           shelf_zone_x: [0.15, 0.75]
#           shelf_zone_y_max: 0.75

LOITER_FRAMES        = 25   # frames stationary in same zone → LOITER event
RAPID_MOVE_THRESH    = 0.12 # normalized position delta/frame → RAPID_MOVEMENT
PICK_ITEM_DWELL      = 8    # frames bbox overlaps "shelf zone" → PICK_ITEM
BYPASS_ZONE_THRESH   = 0.75 # x > 75% of frame without register zone → BYPASS
HOLD_ITEM_INTERVAL   = 30   # emit HOLD_ITEM every N frames while holding
# Score decay for calm behavior — without this, a score that hits 100 stays
# pinned at HIGH_SUSPICION for the rest of the visit even after the person
# returns to completely normal behavior. Real alert-fatigue driver ("it's
# always going off"). Mirrors HOLD_ITEM_INTERVAL's periodic re-fire pattern.
IDLE_DECAY_INTERVAL = 50    # processed frames of calm before each decay tick (~10s at 5fps)
EXIT_ZONE_X          = 0.85 # x > 85% = near exit
REGISTER_ZONE_X      = (0.15, 0.55)  # x range of register zone
SHELF_ZONE_X         = (0.15, 0.75)  # x range treated as "near shelves"
SHELF_ZONE_Y_MAX     = 0.75          # y below this treated as "near shelves"


@dataclass
class ZoneConfig:
    """Per-camera zone thresholds. Defaults match the module constants above."""
    register_zone_x: Tuple[float, float] = REGISTER_ZONE_X
    exit_zone_x:      float              = EXIT_ZONE_X
    shelf_zone_x:      Tuple[float, float] = SHELF_ZONE_X
    shelf_zone_y_max:  float              = SHELF_ZONE_Y_MAX

    # Staff detection — same signal class as everything else this system
    # tracks (color, not identity): if a person's measured dominant color
    # (torso region) matches a configured uniform color within tolerance,
    # they're treated as staff and skip suspicion scoring. This is a soft
    # heuristic (a customer in a similar-colored shirt will false-match) —
    # the Sensor Bus badge-scan path is the authoritative override.
    staff_uniform_colors: Tuple[str, ...] = ()
    staff_color_tolerance: float          = 45.0   # max RGB euclidean distance to count as a match

    @classmethod
    def from_dict(cls, d: Optional[Dict]) -> "ZoneConfig":
        d = d or {}
        cfg = cls()
        if "register_zone_x" in d:
            cfg.register_zone_x = tuple(d["register_zone_x"])
        if "exit_zone_x" in d:
            cfg.exit_zone_x = float(d["exit_zone_x"])
        if "shelf_zone_x" in d:
            cfg.shelf_zone_x = tuple(d["shelf_zone_x"])
        if "shelf_zone_y_max" in d:
            cfg.shelf_zone_y_max = float(d["shelf_zone_y_max"])
        if "staff_uniform_colors" in d:
            cfg.staff_uniform_colors = tuple(d["staff_uniform_colors"])
        if "staff_color_tolerance" in d:
            cfg.staff_color_tolerance = float(d["staff_color_tolerance"])
        return cfg


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _color_distance(hex_a: str, hex_b: str) -> Optional[float]:
    """Euclidean RGB distance between two hex colors, or None if either is invalid."""
    try:
        r1, g1, b1 = _hex_to_rgb(hex_a)
        r2, g2, b2 = _hex_to_rgb(hex_b)
    except (ValueError, IndexError):
        return None
    return ((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) ** 0.5


def _color_disappearance_ratio(
    current: str, held: str, baseline: str, min_contrast: float = COLOR_MIN_CONTRAST_FLOOR
) -> Optional[float]:
    """
    0.0 = current patch still matches the held-item color (still holding it).
    1.0 = current patch has fully reverted to the empty-hand baseline (item's
    visual signature is gone). Self-normalizing per-track — no fixed distance
    threshold in the ratio math itself.
    Returns None if held/baseline don't contrast enough to be meaningful for
    the given min_contrast (item color ~= skin/clothing, or contrast is
    within this track's measured noise floor — see _adaptive_color_thresholds).
    """
    dist_held_baseline = _color_distance(held, baseline)
    if dist_held_baseline is None or dist_held_baseline < min_contrast:
        return None
    dist_to_held = _color_distance(current, held)
    dist_to_baseline = _color_distance(current, baseline)
    if dist_to_held is None or dist_to_baseline is None:
        return None
    return dist_to_held / (dist_to_held + dist_to_baseline + 1e-6)


def _estimate_color_noise(idle_samples) -> float:
    """
    A per-track, per-lighting-condition noise floor: average frame-to-frame
    color jitter measured from this track's OWN idle-frame samples (natural
    resting hand, before any reach starts). A dim room, glare, or a cheap
    sensor all show up here as higher jitter — this is what lets the
    disappearance thresholds adapt without per-camera recalibration.
    Falls back to a conservative default until enough samples exist.
    """
    samples = list(idle_samples)
    if len(samples) < 2:
        return COLOR_NOISE_DEFAULT
    dists = [d for a, b in zip(samples[:-1], samples[1:]) if (d := _color_distance(a, b)) is not None]
    return (sum(dists) / len(dists)) if dists else COLOR_NOISE_DEFAULT


def _adaptive_color_thresholds(noise_estimate: float, held_baseline_contrast: float) -> Tuple[float, float]:
    """
    Returns (min_contrast, ratio_threshold) scaled to this track's measured
    noise floor:
      - min_contrast rises with noise, so a noisy/dim feed doesn't mistake
        sensor jitter for a real item color.
      - ratio_threshold rises toward COLOR_RATIO_MAX as noise becomes a large
        fraction of the actual held-vs-baseline contrast (weak, unreliable
        signal — demand a clearer disappearance before firing) and relaxes
        toward COLOR_RATIO_MIN when the signal is clean relative to noise.
    """
    min_contrast = max(COLOR_MIN_CONTRAST_FLOOR, COLOR_NOISE_MULTIPLIER * noise_estimate)
    noise_fraction = noise_estimate / max(held_baseline_contrast, 1e-6)
    ratio_threshold = COLOR_RATIO_MIN + COLOR_RATIO_NOISE_MARGIN * min(1.0, noise_fraction)
    ratio_threshold = max(COLOR_RATIO_MIN, min(COLOR_RATIO_MAX, ratio_threshold))
    return min_contrast, ratio_threshold


def _color_matches_staff_uniform(dominant_color: str, cfg: "ZoneConfig") -> bool:
    if not cfg.staff_uniform_colors:
        return False
    for uniform_hex in cfg.staff_uniform_colors:
        dist = _color_distance(dominant_color, uniform_hex)
        if dist is not None and dist <= cfg.staff_color_tolerance:
            return True
    return False


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


def _torso_frame(keypoints: Optional[List[Tuple[float, float, float]]]) -> Optional[Tuple[Tuple[float, float], float]]:
    """
    From 17 COCO keypoints, compute (torso_center, torso_scale).
    torso_scale normalizes wrist distances so they're comparable regardless of
    distance from camera. Two tiers, since hips are frequently out of frame
    for desk/checkout-counter cameras (upper body only):
      1. Shoulders + hips both visible → shoulder-to-hip length (most accurate).
      2. Shoulders only → shoulder width as a proxy scale (roughly comparable
         for typical human proportions — an approximation, not exact).
    Returns None only if shoulders themselves aren't confidently visible.
    """
    if not keypoints or len(keypoints) < 13:
        return None
    ls, rs = keypoints[KP_L_SHOULDER], keypoints[KP_R_SHOULDER]
    if ls[2] < KP_CONF_THRESH or rs[2] < KP_CONF_THRESH:
        return None
    shoulder_c = ((ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2)

    lh, rh = keypoints[KP_L_HIP], keypoints[KP_R_HIP]
    if lh[2] >= KP_CONF_THRESH and rh[2] >= KP_CONF_THRESH:
        hip_c = ((lh[0] + rh[0]) / 2, (lh[1] + rh[1]) / 2)
        torso_center = ((shoulder_c[0] + hip_c[0]) / 2, (shoulder_c[1] + hip_c[1]) / 2)
        torso_scale  = ((shoulder_c[0] - hip_c[0]) ** 2 + (shoulder_c[1] - hip_c[1]) ** 2) ** 0.5
    else:
        # Upper-body-only fallback: shoulder width as scale proxy, shoulder
        # midpoint as center (nudged down slightly to approximate chest/torso).
        shoulder_width = ((ls[0] - rs[0]) ** 2 + (ls[1] - rs[1]) ** 2) ** 0.5
        torso_scale  = shoulder_width
        torso_center = (shoulder_c[0], shoulder_c[1] + shoulder_width * 0.3)

    if torso_scale < 1e-4:
        return None
    return torso_center, torso_scale


def _wrist_reach(
    keypoints: List[Tuple[float, float, float]],
    torso_center: Tuple[float, float],
    torso_scale: float,
) -> Optional[Tuple[float, Tuple[float, float]]]:
    """Return (max_reach_ratio, that_wrist_xy) — whichever wrist is further from torso, normalized."""
    best = None
    for idx in (KP_L_WRIST, KP_R_WRIST):
        wx, wy, wc = keypoints[idx]
        if wc < KP_CONF_THRESH:
            continue
        dist = ((wx - torso_center[0]) ** 2 + (wy - torso_center[1]) ** 2) ** 0.5
        ratio = dist / torso_scale
        if best is None or ratio > best[0]:
            best = (ratio, (wx, wy))
    return best


# ── Per-camera pose-availability diagnostics — surfaces via /api/debug/ai so
# we can tell whether the kinematic path is actually engaging or silently
# falling back to the old position-dwell heuristic, PER CAMERA. Keyed by
# camera_id rather than a single flat counter — with multiple cameras, one
# poorly-angled camera's bad pose rate would otherwise be averaged away by a
# well-angled one, hiding exactly the thing you're trying to diagnose. ───────
_POSE_STATS: Dict[str, Dict[str, int]] = defaultdict(lambda: {"with_pose": 0, "without_pose": 0})


def get_pose_stats(camera_id: Optional[str] = None) -> Dict:
    def _fmt(stats):
        total = stats["with_pose"] + stats["without_pose"]
        pct = round(100 * stats["with_pose"] / total, 1) if total else 0.0
        return {**stats, "pose_available_pct": pct}

    if camera_id is not None:
        return _fmt(_POSE_STATS[camera_id])
    return {cam_id: _fmt(stats) for cam_id, stats in _POSE_STATS.items()}


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


def _sample_color_at_point(
    frame: np.ndarray, x_norm: float, y_norm: float, patch_px: int = 18
) -> Optional[str]:
    """Mean color of a small square patch centered on a normalized (x,y) point —
    used to sample whatever's at the wrist (empty hand, or a held item)."""
    h, w = frame.shape[:2]
    cx, cy = int(x_norm * w), int(y_norm * h)
    half = patch_px // 2
    x1, x2 = max(0, cx - half), min(w, cx + half)
    y1, y2 = max(0, cy - half), min(h, cy + half)
    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return None
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
    calm_frames:        int   = 0  # consecutive non-rapid-movement frames — score decay clock
    idle_event_emitted: int   = 0  # how many IDLE_10S decay events emitted
    items_held:         int   = 0
    visited_register:   bool  = False
    bypass_register_emitted: bool = False
    entered_store:      bool  = False
    exited:             bool  = False

    # Dominant color (updated periodically)
    dominant_color: str = "#888888"
    is_staff_by_color: bool = False   # re-evaluated whenever dominant_color refreshes
    is_staff_confirmed: bool = False  # set by a Sensor Bus badge scan — overrides the color guess

    # Position history for velocity calc
    center_history: deque = field(default_factory=lambda: deque(maxlen=10))

    # ── Kinematic hand-behavior state (pose-based) ─────────────────────
    reach_state:          str   = "idle"   # idle | reaching
    reach_frames:         int   = 0        # frames since entering "reaching"
    prev_wrist_xy:        Optional[Tuple[float, float]] = None
    concealment_state:    str   = "exposed"  # exposed | concealed — re-fireable, see CONCEALMENT_RE_EXPOSE_THRESH
    frames_since_pick:    int   = 9999     # processed frames since last PICK_ITEM (large = "no recent pick")
    pose_available:       bool  = False    # did we get a usable pose this track's life
    last_keypoints: Optional[List[Tuple[float, float, float]]] = None  # for live overlay broadcast

    # ── Color-disappearance signal (corroborates kinematic concealment) ─────
    hand_baseline_color:   Optional[str] = None   # sampled just before a reach starts
    held_item_color:       Optional[str] = None   # sampled when a pick completes
    color_disappear_streak: int  = 0
    color_reappear_streak: int  = 0
    color_state:           str  = "visible"  # visible | hidden — re-fireable, see COLOR_REAPPEAR_RATIO
    idle_color_samples: deque = field(default_factory=lambda: deque(maxlen=COLOR_NOISE_SAMPLES))

    # ── Phase 2: navigation pattern tracking (zone revisits, cumulative dwell) ──
    current_zone:        Optional[str] = None
    zone_visit_counts:    Dict[str, int]   = field(default_factory=dict)  # times entered each zone
    zone_dwell_frames:    Dict[str, int]   = field(default_factory=dict)  # cumulative processed frames in each zone
    extended_dwell_emitted: Dict[str, bool] = field(default_factory=dict)  # one EXTENDED_DWELL per zone per visit-cycle
    pending_zone:        Optional[str] = None  # debounce — see ZONE_STABILITY_FRAMES
    pending_zone_frames: int = 0


class BehaviorAnalyzer:
    """
    Converts raw bbox observations into semantic retail behavior events.
    One instance per active track.
    """

    def __init__(self, state: TrackState, zones: Optional["ZoneConfig"] = None):
        self.s = state
        self.z = zones or ZoneConfig()

    def update(
        self,
        bbox: List[float],
        frame: np.ndarray,
        frame_w: int,
        frame_h: int,
        keypoints: Optional[List[Tuple[float, float, float]]] = None,
    ) -> List[Dict]:
        """
        Feed new bbox + pose observation; return list of event dicts to emit.
        All bbox/keypoint coords are normalized [0,1].
        """
        s = self.s
        s.bbox = bbox
        s.last_keypoints = keypoints
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

        # ── Zone visit tracking — must run on EVERY confirmed frame,
        # including the entry frame, or the person's starting zone never
        # gets counted and a later return to it looks like a fresh "visit 1"
        # instead of a real revisit. Debounced (see ZONE_STABILITY_FRAMES)
        # so a brief flicker across a boundary doesn't count as a visit. ─────
        raw_zone = _cx_to_zone(cx, cy)
        if s.current_zone is None:
            # First observation for this track — initialize immediately,
            # nothing to debounce against yet.
            s.current_zone = raw_zone
            s.pending_zone = raw_zone
            s.pending_zone_frames = 0
            s.zone_visit_counts[raw_zone] = 1
        else:
            if raw_zone == s.pending_zone:
                s.pending_zone_frames += 1
            else:
                s.pending_zone = raw_zone
                s.pending_zone_frames = 1

            if raw_zone != s.current_zone and s.pending_zone_frames >= ZONE_STABILITY_FRAMES:
                s.current_zone = raw_zone
                s.zone_visit_counts[raw_zone] = s.zone_visit_counts.get(raw_zone, 0) + 1
                if s.zone_visit_counts[raw_zone] >= REVISIT_MIN_VISITS:
                    s.extended_dwell_emitted[raw_zone] = False
                    events.append(self._make_event(
                        "SHELF_REVISIT", bbox, cx, cy, frame_w, frame_h,
                        extra={"zone_name": raw_zone, "visit_count": s.zone_visit_counts[raw_zone]}
                    ))

        current_zone = s.current_zone  # the debounced/stable zone, not the raw instantaneous one
        s.zone_dwell_frames[current_zone] = s.zone_dwell_frames.get(current_zone, 0) + 1
        if (s.zone_dwell_frames[current_zone] >= EXTENDED_DWELL_FRAMES
                and not s.extended_dwell_emitted.get(current_zone, False)):
            s.extended_dwell_emitted[current_zone] = True
            events.append(self._make_event(
                "EXTENDED_DWELL", bbox, cx, cy, frame_w, frame_h,
                extra={
                    "zone_name": current_zone,
                    "cumulative_seconds": round(s.zone_dwell_frames[current_zone] / 5.0, 1),
                }
            ))

        # ── ENTER_STORE (once, first confirmed frame) ──────────────────────
        if not s.entered_store:
            s.entered_store = True
            # Sample dominant color
            s.dominant_color = _dominant_color_from_bbox(frame, bbox)
            s.is_staff_by_color = _color_matches_staff_uniform(s.dominant_color, self.z)
            events.append(self._make_event("ENTER_STORE", bbox, cx, cy, frame_w, frame_h))
            return events  # nothing else on entry frame

        # ── Update dominant color every 30 frames ─────────────────────────
        if s.age % 30 == 0:
            s.dominant_color = _dominant_color_from_bbox(frame, bbox)
            s.is_staff_by_color = _color_matches_staff_uniform(s.dominant_color, self.z)

        # ── Velocity (normalized per frame) ───────────────────────────────
        velocity = 0.0
        if s.prev_center:
            dx = cx - s.prev_center[0]
            dy = cy - s.prev_center[1]
            velocity = (dx**2 + dy**2) ** 0.5
        s.prev_center = (cx, cy)

        # ── Zone detection (still legitimately spatial — did the person
        # physically pass the register / reach the exit) ──────────────────
        z = self.z
        in_shelf_zone = (z.shelf_zone_x[0] < cx < z.shelf_zone_x[1]) and (cy < z.shelf_zone_y_max)
        in_register_zone = z.register_zone_x[0] < cx < z.register_zone_x[1] and cy > 0.65
        near_exit = cx > z.exit_zone_x

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

        # ── IDLE_10S — score decay for calm behavior. Without this, a score
        # that hits 100 stays pinned at HIGH_SUSPICION for the rest of the
        # visit even after the person returns to completely normal behavior.
        if velocity > RAPID_MOVE_THRESH:
            s.calm_frames = 0
            s.idle_event_emitted = 0
        else:
            s.calm_frames += 1
            idle_threshold = IDLE_DECAY_INTERVAL * (s.idle_event_emitted + 1)
            if s.calm_frames >= idle_threshold:
                s.idle_event_emitted += 1
                events.append(self._make_event(
                    "IDLE_10S", bbox, cx, cy, frame_w, frame_h,
                    extra={"duration_seconds": round(s.calm_frames / 5.0, 1)}
                ))

        # ── PICK_ITEM / CONCEALMENT — driven by hand kinematics when pose
        # is available (reach-out-then-retract = pick; hand parked near hip
        # afterward = concealment), falling back to the old shelf-dwell
        # heuristic only when pose data isn't usable this frame (occlusion,
        # person too small/far, etc.) ───────────────────────────────────────
        torso = _torso_frame(keypoints)
        if torso is not None:
            s.pose_available = True
            _POSE_STATS[s.camera_id]["with_pose"] += 1
            torso_center, torso_scale = torso
            reach = _wrist_reach(keypoints, torso_center, torso_scale)
            if reach is not None:
                ratio, wrist_xy = reach
                wrist_vel = 0.0
                if s.prev_wrist_xy:
                    wdx = (wrist_xy[0] - s.prev_wrist_xy[0]) / torso_scale
                    wdy = (wrist_xy[1] - s.prev_wrist_xy[1]) / torso_scale
                    wrist_vel = (wdx ** 2 + wdy ** 2) ** 0.5
                s.prev_wrist_xy = wrist_xy

                s.frames_since_pick += 1

                if s.reach_state == "idle":
                    # Collect this track's own natural color jitter — the
                    # noise floor the color-disappearance signal adapts to.
                    # Gated on items_held == 0: reach_state resets to "idle"
                    # immediately after a pick too (it just means "not
                    # currently reaching"), so without this an item's own
                    # color would contaminate the empty-hand noise estimate.
                    if s.items_held == 0:
                        idle_sample = _sample_color_at_point(frame, *wrist_xy)
                        if idle_sample:
                            s.idle_color_samples.append(idle_sample)
                    if ratio > REACH_THRESH and in_shelf_zone:
                        s.reach_state = "reaching"
                        s.reach_frames = 0
                        # Sample the empty-hand baseline color right as the
                        # reach begins — before the hand reaches whatever it's
                        # about to grab.
                        s.hand_baseline_color = _sample_color_at_point(frame, *wrist_xy)
                else:  # "reaching"
                    s.reach_frames += 1
                    if ratio < RETRACT_THRESH:
                        if s.reach_frames >= REACH_MIN_FRAMES:
                            # Sustained reach-and-retract → real pick gesture.
                            # A single-frame dip is more likely pose jitter
                            # from an ordinary gesture than a deliberate reach.
                            s.items_held += 1
                            s.holding_frames = 0
                            s.hold_event_emitted = 0
                            s.concealment_state = "exposed"
                            s.frames_since_pick = 0
                            s.held_item_color = _sample_color_at_point(frame, *wrist_xy)
                            s.color_disappear_streak = 0
                            s.color_reappear_streak = 0
                            s.color_state = "visible"
                            events.append(self._make_event(
                                "PICK_ITEM", bbox, cx, cy, frame_w, frame_h,
                                extra={"detection_method": "pose_kinematic"}
                            ))
                        s.reach_state = "idle"
                    elif s.reach_frames > REACH_TIMEOUT_FRAMES:
                        # Arm stayed extended too long without retracting
                        # (pointing, resting on shelf, etc.) — not a pick.
                        s.reach_state = "idle"

                # ── CONCEALMENT: a quick, deep retract of the wrist toward
                # the torso/waist. Real pocketing is a fast transient dip, not
                # a sustained still hold — so this fires on the dip itself
                # rather than requiring stillness. Re-fireable: take the item
                # out to look at it, put it back, and that second concealment
                # counts too — hysteresis (RE_EXPOSE_THRESH well above the
                # conceal threshold) stops the wrist hovering at the boundary
                # from rapidly toggling and spamming re-fires.
                if s.items_held > 0:
                    if s.concealment_state == "exposed" and ratio < CONCEALMENT_RATIO_THRESH:
                        s.concealment_state = "concealed"
                        events.append(self._make_event(
                            "CONCEALMENT", bbox, cx, cy, frame_w, frame_h,
                            extra={"detection_method": "pose_kinematic"}
                        ))
                    elif s.concealment_state == "concealed" and ratio > CONCEALMENT_RE_EXPOSE_THRESH:
                        s.concealment_state = "exposed"

                # ── COLOR_DISAPPEARANCE: corroborating signal, independent of
                # hand position — does the wrist patch's color drift back
                # toward the empty-hand baseline (item no longer visible)?
                # Self-normalizing ratio, denoised over a short streak so a
                # single bad frame (motion blur, glare) can't trigger it.
                # Also a re-fireable visible<->hidden state machine, same
                # reasoning as CONCEALMENT above.
                if s.items_held > 0 and s.held_item_color and s.hand_baseline_color:
                    current_color = _sample_color_at_point(frame, *wrist_xy)
                    noise = _estimate_color_noise(s.idle_color_samples)
                    held_baseline_contrast = _color_distance(s.held_item_color, s.hand_baseline_color) or 0.0
                    adaptive_min_contrast, adaptive_ratio_thresh = _adaptive_color_thresholds(
                        noise, held_baseline_contrast
                    )
                    disappear_ratio = (
                        _color_disappearance_ratio(
                            current_color, s.held_item_color, s.hand_baseline_color,
                            min_contrast=adaptive_min_contrast,
                        )
                        if current_color else None
                    )
                    if disappear_ratio is not None:
                        if s.color_state == "visible" and disappear_ratio >= adaptive_ratio_thresh:
                            s.color_disappear_streak += 1
                            s.color_reappear_streak = 0
                            if s.color_disappear_streak >= COLOR_DISAPPEAR_STREAK:
                                s.color_state = "hidden"
                                s.color_disappear_streak = 0
                                events.append(self._make_event(
                                    "COLOR_DISAPPEARANCE", bbox, cx, cy, frame_w, frame_h,
                                    extra={
                                        "detection_method": "color_kinematic",
                                        "disappearance_ratio": round(disappear_ratio, 3),
                                        "noise_estimate": round(noise, 2),
                                        "adaptive_ratio_threshold": round(adaptive_ratio_thresh, 3),
                                    }
                                ))
                        elif s.color_state == "hidden" and disappear_ratio <= COLOR_REAPPEAR_RATIO:
                            s.color_reappear_streak += 1
                            s.color_disappear_streak = 0
                            if s.color_reappear_streak >= COLOR_DISAPPEAR_STREAK:
                                s.color_state = "visible"
                                s.color_reappear_streak = 0
                        else:
                            s.color_disappear_streak = max(0, s.color_disappear_streak - 1)
                            s.color_reappear_streak = max(0, s.color_reappear_streak - 1)
        else:
            _POSE_STATS[s.camera_id]["without_pose"] += 1

        if torso is None and not s.pose_available:
            # Degraded fallback: no pose ever obtained for this track (too
            # small/far/occluded) — use the old position-dwell heuristic so
            # the system still functions, just less precisely.
            if in_shelf_zone and velocity < 0.015:
                s.shelf_dwell_frames += 1
                if s.shelf_dwell_frames == PICK_ITEM_DWELL:
                    s.items_held += 1
                    s.holding_frames = 0
                    s.hold_event_emitted = 0
                    events.append(self._make_event(
                        "PICK_ITEM", bbox, cx, cy, frame_w, frame_h,
                        extra={"detection_method": "position_fallback"}
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
                and not s.bypass_register_emitted
                and cx > z.register_zone_x[1] + 0.05
                and near_exit):
            s.bypass_register_emitted = True
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
            "is_staff":       s.is_staff_confirmed or s.is_staff_by_color,
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

    def __init__(self, camera_id: str, zones: Optional["ZoneConfig"] = None):
        self.camera_id   = camera_id
        self.zones       = zones or ZoneConfig()
        self._next_id    = 1
        self._tracks:    Dict[int, TrackState] = {}
        self._analyzers: Dict[int, BehaviorAnalyzer] = {}

    def update(
        self,
        detections: List[Tuple[List[float], float, Optional[List[Tuple[float, float, float]]]]],
        # [(bbox_norm, conf, keypoints_norm_or_None), ...]
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
        for det_idx, (det_box, det_conf, det_kp) in enumerate(detections):
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
            bbox, conf, kp = detections[det_idx]
            evts = self._analyzers[tid].update(bbox, frame, frame_w, frame_h, kp)
            events.extend(evts)
            self._tracks[tid].missed = 0
            matched_det_indices.add(det_idx)

        # ── Increment missed counter for unmatched tracks ──────────────────
        for tid in unmatched_tracks:
            self._tracks[tid].missed += 1
            self._tracks[tid].age    += 1

        # ── Create new tracks for unmatched detections ────────────────────
        for det_idx, (det_box, det_conf, det_kp) in enumerate(detections):
            if det_idx in matched_det_indices:
                continue
            tid        = self._next_id
            self._next_id += 1
            session_id = f"CAM{self.camera_id[-4:] if len(self.camera_id) > 4 else self.camera_id}_{_RUN_ID}_T{tid:04d}"
            state      = TrackState(
                track_id=tid,
                session_id=session_id,
                camera_id=self.camera_id,
                bbox=det_box,
            )
            self._tracks[tid]    = state
            self._analyzers[tid] = BehaviorAnalyzer(state, self.zones)

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

    # ── Detection counter for diagnostics ────────────────────────────────────
    _total_inferences: int = 0
    _total_persons_detected: int = 0

    @classmethod
    def detect(cls, frame: np.ndarray) -> List[Tuple[List[float], float, Optional[List[Tuple[float, float, float]]]]]:
        """
        Run YOLOv8-pose inference on a BGR frame.
        Returns list of (bbox_normalized [x1,y1,x2,y2], confidence, keypoints) for persons.
        keypoints is a list of 17 (x, y, conf) tuples normalized to [0,1], or None
        if this model/detection has no pose data.
        """
        if cls._model is None:
            # Log once so the user knows why nothing is happening
            if cls._total_inferences == 0:
                logger.error(
                    "🚨 YOLO model is None — detect() returning empty. "
                    "Model failed to load at startup. Check logs for download errors."
                )
            cls._total_inferences += 1
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
                kp_xyn  = r.keypoints.xyn  if r.keypoints is not None else None   # (N,17,2) normalized
                kp_conf = r.keypoints.conf if r.keypoints is not None else None   # (N,17)
                for i, box in enumerate(r.boxes):
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf[0])
                    bbox_norm = [
                        round(x1 / w, 4), round(y1 / h, 4),
                        round(x2 / w, 4), round(y2 / h, 4),
                    ]
                    keypoints = None
                    if kp_xyn is not None and i < len(kp_xyn):
                        xy = kp_xyn[i].tolist()
                        cf = kp_conf[i].tolist() if kp_conf is not None else [1.0] * len(xy)
                        keypoints = [(round(p[0], 4), round(p[1], 4), round(c, 3)) for p, c in zip(xy, cf)]
                    detections.append((bbox_norm, conf, keypoints))

            cls._total_inferences += 1
            cls._total_persons_detected += len(detections)

            # Log every 30 inferences so the user can see YOLO is working
            if cls._total_inferences % 30 == 0:
                logger.info(
                    f"🤖 YOLO stats: {cls._total_inferences} inferences, "
                    f"{cls._total_persons_detected} total person detections "
                    f"(current frame: {len(detections)} person(s))"
                )
            elif detections:
                logger.debug(
                    f"🎯 YOLO detected {len(detections)} person(s) "
                    f"[confs: {[round(d[1],2) for d in detections]}]"
                )

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

    def __init__(self, camera_id: str, callback, zones: Optional["ZoneConfig"] = None):
        self.camera_id = camera_id
        self._callback  = callback
        self._tracker   = IoUTracker(camera_id, zones)
        self._frame_count = 0
        # Process every Nth frame to reduce CPU load (10fps effective at 30fps input)
        self._process_every = int(os.environ.get("RBIS_AI_FRAME_SKIP", "3"))
        # Frames are scheduled onto the event loop from the camera's capture
        # thread without waiting for the previous frame's processing to
        # finish (see camera_stream.py's run_coroutine_threadsafe). Since
        # YOLO inference now awaits a thread-executor call, the event loop
        # can start a NEW frame's on_frame() while an OLDER one is still
        # awaiting its executor result — and if that older one's inference
        # happens to finish later, it overwrites the tracker with stale
        # positions (visually: the overlay stops tracking/lags/jumps back).
        # This flag keeps frame processing strictly one-at-a-time per camera,
        # same as before the executor offload — a frame that arrives while
        # busy is simply dropped, consistent with the existing frame-skip
        # philosophy (freshness over completeness).
        self._processing = False
        logger.info(f"CameraAIProcessor ready for {camera_id} (skip={self._process_every})")

    async def on_frame(self, frame: np.ndarray):
        """Called for every frame from CameraStream. Skips frames per config."""
        self._frame_count += 1

        # Log the first frame received so we know the pipeline is wired
        if self._frame_count == 1:
            logger.info(
                f"✅ [{self.camera_id}] First frame received by AI processor "
                f"(shape={frame.shape}) — YOLO detection starting"
            )

        if self._frame_count % self._process_every != 0:
            return

        if self._processing:
            # Previous frame's inference is still in flight — drop this one
            # rather than risk it finishing first and overwriting the
            # tracker with stale (older) positions.
            return
        self._processing = True

        try:
            h, w = frame.shape[:2]
            # YOLO inference is CPU-bound and was previously called directly on
            # the asyncio event loop — meaning every inference call blocked ALL
            # other work on the server (HTTP requests, WebSocket messages, alert
            # dispatch) for its full duration. Under sustained load this can
            # snowball into total unresponsiveness. Offloading to a thread lets
            # the event loop keep serving everything else while inference runs.
            loop = asyncio.get_event_loop()
            detections = await loop.run_in_executor(None, YOLOInferenceEngine.detect, frame)
            events     = self._tracker.update(detections, frame, w, h)
        finally:
            self._processing = False

        # ── Broadcast live keypoints every processed frame (not just on
        # behavior events) so the UI can draw a real skeleton overlay —
        # visible proof the pose model is actually tracking hands, not just
        # a body bounding box. ─────────────────────────────────────────────
        try:
            from app.core.websocket import manager as ws_manager
            poses = [
                {
                    "session_id": t.session_id,
                    "bbox": [round(v, 4) for v in t.bbox],
                    "keypoints": t.last_keypoints,
                }
                for t in self._tracker._tracks.values()
                if t.confirmed and t.last_keypoints
            ]
            if poses:
                await ws_manager.broadcast("pose", {
                    "type": "pose_update",
                    "camera_id": self.camera_id,
                    "poses": poses,
                })
        except Exception as e:
            logger.debug(f"pose broadcast skipped: {e}")

        # Periodic heartbeat so the user knows frames are being processed
        processed_count = self._frame_count // self._process_every
        if processed_count % 50 == 0:
            logger.info(
                f"📷 [{self.camera_id}] Processed {processed_count} frames, "
                f"{self._tracker.active_count()} active person(s), "
                f"{len(detections)} detection(s) this frame"
            )

        for evt in events:
            logger.info(
                f"🚨 [{self.camera_id}] EVENT → {evt.get('event_type')} "
                f"session={evt.get('session_id')} zone={evt.get('zone')}"
            )
            try:
                await self._callback(evt)
            except Exception as e:
                logger.error(f"AI callback error [{self.camera_id}]: {e}", exc_info=True)

    def active_persons(self) -> int:
        return self._tracker.active_count()


# ── Global registry of per-camera processors ─────────────────────────────────

_processors: Dict[str, CameraAIProcessor] = {}
_registry_lock = threading.Lock()


def get_or_create_processor(camera_id: str, callback, zones: Optional["ZoneConfig"] = None) -> CameraAIProcessor:
    with _registry_lock:
        if camera_id not in _processors:
            _processors[camera_id] = CameraAIProcessor(camera_id, callback, zones)
        return _processors[camera_id]


def remove_processor(camera_id: str):
    with _registry_lock:
        _processors.pop(camera_id, None)


def get_active_person_count() -> int:
    with _registry_lock:
        return sum(p.active_persons() for p in _processors.values())


def is_model_loaded() -> bool:
    return YOLOInferenceEngine._model is not None
