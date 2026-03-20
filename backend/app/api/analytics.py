from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/heatmap")
async def heatmap(
    db: AsyncSession = Depends(get_db),
    day: Optional[str] = None,
    hour: Optional[int] = None,
    interaction_type: Optional[str] = None,
):
    from app.services.heatmap import get_heatmap_data
    return await get_heatmap_data(db, day, hour, interaction_type)


@router.get("/heatmap/hourly")
async def heatmap_hourly(
    db: AsyncSession = Depends(get_db),
    day: Optional[str] = None,
):
    from app.services.heatmap import get_hourly_summary
    return {"summary": await get_hourly_summary(db, day)}


@router.get("/heatmap/hotspots")
async def hotspots(
    db: AsyncSession = Depends(get_db),
    day: Optional[str] = None,
):
    from app.services.heatmap import get_zone_hotspots
    return {"hotspots": await get_zone_hotspots(db, day)}


@router.get("/repeat-visitors")
async def repeat_visitors(db: AsyncSession = Depends(get_db)):
    from app.services.repeat_visitor import get_all_clusters
    clusters = await get_all_clusters(db)
    return {
        "clusters": [
            {
                "cluster_id": c.cluster_id,
                "visit_count": c.visit_count,
                "first_seen": c.first_seen.isoformat() if c.first_seen else None,
                "last_seen": c.last_seen.isoformat() if c.last_seen else None,
                "avg_suspicion_score": c.avg_suspicion_score,
                "max_suspicion_score": c.max_suspicion_score,
                "is_flagged_pattern": c.is_flagged_pattern,
                "dominant_color": c.dominant_color,
                "total_incidents": c.total_incidents,
            }
            for c in clusters
        ]
    }


@router.get("/repeat-visitors/flagged")
async def flagged_repeat_visitors(db: AsyncSession = Depends(get_db)):
    from app.services.repeat_visitor import get_flagged_repeat_visitors
    flagged = await get_flagged_repeat_visitors(db)
    return {
        "flagged_visitors": [
            {
                "cluster_id": c.cluster_id,
                "visit_count": c.visit_count,
                "avg_suspicion_score": c.avg_suspicion_score,
                "max_suspicion_score": c.max_suspicion_score,
                "total_incidents": c.total_incidents,
                "dominant_color": c.dominant_color,
            }
            for c in flagged
        ]
    }


@router.get("/reports")
async def list_reports(db: AsyncSession = Depends(get_db), limit: int = 30):
    from sqlalchemy import select, desc
    from app.models.analytics import DailyReport
    result = await db.execute(
        select(DailyReport).order_by(desc(DailyReport.report_date)).limit(limit)
    )
    reports = result.scalars().all()
    return {"reports": [r.to_dict() for r in reports]}


@router.post("/reports/generate")
async def generate_report(
    db: AsyncSession = Depends(get_db),
    date: Optional[str] = None,
):
    from app.services.report_service import generate_daily_report
    report = await generate_daily_report(db, date)
    return report.to_dict()


@router.get("/reports/{report_date}")
async def get_report(report_date: str, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from app.models.analytics import DailyReport
    from fastapi import HTTPException
    result = await db.execute(
        select(DailyReport).where(DailyReport.report_date == report_date)
    )
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(404, "Report not found")
    return r.to_dict()
