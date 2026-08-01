"""
store_health.py — Store Health Score.

Reframes RBIS from "theft detection tool" to "business intelligence
platform" using data the system already collects — this isn't a new
detection pipeline, it's a different lens on the same events/alerts.

  - Response time: how fast staff acknowledge alerts (Alert.timestamp vs
    Alert.acknowledged_at — both already exist on every alert).
  - Peak risk window: which hour sees the most alerts (same aggregation
    report_service.py already does for daily reports).
  - High risk zones: which named zones produce the most suspicious events
    (Event.zone is already populated on every event).
  - Risk trend: this period's alert volume vs the prior period of equal length.
  - Composite health score: a single 0-100 number combining the above,
    the number a business owner actually wants to see first.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import Alert
from app.models.event import Event
from app.camera.camera_manager import get_zone_labels

logger = logging.getLogger(__name__)

# ── Composite score penalties — tunable, each capped so no single factor
# can single-handedly wipe out the score ────────────────────────────────────
CRITICAL_ALERT_PENALTY_PER  = 4.0   # points off per CRITICAL alert in the period
CRITICAL_ALERT_PENALTY_CAP  = 40.0
SLOW_RESPONSE_THRESHOLD_S   = 60.0  # response times under this cost nothing
SLOW_RESPONSE_PENALTY_PER_S = 1.0 / 30.0  # points off per second over threshold
SLOW_RESPONSE_PENALTY_CAP   = 20.0
RISING_TREND_PENALTY_PER_PCT = 1.0 / 5.0  # points off per % increase in alert volume
RISING_TREND_PENALTY_CAP    = 20.0


async def get_store_health(db: AsyncSession, days: int = 7, camera_id: Optional[str] = None) -> Dict:
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=days)
    prev_period_start = period_start - timedelta(days=days)

    # ── Response time ───────────────────────────────────────────────────────
    resp_stmt = select(Alert.timestamp, Alert.acknowledged_at).where(
        Alert.timestamp >= period_start,
        Alert.is_acknowledged == True,  # noqa: E712
        Alert.acknowledged_at.isnot(None),
    )
    if camera_id:
        resp_stmt = resp_stmt.where(Alert.camera_id == camera_id)
    resp_rows = (await db.execute(resp_stmt)).all()
    response_times = [
        (ack - ts).total_seconds() for ts, ack in resp_rows
        if ack is not None and ts is not None and ack >= ts
    ]
    avg_response_seconds = round(sum(response_times) / len(response_times), 1) if response_times else None

    # ── Peak risk window ─────────────────────────────────────────────────────
    peak_stmt = (
        select(func.strftime("%H", Alert.timestamp), func.count(Alert.id))
        .where(Alert.timestamp >= period_start)
        .group_by(func.strftime("%H", Alert.timestamp))
        .order_by(func.count(Alert.id).desc())
        .limit(1)
    )
    if camera_id:
        peak_stmt = peak_stmt.where(Alert.camera_id == camera_id)
    peak_row = (await db.execute(peak_stmt)).first()
    peak_hour = int(peak_row[0]) if peak_row and peak_row[0] is not None else None

    # ── High risk zones ──────────────────────────────────────────────────────
    zone_stmt = (
        select(Event.zone, func.count(Event.id))
        .where(Event.timestamp >= period_start, Event.is_suspicious == True, Event.zone.isnot(None))  # noqa: E712
        .group_by(Event.zone)
        .order_by(func.count(Event.id).desc())
        .limit(5)
    )
    if camera_id:
        zone_stmt = zone_stmt.where(Event.camera_id == camera_id)
    zone_rows = (await db.execute(zone_stmt)).all()
    labels = get_zone_labels(camera_id) if camera_id else {}
    high_risk_zones = [
        {"zone": z, "label": labels.get(z, z), "suspicious_events": c}
        for z, c in zone_rows
    ]

    # ── Risk trend: this period vs the prior period of equal length ────────
    cur_count_stmt = select(func.count(Alert.id)).where(Alert.timestamp >= period_start)
    prev_count_stmt = select(func.count(Alert.id)).where(
        Alert.timestamp >= prev_period_start, Alert.timestamp < period_start
    )
    if camera_id:
        cur_count_stmt = cur_count_stmt.where(Alert.camera_id == camera_id)
        prev_count_stmt = prev_count_stmt.where(Alert.camera_id == camera_id)
    cur_count = (await db.execute(cur_count_stmt)).scalar() or 0
    prev_count = (await db.execute(prev_count_stmt)).scalar() or 0
    if prev_count > 0:
        risk_trend_pct = round(100 * (cur_count - prev_count) / prev_count, 1)
    else:
        risk_trend_pct = 0.0 if cur_count == 0 else 100.0

    critical_stmt = select(func.count(Alert.id)).where(
        Alert.timestamp >= period_start, Alert.severity == "CRITICAL"
    )
    if camera_id:
        critical_stmt = critical_stmt.where(Alert.camera_id == camera_id)
    critical_count = (await db.execute(critical_stmt)).scalar() or 0

    # ── Composite score ──────────────────────────────────────────────────────
    score = 100.0
    score -= min(CRITICAL_ALERT_PENALTY_CAP, critical_count * CRITICAL_ALERT_PENALTY_PER)
    if avg_response_seconds is not None and avg_response_seconds > SLOW_RESPONSE_THRESHOLD_S:
        overage = avg_response_seconds - SLOW_RESPONSE_THRESHOLD_S
        score -= min(SLOW_RESPONSE_PENALTY_CAP, overage * SLOW_RESPONSE_PENALTY_PER_S)
    if risk_trend_pct > 0:
        score -= min(RISING_TREND_PENALTY_CAP, risk_trend_pct * RISING_TREND_PENALTY_PER_PCT)
    score = max(0.0, min(100.0, round(score, 1)))

    return {
        "period_days": days,
        "health_score": score,
        "risk_trend_pct": risk_trend_pct,
        "critical_alerts": critical_count,
        "total_alerts": cur_count,
        "avg_response_seconds": avg_response_seconds,
        "peak_risk_hour": peak_hour,
        "high_risk_zones": high_risk_zones,
    }
