"""
test_api_alerts.py — HTTP-level tests for the /api/alerts endpoints.

Covers:
  - GET /api/alerts/               list all alerts
  - GET /api/alerts/stats          severity breakdown
  - GET /api/alerts/top-incidents  highest score alerts
  - GET /api/alerts/{id}           single alert
  - POST /api/alerts/{id}/acknowledge
  - Severity filter and unacknowledged_only filter
  - 404 / 422 error cases
  - session_id present in to_dict() response (Bug 1.4)
"""
import uuid
import pytest

from app.models.analytics import Alert
from app.models.person import Person


def valid_uuid():
    return str(uuid.uuid4())


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _create_alert(db, session_id=None, severity="HIGH", score=75.0, alert_type="HIGH_SUSPICION", acknowledged=False):
    from app.models.person import Person
    sid = session_id or f"Person_{uuid.uuid4().hex[:6]}"
    p = Person(session_id=sid)
    db.add(p)
    await db.flush()

    a = Alert(
        person_id=p.id,
        session_id=sid,
        alert_type=alert_type,
        severity=severity,
        suspicion_score=score,
        title=f"Test alert for {sid}",
        description="Test description",
        is_acknowledged=acknowledged,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


# ── GET /api/alerts/ ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_alerts_empty(client):
    resp = await client.get("/api/alerts/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert data["alerts"] == []


@pytest.mark.asyncio
async def test_list_alerts_returns_all(client, db):
    await _create_alert(db)
    await _create_alert(db)
    resp = await client.get("/api/alerts/")
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


@pytest.mark.asyncio
async def test_list_alerts_response_has_session_id(client, db):
    """Bug 1.4: session_id must appear in the alert response."""
    a = await _create_alert(db, session_id="Person_999")
    resp = await client.get("/api/alerts/")
    assert resp.status_code == 200
    alerts = resp.json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["session_id"] == "Person_999"


@pytest.mark.asyncio
async def test_list_alerts_filter_severity(client, db):
    await _create_alert(db, severity="LOW")
    await _create_alert(db, severity="CRITICAL")
    resp = await client.get("/api/alerts/?severity=CRITICAL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["alerts"][0]["severity"] == "CRITICAL"


@pytest.mark.asyncio
async def test_list_alerts_invalid_severity_422(client):
    resp = await client.get("/api/alerts/?severity=ULTRA")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_alerts_unacknowledged_only(client, db):
    await _create_alert(db, acknowledged=False)
    await _create_alert(db, acknowledged=True)
    resp = await client.get("/api/alerts/?unacknowledged_only=true")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert resp.json()["alerts"][0]["is_acknowledged"] is False


# ── GET /api/alerts/stats ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_alert_stats_empty(client):
    resp = await client.get("/api/alerts/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["critical"] == 0


@pytest.mark.asyncio
async def test_alert_stats_counts(client, db):
    await _create_alert(db, severity="CRITICAL")
    await _create_alert(db, severity="CRITICAL")
    await _create_alert(db, severity="HIGH")
    resp = await client.get("/api/alerts/stats")
    data = resp.json()
    assert data["total"] == 3
    assert data["critical"] == 2
    assert data["high"] == 1


# ── GET /api/alerts/top-incidents ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_top_incidents_empty(client):
    resp = await client.get("/api/alerts/top-incidents")
    assert resp.status_code == 200
    assert resp.json()["incidents"] == []


@pytest.mark.asyncio
async def test_top_incidents_ordered_by_score(client, db):
    await _create_alert(db, score=40.0)
    await _create_alert(db, score=90.0)
    await _create_alert(db, score=65.0)
    resp = await client.get("/api/alerts/top-incidents")
    incidents = resp.json()["incidents"]
    assert len(incidents) == 3
    # Should be sorted highest score first
    assert incidents[0]["suspicion_score"] >= incidents[1]["suspicion_score"]
    assert incidents[1]["suspicion_score"] >= incidents[2]["suspicion_score"]


# ── GET /api/alerts/{id} ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_alert_found(client, db):
    a = await _create_alert(db, session_id="Person_042")
    resp = await client.get(f"/api/alerts/{a.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == a.id
    assert resp.json()["session_id"] == "Person_042"


@pytest.mark.asyncio
async def test_get_alert_not_found(client):
    resp = await client.get(f"/api/alerts/{valid_uuid()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_alert_invalid_uuid_422(client):
    resp = await client.get("/api/alerts/not-a-uuid")
    assert resp.status_code == 422


# ── POST /api/alerts/{id}/acknowledge ────────────────────────────────────────

@pytest.mark.asyncio
async def test_acknowledge_alert(client, db):
    a = await _create_alert(db, acknowledged=False)
    resp = await client.post(f"/api/alerts/{a.id}/acknowledge?acknowledged_by=operator1")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_acknowledge_alert_not_found(client):
    resp = await client.post(f"/api/alerts/{valid_uuid()}/acknowledge")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_acknowledge_alert_invalid_uuid_422(client):
    resp = await client.post("/api/alerts/bad-uuid/acknowledge")
    assert resp.status_code == 422
