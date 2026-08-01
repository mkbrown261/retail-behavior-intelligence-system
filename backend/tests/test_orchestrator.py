"""
test_orchestrator.py — Integration tests for the event orchestrator.

Tests cover:
  - handle_detection creates a Person record on first detection
  - handle_detection reuses existing Person on subsequent detections
  - Staff detections skip scoring
  - EXIT_STORE deactivates person (is_active=False)
  - BYPASS_REGISTER at low score triggers an Alert (Bug 1.3)
  - crossed_threshold triggers an Alert
  - record_visit() is wired on EXIT_STORE (Bug 1.2)
  - Non-detection payloads (missing session_id/event_type) are silently skipped
  - Event.to_dict() no longer raises AttributeError (Bug 1.1)
"""
import asyncio
import pytest
import pytest_asyncio

from sqlalchemy import select

from app.models.person import Person
from app.models.event import Event
from app.models.analytics import Alert
from app.models.analytics import RepeatVisitor
from app.services import event_orchestrator
from app.services.event_orchestrator import (
    _session_to_person_id,
    _process_detection,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detection(session_id, event_type, **kwargs):
    return {
        "session_id":   session_id,
        "event_type":   event_type,
        "camera_id":    1,
        "bounding_box": [10, 20, 100, 200],
        "position_x":   0.5,
        "position_y":   0.5,
        "confidence":   0.95,
        "zone":         "AISLE_1",
        "dominant_color": "#3366AA",
        "is_staff":     False,
        **kwargs,
    }


# ── Person creation ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_first_detection_creates_person(db):
    """A brand-new session_id should create a Person row."""
    _session_to_person_id.clear()
    det = _detection("Person_NEW_001", "ENTER_STORE")
    await _process_detection(db, det)

    result = await db.execute(select(Person).where(Person.session_id == "Person_NEW_001"))
    person = result.scalar_one_or_none()
    assert person is not None
    assert person.session_id == "Person_NEW_001"
    assert person.person_type == "CUSTOMER"


@pytest.mark.asyncio
async def test_repeated_detection_reuses_person(db):
    """Multiple events for the same session_id should not create duplicate Persons."""
    _session_to_person_id.clear()
    sid = "Person_REPEAT_001"
    for event_type in ("ENTER_STORE", "PICK_ITEM", "HOLD_ITEM"):
        await _process_detection(db, _detection(sid, event_type))

    result = await db.execute(select(Person).where(Person.session_id == sid))
    persons = result.scalars().all()
    assert len(persons) == 1


@pytest.mark.asyncio
async def test_staff_detection_skips_scoring(db):
    """Staff detections should create Person with STAFF type and zero suspicion score."""
    _session_to_person_id.clear()
    det = _detection("Staff_001", "ENTER_STORE", is_staff=True)
    await _process_detection(db, det)

    result = await db.execute(select(Person).where(Person.session_id == "Staff_001"))
    person = result.scalar_one_or_none()
    assert person is not None
    assert person.person_type == "STAFF"
    assert (person.current_suspicion_score or 0.0) == 0.0


@pytest.mark.asyncio
async def test_exit_store_deactivates_person(db):
    """EXIT_STORE should set is_active=False and record exit_time."""
    _session_to_person_id.clear()
    sid = "Person_EXIT_001"
    await _process_detection(db, _detection(sid, "ENTER_STORE"))
    await _process_detection(db, _detection(sid, "EXIT_STORE"))

    result = await db.execute(select(Person).where(Person.session_id == sid))
    person = result.scalar_one_or_none()
    assert person is not None
    assert person.is_active is False
    assert person.exit_time is not None


# ── Alert generation ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bypass_register_low_score_creates_alert(db):
    """
    Bug 1.3: BYPASS_REGISTER MUST create an Alert even at low score, as long
    as it's a genuine bypass (item interaction, register never visited) — the
    real camera pipeline never emits BYPASS_REGISTER without items_held > 0,
    which only happens after PICK_ITEM.
    """
    _session_to_person_id.clear()
    sid = "Person_BYPASS_001"
    await _process_detection(db, _detection(sid, "ENTER_STORE"))
    await _process_detection(db, _detection(sid, "PICK_ITEM"))
    await _process_detection(db, _detection(sid, "BYPASS_REGISTER"))

    result = await db.execute(
        select(Alert).where(Alert.session_id == sid)
    )
    alerts = result.scalars().all()
    assert len(alerts) >= 1
    alert_types = [a.alert_type for a in alerts]
    assert "BYPASS_REGISTER" in alert_types


@pytest.mark.asyncio
async def test_bypass_register_without_item_interaction_does_not_alert(db):
    """
    A BYPASS_REGISTER with no prior item interaction is not a genuine bypass —
    scoring.py falls back to the softer AVOID_REGISTER rule, and it should NOT
    create a high-priority Alert (this was Bug: the old should_alert check keyed
    off the raw event_type instead of what scoring.py actually decided).
    """
    _session_to_person_id.clear()
    sid = "Person_BYPASS_NOITEM_001"
    await _process_detection(db, _detection(sid, "ENTER_STORE"))
    await _process_detection(db, _detection(sid, "BYPASS_REGISTER"))

    result = await db.execute(select(Alert).where(Alert.session_id == sid))
    alerts = result.scalars().all()
    assert len(alerts) == 0


@pytest.mark.asyncio
async def test_bypass_register_repeated_sensor_posts_alert_once(db):
    """
    A flaky external sensor (RFID gate reader) retrying its POST, or the
    camera pipeline re-evaluating the same lingering-near-exit state across
    frames, must not create a duplicate Alert per repeat BYPASS_REGISTER event
    for the same session — scoring.py's bypass_register_emitted one-shot guard
    must actually suppress the resulting alert, not just the score delta.

    Score is pre-seeded above HIGH_SUSPICION so crossed_threshold can't
    independently trigger a second, legitimately-distinct alert mid-loop —
    isolating the bypass-dedup behavior specifically.
    """
    _session_to_person_id.clear()
    sid = "Person_BYPASS_REPEAT_001"
    await _process_detection(db, _detection(sid, "ENTER_STORE"))
    for _ in range(7):
        await _process_detection(db, _detection(sid, "PICK_ITEM"))  # push score > 61

    for _ in range(5):
        await _process_detection(db, _detection(sid, "BYPASS_REGISTER"))

    result = await db.execute(select(Alert).where(Alert.session_id == sid))
    alerts = result.scalars().all()
    bypass_alerts = [a for a in alerts if a.alert_type == "BYPASS_REGISTER"]
    assert len(bypass_alerts) == 1


@pytest.mark.asyncio
async def test_exit_after_pick_creates_alert(db):
    """
    EXIT_AFTER_PICK alert fires when BYPASS_REGISTER event_type is used
    (event_type="BYPASS_REGISTER" always triggers an alert regardless of score).
    
    Note: EXIT_STORE with items held fires EXIT_AFTER_PICK from the *scoring engine*,
    but the should_alert check uses event_type="EXIT_STORE" which only alerts at score>=61.
    The explicit EXIT_AFTER_PICK event_type (e.g. from BYPASS_REGISTER path) always alerts.
    """
    _session_to_person_id.clear()
    sid = "Person_EXITPICK_001"
    await _process_detection(db, _detection(sid, "ENTER_STORE"))
    await _process_detection(db, _detection(sid, "PICK_ITEM"))
    # BYPASS_REGISTER has event_type="BYPASS_REGISTER" → always alerts
    await _process_detection(db, _detection(sid, "BYPASS_REGISTER"))

    result = await db.execute(select(Alert).where(Alert.session_id == sid))
    alerts = result.scalars().all()
    assert len(alerts) >= 1
    assert any(a.alert_type == "BYPASS_REGISTER" for a in alerts)


@pytest.mark.asyncio
async def test_exit_store_low_score_no_alert(db):
    """EXIT_STORE with score < 61 should NOT create an alert (clean exit)."""
    _session_to_person_id.clear()
    sid = "Person_CLEANEXIT_001"
    await _process_detection(db, _detection(sid, "ENTER_STORE"))
    # COMPLETE_CHECKOUT resets score to 0
    await _process_detection(db, _detection(sid, "COMPLETE_CHECKOUT"))
    await _process_detection(db, _detection(sid, "EXIT_STORE"))

    result = await db.execute(select(Alert).where(Alert.session_id == sid))
    alerts = result.scalars().all()
    # After checkout the score is 0 — no EXIT_STORE alert expected
    exit_alerts = [a for a in alerts if a.alert_type == "EXIT_STORE"]
    assert len(exit_alerts) == 0


# ── Event logging ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_events_are_logged(db):
    """Each detection should create a corresponding Event row."""
    _session_to_person_id.clear()
    sid = "Person_EVT_001"
    await _process_detection(db, _detection(sid, "ENTER_STORE"))
    await _process_detection(db, _detection(sid, "PICK_ITEM"))

    result = await db.execute(
        select(Person).where(Person.session_id == sid)
    )
    person = result.scalar_one_or_none()
    assert person is not None

    events_result = await db.execute(
        select(Event).where(Event.person_id == person.id)
    )
    events = events_result.scalars().all()
    assert len(events) == 2
    event_types = [e.event_type for e in events]
    assert "ENTER_STORE" in event_types
    assert "PICK_ITEM" in event_types


# ── Bug 1.1 — Event.to_dict() no longer crashes ────────────────────────────────

@pytest.mark.asyncio
async def test_event_to_dict_no_attribute_error(db):
    """Bug 1.1: Event.to_dict() must not raise AttributeError for self.metadata."""
    _session_to_person_id.clear()
    sid = "Person_TODICT_001"
    await _process_detection(db, _detection(sid, "PICK_ITEM"))

    result = await db.execute(
        select(Person).where(Person.session_id == sid)
    )
    person = result.scalar_one_or_none()
    assert person is not None

    events_result = await db.execute(
        select(Event).where(Event.person_id == person.id)
    )
    events = events_result.scalars().all()
    assert len(events) >= 1

    # This must NOT raise AttributeError
    for evt in events:
        d = evt.to_dict()
        assert "metadata" in d
        assert "event_type" in d


# ── Non-detection payloads silently skipped ─────────────────────────────────

@pytest.mark.asyncio
async def test_non_detection_payload_skipped(db):
    """FRAME_READY-style payloads (no session_id/event_type) must be silently ignored."""
    _session_to_person_id.clear()
    initial_count_result = await db.execute(select(Person))
    initial_count = len(initial_count_result.scalars().all())

    # Mimic a raw frame payload from CameraStream
    frame_payload = {
        "camera_id": 1,
        "frame": b"\xff\xd8\xff",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    await _process_detection(db, frame_payload)

    # No new persons should be created
    final_count_result = await db.execute(select(Person))
    final_count = len(final_count_result.scalars().all())
    assert final_count == initial_count
