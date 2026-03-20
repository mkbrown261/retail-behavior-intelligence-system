from sqlalchemy import Column, String, Float, DateTime, Integer, ForeignKey, JSON, Boolean, Text
from sqlalchemy.sql import func
from app.core.database import Base
import uuid


def gen_uuid():
    return str(uuid.uuid4())


class HeatmapPoint(Base):
    __tablename__ = "heatmap_points"

    id = Column(String, primary_key=True, default=gen_uuid)
    person_id = Column(String, ForeignKey("persons.id"), nullable=True)
    camera_id = Column(Integer, nullable=False)

    # Grid cell (normalized 0–1 mapped to store grid)
    grid_x = Column(Integer, nullable=False)
    grid_y = Column(Integer, nullable=False)
    norm_x = Column(Float, nullable=False)
    norm_y = Column(Float, nullable=False)

    # Interaction type contribution
    interaction_type = Column(String, nullable=True)  # WALK | INTERACT | SUSPICIOUS
    weight = Column(Float, default=1.0)

    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    hour_bucket = Column(Integer, nullable=True)   # 0–23 for hourly aggregation
    day_bucket = Column(String, nullable=True)     # YYYY-MM-DD


class RepeatVisitor(Base):
    __tablename__ = "repeat_visitors"

    id = Column(String, primary_key=True, default=gen_uuid)
    cluster_id = Column(String, nullable=False, unique=True, index=True)

    visit_count = Column(Integer, default=1)
    first_seen = Column(DateTime(timezone=True), server_default=func.now())
    last_seen = Column(DateTime(timezone=True), server_default=func.now())

    avg_suspicion_score = Column(Float, default=0.0)
    max_suspicion_score = Column(Float, default=0.0)
    is_flagged_pattern = Column(Boolean, default=False)

    # Appearance summary
    dominant_color = Column(String, nullable=True)
    appearance_summary = Column(JSON, nullable=True)

    # Behavior summary
    avg_dwell_minutes = Column(Float, default=0.0)
    total_incidents = Column(Integer, default=0)
    behavior_summary = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String, primary_key=True, default=gen_uuid)
    person_id = Column(String, ForeignKey("persons.id"), nullable=True, index=True)

    alert_type = Column(String, nullable=False)       # SUSPICION_HIGH | BYPASS_REGISTER | etc
    severity = Column(String, nullable=False)         # LOW | MEDIUM | HIGH | CRITICAL
    suspicion_score = Column(Float, nullable=False)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    camera_id = Column(Integer, nullable=True)
    snapshot_path = Column(String, nullable=True)
    clip_path = Column(String, nullable=True)

    is_acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String, nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)

    is_notified = Column(Boolean, default=False)
    notification_channels = Column(JSON, nullable=True)

    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    event_breakdown = Column(JSON, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "person_id": self.person_id,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "suspicion_score": self.suspicion_score,
            "title": self.title,
            "description": self.description,
            "camera_id": self.camera_id,
            "snapshot_path": self.snapshot_path,
            "clip_path": self.clip_path,
            "is_acknowledged": self.is_acknowledged,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "event_breakdown": self.event_breakdown,
        }


class DailyReport(Base):
    __tablename__ = "daily_reports"

    id = Column(String, primary_key=True, default=gen_uuid)
    report_date = Column(String, nullable=False, unique=True, index=True)  # YYYY-MM-DD

    total_visitors = Column(Integer, default=0)
    unique_customers = Column(Integer, default=0)
    staff_count = Column(Integer, default=0)

    total_events = Column(Integer, default=0)
    suspicious_events = Column(Integer, default=0)
    total_alerts = Column(Integer, default=0)
    critical_alerts = Column(Integer, default=0)

    avg_suspicion_score = Column(Float, default=0.0)
    peak_hour = Column(Integer, nullable=True)
    busiest_zone = Column(String, nullable=True)

    top_incidents = Column(JSON, nullable=True)      # list of alert ids
    risk_time_windows = Column(JSON, nullable=True)  # [{hour, risk_score}]
    most_targeted_areas = Column(JSON, nullable=True)

    pdf_path = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "report_date": self.report_date,
            "total_visitors": self.total_visitors,
            "unique_customers": self.unique_customers,
            "total_events": self.total_events,
            "suspicious_events": self.suspicious_events,
            "total_alerts": self.total_alerts,
            "critical_alerts": self.critical_alerts,
            "avg_suspicion_score": self.avg_suspicion_score,
            "peak_hour": self.peak_hour,
            "busiest_zone": self.busiest_zone,
            "pdf_path": self.pdf_path,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
