"""
admin.py — data retention policy visibility + manual purge trigger.

NOTE: not access-controlled yet. RBAC (User/role model, JWT auth) exists in
app/models/user.py and app/api/auth.py but isn't enforced on any endpoint
except user management itself — see app/api/auth.py's require_role(). Once
that's wired up, /purge-now should require at least MANAGER.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.services.retention import purge_expired_data

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/retention-policy")
async def get_retention_policy():
    """
    Current data retention configuration — structural enforcement of the
    "behavioral signals only, no PII" privacy stance. Tracking data
    (events, scores, heatmap points, sensor events) is purged after
    DATA_RETENTION_DAYS; alerts are kept longer since they're the record a
    business needs to justify an action already taken.
    """
    return {
        "data_retention_days":  settings.DATA_RETENTION_DAYS,
        "alert_retention_days": settings.ALERT_RETENTION_DAYS,
        "purge_schedule_utc":   f"{settings.RETENTION_PURGE_HOUR:02d}:{settings.RETENTION_PURGE_MINUTE:02d}",
        "purged_data_types": [
            "events", "suspicion_scores", "heatmap_points",
            "sensor_events", "inactive_persons_with_no_active_alert",
        ],
    }


@router.post("/purge-now")
async def purge_now(db: AsyncSession = Depends(get_db)):
    """Manually trigger the retention purge immediately (also runs daily on schedule)."""
    counts = await purge_expired_data(db)
    return {"purged": True, "counts": counts}
