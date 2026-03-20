from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, and_
from typing import Optional
from datetime import datetime, timezone

from app.core.database import get_db
from app.models.analytics import Alert

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("/")
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    severity: Optional[str] = None,
    unacknowledged_only: bool = False,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    from app.services.alert_service import get_recent_alerts
    alerts = await get_recent_alerts(db, limit=limit, severity=severity, unacknowledged_only=unacknowledged_only)
    return {"alerts": [a.to_dict() for a in alerts], "count": len(alerts)}


@router.get("/stats")
async def alert_stats(db: AsyncSession = Depends(get_db)):
    from app.services.alert_service import get_alert_stats
    return await get_alert_stats(db)


@router.get("/top-incidents")
async def top_incidents(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(10, le=50),
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
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(404)
    return a.to_dict()


@router.post("/{alert_id}/acknowledge")
async def acknowledge(
    alert_id: str,
    acknowledged_by: str = Query("operator"),
    db: AsyncSession = Depends(get_db),
):
    from app.services.alert_service import acknowledge_alert
    ok = await acknowledge_alert(db, alert_id, acknowledged_by)
    if not ok:
        raise HTTPException(404)
    return {"ok": True}
