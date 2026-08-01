"""
test_color_disappearance.py — the color-disappearance corroborating signal
(wrist patch color drifting back to the empty-hand baseline after a pick)
and its cross-referencing with the kinematic CONCEALMENT signal in the
Confidence Score engine.
"""
import numpy as np
import pytest

from app.services.ai_inference import (
    IoUTracker, _color_disappearance_ratio, _color_distance, _sample_color_at_point,
    _estimate_color_noise, _adaptive_color_thresholds,
    COLOR_RATIO_MIN, COLOR_RATIO_MAX, COLOR_MIN_CONTRAST_FLOOR, COLOR_NOISE_DEFAULT,
)
from app.services import confidence

W, H = 640, 480
BBOX = [0.4, 0.2, 0.6, 0.9]
BASELINE_BGR = (139, 90, 43)   # skin-ish tone
ITEM_BGR     = (0, 0, 255)     # bright red, BGR order


def _kp(wrist_xy):
    k = [(0.5, 0.5, 0.9)] * 17
    k[5] = (0.45, 0.3, 0.9); k[6] = (0.55, 0.3, 0.9)
    k[11] = (0.45, 0.6, 0.9); k[12] = (0.55, 0.6, 0.9)
    k[9] = (wrist_xy[0], wrist_xy[1], 0.9)
    return k


def _frame(wrist_xy_norm, patch_bgr, base_bgr=BASELINE_BGR):
    frame = np.full((H, W, 3), base_bgr, dtype=np.uint8)
    cx, cy = int(wrist_xy_norm[0] * W), int(wrist_xy_norm[1] * H)
    frame[max(0, cy - 9):cy + 9, max(0, cx - 9):cx + 9] = patch_bgr
    return frame


IDLE_KP    = _kp((0.40, 0.62))
REACH_KP   = _kp((0.05, 0.25))
RETRACT_KP = _kp((0.5, 0.5))


# ── Pure math ──────────────────────────────────────────────────────────────────

def test_ratio_zero_when_still_matches_held_color():
    assert _color_disappearance_ratio("#FF0000", "#FF0000", "#8B5A2B") == pytest.approx(0.0, abs=1e-6)


def test_ratio_one_when_fully_reverted_to_baseline():
    assert _color_disappearance_ratio("#8B5A2B", "#FF0000", "#8B5A2B") == pytest.approx(1.0, abs=1e-4)


def test_ratio_none_when_insufficient_contrast():
    assert _color_disappearance_ratio("#8B5A2B", "#8B5A2C", "#8B5A2B") is None


def test_sample_color_at_point_reads_patch():
    frame = _frame((0.5, 0.5), ITEM_BGR)
    color = _sample_color_at_point(frame, 0.5, 0.5)
    assert color == "#FF0000"  # BGR (0,0,255) -> RGB hex #FF0000


# ── Full tracker integration ────────────────────────────────────────────────────

def test_color_disappearance_fires_after_item_visually_vanishes():
    t = IoUTracker("webcam")
    for _ in range(3):
        t.update([(BBOX, 0.9, IDLE_KP)], _frame((0.40, 0.62), BASELINE_BGR), W, H)
    for _ in range(3):
        t.update([(BBOX, 0.9, REACH_KP)], _frame((0.05, 0.25), BASELINE_BGR), W, H)

    evts = t.update([(BBOX, 0.9, RETRACT_KP)], _frame((0.5, 0.5), ITEM_BGR), W, H)
    assert "PICK_ITEM" in [e["event_type"] for e in evts]

    # still visibly holding — no disappearance yet
    for _ in range(3):
        evts = t.update([(BBOX, 0.9, RETRACT_KP)], _frame((0.5, 0.5), ITEM_BGR), W, H)
        assert "COLOR_DISAPPEARANCE" not in [e["event_type"] for e in evts]

    # color reverts to baseline — item's visual signature is gone
    fired = False
    for _ in range(8):
        evts = t.update([(BBOX, 0.9, RETRACT_KP)], _frame((0.5, 0.5), BASELINE_BGR), W, H)
        if "COLOR_DISAPPEARANCE" in [e["event_type"] for e in evts]:
            fired = True
            evt = next(e for e in evts if e["event_type"] == "COLOR_DISAPPEARANCE")
            assert evt["disappearance_ratio"] > 0.5
    assert fired


def test_no_false_positive_when_item_color_matches_skin():
    """Honest limitation: item color ~= baseline color -> signal correctly abstains."""
    t = IoUTracker("webcam")
    near_skin_bgr = (140, 91, 44)  # nearly identical to BASELINE_BGR
    for _ in range(3):
        t.update([(BBOX, 0.9, IDLE_KP)], _frame((0.40, 0.62), BASELINE_BGR), W, H)
    for _ in range(3):
        t.update([(BBOX, 0.9, REACH_KP)], _frame((0.05, 0.25), BASELINE_BGR), W, H)
    t.update([(BBOX, 0.9, RETRACT_KP)], _frame((0.5, 0.5), near_skin_bgr), W, H)

    fired = False
    for _ in range(10):
        evts = t.update([(BBOX, 0.9, RETRACT_KP)], _frame((0.5, 0.5), BASELINE_BGR), W, H)
        if "COLOR_DISAPPEARANCE" in [e["event_type"] for e in evts]:
            fired = True
    assert not fired


# ── Lighting-adaptive thresholds ─────────────────────────────────────────────────

def test_noise_estimate_defaults_with_too_few_samples():
    assert _estimate_color_noise([]) == COLOR_NOISE_DEFAULT
    assert _estimate_color_noise(["#8B5A2B"]) == COLOR_NOISE_DEFAULT


def test_noise_estimate_reflects_actual_jitter():
    stable = _estimate_color_noise(["#8B5A2B", "#8B5A2C", "#8C5A2B"])
    jittery = _estimate_color_noise(["#8B5A2B", "#FF0000", "#00FF00", "#0000FF"])
    assert stable < 5.0
    assert jittery > 50.0


def test_adaptive_thresholds_relax_when_clean_signal():
    min_contrast, ratio = _adaptive_color_thresholds(noise_estimate=1.0, held_baseline_contrast=200.0)
    assert min_contrast == COLOR_MIN_CONTRAST_FLOOR  # noise negligible, floor applies
    assert ratio == pytest.approx(COLOR_RATIO_MIN, abs=0.02)  # clean signal -> most sensitive


def test_adaptive_thresholds_tighten_when_noisy_signal():
    min_contrast, ratio = _adaptive_color_thresholds(noise_estimate=40.0, held_baseline_contrast=50.0)
    assert min_contrast > COLOR_MIN_CONTRAST_FLOOR * 2  # noise-driven, well above the floor
    assert ratio == pytest.approx(COLOR_RATIO_MAX, abs=0.02)  # noisy signal -> most conservative


def test_noisy_environment_suppresses_a_borderline_false_positive():
    """
    A wrist patch that only PARTIALLY reverts toward baseline (a realistic,
    ambiguous case — maybe the item just shifted in hand, not truly gone)
    should NOT fire in a noisy/flickering-light environment, but SHOULD fire
    once conditions are clean, using the exact same detection code — this is
    the actual lighting-adaptivity, not just two different fixed thresholds.
    """
    # A moderate-contrast item (not the maximal red-vs-skin case used
    # elsewhere) — realistic enough that noise can meaningfully compete with
    # the signal, which is the point of this test.
    moderate_item_bgr = (60, 70, 120)

    def run(idle_bgrs, partial_revert_bgr):
        t = IoUTracker("webcam")
        # Feed jittery (or stable) idle samples before the reach starts, to
        # seed this track's own noise floor. Fill the whole frame (not just
        # the patch) so the sampled idle color actually varies per sample.
        for bgr in idle_bgrs:
            t.update([(BBOX, 0.9, IDLE_KP)], _frame((0.40, 0.62), bgr, base_bgr=bgr), W, H)
        for _ in range(3):
            t.update([(BBOX, 0.9, REACH_KP)], _frame((0.05, 0.25), BASELINE_BGR, base_bgr=BASELINE_BGR), W, H)
        t.update([(BBOX, 0.9, RETRACT_KP)], _frame((0.5, 0.5), moderate_item_bgr), W, H)

        fired = False
        for _ in range(8):
            evts = t.update([(BBOX, 0.9, RETRACT_KP)], _frame((0.5, 0.5), partial_revert_bgr), W, H)
            if "COLOR_DISAPPEARANCE" in [e["event_type"] for e in evts]:
                fired = True
        return fired

    # A patch about 65% of the way back to baseline — genuinely ambiguous.
    partial_revert = tuple(int(a + 0.65 * (b - a)) for a, b in zip(moderate_item_bgr, BASELINE_BGR))

    stable_idle = [BASELINE_BGR] * 6
    jittery_idle = [(139, 90, 43), (170, 60, 80), (100, 130, 20), (160, 70, 90), (110, 100, 60), (150, 80, 30)]

    assert run(stable_idle, partial_revert) is True     # clean signal -> sensitive enough to catch it
    assert run(jittery_idle, partial_revert) is False   # noisy signal -> correctly holds back


# ── Confidence engine corroboration ─────────────────────────────────────────────

def test_confidence_corroboration_bonus_requires_both_signals():
    confidence.record_event("solo", "s1", "PICK_ITEM")
    confidence.record_event("solo", "s1", "CONCEALMENT")
    solo = confidence.get_breakdown("solo")
    assert solo["corroboration_bonus"] == 0.0

    confidence.record_event("both", "s2", "PICK_ITEM")
    confidence.record_event("both", "s2", "CONCEALMENT")
    confidence.record_event("both", "s2", "COLOR_DISAPPEARANCE")
    both = confidence.get_breakdown("both")
    assert both["corroboration_bonus"] > 0.0
    assert both["overall_confidence"] > solo["overall_confidence"] + 5  # meaningfully higher, not just additive


def test_color_disappearance_alone_does_not_corroborate():
    confidence.record_event("color_only", "s3", "COLOR_DISAPPEARANCE")
    result = confidence.get_breakdown("color_only")
    assert result["corroboration_bonus"] == 0.0
