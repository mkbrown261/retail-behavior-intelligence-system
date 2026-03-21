"""
alerts.py — REST endpoints for alert management.

Security notes:
  • alert_id validated as UUID to prevent injection.
  • acknowledged_by is length-limited and stripped of control characters.
  • Query limits enforced via FastAPI Query(le=...).
"""

import re
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import Optional

from app.core.database import get_db
from app.models.analytics import Alert

router = APIRouter(prefix="/alerts", tags=["Alerts"])

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def _validate_uuid(value: str, label: str = "id") -> str:
    if not _UUID_RE.match(value):
        raise HTTPException(status_code=422, detail=f"Invalid {label} format")
    return value


def _sanitize_operator_name(name: str) -> str:
    """Strip non-printable / control characters; limit length."""
    name = re.sub(r'[^\x20-\x7E]', '', name)  # ASCII printable only
    return name[:64]


@router.get("/")
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    severity: Optional[str] = None,
    unacknowledged_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    # Restrict allowed severity values
    if severity and severity not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
        raise HTTPException(status_code=422, detail="severity must be LOW, MEDIUM, HIGH, or CRITICAL")

    from app.services.alert_service import get_recent_alerts
    alerts = await get_recent_alerts(
        db, limit=limit, severity=severity,
        unacknowledged_only=unacknowledged_only,
    )
    return {"alerts": [a.to_dict() for a in alerts], "count": len(alerts)}


@router.get("/stats")
async def alert_stats(db: AsyncSession = Depends(get_db)):
    from app.services.alert_service import get_alert_stats
    return await get_alert_stats(db)


@router.get("/top-incidents")
async def top_incidents(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(10, ge=1, le=50),
):
    result = await db.execute(
        select(Alert)
        .order_by(desc(Alert.suspicion_score))
        .limit(limit)
    )
    alerts = result.scalars().all()
    return {"incidents": [a.to_dict() for a in alerts]}


@router.get("/{alert_id}")
async def get_alert(alert_id: str, db: AsyncSession = Depends(get_db)):
    _validate_uuid(alert_id, "alert_id")
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(404)
    return a.to_dict()


@router.post("/{alert_id}/acknowledge")
async def acknowledge(
    alert_id: str,
    acknowledged_by: str = Query("operator", max_length=64),
    db: AsyncSession = Depends(get_db),
):
    _validate_uuid(alert_id, "alert_id")
    safe_name = _sanitize_operator_name(acknowledged_by)
    from app.services.alert_service import acknowledge_alert
    ok = await acknowledge_alert(db, alert_id, safe_name)
    if not ok:
        raise HTTPException(404)
    return {"ok": True}
