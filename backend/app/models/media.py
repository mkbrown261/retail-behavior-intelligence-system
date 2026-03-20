from sqlalchemy import Column, String, Float, DateTime, Integer, ForeignKey, JSON, Boolean, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import uuid


def gen_uuid():
    return str(uuid.uuid4())


class Media(Base):
    __tablename__ = "media"

    id = Column(String, primary_key=True, default=gen_uuid)
    person_id = Column(String, ForeignKey("persons.id"), nullable=True, index=True)

    media_type = Column(String, nullable=False)   # SNAPSHOT | CLIP | REPORT
    file_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=True)

    camera_id = Column(Integer, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # For clips
    clip_start = Column(DateTime(timezone=True), nullable=True)
    clip_end = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Float, nullable=True)

    # Context
    trigger_event = Column(String, nullable=True)
    suspicion_score_at_capture = Column(Float, nullable=True)
    is_alert_media = Column(Boolean, default=False)

    extra_data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    person = relationship("Person", back_populates="media")

    def to_dict(self):
        return {
            "id": self.id,
            "person_id": self.person_id,
            "media_type": self.media_type,
            "file_path": self.file_path,
            "camera_id": self.camera_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "trigger_event": self.trigger_event,
            "suspicion_score_at_capture": self.suspicion_score_at_capture,
            "is_alert_media": self.is_alert_media,
        }
