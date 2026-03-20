from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import Optional

from app.core.database import get_db
from app.models.event import Event
from app.models.media import Media

router = APIRouter(tags=["Events & Media"])


@router.get("/events")
async def list_events(
    db: AsyncSession = Depends(get_db),
    event_type: Optional[str] = None,
    camera_id: Optional[int] = None,
    suspicious_only: bool = False,
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    stmt = select(Event).order_by(desc(Event.timestamp))
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
    if camera_id is not None:
        stmt = stmt.where(Event.camera_id == camera_id)
    if suspicious_only:
        stmt = stmt.where(Event.is_suspicious == True)  # noqa: E712
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    events = result.scalars().all()
    return {"events": [e.to_dict() for e in events], "count": len(events)}


@router.get("/events/{event_id}")
async def get_event(event_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Event).where(Event.id == event_id))
    e = result.scalar_one_or_none()
    if not e:
        raise HTTPException(404)
    return e.to_dict()


@router.get("/media")
async def list_media(
    db: AsyncSession = Depends(get_db),
    person_id: Optional[str] = None,
    media_type: Optional[str] = None,
    alert_only: bool = False,
    limit: int = Query(50, le=200),
):
    stmt = select(Media).order_by(desc(Media.timestamp)).limit(limit)
    if person_id:
        stmt = stmt.where(Media.person_id == person_id)
    if media_type:
        stmt = stmt.where(Media.media_type == media_type)
    if alert_only:
        stmt = stmt.where(Media.is_alert_media == True)  # noqa: E712
    result = await db.execute(stmt)
    items = result.scalars().all()
    return {"media": [m.to_dict() for m in items]}
