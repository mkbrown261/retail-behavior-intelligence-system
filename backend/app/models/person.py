from sqlalchemy import Column, String, Float, Boolean, DateTime, Integer, Text, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import uuid


def gen_uuid():
    return str(uuid.uuid4())


class Person(Base):
    __tablename__ = "persons"

    id = Column(String, primary_key=True, default=gen_uuid)
    session_id = Column(String, unique=True, nullable=False, index=True)  # Person_001
    entry_time = Column(DateTime(timezone=True), server_default=func.now())
    exit_time = Column(DateTime(timezone=True), nullable=True)

    # Appearance features (non-facial)
    dominant_color = Column(String, nullable=True)       # clothing dominant color hex
    color_histogram = Column(Text, nullable=True)        # JSON blob of color histogram
    appearance_embedding = Column(Text, nullable=True)   # JSON blob of appearance vector
    body_shape_descriptor = Column(String, nullable=True)

    # Classification
    person_type = Column(String, default="CUSTOMER")     # CUSTOMER | STAFF
    is_active = Column(Boolean, default=True)

    # Scoring
    current_suspicion_score = Column(Float, default=0.0)
    max_suspicion_score = Column(Float, default=0.0)
    suspicion_level = Column(String, default="NORMAL")   # NORMAL | WATCH | HIGH_SUSPICION

    # Repeat visitor
    appearance_cluster_id = Column(String, nullable=True, index=True)
    visit_count = Column(Integer, default=1)

    # Camera tracking
    first_camera_id = Column(Integer, nullable=True)
    last_camera_id = Column(Integer, nullable=True)
    cameras_seen = Column(JSON, default=list)

    # Position
    last_x = Column(Float, nullable=True)
    last_y = Column(Float, nullable=True)
    last_bbox = Column(JSON, nullable=True)

    # Metadata
    is_flagged = Column(Boolean, default=False)
    flag_reason = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    events = relationship("Event", back_populates="person", lazy="dynamic")
    suspicion_scores = relationship("SuspicionScore", back_populates="person", lazy="dynamic")
    media = relationship("Media", back_populates="person", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "person_type": self.person_type,
            "is_active": self.is_active,
            "current_suspicion_score": self.current_suspicion_score,
            "max_suspicion_score": self.max_suspicion_score,
            "suspicion_level": self.suspicion_level,
            "is_flagged": self.is_flagged,
            "dominant_color": self.dominant_color,
            "last_camera_id": self.last_camera_id,
            "cameras_seen": self.cameras_seen,
            "last_bbox": self.last_bbox,
            "visit_count": self.visit_count,
        }
