"""
Alert service — creates, persists and dispatches alerts.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, desc

from app.core.config import settings
from app.models.analytics import Alert
from app.models.person import Person

logger = logging.getLogger(__name__)

# ── Severity mapping ──────────────────────────────────────────────────────────
def _severity(score: float, event_type: str) -> str:
    if score >= 85 or event_type in ("BYPASS_REGISTER", "EXIT_AFTER_PICK"):
        return "CRITICAL"
    elif score >= 70:
        return "HIGH"
    elif score >= 50:
        return "MEDIUM"
    return "LOW"


_SEVERITY_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}


async def create_alert(
    db: AsyncSession,
    person_id: str,
    session_id: str,
    suspicion_score: float,
    trigger_event: str,
    camera_id: Optional[int] = None,
    snapshot_path: Optional[str] = None,
    clip_path: Optional[str] = None,
    event_breakdown: Optional[list] = None,
) -> Alert:
    severity = _severity(suspicion_score, trigger_event)
    title = _build_title(trigger_event, session_id, severity)
    description = _build_description(trigger_event, suspicion_score, session_id)

    alert = Alert(
        person_id=person_id,
        alert_type=trigger_event,
        severity=severity,
        suspicion_score=suspicion_score,
        title=title,
        description=description,
        camera_id=camera_id,
        snapshot_path=snapshot_path,
        clip_path=clip_path,
        event_breakdown=event_breakdown or [],
        is_notified=False,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    logger.warning(f"ALERT [{severity}] {title}")
    return alert


def _build_title(event: str, session_id: str, severity: str) -> str:
    templates = {
        "HIGH_SUSPICION": f"⚠️ High Suspicion — {session_id}",
        "BYPASS_REGISTER": f"🚨 Register Bypass — {session_id}",
        "EXIT_AFTER_PICK": f"🚨 Exit After Item Pickup — {session_id}",
        "RAPID_EXIT": f"⚡ Rapid Exit — {session_id}",
        "MULTI_ITEM": f"📦 Multiple Items Held — {session_id}",
    }
    base = templates.get(event, f"Alert — {session_id} [{event}]")
    if severity == "CRITICAL":
        return f"🔴 CRITICAL: {base}"
    return base


def _build_description(event: str, score: float, session_id: str) -> str:
    return (
        f"{session_id} triggered a '{event}' event with suspicion score {score:.1f}/100. "
        f"Immediate review recommended."
    )


async def get_recent_alerts(
    db: AsyncSession,
    limit: int = 50,
    severity: Optional[str] = None,
    unacknowledged_only: bool = False,
) -> List[Alert]:
    stmt = select(Alert).order_by(desc(Alert.timestamp))
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if unacknowledged_only:
        stmt = stmt.where(Alert.is_acknowledged == False)  # noqa: E712
    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def acknowledge_alert(db: AsyncSession, alert_id: str, acknowledged_by: str = "system") -> bool:
    result = await db.execute(
        update(Alert)
        .where(Alert.id == alert_id)
        .values(
            is_acknowledged=True,
            acknowledged_by=acknowledged_by,
            acknowledged_at=datetime.now(timezone.utc),
        )
        .returning(Alert.id)
    )
    await db.commit()
    return result.rowcount > 0


async def get_alert_stats(db: AsyncSession) -> dict:
    from sqlalchemy import func
    result = await db.execute(
        select(Alert.severity, func.count(Alert.id))
        .group_by(Alert.severity)
    )
    stats = {r[0]: r[1] for r in result.all()}
    total = sum(stats.values())
    return {
        "total": total,
        "by_severity": stats,
        "critical": stats.get("CRITICAL", 0),
        "high": stats.get("HIGH", 0),
        "medium": stats.get("MEDIUM", 0),
        "low": stats.get("LOW", 0),
    }
