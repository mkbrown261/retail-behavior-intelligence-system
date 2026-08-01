"""
test_sensor_bus.py — HTTP-level tests for the generic Sensor Bus ingestion
endpoint (/api/sensors/event) and the routing logic in services/sensor_bus.py.
"""
import pytest


@pytest.mark.asyncio
async def test_unroutable_event_is_logged_only(client):
    """An event type we don't know how to score is persisted but not routed."""
    resp = await client.post("/api/sensors/event", json={
        "sensor_type": "DOOR_SENSOR",
        "event_type": "DOOR_OPENED",
        "payload": {"door_id": "back_entrance"},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["correlated"] == "logged_only"
    assert data["sensor_type"] == "DOOR_SENSOR"
    assert data["payload"]["door_id"] == "back_entrance"


@pytest.mark.asyncio
async def test_routable_event_without_session_id_is_logged_only(client):
    """Even a routable event_type needs a session_id to actually route."""
    resp = await client.post("/api/sensors/event", json={
        "sensor_type": "POS",
        "event_type": "COMPLETE_CHECKOUT",
    })
    assert resp.status_code == 200
    assert resp.json()["correlated"] == "logged_only"


@pytest.mark.asyncio
async def test_routable_event_with_session_id_routes_into_scoring(client):
    """
    A POS terminal reporting a completed checkout for a known tracked person
    should feed the same scoring pipeline a camera detection would.
    """
    session_id = "CAMbcam_test_T0001"

    resp = await client.post("/api/sensors/event", json={
        "sensor_type": "POS",
        "event_type": "COMPLETE_CHECKOUT",
        "session_id": session_id,
        "camera_id": "webcam",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["correlated"] == "routed"
    assert data["session_id"] == session_id

    # The routed event should have created a Person row via the normal pipeline
    persons_resp = await client.get("/api/persons/", params={"limit": 10})
    assert persons_resp.status_code == 200
    sessions = [p["session_id"] for p in persons_resp.json()["persons"]]
    assert session_id in sessions


@pytest.mark.asyncio
async def test_invalid_confidence_rejected(client):
    resp = await client.post("/api/sensors/event", json={
        "sensor_type": "RFID_GATE",
        "event_type": "TAG_READ",
        "confidence": 1.5,  # out of [0,1] range
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_sensor_events_filters_by_sensor_type(client):
    await client.post("/api/sensors/event", json={"sensor_type": "RFID_GATE", "event_type": "TAG_READ"})
    await client.post("/api/sensors/event", json={"sensor_type": "DOOR_SENSOR", "event_type": "DOOR_OPENED"})

    resp = await client.get("/api/sensors/events", params={"sensor_type": "RFID_GATE"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["events"][0]["sensor_type"] == "RFID_GATE"
