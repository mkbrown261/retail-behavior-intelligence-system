"""
Heatmap analytics service.
Aggregates positional data into grid cells for store-level heatmaps.
"""
import logging
from datetime import datetime, timezone, date, timedelta
from typing import List, Dict, Optional
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, text

from app.models.analytics import HeatmapPoint

logger = logging.getLogger(__name__)

GRID_W = 50   # columns
GRID_H = 40   # rows


def _to_grid(norm_x: float, norm_y: float):
    gx = min(int(norm_x * GRID_W), GRID_W - 1)
    gy = min(int(norm_y * GRID_H), GRID_H - 1)
    return gx, gy


async def record_position(
    db: AsyncSession,
    person_id: str,
    camera_id: int,
    norm_x: float,
    norm_y: float,
    interaction_type: str = "WALK",
    weight: float = 1.0,
):
    now = datetime.now(timezone.utc)
    gx, gy = _to_grid(norm_x, norm_y)
    point = HeatmapPoint(
        person_id=person_id,
        camera_id=camera_id,
        grid_x=gx,
        grid_y=gy,
        norm_x=norm_x,
        norm_y=norm_y,
        interaction_type=interaction_type,
        weight=weight,
        hour_bucket=now.hour,
        day_bucket=now.strftime("%Y-%m-%d"),
    )
    db.add(point)


async def get_heatmap_data(
    db: AsyncSession,
    day: Optional[str] = None,
    hour: Optional[int] = None,
    interaction_type: Optional[str] = None,
) -> Dict:
    """Return aggregated grid cell weights for the frontend heatmap."""
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    conditions = [HeatmapPoint.day_bucket == day]
    if hour is not None:
        conditions.append(HeatmapPoint.hour_bucket == hour)
    if interaction_type:
        conditions.append(HeatmapPoint.interaction_type == interaction_type)

    stmt = (
        select(
            HeatmapPoint.grid_x,
            HeatmapPoint.grid_y,
            func.sum(HeatmapPoint.weight).label("total_weight"),
            func.count(HeatmapPoint.id).label("count"),
        )
        .where(and_(*conditions))
        .group_by(HeatmapPoint.grid_x, HeatmapPoint.grid_y)
    )
    result = await db.execute(stmt)
    rows = result.all()

    cells = [
        {"x": r.grid_x, "y": r.grid_y, "weight": float(r.total_weight), "count": r.count}
        for r in rows
    ]

    max_w = max((c["weight"] for c in cells), default=1.0)

    return {
        "grid_width": GRID_W,
        "grid_height": GRID_H,
        "day": day,
        "hour": hour,
        "interaction_type": interaction_type,
        "cells": cells,
        "max_weight": max_w,
        "total_points": sum(c["count"] for c in cells),
    }


async def get_hourly_summary(db: AsyncSession, day: Optional[str] = None) -> List[Dict]:
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stmt = (
        select(
            HeatmapPoint.hour_bucket,
            func.count(HeatmapPoint.id).label("count"),
            func.sum(HeatmapPoint.weight).label("weight"),
        )
        .where(HeatmapPoint.day_bucket == day)
        .group_by(HeatmapPoint.hour_bucket)
        .order_by(HeatmapPoint.hour_bucket)
    )
    result = await db.execute(stmt)
    return [{"hour": r.hour_bucket, "count": r.count, "weight": float(r.weight)} for r in result.all()]


async def get_zone_hotspots(db: AsyncSession, day: Optional[str] = None) -> List[Dict]:
    """Return top 10 most active grid cells."""
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stmt = (
        select(
            HeatmapPoint.grid_x,
            HeatmapPoint.grid_y,
            func.sum(HeatmapPoint.weight).label("weight"),
        )
        .where(HeatmapPoint.day_bucket == day)
        .group_by(HeatmapPoint.grid_x, HeatmapPoint.grid_y)
        .order_by(func.sum(HeatmapPoint.weight).desc())
        .limit(10)
    )
    result = await db.execute(stmt)
    return [{"x": r.grid_x, "y": r.grid_y, "weight": float(r.weight)} for r in result.all()]
