"""
sensor.py — generic Sensor Bus event log.

Every non-camera sensor (POS, RFID gate/shelf, door sensor, smart shelf,
BLE beacon, etc.) speaks through the same schema instead of a bespoke
integration per device. See app/api/sensors.py for the ingestion endpoint
and app/services/sensor_bus.py for how events get routed.
"""
from sqlalchemy import Column, String, Float, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base
import uuid


def gen_uuid():
    return str(uuid.uuid4())


class SensorEvent(Base):
    __tablename__ = "sensor_events"

    id = Column(String, primary_key=True, default=gen_uuid)

    sensor_type = Column(String, nullable=False, index=True)   # POS | RFID_GATE | DOOR_SENSOR | SMART_SHELF | ...
    event_type  = Column(String, nullable=False, index=True)   # e.g. COMPLETE_CHECKOUT, DOOR_OPEN, TAG_READ

    # Correlation — if session_id is known, the event is routed into the
    # existing person/scoring pipeline (see sensor_bus.py). Otherwise this
    # row is just an audit-trail record with no effect on any person's score.
    session_id  = Column(String, nullable=True, index=True)
    correlated  = Column(String, nullable=True)   # "routed" | "logged_only" | "error:<msg>"

    camera_id   = Column(String, nullable=True)
    zone        = Column(String, nullable=True)
    confidence  = Column(Float, default=1.0)
    payload     = Column(JSON, nullable=True)   # raw sensor-specific metadata

    timestamp   = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "sensor_type": self.sensor_type,
            "event_type": self.event_type,
            "session_id": self.session_id,
            "correlated": self.correlated,
            "camera_id": self.camera_id,
            "zone": self.zone,
            "confidence": self.confidence,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
