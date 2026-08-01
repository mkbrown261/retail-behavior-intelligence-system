"""
test_item_identification.py — ITEM_IDENTIFIED sensor events merged into a
person's timeline, correlated by session_id (not auto-linked to a specific
PICK_ITEM — a human reviewer draws that connection by proximity in time).
"""
import uuid
import pytest

from app.models.person import Person


def _sid():
    return f"Person_{uuid.uuid4().hex[:6]}"


async def _create_person(db, session_id, person_type="CUSTOMER"):
    p = Person(session_id=session_id, person_type=person_type, current_suspicion_score=0.0)
    db.add(p)
    await db.flush()
    await db.commit()
    return p


@pytest.mark.asyncio
async def test_item_identified_is_logged_and_not_routed_to_scoring(client):
    resp = await client.post("/api/sensors/event", json={
        "sensor_type": "SMART_SHELF",
        "event_type": "ITEM_IDENTIFIED",
        "session_id": "some_session",
        "payload": {"tag_id": "E200341203AABBCC", "item_name": "Nike Hoodie", "sku": "12345", "price": 39.99},
    })
    assert resp.status_code == 200
    data = resp.json()
    # ITEM_IDENTIFIED isn't in ROUTABLE_EVENT_TYPES — informational only
    assert data["correlated"] == "logged_only"
    assert data["payload"]["item_name"] == "Nike Hoodie"


@pytest.mark.asyncio
async def test_item_identified_appears_in_person_timeline(client, db):
    session_id = _sid()
    person = await _create_person(db, session_id)

    await client.post("/api/sensors/event", json={
        "sensor_type": "RFID_GATE",
        "event_type": "ITEM_IDENTIFIED",
        "session_id": session_id,
        "payload": {"tag_id": "E200341203AABBCC", "item_name": "Nike Hoodie", "sku": "12345"},
    })

    resp = await client.get(f"/api/persons/{person.id}/timeline")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sensor_events"] == 1

    sensor_entries = [t for t in data["timeline"] if t["kind"] == "SENSOR"]
    assert len(sensor_entries) == 1
    assert sensor_entries[0]["data"]["payload"]["item_name"] == "Nike Hoodie"


@pytest.mark.asyncio
async def test_timeline_with_no_sensor_events_still_works(client, db):
    session_id = _sid()
    person = await _create_person(db, session_id)

    resp = await client.get(f"/api/persons/{person.id}/timeline")
    assert resp.status_code == 200
    assert resp.json()["sensor_events"] == 0
