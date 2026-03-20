"""
Repeat Visitor Detection (non-identity, appearance-based clustering).
Uses dominant colour + body shape descriptor for approximate matching.
"""
import logging
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.models.person import Person
from app.models.analytics import RepeatVisitor

logger = logging.getLogger(__name__)


def _color_distance(hex1: str, hex2: str) -> float:
    """Simple Euclidean distance in RGB space (0–441)."""
    def _hex_to_rgb(h: str):
        h = h.lstrip("#")
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    try:
        r1, g1, b1 = _hex_to_rgb(hex1)
        r2, g2, b2 = _hex_to_rgb(hex2)
        return ((r1-r2)**2 + (g1-g2)**2 + (b1-b2)**2) ** 0.5
    except Exception:
        return 999.0


COLOR_THRESHOLD = 60.0   # max RGB distance to consider same colour cluster


async def find_or_create_cluster(
    db: AsyncSession,
    dominant_color: str,
    appearance_embedding: Optional[str] = None,
) -> str:
    """Return an existing cluster_id or create a new one."""
    result = await db.execute(select(RepeatVisitor))
    visitors = result.scalars().all()

    for v in visitors:
        if v.dominant_color and _color_distance(dominant_color, v.dominant_color) < COLOR_THRESHOLD:
            return v.cluster_id

    # New cluster
    import uuid
    cluster_id = f"cluster_{uuid.uuid4().hex[:8]}"
    rv = RepeatVisitor(
        cluster_id=cluster_id,
        dominant_color=dominant_color,
        visit_count=1,
        appearance_summary={"colors": [dominant_color]},
    )
    db.add(rv)
    await db.commit()
    logger.info(f"New appearance cluster: {cluster_id}")
    return cluster_id


async def record_visit(
    db: AsyncSession,
    cluster_id: str,
    suspicion_score: float,
    dwell_minutes: float,
    had_incident: bool,
):
    """Update a cluster's visit statistics."""
    result = await db.execute(
        select(RepeatVisitor).where(RepeatVisitor.cluster_id == cluster_id)
    )
    rv = result.scalar_one_or_none()
    if rv is None:
        return

    rv.visit_count += 1
    rv.last_seen = datetime.now(timezone.utc)
    rv.max_suspicion_score = max(rv.max_suspicion_score, suspicion_score)
    # Rolling average
    n = rv.visit_count
    rv.avg_suspicion_score = ((rv.avg_suspicion_score * (n - 1)) + suspicion_score) / n
    rv.avg_dwell_minutes = ((rv.avg_dwell_minutes * (n - 1)) + dwell_minutes) / n
    if had_incident:
        rv.total_incidents += 1

    rv.is_flagged_pattern = (
        rv.visit_count >= 3 and rv.avg_suspicion_score >= 50
    ) or rv.total_incidents >= 2

    await db.commit()


async def get_flagged_repeat_visitors(db: AsyncSession):
    result = await db.execute(
        select(RepeatVisitor)
        .where(RepeatVisitor.is_flagged_pattern == True)  # noqa: E712
        .order_by(RepeatVisitor.max_suspicion_score.desc())
    )
    return result.scalars().all()


async def get_all_clusters(db: AsyncSession):
    result = await db.execute(
        select(RepeatVisitor).order_by(RepeatVisitor.visit_count.desc())
    )
    return result.scalars().all()
