"""
test_zone_debounce.py — SHELF_REVISIT/EXTENDED_DWELL zone-transition
debouncing. _cx_to_zone() divides the frame into fixed AISLE_A/B/C/etc.
percentages independent of the Zone Editor's per-camera calibration — on a
close-up camera, normal body sway crosses these boundaries constantly. A
zone must be the stable read for ZONE_STABILITY_FRAMES consecutive frames
before it counts as a real transition, so boundary flicker can't flood
SHELF_REVISIT on every step.
"""
import numpy as np
import pytest

from app.services.ai_inference import IoUTracker

W, H = 640, 480


def _bbox_at(cx):
    return [cx - 0.05, 0.3, cx + 0.05, 0.5]


def _frame():
    return np.zeros((H, W, 3), dtype=np.uint8)


def test_rapid_boundary_oscillation_does_not_flood_shelf_revisit():
    t = IoUTracker("webcam")
    for _ in range(3):
        t.update([(_bbox_at(0.30), 0.9, None)], _frame(), W, H)  # AISLE_A, confirmed

    revisit_count = 0
    # Oscillate every single frame across the AISLE_A/AISLE_B boundary (0.35) —
    # exactly the kind of noise normal body sway produces on a close-up camera.
    for i in range(30):
        cx = 0.33 if i % 2 == 0 else 0.37
        evts = t.update([(_bbox_at(cx), 0.9, None)], _frame(), W, H)
        revisit_count += sum(1 for e in evts if e["event_type"] == "SHELF_REVISIT")

    assert revisit_count == 0


def test_genuine_sustained_revisit_still_fires_once():
    t = IoUTracker("webcam")
    for _ in range(3):
        t.update([(_bbox_at(0.25), 0.9, None)], _frame(), W, H)  # AISLE_A

    # Gradual walk to AISLE_B and stay there — a real, sustained transition.
    for cx in np.arange(0.25, 0.46, 0.02):
        t.update([(_bbox_at(cx), 0.9, None)], _frame(), W, H)
    for _ in range(6):
        t.update([(_bbox_at(0.45), 0.9, None)], _frame(), W, H)

    # Gradual walk back to AISLE_A and stay — should fire exactly one SHELF_REVISIT.
    events_seen = []
    for cx in np.arange(0.45, 0.24, -0.02):
        evts = t.update([(_bbox_at(cx), 0.9, None)], _frame(), W, H)
        events_seen += [e["event_type"] for e in evts]
    for _ in range(6):
        evts = t.update([(_bbox_at(0.25), 0.9, None)], _frame(), W, H)
        events_seen += [e["event_type"] for e in evts]

    assert events_seen.count("SHELF_REVISIT") == 1


def test_brief_flicker_does_not_reset_dwell_progress():
    """A one-frame dip into another zone shouldn't restart EXTENDED_DWELL's
    cumulative timer — the debounced zone should absorb the flicker."""
    t = IoUTracker("webcam")
    for _ in range(3):
        t.update([(_bbox_at(0.25), 0.9, None)], _frame(), W, H)

    tid = list(t._tracks.keys())[0]
    s = t._tracks[tid]

    for _ in range(100):
        t.update([(_bbox_at(0.25), 0.9, None)], _frame(), W, H)
    dwell_before_flicker = s.zone_dwell_frames.get("AISLE_A", 0)

    # A single-frame flicker toward AISLE_B, immediately back — should not
    # cross ZONE_STABILITY_FRAMES, so current_zone never actually changes.
    t.update([(_bbox_at(0.36), 0.9, None)], _frame(), W, H)
    t.update([(_bbox_at(0.25), 0.9, None)], _frame(), W, H)

    assert s.current_zone == "AISLE_A"
    assert s.zone_dwell_frames.get("AISLE_A", 0) >= dwell_before_flicker
