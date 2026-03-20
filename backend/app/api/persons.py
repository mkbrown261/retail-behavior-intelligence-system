from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, and_
from typing import Optional, List
from datetime import datetime, timezone

from app.core.database import get_db
from app.models.person import Person
from app.models.event import Event
from app.models.suspicion import SuspicionScore
from app.services.scoring import get_all_live_scores

router = APIRouter(prefix="/persons", tags=["Persons"])


@router.get("/")
async def list_persons(
    db: AsyncSession = Depends(get_db),
    active_only: bool = False,
    person_type: Optional[str] = None,
    flagged_only: bool = False,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
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
    total = await db.execute(select(func.count(Person.id)))
    active = await db.execute(select(func.count(Person.id)).where(Person.is_active == True))  # noqa
    flagged = await db.execute(select(func.count(Person.id)).where(Person.is_flagged == True))  # noqa
    staff = await db.execute(select(func.count(Person.id)).where(Person.person_type == "STAFF"))
    customers = await db.execute(select(func.count(Person.id)).where(Person.person_type == "CUSTOMER"))
    return {
        "total": total.scalar(),
        "active": active.scalar(),
        "flagged": flagged.scalar(),
        "staff": staff.scalar(),
        "customers": customers.scalar(),
    }


@router.get("/{person_id}")
async def get_person(person_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Person).where(Person.id == person_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, f"Person {person_id} not found")
    return p.to_dict()


@router.get("/{person_id}/events")
async def get_person_events(
    person_id: str,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, le=500),
):
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
    person_q = await db.execute(select(Person).where(Person.id == person_id))
    p = person_q.scalar_one_or_none()
    if not p:
        raise HTTPException(404)

    events_q = await db.execute(
        select(Event).where(Event.person_id == person_id).order_by(Event.timestamp)
    )
    scores_q = await db.execute(
        select(SuspicionScore).where(SuspicionScore.person_id == person_id).order_by(SuspicionScore.timestamp)
    )

    events = [e.to_dict() for e in events_q.scalars().all()]
    scores = [s.to_dict() for s in scores_q.scalars().all()]

    # Merge & sort by timestamp
    timeline = []
    for e in events:
        timeline.append({"kind": "EVENT", "data": e, "timestamp": e["timestamp"]})
    for s in scores:
        timeline.append({"kind": "SCORE", "data": s, "timestamp": s["timestamp"]})
    timeline.sort(key=lambda x: x["timestamp"] or "")

    return {
        "person": p.to_dict(),
        "timeline": timeline,
        "event_count": len(events),
        "score_snapshots": len(scores),
    }


@router.get("/{person_id}/score-history")
async def get_score_history(person_id: str, db: AsyncSession = Depends(get_db)):
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
    result = await db.execute(select(Person).where(Person.id == person_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404)
    p.person_type = person_type
    await db.commit()
    return {"ok": True, "person_type": person_type}
