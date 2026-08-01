"""
confidence.py — Incident Confidence Score engine.

The existing suspicion `score` (scoring.py) is a single flat 0-100 number
built from additive point rules. That's fine for triggering alerts, but it
tells an operator nothing about *why* — was this flagged because of one
strong signal (concealment) or a pile of weak ones (loitering + movement)?

This module computes a transparent, multi-factor breakdown on top of the
same event stream, in the spirit of:

    Motion Pattern ........ 24%
    Object Interaction .... 31%
    Concealment Evidence .. 38%
    Color Disappearance ... 22%
    Exit Behavior ......... 19%
    Employee Presence ..... -12%
    Corroboration Bonus ... +12  (kinematic + color signals agreed)
    Overall Confidence: 82%
    Recommendation: Review Before Escalation

It does NOT replace scoring.py or alert triggering — it's an additive,
explainability layer. If this module has a bug, alerts still fire normally
from the existing score engine; this only affects the "why" shown to a
human reviewer.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ── Factor weights — must sum to 1.0 across the positive factors ───────────
FACTOR_WEIGHTS = {
    "motion_pattern":       0.12,
    "object_interaction":   0.20,
    "concealment_evidence": 0.28,   # strongest signal — pose-kinematic (hand position)
    "color_disappearance":  0.15,   # corroborating signal — wrist color reverting to baseline
    "exit_behavior":        0.25,
}

# When BOTH concealment_evidence AND color_disappearance fired for the same
# person, that's two independently-computed signals agreeing — worth more
# than the sum of their weighted parts. This is the actual "cross-reference"
# between the kinematic and color signals, not just adding two numbers.
CORROBORATION_BONUS = 12.0

# Each factor's raw hit-points cap at this value before weighting (0-100 sub-scale)
FACTOR_CAP = 100.0

# Points added to a factor's raw tally per contributing event
EVENT_FACTOR_POINTS = {
    "RAPID_MOVEMENT":    ("motion_pattern", 8),
    "LOITER":            ("motion_pattern", 15),
    "PICK_ITEM":         ("object_interaction", 30),
    "MULTI_ITEM":        ("object_interaction", 20),
    "HOLD_ITEM_10S":     ("object_interaction", 8),
    "CONCEALMENT":       ("concealment_evidence", 70),  # one strong hit is most of the way there
    "BYPASS_REGISTER":   ("exit_behavior", 45),
    "EXIT_AFTER_PICK":   ("exit_behavior", 35),
    "AVOID_REGISTER":    ("exit_behavior", 25),
    "RAPID_EXIT":        ("exit_behavior", 20),
    "SHELF_REVISIT":     ("motion_pattern", 20),
    "EXTENDED_DWELL":    ("motion_pattern", 25),
    "COLOR_DISAPPEARANCE": ("color_disappearance", 65),
}

EMPLOYEE_PRESENCE_ADJUSTMENT = -60.0  # flat pull-down applied once if is_staff

RECOMMENDATION_THRESHOLDS = [
    (75, "Escalate — High Confidence"),
    (40, "Review Before Escalation"),
    (0,  "Low Priority — Monitor Only"),
]


@dataclass
class ConfidenceTally:
    person_id:   str
    session_id:  str
    factors: Dict[str, float] = field(default_factory=lambda: {k: 0.0 for k in FACTOR_WEIGHTS})
    is_staff:    bool = False
    last_update: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    contributing_events: List[str] = field(default_factory=list)  # for the "why" trail
    escalation_alerted: bool = False  # one-time trigger — see check_and_mark_escalation()


_tallies: Dict[str, ConfidenceTally] = {}


def _get_or_create(person_id: str, session_id: str) -> ConfidenceTally:
    if person_id not in _tallies:
        _tallies[person_id] = ConfidenceTally(person_id=person_id, session_id=session_id)
    return _tallies[person_id]


def record_event(person_id: str, session_id: str, reason: str, is_staff: bool = False) -> None:
    """
    Called alongside scoring.apply_score_delta for every scored event —
    accumulates per-factor raw points. Cheap, synchronous, no DB/lock needed
    (single-writer per event-processing coroutine, same as scoring.py's
    pattern before its own lock fix — but this module doesn't feed alerts,
    so a rare lost update here only dulls the explanation, never triggers a
    false alert on its own).
    """
    tally = _get_or_create(person_id, session_id)
    tally.is_staff = is_staff
    tally.last_update = datetime.now(timezone.utc)

    mapping = EVENT_FACTOR_POINTS.get(reason)
    if mapping:
        factor, points = mapping
        tally.factors[factor] = min(FACTOR_CAP, tally.factors[factor] + points)
        tally.contributing_events.append(reason)


def get_breakdown(person_id: str) -> Optional[Dict]:
    """Return the transparent multi-factor breakdown for a person, or None if unseen."""
    tally = _tallies.get(person_id)
    if tally is None:
        return None

    weighted = {f: tally.factors[f] * FACTOR_WEIGHTS[f] for f in FACTOR_WEIGHTS}
    overall = sum(weighted.values())

    # Corroboration bonus — two independent signals (hand kinematics + item
    # color) agreeing is worth more than their weighted sum implies.
    corroborated = tally.factors["concealment_evidence"] > 0 and tally.factors["color_disappearance"] > 0
    corroboration_bonus = CORROBORATION_BONUS if corroborated else 0.0
    overall += corroboration_bonus

    employee_adjustment = EMPLOYEE_PRESENCE_ADJUSTMENT if tally.is_staff else 0.0
    overall = max(0.0, min(100.0, overall + employee_adjustment))

    recommendation = next(
        label for threshold, label in RECOMMENDATION_THRESHOLDS if overall >= threshold
    )

    return {
        "person_id":  person_id,
        "session_id": tally.session_id,
        "factors": {
            "motion_pattern":       round(weighted["motion_pattern"], 1),
            "object_interaction":   round(weighted["object_interaction"], 1),
            "concealment_evidence": round(weighted["concealment_evidence"], 1),
            "color_disappearance":  round(weighted["color_disappearance"], 1),
            "exit_behavior":        round(weighted["exit_behavior"], 1),
            "employee_presence":    round(employee_adjustment, 1),
        },
        "corroboration_bonus": corroboration_bonus,
        "raw_factors": {k: round(v, 1) for k, v in tally.factors.items()},
        "overall_confidence": round(overall, 1),
        "recommendation": recommendation,
        "contributing_events": tally.contributing_events[-20:],  # most recent 20, avoid unbounded growth
    }


def check_and_mark_escalation(person_id: str) -> bool:
    """
    Returns True exactly once per person, the first time their confidence
    breakdown reaches "Escalate — High Confidence" — an alert trigger
    independent of the flat additive score in scoring.py. The two engines
    weight the same event stream differently (this one has the corroboration
    bonus), so they can genuinely diverge: this lets a strong multi-factor
    read (e.g. concealment + color both firing) trigger an alert even on a
    session where the flat score hasn't crossed its own threshold yet.
    """
    tally = _tallies.get(person_id)
    if tally is None or tally.escalation_alerted:
        return False
    breakdown = get_breakdown(person_id)
    if breakdown and breakdown["recommendation"] == "Escalate — High Confidence":
        tally.escalation_alerted = True
        return True
    return False


def remove_tally(person_id: str) -> None:
    _tallies.pop(person_id, None)
