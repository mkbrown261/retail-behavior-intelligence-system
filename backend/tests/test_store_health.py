"""
test_store_health.py — Store Health Score: response time, peak risk window,
high-risk named zones, risk trend, and the composite score. Reframes
existing alert/event data as business intelligence rather than new
detection logic — all fixtures below use data already collected today.
"""
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from app.models.person import Person
from app.models.event import Event
from app.models.analytics import Alert
from app.services.store_health import get_store_health

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def fake_webcam_stream():
    """
    The test app runs with lifespan=False (see conftest.py) — no real camera
    streams start, so endpoints that check camera_manager.get_stream() would
    404 for a camera that's never actually running. Inject a placeholder
    entry so 'webcam' resolves to something truthy, matching what a real
    running instance would have.
    """
    from app.camera.camera_manager import camera_manager
    camera_manager._streams["webcam"] = object()
    yield
    camera_manager._streams.pop("webcam", None)


def _sid():
    return f"Person_{uuid.uuid4().hex[:6]}"


async def _mk_person(db):
    p = Person(session_id=_sid(), person_type="CUSTOMER", current_suspicion_score=0.0)
    db.add(p)
    await db.flush()
    return p


async def _mk_alert(db, person, ts, severity="HIGH", acknowledged_at=None, camera_id="webcam"):
    a = Alert(
        person_id=person.id, session_id=person.session_id, alert_type="CONCEALMENT",
        severity=severity, suspicion_score=80.0, title="t", timestamp=ts, camera_id=camera_id,
        is_acknowledged=acknowledged_at is not None, acknowledged_at=acknowledged_at,
    )
    db.add(a)
    return a


async def _mk_event(db, person, ts, zone, is_suspicious=True, camera_id="webcam"):
    e = Event(
        person_id=person.id, event_type="CONCEALMENT", camera_id=camera_id,
        zone=zone, is_suspicious=is_suspicious, timestamp=ts,
    )
    db.add(e)
    return e


@pytest.mark.asyncio
async def test_empty_period_returns_perfect_health(db):
    result = await get_store_health(db, days=7)
    assert result["health_score"] == 100.0
    assert result["critical_alerts"] == 0
    assert result["avg_response_seconds"] is None
    assert result["high_risk_zones"] == []


@pytest.mark.asyncio
async def test_response_time_computed_from_real_timestamps(db):
    p = await _mk_person(db)
    await _mk_alert(db, p, NOW - timedelta(hours=1), acknowledged_at=NOW - timedelta(hours=1) + timedelta(seconds=30))
    await _mk_alert(db, p, NOW - timedelta(hours=2), acknowledged_at=NOW - timedelta(hours=2) + timedelta(seconds=90))
    await db.commit()

    result = await get_store_health(db, days=7)
    assert result["avg_response_seconds"] == pytest.approx(60.0, abs=0.1)


@pytest.mark.asyncio
async def test_unacknowledged_alerts_excluded_from_response_time(db):
    p = await _mk_person(db)
    await _mk_alert(db, p, NOW - timedelta(hours=1))  # never acknowledged
    await db.commit()

    result = await get_store_health(db, days=7)
    assert result["avg_response_seconds"] is None


@pytest.mark.asyncio
async def test_high_risk_zones_ranked_by_suspicious_event_count(db):
    p = await _mk_person(db)
    for _ in range(5):
        await _mk_event(db, p, NOW, "AISLE_A")
    for _ in range(2):
        await _mk_event(db, p, NOW, "AISLE_B")
    await _mk_event(db, p, NOW, "CHECKOUT", is_suspicious=False)  # not suspicious, excluded
    await db.commit()

    result = await get_store_health(db, days=7)
    zones = {z["zone"]: z["suspicious_events"] for z in result["high_risk_zones"]}
    assert zones["AISLE_A"] == 5
    assert zones["AISLE_B"] == 2
    assert "CHECKOUT" not in zones
    assert result["high_risk_zones"][0]["zone"] == "AISLE_A"  # ranked highest first


@pytest.mark.asyncio
async def test_high_risk_zones_use_business_labels_when_set(client, db):
    p = await _mk_person(db)
    await _mk_event(db, p, NOW, "AISLE_A")
    await db.commit()

    await client.put("/api/cameras/webcam/zone-labels", json={"labels": {"AISLE_A": "Hair Products"}})

    result = await get_store_health(db, days=7, camera_id="webcam")
    assert result["high_risk_zones"][0]["label"] == "Hair Products"
    assert result["high_risk_zones"][0]["zone"] == "AISLE_A"


@pytest.mark.asyncio
async def test_risk_trend_reflects_period_over_period_change(db):
    p = await _mk_person(db)
    # previous 7-day period: 2 alerts
    await _mk_alert(db, p, NOW - timedelta(days=10))
    await _mk_alert(db, p, NOW - timedelta(days=12))
    # current 7-day period: 4 alerts (100% increase)
    for i in range(4):
        await _mk_alert(db, p, NOW - timedelta(hours=i))
    await db.commit()

    result = await get_store_health(db, days=7)
    assert result["risk_trend_pct"] == pytest.approx(100.0, abs=0.1)
    assert result["total_alerts"] == 4


@pytest.mark.asyncio
async def test_composite_score_penalizes_critical_alerts(db):
    p = await _mk_person(db)
    for i in range(5):
        await _mk_alert(db, p, NOW - timedelta(hours=i), severity="CRITICAL")
    await db.commit()

    result = await get_store_health(db, days=7)
    assert result["health_score"] < 100.0
    assert result["critical_alerts"] == 5


@pytest.mark.asyncio
async def test_composite_score_never_negative(db):
    p = await _mk_person(db)
    for i in range(50):
        await _mk_alert(
            db, p, NOW - timedelta(minutes=i), severity="CRITICAL",
            acknowledged_at=NOW - timedelta(minutes=i) + timedelta(hours=2),
        )
    await db.commit()

    result = await get_store_health(db, days=7)
    assert result["health_score"] >= 0.0


# ── API endpoints ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_store_health_endpoint(client):
    resp = await client.get("/api/analytics/store-health")
    assert resp.status_code == 200
    data = resp.json()
    assert "health_score" in data
    assert "high_risk_zones" in data


@pytest.mark.asyncio
async def test_zone_labels_roundtrip(client):
    resp = await client.put("/api/cameras/webcam/zone-labels", json={"labels": {"AISLE_B": "Electronics"}})
    assert resp.status_code == 200

    resp = await client.get("/api/cameras/webcam/zone-labels")
    assert resp.status_code == 200
    assert resp.json()["labels"]["AISLE_B"] == "Electronics"


@pytest.mark.asyncio
async def test_zone_labels_rejects_unknown_zone_code(client):
    resp = await client.put("/api/cameras/webcam/zone-labels", json={"labels": {"NOT_A_REAL_ZONE": "x"}})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_zone_labels_404_for_unknown_camera(client):
    resp = await client.get("/api/cameras/nonexistent_camera_xyz/zone-labels")
    assert resp.status_code == 404
