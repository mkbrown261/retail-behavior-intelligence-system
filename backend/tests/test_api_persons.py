"""
test_api_persons.py — HTTP-level tests for the /api/persons endpoints.

Covers:
  - GET /api/persons/               list all persons
  - GET /api/persons/stats          aggregate counts
  - GET /api/persons/live-scores    in-memory live scores
  - GET /api/persons/{id}           single person fetch
  - GET /api/persons/{id}/events    person's events
  - GET /api/persons/{id}/timeline  interleaved timeline
  - GET /api/persons/{id}/score-history  suspicion score snapshots
  - PATCH /api/persons/{id}/type    update person type
  - 404 / 422 error cases
"""
import uuid
import pytest

from app.models.person import Person
from app.models.event import Event


def valid_uuid():
    return str(uuid.uuid4())


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _create_person(db, session_id=None, person_type="CUSTOMER", is_flagged=False):
    p = Person(
        session_id=session_id or f"Person_{uuid.uuid4().hex[:6]}",
        person_type=person_type,
        is_flagged=is_flagged,
        current_suspicion_score=0.0,
    )
    db.add(p)
    await db.flush()
    await db.commit()
    return p


# ── GET /api/persons/ ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_persons_empty(client):
    resp = await client.get("/api/persons/")
    assert resp.status_code == 200
    data = resp.json()
    assert "persons" in data
    assert data["count"] == 0


@pytest.mark.asyncio
async def test_list_persons_returns_all(client, db):
    await _create_person(db)
    await _create_person(db)
    resp = await client.get("/api/persons/")
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


@pytest.mark.asyncio
async def test_list_persons_filter_active(client, db):
    p1 = await _create_person(db)
    p2 = await _create_person(db)
    p2.is_active = False
    await db.commit()

    resp = await client.get("/api/persons/?active_only=true")
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["persons"]]
    assert p1.id in ids
    assert p2.id not in ids


@pytest.mark.asyncio
async def test_list_persons_filter_flagged(client, db):
    await _create_person(db, is_flagged=False)
    flagged = await _create_person(db, is_flagged=True)

    resp = await client.get("/api/persons/?flagged_only=true")
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["persons"]]
    assert flagged.id in ids
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_list_persons_filter_staff(client, db):
    await _create_person(db, person_type="CUSTOMER")
    staff = await _create_person(db, person_type="STAFF")

    resp = await client.get("/api/persons/?person_type=STAFF")
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["persons"]]
    assert staff.id in ids
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_list_persons_invalid_type_422(client):
    resp = await client.get("/api/persons/?person_type=ROBOT")
    assert resp.status_code == 422


# ── GET /api/persons/stats ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_person_stats_empty(client):
    resp = await client.get("/api/persons/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["active"] == 0
    assert data["flagged"] == 0


@pytest.mark.asyncio
async def test_person_stats_counts(client, db):
    await _create_person(db, person_type="CUSTOMER", is_flagged=True)
    await _create_person(db, person_type="STAFF")
    await _create_person(db, person_type="CUSTOMER")

    resp = await client.get("/api/persons/stats")
    data = resp.json()
    assert data["total"] == 3
    assert data["staff"] == 1
    assert data["customers"] == 2
    assert data["flagged"] == 1


# ── GET /api/persons/live-scores ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_live_scores_returns_list(client):
    resp = await client.get("/api/persons/live-scores")
    assert resp.status_code == 200
    assert "scores" in resp.json()
    assert isinstance(resp.json()["scores"], list)


# ── GET /api/persons/{id} ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_person_found(client, db):
    p = await _create_person(db)
    resp = await client.get(f"/api/persons/{p.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == p.id
    assert resp.json()["session_id"] == p.session_id


@pytest.mark.asyncio
async def test_get_person_not_found(client):
    resp = await client.get(f"/api/persons/{valid_uuid()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_person_invalid_uuid_422(client):
    resp = await client.get("/api/persons/not-a-uuid")
    assert resp.status_code == 422


# ── GET /api/persons/{id}/events ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_person_events_empty(client, db):
    p = await _create_person(db)
    resp = await client.get(f"/api/persons/{p.id}/events")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


@pytest.mark.asyncio
async def test_get_person_events_returns_events(client, db):
    p = await _create_person(db)
    evt = Event(person_id=p.id, event_type="PICK_ITEM", camera_id=1, position_x=0.5, position_y=0.5, confidence=0.9, zone="AISLE")
    db.add(evt)
    await db.commit()

    resp = await client.get(f"/api/persons/{p.id}/events")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    # Bug 1.1 — to_dict() must not crash
    assert data["events"][0]["event_type"] == "PICK_ITEM"
    assert "metadata" in data["events"][0]


# ── GET /api/persons/{id}/timeline ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_person_timeline(client, db):
    p = await _create_person(db)
    evt = Event(person_id=p.id, event_type="ENTER_STORE", camera_id=1, position_x=0.5, position_y=0.5, confidence=0.9, zone="ENTRANCE")
    db.add(evt)
    await db.commit()

    resp = await client.get(f"/api/persons/{p.id}/timeline")
    assert resp.status_code == 200
    data = resp.json()
    assert "person" in data
    assert "timeline" in data
    assert data["event_count"] == 1


@pytest.mark.asyncio
async def test_get_person_timeline_not_found(client):
    resp = await client.get(f"/api/persons/{valid_uuid()}/timeline")
    assert resp.status_code == 404


# ── GET /api/persons/{id}/score-history ──────────────────────────────────────

@pytest.mark.asyncio
async def test_get_score_history_empty(client, db):
    p = await _create_person(db)
    resp = await client.get(f"/api/persons/{p.id}/score-history")
    assert resp.status_code == 200
    assert resp.json()["scores"] == []


# ── PATCH /api/persons/{id}/type ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_person_type_to_staff(client, db):
    p = await _create_person(db, person_type="CUSTOMER")
    resp = await client.patch(f"/api/persons/{p.id}/type?person_type=STAFF")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["person_type"] == "STAFF"


@pytest.mark.asyncio
async def test_update_person_type_invalid_value(client, db):
    p = await _create_person(db)
    resp = await client.patch(f"/api/persons/{p.id}/type?person_type=ROBOT")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_person_type_not_found(client):
    resp = await client.patch(f"/api/persons/{valid_uuid()}/type?person_type=STAFF")
    assert resp.status_code == 404
