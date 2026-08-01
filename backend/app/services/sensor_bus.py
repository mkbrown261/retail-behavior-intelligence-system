"""
sensor_bus.py — Universal Sensor Bus routing.

Any non-camera sensor (POS terminal, RFID gate/shelf reader, door sensor,
smart shelf, BLE beacon, etc.) speaks through the SAME event_type vocabulary
the camera pipeline already uses (see ai_inference.py's emitted events).
If a sensor knows which tracked person it corresponds to (session_id), the
event is routed through the exact same handle_detection() pipeline a camera
detection would use — same scoring, same confidence engine, same alerts.

If no session_id is given, or the event_type isn't one we know how to score,
it's still persisted as an audit-trail SensorEvent row, just with no effect
on any person's score. This is intentionally conservative: better to log an
unroutable event than guess at a wrong correlation.
"""
import logging
from typing import Optional, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sensor import SensorEvent

logger = logging.getLogger(__name__)

# Event types a sensor can directly assert into the existing internal
# vocabulary. Anything else is logged as an audit record only until a
# specific correlation rule is written for it.
ROUTABLE_EVENT_TYPES = {
    "COMPLETE_CHECKOUT", "PICK_ITEM", "RETURN_ITEM",
    "BYPASS_REGISTER", "ENTER_STORE", "EXIT_STORE",
}


async def ingest_sensor_event(
    db: AsyncSession,
    sensor_type: str,
    event_type: str,
    session_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    zone: Optional[str] = None,
    confidence: float = 1.0,
    payload: Optional[Dict] = None,
) -> SensorEvent:
    correlated = "logged_only"

    if session_id and event_type == "STAFF_BADGE_SCAN":
        # Authoritative staff confirmation — a badge scan overrides the soft
        # uniform-color guess. Only ever promotes toward STAFF, never away
        # from it (same one-directional rule as the color heuristic).
        try:
            from sqlalchemy import select
            from app.models.person import Person
            result = await db.execute(select(Person).where(Person.session_id == session_id))
            p = result.scalar_one_or_none()
            if p:
                p.person_type = "STAFF"
                correlated = "routed"
            else:
                correlated = "logged_only"  # no tracked person with this session_id yet
        except Exception as e:
            logger.error(f"Staff badge scan failed [{sensor_type}]: {e}", exc_info=True)
            correlated = f"error:{e}"

    elif session_id and event_type in ROUTABLE_EVENT_TYPES:
        try:
            from app.services.event_orchestrator import handle_detection
            await handle_detection({
                "session_id": session_id,
                "event_type": event_type,
                "camera_id": camera_id or "sensor",
                "zone": zone or "UNKNOWN",
                "confidence": confidence,
            })
            correlated = "routed"
        except Exception as e:
            logger.error(f"Sensor event routing failed [{sensor_type}/{event_type}]: {e}", exc_info=True)
            correlated = f"error:{e}"

    record = SensorEvent(
        sensor_type=sensor_type,
        event_type=event_type,
        session_id=session_id,
        correlated=correlated,
        camera_id=camera_id,
        zone=zone,
        confidence=confidence,
        payload=payload or {},
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    logger.info(f"Sensor event [{sensor_type}/{event_type}] session={session_id} -> {correlated}")
    return record
