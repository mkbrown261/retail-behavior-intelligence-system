from sqlalchemy import Column, String, Float, DateTime, Integer, ForeignKey, JSON, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import uuid


def gen_uuid():
    return str(uuid.uuid4())


class SuspicionScore(Base):
    __tablename__ = "suspicion_scores"

    id = Column(String, primary_key=True, default=gen_uuid)
    person_id = Column(String, ForeignKey("persons.id"), nullable=False, index=True)

    score = Column(Float, nullable=False)
    delta = Column(Float, default=0.0)          # change that triggered this entry
    reason = Column(String, nullable=True)       # e.g. "PICK_ITEM"
    level = Column(String, nullable=True)        # NORMAL | WATCH | HIGH_SUSPICION

    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    camera_id = Column(Integer, nullable=True)

    # Relationship
    person = relationship("Person", back_populates="suspicion_scores")

    def to_dict(self):
        return {
            "id": self.id,
            "person_id": self.person_id,
            "score": self.score,
            "delta": self.delta,
            "reason": self.reason,
            "level": self.level,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "camera_id": self.camera_id,
        }
