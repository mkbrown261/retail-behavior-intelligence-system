from sqlalchemy import Column, String, Float, DateTime, Integer, ForeignKey, JSON, Text, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import uuid


def gen_uuid():
    return str(uuid.uuid4())


class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=gen_uuid)
    person_id = Column(String, ForeignKey("persons.id"), nullable=False, index=True)

    event_type = Column(String, nullable=False, index=True)
    # ENTER_STORE | EXIT_STORE | PICK_ITEM | HOLD_ITEM | RETURN_ITEM
    # APPROACH_REGISTER | COMPLETE_CHECKOUT | BYPASS_REGISTER

    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    camera_id = Column(Integer, nullable=False)

    # Bounding box [x1,y1,x2,y2]
    bounding_box = Column(JSON, nullable=True)
    confidence = Column(Float, default=0.0)

    # Normalised position in store (0.0–1.0)
    position_x = Column(Float, nullable=True)
    position_y = Column(Float, nullable=True)

    # Associated zone
    zone = Column(String, nullable=True)   # ENTRANCE | AISLE_A | CHECKOUT | EXIT …

    # Duration (for HOLD_ITEM events)
    duration_seconds = Column(Float, nullable=True)

    # Extra metadata
    extra_data = Column(JSON, nullable=True)

    # Snapshot
    snapshot_path = Column(String, nullable=True)
    is_suspicious = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    person = relationship("Person", back_populates="events")

    def to_dict(self):
        return {
            "id": self.id,
            "person_id": self.person_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "camera_id": self.camera_id,
            "bounding_box": self.bounding_box,
            "confidence": self.confidence,
            "position_x": self.position_x,
            "position_y": self.position_y,
            "zone": self.zone,
            "duration_seconds": self.duration_seconds,
            "metadata": self.metadata,
            "snapshot_path": self.snapshot_path,
            "is_suspicious": self.is_suspicious,
        }
