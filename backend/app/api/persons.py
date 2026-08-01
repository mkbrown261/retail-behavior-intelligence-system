"""
persons.py — REST endpoints for person tracking and suspicion scores.

Security notes:
  • All person_id parameters are validated as UUIDs to prevent injection.
  • Query limits are enforced via FastAPI's Query(le=...).
  • No raw SQL — all queries go through SQLAlchemy ORM.
"""

import re
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from typing import Optional
from datetime import datetime, timezone

from app.core.database import get_db
from app.models.person import Person
from app.models.event import Event
from app.models.suspicion import SuspicionScore
from app.models.sensor import SensorEvent
from app.services.scoring import get_all_live_scores

router = APIRouter(prefix="/persons", tags=["Persons"])

# UUID v4 pattern — prevents passing arbitrary strings as person IDs
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def _validate_uuid(value: str, label: str = "id") -> str:
    """Raise 422 if value is not a valid UUID v4."""
    if not _UUID_RE.match(value):
        raise HTTPException(status_code=422, detail=f"Invalid {label} format")
    return value


@router.get("/")
async def list_persons(
    db: AsyncSession = Depends(get_db),
    active_only: bool = False,
    person_type: Optional[str] = None,
    flagged_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    # Restrict allowed person_type values
    if person_type and person_type not in ("STAFF", "CUSTOMER"):
        raise HTTPException(status_code=422, detail="person_type must be STAFF or CUSTOMER")

    stmt = select(Person).order_by(desc(Person.entry_time))
    if active_only:
        stmt = stmt.where(Person.is_active == True)  # noqa: E712
    if person_type:
        stmt = stmt.where(Person.person_type == person_type)
    if flagged_only:
        stmt = stmt.where(Person.is_flagged == True)  # noqa: E712
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    persons = result.scalars().all()
    return {"persons": [p.to_dict() for p in persons], "count": len(persons)}


@router.get("/live-scores")
async def live_scores():
    return {"scores": get_all_live_scores()}


@router.get("/stats")
async def person_stats(db: AsyncSession = Depends(get_db)):
    total     = await db.execute(select(func.count(Person.id)))
    active    = await db.execute(select(func.count(Person.id)).where(Person.is_active == True))    # noqa
    flagged   = await db.execute(select(func.count(Person.id)).where(Person.is_flagged == True))   # noqa
    staff     = await db.execute(select(func.count(Person.id)).where(Person.person_type == "STAFF"))
    customers = await db.execute(select(func.count(Person.id)).where(Person.person_type == "CUSTOMER"))
    return {
        "total":     total.scalar(),
        "active":    active.scalar(),
        "flagged":   flagged.scalar(),
        "staff":     staff.scalar(),
        "customers": customers.scalar(),
    }


@router.get("/{person_id}")
async def get_person(person_id: str, db: AsyncSession = Depends(get_db)):
    _validate_uuid(person_id, "person_id")
    result = await db.execute(select(Person).where(Person.id == person_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, f"Person {person_id} not found")
    return p.to_dict()


@router.get("/{person_id}/events")
async def get_person_events(
    person_id: str,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
):
    _validate_uuid(person_id, "person_id")
    result = await db.execute(
        select(Event)
        .where(Event.person_id == person_id)
        .order_by(Event.timestamp)
        .limit(limit)
    )
    events = result.scalars().all()
    return {"events": [e.to_dict() for e in events], "count": len(events)}


@router.get("/{person_id}/timeline")
async def get_person_timeline(person_id: str, db: AsyncSession = Depends(get_db)):
    """Full reconstructed timeline: events + score changes."""
    _validate_uuid(person_id, "person_id")
    person_q = await db.execute(select(Person).where(Person.id == person_id))
    p = person_q.scalar_one_or_none()
    if not p:
        raise HTTPException(404)

    events_q = await db.execute(
        select(Event).where(Event.person_id == person_id).order_by(Event.timestamp)
    )
    scores_q = await db.execute(
        select(SuspicionScore)
        .where(SuspicionScore.person_id == person_id)
        .order_by(SuspicionScore.timestamp)
    )
    # Sensor Bus events (RFID/smart-shelf item reads, badge scans, etc.) are
    # correlated by session_id, not person_id — merged in here so a reviewer
    # sees "PICK_ITEM" from the camera next to "ITEM_IDENTIFIED: Nike Hoodie"
    # from a shelf sensor in one timeline, without a rigid auto-link between
    # the two (a human draws that connection by proximity in time).
    sensors_q = await db.execute(
        select(SensorEvent).where(SensorEvent.session_id == p.session_id).order_by(SensorEvent.timestamp)
    ) if p.session_id else None

    events = [e.to_dict() for e in events_q.scalars().all()]
    scores = [s.to_dict() for s in scores_q.scalars().all()]
    sensor_events = [s.to_dict() for s in sensors_q.scalars().all()] if sensors_q else []

    timeline = []
    for e in events:
        timeline.append({"kind": "EVENT", "data": e, "timestamp": e["timestamp"]})
    for s in scores:
        timeline.append({"kind": "SCORE", "data": s, "timestamp": s["timestamp"]})
    for se in sensor_events:
        timeline.append({"kind": "SENSOR", "data": se, "timestamp": se["timestamp"]})
    timeline.sort(key=lambda x: x["timestamp"] or "")

    return {
        "person":          p.to_dict(),
        "timeline":        timeline,
        "event_count":     len(events),
        "score_snapshots": len(scores),
        "sensor_events":   len(sensor_events),
    }


@router.get("/{person_id}/confidence")
async def get_person_confidence(person_id: str, db: AsyncSession = Depends(get_db)):
    """
    Multi-factor Incident Confidence breakdown for a currently-tracked person —
    transparent "why" behind the suspicion score (motion/object-interaction/
    concealment/exit-behavior factors + a human recommendation), not just a
    flat number. Returns null fields if the person has already exited (the
    live tally is cleared then; use the alert's stored event_breakdown for
    historical incidents instead).
    """
    from app.services import confidence as confidence_engine
    _validate_uuid(person_id, "person_id")
    breakdown = confidence_engine.get_breakdown(person_id)
    if breakdown is None:
        return {"person_id": person_id, "available": False, "reason": "no live tally (person not tracked or already exited)"}
    return {"available": True, **breakdown}


@router.get("/{person_id}/score-history")
async def get_score_history(person_id: str, db: AsyncSession = Depends(get_db)):
    _validate_uuid(person_id, "person_id")
    result = await db.execute(
        select(SuspicionScore)
        .where(SuspicionScore.person_id == person_id)
        .order_by(SuspicionScore.timestamp)
    )
    scores = result.scalars().all()
    return {"scores": [s.to_dict() for s in scores]}


@router.patch("/{person_id}/type")
async def update_person_type(
    person_id: str,
    person_type: str = Query(..., regex="^(STAFF|CUSTOMER)$"),
    db: AsyncSession = Depends(get_db),
):
    _validate_uuid(person_id, "person_id")
    result = await db.execute(select(Person).where(Person.id == person_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404)
    p.person_type = person_type
    await db.commit()
    return {"ok": True, "person_type": person_type}
