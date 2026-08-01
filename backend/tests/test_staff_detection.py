"""
test_staff_detection.py — uniform-color heuristic + Sensor Bus badge-scan
staff detection.
"""
import uuid
import pytest

from app.models.person import Person
from app.services.ai_inference import ZoneConfig, _color_matches_staff_uniform


def _sid():
    return f"Person_{uuid.uuid4().hex[:6]}"


async def _create_person(db, session_id, person_type="CUSTOMER"):
    p = Person(session_id=session_id, person_type=person_type, current_suspicion_score=0.0)
    db.add(p)
    await db.flush()
    await db.commit()
    return p


# ── Color-matching heuristic ──────────────────────────────────────────────────

def test_no_configured_colors_never_matches():
    cfg = ZoneConfig()
    assert _color_matches_staff_uniform("#1A3C6E", cfg) is False


def test_exact_color_match():
    cfg = ZoneConfig.from_dict({"staff_uniform_colors": ["#1A3C6E"]})
    assert _color_matches_staff_uniform("#1A3C6E", cfg) is True


def test_close_color_within_tolerance_matches():
    cfg = ZoneConfig.from_dict({"staff_uniform_colors": ["#1A3C6E"], "staff_color_tolerance": 45})
    assert _color_matches_staff_uniform("#203F70", cfg) is True  # small delta


def test_far_color_does_not_match():
    cfg = ZoneConfig.from_dict({"staff_uniform_colors": ["#1A3C6E"]})
    assert _color_matches_staff_uniform("#FF0000", cfg) is False


def test_tighter_tolerance_rejects_previously_matching_color():
    cfg = ZoneConfig.from_dict({"staff_uniform_colors": ["#1A3C6E"], "staff_color_tolerance": 5})
    assert _color_matches_staff_uniform("#203F70", cfg) is False


# ── Sensor Bus badge scan ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_badge_scan_promotes_customer_to_staff(client, db):
    session_id = _sid()
    await _create_person(db, session_id, person_type="CUSTOMER")

    resp = await client.post("/api/sensors/event", json={
        "sensor_type": "BADGE_READER",
        "event_type": "STAFF_BADGE_SCAN",
        "session_id": session_id,
    })
    assert resp.status_code == 200
    assert resp.json()["correlated"] == "routed"

    person_resp = await client.get("/api/persons/", params={"limit": 10})
    match = next(p for p in person_resp.json()["persons"] if p["session_id"] == session_id)
    assert match["person_type"] == "STAFF"


@pytest.mark.asyncio
async def test_badge_scan_for_unknown_session_is_logged_only(client):
    resp = await client.post("/api/sensors/event", json={
        "sensor_type": "BADGE_READER",
        "event_type": "STAFF_BADGE_SCAN",
        "session_id": "nonexistent_session",
    })
    assert resp.status_code == 200
    assert resp.json()["correlated"] == "logged_only"


@pytest.mark.asyncio
async def test_badge_scan_without_session_id_is_logged_only(client):
    resp = await client.post("/api/sensors/event", json={
        "sensor_type": "BADGE_READER",
        "event_type": "STAFF_BADGE_SCAN",
    })
    assert resp.status_code == 200
    assert resp.json()["correlated"] == "logged_only"
