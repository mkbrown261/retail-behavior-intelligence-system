"""
test_retention.py — data retention purge (structural enforcement of the
"behavioral signals only, no PII" privacy stance).
"""
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from app.core.config import settings
from app.models.person import Person
from app.models.event import Event
from app.models.suspicion import SuspicionScore
from app.models.analytics import Alert, HeatmapPoint
from app.models.sensor import SensorEvent
from app.services.retention import purge_expired_data

OLD = datetime.now(timezone.utc) - timedelta(days=settings.DATA_RETENTION_DAYS + 5)
RECENT = datetime.now(timezone.utc) - timedelta(days=1)
OLD_BUT_WITHIN_ALERT_WINDOW = datetime.now(timezone.utc) - timedelta(days=settings.DATA_RETENTION_DAYS + 5)


def _sid():
    return f"Person_{uuid.uuid4().hex[:6]}"


async def _mk_person(db, entry_time, is_active=False):
    p = Person(session_id=_sid(), person_type="CUSTOMER", entry_time=entry_time, is_active=is_active)
    db.add(p)
    await db.flush()
    return p


@pytest.mark.asyncio
async def test_old_events_are_purged(db):
    p = await _mk_person(db, OLD)
    old_event = Event(person_id=p.id, event_type="PICK_ITEM", camera_id="webcam", timestamp=OLD)
    recent_event = Event(person_id=p.id, event_type="PICK_ITEM", camera_id="webcam", timestamp=RECENT)
    db.add_all([old_event, recent_event])
    await db.commit()

    counts = await purge_expired_data(db)
    assert counts["events"] == 1

    from sqlalchemy import select
    remaining = (await db.execute(select(Event))).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].timestamp.replace(tzinfo=timezone.utc) > OLD.replace(tzinfo=timezone.utc) + timedelta(days=1)


@pytest.mark.asyncio
async def test_old_suspicion_scores_and_heatmap_and_sensor_events_purged(db):
    p = await _mk_person(db, OLD)
    db.add(SuspicionScore(person_id=p.id, score=50.0, delta=10.0, reason="PICK_ITEM", level="WATCH", timestamp=OLD))
    db.add(HeatmapPoint(person_id=p.id, camera_id="webcam", grid_x=1, grid_y=1, norm_x=0.5, norm_y=0.5, timestamp=OLD))
    db.add(SensorEvent(sensor_type="RFID_GATE", event_type="TAG_READ", correlated="logged_only", timestamp=OLD))
    await db.commit()

    counts = await purge_expired_data(db)
    assert counts["suspicion_scores"] == 1
    assert counts["heatmap_points"] == 1
    assert counts["sensor_events"] == 1


@pytest.mark.asyncio
async def test_inactive_old_person_with_no_alert_is_purged(db):
    p = await _mk_person(db, OLD, is_active=False)
    await db.commit()

    counts = await purge_expired_data(db)
    assert counts["persons"] == 1


@pytest.mark.asyncio
async def test_active_person_is_never_purged_even_if_old(db):
    p = await _mk_person(db, OLD, is_active=True)
    await db.commit()

    counts = await purge_expired_data(db)
    assert counts["persons"] == 0

    from sqlalchemy import select
    remaining = (await db.execute(select(Person).where(Person.id == p.id))).scalar_one_or_none()
    assert remaining is not None


@pytest.mark.asyncio
async def test_person_with_surviving_alert_is_not_purged(db):
    """A person referenced by a still-valid (not-yet-expired) alert survives
    even past the data retention window — the alert needs a valid person link."""
    p = await _mk_person(db, OLD, is_active=False)
    db.add(Alert(
        person_id=p.id, session_id=p.session_id, alert_type="CONCEALMENT",
        severity="HIGH", suspicion_score=80.0, title="test alert",
        timestamp=datetime.now(timezone.utc) - timedelta(days=1),  # recent alert
    ))
    await db.commit()

    counts = await purge_expired_data(db)
    assert counts["persons"] == 0


@pytest.mark.asyncio
async def test_alert_retention_is_longer_than_data_retention(db):
    p = await _mk_person(db, OLD)
    # Alert older than DATA_RETENTION_DAYS but within ALERT_RETENTION_DAYS should survive
    within_alert_window = datetime.now(timezone.utc) - timedelta(days=settings.DATA_RETENTION_DAYS + 5)
    assert settings.ALERT_RETENTION_DAYS > settings.DATA_RETENTION_DAYS + 5  # sanity check on test fixture

    db.add(Alert(
        person_id=p.id, session_id=p.session_id, alert_type="CONCEALMENT",
        severity="HIGH", suspicion_score=80.0, title="still valid",
        timestamp=within_alert_window,
    ))
    truly_old_alert = datetime.now(timezone.utc) - timedelta(days=settings.ALERT_RETENTION_DAYS + 5)
    db.add(Alert(
        person_id=p.id, session_id=p.session_id, alert_type="CONCEALMENT",
        severity="HIGH", suspicion_score=80.0, title="expired",
        timestamp=truly_old_alert,
    ))
    await db.commit()

    counts = await purge_expired_data(db)
    assert counts["alerts"] == 1  # only the truly-old one

    from sqlalchemy import select
    remaining = (await db.execute(select(Alert))).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].title == "still valid"


# ── API endpoints ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retention_policy_endpoint(client):
    resp = await client.get("/api/admin/retention-policy")
    assert resp.status_code == 200
    data = resp.json()
    assert data["data_retention_days"] == settings.DATA_RETENTION_DAYS
    assert data["alert_retention_days"] == settings.ALERT_RETENTION_DAYS


@pytest.mark.asyncio
async def test_purge_now_endpoint(client, db):
    p = await _mk_person(db, OLD)
    db.add(Event(person_id=p.id, event_type="PICK_ITEM", camera_id="webcam", timestamp=OLD))
    await db.commit()

    resp = await client.post("/api/admin/purge-now")
    assert resp.status_code == 200
    data = resp.json()
    assert data["purged"] is True
    assert data["counts"]["events"] == 1
