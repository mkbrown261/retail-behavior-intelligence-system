"""
retention.py — data retention enforcement.

This is what makes the privacy stance ("we only track behavioral signals —
height, skin tone, movement — never PII or biometric identity") structural
rather than just a policy statement. Tracking data older than
DATA_RETENTION_DAYS is purged automatically; alerts (the record a business
needs to justify an action already taken) get a longer window,
ALERT_RETENTION_DAYS.

Runs daily via apscheduler (see main.py) and is also available as a manual
trigger through the API for testing/on-demand cleanup.
"""
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.person import Person
from app.models.event import Event
from app.models.suspicion import SuspicionScore
from app.models.analytics import Alert, HeatmapPoint
from app.models.sensor import SensorEvent
from app.models.media import Media

logger = logging.getLogger(__name__)


async def purge_expired_data(db: AsyncSession) -> Dict[str, int]:
    """
    Delete tracking data past its retention window. Returns a dict of
    {table_name: rows_deleted} plus {"snapshot_files": N, "clip_files": N}
    for files removed from disk.
    """
    now = datetime.now(timezone.utc)
    data_cutoff  = now - timedelta(days=settings.DATA_RETENTION_DAYS)
    alert_cutoff = now - timedelta(days=settings.ALERT_RETENTION_DAYS)

    counts: Dict[str, int] = {}

    # ── Alerts — longer retention window ────────────────────────────────────
    result = await db.execute(delete(Alert).where(Alert.timestamp < alert_cutoff))
    counts["alerts"] = result.rowcount or 0

    # ── Media files referencing now/soon-expired data ───────────────────────
    # Alert-linked media gets the longer window; everything else the shorter one.
    media_q = await db.execute(
        select(Media).where(
            ((Media.is_alert_media == True) & (Media.timestamp < alert_cutoff))   # noqa: E712
            | ((Media.is_alert_media != True) & (Media.timestamp < data_cutoff))  # noqa: E712
        )
    )
    expired_media = media_q.scalars().all()
    files_removed = 0
    for m in expired_media:
        if m.file_path:
            full_path = os.path.join(settings.LOCAL_STORAGE_PATH, m.file_path) \
                if not os.path.isabs(m.file_path) else m.file_path
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
                    files_removed += 1
            except OSError as e:
                logger.warning(f"Retention: could not remove media file {full_path}: {e}")
        await db.delete(m)
    counts["media"] = len(expired_media)
    counts["media_files_removed"] = files_removed

    # ── Behavioral tracking data — short retention window ───────────────────
    for model, ts_col, name in [
        (Event,          Event.timestamp,          "events"),
        (SuspicionScore, SuspicionScore.timestamp, "suspicion_scores"),
        (HeatmapPoint,   HeatmapPoint.timestamp,    "heatmap_points"),
        (SensorEvent,    SensorEvent.timestamp,     "sensor_events"),
    ]:
        result = await db.execute(delete(model).where(ts_col < data_cutoff))
        counts[name] = result.rowcount or 0

    # ── Persons — only inactive ones past retention, and only if no
    # surviving (non-expired) alert still references them ───────────────────
    still_referenced = select(Alert.person_id).where(Alert.person_id.isnot(None))
    result = await db.execute(
        delete(Person).where(
            Person.entry_time < data_cutoff,
            Person.is_active == False,                # noqa: E712
            Person.id.notin_(still_referenced),
        )
    )
    counts["persons"] = result.rowcount or 0

    await db.commit()

    total = sum(v for k, v in counts.items() if not k.endswith("_removed"))
    logger.info(f"Retention purge complete: {counts} (total rows: {total})")
    return counts
