"""
test_bypass_register_dedup.py — BYPASS_REGISTER previously had no one-shot
guard of its own: unlike APPROACH_REGISTER (guarded by visited_register) and
EXIT_STORE (guarded by exited), it re-evaluated its raw conditions on every
single processed frame. A person with an item who lingers past the register,
near the exit, without ever entering the register zone would generate a new
BYPASS_REGISTER event on every frame — and since event_orchestrator treats
BYPASS_REGISTER as always-alert regardless of prior state, that meant a
burst of duplicate Alert rows (and duplicate notification dispatches) for
one continuous incident. Fixed with a dedicated bypass_register_emitted
one-shot flag, mirroring the existing pattern.
"""
import numpy as np

from app.services.ai_inference import IoUTracker

W, H = 640, 480


def _bbox_at(cx, cy=0.3):
    return [cx - 0.05, cy - 0.1, cx + 0.05, cy + 0.1]


def _frame():
    return np.zeros((H, W, 3), dtype=np.uint8)


def test_bypass_register_fires_once_while_lingering_near_exit():
    t = IoUTracker("webcam")

    # Confirm a track, away from the register zone.
    for _ in range(3):
        t.update([(_bbox_at(0.90), 0.9, None)], _frame(), W, H)

    tid = list(t._tracks.keys())[0]
    s = t._tracks[tid]
    s.items_held = 1  # simulate having picked up an item

    bypass_count = 0
    for _ in range(20):
        evts = t.update([(_bbox_at(0.90), 0.9, None)], _frame(), W, H)
        bypass_count += sum(1 for e in evts if e["event_type"] == "BYPASS_REGISTER")

    assert bypass_count == 1
    assert s.bypass_register_emitted is True
