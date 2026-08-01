"""
sensors.py — Universal Sensor Bus ingestion endpoint.

Any external system (POS terminal, RFID gate/shelf reader, door sensor,
smart shelf, BLE beacon, etc.) posts events here through one shared schema
instead of a bespoke integration per device. See app/services/sensor_bus.py
for how events get routed into the existing person/scoring pipeline.
"""
from typing import Optional, Dict
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.models.sensor import SensorEvent
from app.services.sensor_bus import ingest_sensor_event, ROUTABLE_EVENT_TYPES

router = APIRouter(prefix="/sensors", tags=["Sensor Bus"])


class SensorEventRequest(BaseModel):
    sensor_type: str = Field(..., description='e.g. "POS", "RFID_GATE", "SMART_SHELF", "DOOR_SENSOR", "BLE_BEACON", "BADGE_READER"')
    event_type:  str = Field(
        ...,
        description=(
            f"Routes into scoring if one of {sorted(ROUTABLE_EVENT_TYPES)}, or 'STAFF_BADGE_SCAN' "
            "to promote a tracked person to STAFF. 'ITEM_IDENTIFIED' is a recognized informational "
            "type (from an RFID/smart-shelf reader that already resolved the tag to a product — see "
            "payload below) merged into the person's timeline next to the camera's PICK_ITEM, but "
            "does not itself affect scoring. Any other value is just logged."
        ),
    )
    session_id:  Optional[str] = Field(None, description="If known, correlates this event to a tracked person")
    camera_id:   Optional[str] = None
    zone:        Optional[str] = None
    confidence:  float = Field(1.0, ge=0.0, le=1.0)
    payload:     Dict = Field(
        default_factory=dict,
        description=(
            "Raw sensor-specific data. For ITEM_IDENTIFIED, expected shape: "
            '{"tag_id": "E200341203...", "item_name": "Nike Hoodie", "sku": "12345", "price": 39.99}. '
            "RBIS trusts this payload as already-resolved — it does not maintain its own tag/product "
            "catalog. The reader/middleware (or the store's POS/inventory system) is the source of truth "
            "for what a tag ID means."
        ),
    )


@router.post("/event")
async def post_sensor_event(req: SensorEventRequest, db: AsyncSession = Depends(get_db)):
    """
    Ingest one event from any connected sensor. If session_id is given and
    event_type is a routable one, this feeds the same scoring/confidence/
    alert pipeline a camera detection would — otherwise it's persisted as an
    audit-trail record only.
    """
    record = await ingest_sensor_event(
        db,
        sensor_type=req.sensor_type,
        event_type=req.event_type,
        session_id=req.session_id,
        camera_id=req.camera_id,
        zone=req.zone,
        confidence=req.confidence,
        payload=req.payload,
    )
    return record.to_dict()


@router.get("/events")
async def list_sensor_events(
    db: AsyncSession = Depends(get_db),
    sensor_type: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = Query(100, le=500),
):
    """Recent sensor events — audit trail across every connected system."""
    stmt = select(SensorEvent).order_by(desc(SensorEvent.timestamp)).limit(limit)
    if sensor_type:
        stmt = stmt.where(SensorEvent.sensor_type == sensor_type)
    if session_id:
        stmt = stmt.where(SensorEvent.session_id == session_id)
    result = await db.execute(stmt)
    events = result.scalars().all()
    return {"events": [e.to_dict() for e in events], "count": len(events)}
