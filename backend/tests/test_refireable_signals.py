"""
test_refireable_signals.py — CONCEALMENT and COLOR_DISAPPEARANCE as
re-fireable exposed/hidden state machines (not one-shot-per-pick), and the
IDLE_10S score decay that prevents a score from staying pinned at 100
forever once a person returns to calm behavior.
"""
import asyncio
from unittest.mock import AsyncMock

import numpy as np
import pytest

from app.services.ai_inference import IoUTracker
from app.services.scoring import process_event_for_score

W, H = 640, 480
BBOX = [0.4, 0.2, 0.6, 0.9]


def _kp(wrist_xy):
    k = [(0.5, 0.5, 0.9)] * 17
    k[5] = (0.45, 0.3, 0.9); k[6] = (0.55, 0.3, 0.9)
    k[11] = (0.45, 0.6, 0.9); k[12] = (0.55, 0.6, 0.9)
    k[9] = (wrist_xy[0], wrist_xy[1], 0.9)
    return k


IDLE_KP    = _kp((0.40, 0.62))
REACH_KP   = _kp((0.05, 0.25))
DEEP_KP    = _kp((0.5, 0.5))     # deep retract -> concealed
EXPOSED_KP = _kp((0.15, 0.30))   # pulled back out, well above re-expose threshold


def _frame():
    return np.zeros((H, W, 3), dtype=np.uint8)


# ── CONCEALMENT re-fire ────────────────────────────────────────────────────────

def test_concealment_refires_after_reexposure():
    t = IoUTracker("webcam")
    for _ in range(3):
        t.update([(BBOX, 0.9, IDLE_KP)], _frame(), W, H)
    for _ in range(3):
        t.update([(BBOX, 0.9, REACH_KP)], _frame(), W, H)

    evts = t.update([(BBOX, 0.9, DEEP_KP)], _frame(), W, H)
    assert "CONCEALMENT" in [e["event_type"] for e in evts]

    evts = t.update([(BBOX, 0.9, EXPOSED_KP)], _frame(), W, H)
    assert "CONCEALMENT" not in [e["event_type"] for e in evts]

    evts = t.update([(BBOX, 0.9, DEEP_KP)], _frame(), W, H)
    assert "CONCEALMENT" in [e["event_type"] for e in evts]


def test_concealment_does_not_spam_while_staying_concealed():
    t = IoUTracker("webcam")
    for _ in range(3):
        t.update([(BBOX, 0.9, IDLE_KP)], _frame(), W, H)
    for _ in range(3):
        t.update([(BBOX, 0.9, REACH_KP)], _frame(), W, H)

    fire_count = 0
    for _ in range(10):
        evts = t.update([(BBOX, 0.9, DEEP_KP)], _frame(), W, H)
        fire_count += evts.count if False else sum(1 for e in evts if e["event_type"] == "CONCEALMENT")
    assert fire_count == 1  # only the transition into "concealed", not every frame spent there


def test_concealment_does_not_toggle_at_boundary_hysteresis():
    """A wrist hovering between the conceal and re-expose thresholds
    shouldn't rapidly re-fire — hysteresis gap should absorb it."""
    t = IoUTracker("webcam")
    for _ in range(3):
        t.update([(BBOX, 0.9, IDLE_KP)], _frame(), W, H)
    for _ in range(3):
        t.update([(BBOX, 0.9, REACH_KP)], _frame(), W, H)

    borderline_kp = _kp((0.35, 0.42))  # somewhere between conceal (0.50) and re-expose (0.80) ratios

    evts = t.update([(BBOX, 0.9, DEEP_KP)], _frame(), W, H)
    first_fire = "CONCEALMENT" in [e["event_type"] for e in evts]

    fire_count = 0
    for _ in range(10):
        evts = t.update([(BBOX, 0.9, borderline_kp)], _frame(), W, H)
        fire_count += sum(1 for e in evts if e["event_type"] == "CONCEALMENT")

    assert first_fire is True
    assert fire_count == 0  # still "concealed" state — borderline ratio never crossed re-expose


# ── COLOR_DISAPPEARANCE re-fire ─────────────────────────────────────────────────

def test_color_disappearance_refires_after_reappearance():
    BASELINE_BGR = (139, 90, 43)
    ITEM_BGR = (0, 0, 255)

    def frame_at(wrist_xy_norm, patch_bgr):
        f = np.full((H, W, 3), BASELINE_BGR, dtype=np.uint8)
        cx, cy = int(wrist_xy_norm[0] * W), int(wrist_xy_norm[1] * H)
        f[max(0, cy - 9):cy + 9, max(0, cx - 9):cx + 9] = patch_bgr
        return f

    t = IoUTracker("webcam")
    for _ in range(3):
        t.update([(BBOX, 0.9, IDLE_KP)], frame_at((0.40, 0.62), BASELINE_BGR), W, H)
    for _ in range(3):
        t.update([(BBOX, 0.9, REACH_KP)], frame_at((0.05, 0.25), BASELINE_BGR), W, H)
    t.update([(BBOX, 0.9, DEEP_KP)], frame_at((0.5, 0.5), ITEM_BGR), W, H)

    # color disappears (reverts to baseline)
    fired_hidden = False
    for _ in range(6):
        evts = t.update([(BBOX, 0.9, DEEP_KP)], frame_at((0.5, 0.5), BASELINE_BGR), W, H)
        if "COLOR_DISAPPEARANCE" in [e["event_type"] for e in evts]:
            fired_hidden = True
    assert fired_hidden

    # color reappears (item color shows again)
    for _ in range(6):
        t.update([(BBOX, 0.9, DEEP_KP)], frame_at((0.5, 0.5), ITEM_BGR), W, H)

    # color disappears again — should re-fire
    fired_again = False
    for _ in range(6):
        evts = t.update([(BBOX, 0.9, DEEP_KP)], frame_at((0.5, 0.5), BASELINE_BGR), W, H)
        if "COLOR_DISAPPEARANCE" in [e["event_type"] for e in evts]:
            fired_again = True
    assert fired_again


# ── IDLE_10S score decay ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_idle_decay_reduces_score_incrementally_not_compounding():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.add = lambda x: None

    pid, sid = "decay_person", "s1"
    await process_event_for_score(db, pid, sid, "PICK_ITEM")
    r = await process_event_for_score(db, pid, sid, "CONCEALMENT")
    score_after_conceal = r["score"]

    r1 = await process_event_for_score(db, pid, sid, "IDLE_10S", metadata={"duration_seconds": 10})
    r2 = await process_event_for_score(db, pid, sid, "IDLE_10S", metadata={"duration_seconds": 20})
    r3 = await process_event_for_score(db, pid, sid, "IDLE_10S", metadata={"duration_seconds": 30})

    assert r1["delta"] == -1
    assert r2["delta"] == -1  # flat -1 per NEW increment, not compounding
    assert r3["delta"] == -1
    assert r3["score"] == pytest.approx(score_after_conceal - 3, abs=0.01)


@pytest.mark.asyncio
async def test_idle_decay_never_goes_below_zero():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.add = lambda x: None

    pid, sid = "low_score_person", "s2"
    r = None
    for dur in range(10, 500, 10):
        r = await process_event_for_score(db, pid, sid, "IDLE_10S", metadata={"duration_seconds": dur})
    assert r["score"] == 0.0
