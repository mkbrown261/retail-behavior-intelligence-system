"""
test_report_generation.py — daily PDF/JSON report generator.

Covers: aggregation correctness (visitors/staff/events/alerts), the new
event_type_breakdown and sensor_events_count fields, top-incident confidence
enrichment, PDF file creation, and the /api/analytics/reports* endpoints.
"""
import os
import uuid
from datetime import datetime, timezone

import pytest

from app.models.person import Person
from app.models.event import Event
from app.models.analytics import Alert
from app.services.report_service import generate_daily_report

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _sid():
    return f"Person_{uuid.uuid4().hex[:6]}"


async def _mk_person(db, person_type="CUSTOMER"):
    p = Person(session_id=_sid(), person_type=person_type, current_suspicion_score=0.0)
    db.add(p)
    await db.flush()
    return p


async def _mk_event(db, person, event_type, is_suspicious=False):
    e = Event(person_id=person.id, event_type=event_type, camera_id="webcam", is_suspicious=is_suspicious)
    db.add(e)
    return e


async def _mk_alert(db, person, score, severity="HIGH", breakdown=None):
    a = Alert(
        person_id=person.id, session_id=person.session_id,
        alert_type="CONCEALMENT", severity=severity, suspicion_score=score,
        title=f"Alert for {person.session_id}", event_breakdown=breakdown,
    )
    db.add(a)
    return a


@pytest.mark.asyncio
async def test_empty_day_does_not_crash(db):
    report = await generate_daily_report(db, report_date="2020-01-01")
    assert report.total_visitors == 0
    assert report.total_alerts == 0
    assert report.avg_suspicion_score == 0.0
    assert report.event_type_breakdown == {}
    assert report.sensor_events_count == 0


@pytest.mark.asyncio
async def test_aggregation_counts_are_correct(db):
    customer = await _mk_person(db, "CUSTOMER")
    staff = await _mk_person(db, "STAFF")
    await _mk_event(db, customer, "PICK_ITEM")
    await _mk_event(db, customer, "PICK_ITEM")
    await _mk_event(db, customer, "CONCEALMENT", is_suspicious=True)
    await _mk_alert(db, customer, 92.0, severity="CRITICAL")
    await db.commit()

    report = await generate_daily_report(db, report_date=TODAY)

    assert report.total_visitors == 2
    assert report.staff_count == 1
    assert report.unique_customers == 1
    assert report.total_events == 3
    assert report.suspicious_events == 1
    assert report.total_alerts == 1
    assert report.critical_alerts == 1
    assert report.event_type_breakdown == {"PICK_ITEM": 2, "CONCEALMENT": 1}


@pytest.mark.asyncio
async def test_sensor_events_counted(client, db):
    await client.post("/api/sensors/event", json={"sensor_type": "RFID_GATE", "event_type": "TAG_READ"})
    await client.post("/api/sensors/event", json={"sensor_type": "POS", "event_type": "COMPLETE_CHECKOUT"})

    report = await generate_daily_report(db, report_date=TODAY)
    assert report.sensor_events_count == 2


@pytest.mark.asyncio
async def test_top_incident_includes_confidence_recommendation(db):
    person = await _mk_person(db, "CUSTOMER")
    await _mk_alert(db, person, 88.0, severity="CRITICAL", breakdown={
        "overall_confidence": 82.0,
        "recommendation": "Escalate — High Confidence",
    })
    await db.commit()

    report = await generate_daily_report(db, report_date=TODAY)
    assert len(report.top_incidents) == 1
    assert report.top_incidents[0]["confidence"] == 82.0
    assert report.top_incidents[0]["recommendation"] == "Escalate — High Confidence"


@pytest.mark.asyncio
async def test_pdf_file_is_created(db):
    person = await _mk_person(db, "CUSTOMER")
    await _mk_alert(db, person, 75.0)
    await db.commit()

    report = await generate_daily_report(db, report_date=TODAY)
    assert report.pdf_path is not None
    assert os.path.exists(report.pdf_path)
    assert os.path.getsize(report.pdf_path) > 0


@pytest.mark.asyncio
async def test_regenerating_same_date_updates_not_duplicates(db):
    person = await _mk_person(db, "CUSTOMER")
    await db.commit()

    r1 = await generate_daily_report(db, report_date=TODAY)
    await _mk_alert(db, person, 60.0)
    await db.commit()
    r2 = await generate_daily_report(db, report_date=TODAY)

    assert r1.id == r2.id  # same row updated, not a duplicate
    assert r2.total_alerts == 1


# ── API endpoints ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_report_endpoint(client, db):
    person = await _mk_person(db, "CUSTOMER")
    await _mk_alert(db, person, 70.0)
    await db.commit()

    resp = await client.post("/api/analytics/reports/generate", params={"date": TODAY})
    assert resp.status_code == 200
    data = resp.json()
    assert data["report_date"] == TODAY
    assert data["total_visitors"] == 1
    assert "top_incidents" in data
    assert "event_type_breakdown" in data


@pytest.mark.asyncio
async def test_get_report_by_date_after_generation(client, db):
    await generate_daily_report(db, report_date=TODAY)
    resp = await client.get(f"/api/analytics/reports/{TODAY}")
    assert resp.status_code == 200
    assert resp.json()["report_date"] == TODAY


@pytest.mark.asyncio
async def test_list_reports_includes_generated(client, db):
    await generate_daily_report(db, report_date=TODAY)
    resp = await client.get("/api/analytics/reports")
    assert resp.status_code == 200
    dates = [r["report_date"] for r in resp.json()["reports"]]
    assert TODAY in dates
