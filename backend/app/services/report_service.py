"""
Daily Intelligence Report generator.
Creates PDF + JSON summaries for store operators.
"""
import logging
import os
from datetime import datetime, timezone, date, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.core.config import settings
from app.models.analytics import DailyReport, Alert
from app.models.person import Person
from app.models.event import Event

logger = logging.getLogger(__name__)


async def generate_daily_report(
    db: AsyncSession,
    report_date: Optional[str] = None,
) -> DailyReport:
    target = report_date or (datetime.now(timezone.utc) - timedelta(days=0)).strftime("%Y-%m-%d")
    day_start = datetime.fromisoformat(f"{target}T00:00:00+00:00")
    day_end = datetime.fromisoformat(f"{target}T23:59:59+00:00")

    # ── Person stats ─────────────────────────────────────────────────────────
    persons_q = await db.execute(
        select(func.count(Person.id))
        .where(Person.entry_time.between(day_start, day_end))
    )
    total_visitors = persons_q.scalar() or 0

    staff_q = await db.execute(
        select(func.count(Person.id))
        .where(and_(Person.entry_time.between(day_start, day_end), Person.person_type == "STAFF"))
    )
    staff_count = staff_q.scalar() or 0

    # ── Event stats ───────────────────────────────────────────────────────────
    events_q = await db.execute(
        select(func.count(Event.id)).where(Event.timestamp.between(day_start, day_end))
    )
    total_events = events_q.scalar() or 0

    suspicious_events_q = await db.execute(
        select(func.count(Event.id))
        .where(and_(Event.timestamp.between(day_start, day_end), Event.is_suspicious == True))  # noqa: E712
    )
    suspicious_events = suspicious_events_q.scalar() or 0

    # ── Alert stats ───────────────────────────────────────────────────────────
    alerts_q = await db.execute(
        select(func.count(Alert.id)).where(Alert.timestamp.between(day_start, day_end))
    )
    total_alerts = alerts_q.scalar() or 0

    critical_q = await db.execute(
        select(func.count(Alert.id))
        .where(and_(Alert.timestamp.between(day_start, day_end), Alert.severity == "CRITICAL"))
    )
    critical_alerts = critical_q.scalar() or 0

    # ── Top 10 incidents ──────────────────────────────────────────────────────
    top_alerts_q = await db.execute(
        select(Alert.id, Alert.severity, Alert.suspicion_score, Alert.title, Alert.person_id)
        .where(Alert.timestamp.between(day_start, day_end))
        .order_by(Alert.suspicion_score.desc())
        .limit(10)
    )
    top_incidents = [
        {"id": r[0], "severity": r[1], "score": r[2], "title": r[3], "person_id": r[4]}
        for r in top_alerts_q.all()
    ]

    # ── Peak hour ─────────────────────────────────────────────────────────────
    from app.models.analytics import HeatmapPoint
    peak_q = await db.execute(
        select(HeatmapPoint.hour_bucket, func.count(HeatmapPoint.id).label("cnt"))
        .where(HeatmapPoint.day_bucket == target)
        .group_by(HeatmapPoint.hour_bucket)
        .order_by(func.count(HeatmapPoint.id).desc())
        .limit(1)
    )
    peak_row = peak_q.first()
    peak_hour = peak_row[0] if peak_row else None

    # ── Average suspicion ─────────────────────────────────────────────────────
    avg_score_q = await db.execute(
        select(func.avg(Person.current_suspicion_score))
        .where(Person.entry_time.between(day_start, day_end))
    )
    avg_score = float(avg_score_q.scalar() or 0.0)

    # ── Risk time windows ─────────────────────────────────────────────────────
    hourly_alerts_q = await db.execute(
        select(
            func.strftime("%H", Alert.timestamp).label("hr"),
            func.count(Alert.id).label("cnt"),
        )
        .where(Alert.timestamp.between(day_start, day_end))
        .group_by(func.strftime("%H", Alert.timestamp))
        .order_by(func.count(Alert.id).desc())
        .limit(5)
    )
    risk_windows = [{"hour": int(r[0]), "alert_count": r[1]} for r in hourly_alerts_q.all()]

    # ── Build or update report ────────────────────────────────────────────────
    existing_q = await db.execute(
        select(DailyReport).where(DailyReport.report_date == target)
    )
    report = existing_q.scalar_one_or_none()

    data = dict(
        total_visitors=total_visitors,
        unique_customers=max(0, total_visitors - staff_count),
        staff_count=staff_count,
        total_events=total_events,
        suspicious_events=suspicious_events,
        total_alerts=total_alerts,
        critical_alerts=critical_alerts,
        avg_suspicion_score=avg_score,
        peak_hour=peak_hour,
        top_incidents=top_incidents,
        risk_time_windows=risk_windows,
    )

    if report:
        for k, v in data.items():
            setattr(report, k, v)
    else:
        report = DailyReport(report_date=target, **data)
        db.add(report)

    await db.commit()
    await db.refresh(report)

    # Generate PDF
    pdf_path = await _generate_pdf(report, top_incidents, risk_windows)
    if pdf_path:
        report.pdf_path = pdf_path
        await db.commit()

    logger.info(f"Daily report generated for {target}: {total_visitors} visitors, {total_alerts} alerts")
    return report


async def _generate_pdf(report: DailyReport, top_incidents: list, risk_windows: list) -> Optional[str]:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        )

        reports_dir = os.path.join(settings.LOCAL_STORAGE_PATH, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        pdf_path = os.path.join(reports_dir, f"report_{report.report_date}.pdf")

        doc = SimpleDocTemplate(pdf_path, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        # ── Title ──────────────────────────────────────────────────────────
        title_style = ParagraphStyle(
            "Title2", parent=styles["Title"],
            fontSize=22, textColor=colors.HexColor("#1a237e"), spaceAfter=6
        )
        story.append(Paragraph("Retail Behavior Intelligence System", title_style))
        story.append(Paragraph(f"Daily Intelligence Report — {report.report_date}", styles["Heading2"]))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#3f51b5")))
        story.append(Spacer(1, 0.4 * cm))

        # ── Summary KPIs ──────────────────────────────────────────────────
        story.append(Paragraph("Executive Summary", styles["Heading2"]))
        kpi_data = [
            ["Metric", "Value"],
            ["Total Visitors", str(report.total_visitors)],
            ["Unique Customers", str(report.unique_customers)],
            ["Staff Members", str(report.staff_count)],
            ["Total Events Detected", str(report.total_events)],
            ["Suspicious Events", str(report.suspicious_events)],
            ["Total Alerts", str(report.total_alerts)],
            ["Critical Alerts", str(report.critical_alerts)],
            ["Avg Suspicion Score", f"{report.avg_suspicion_score:.1f}/100"],
            ["Peak Activity Hour", f"{report.peak_hour:02d}:00" if report.peak_hour is not None else "N/A"],
        ]
        t = Table(kpi_data, colWidths=[9 * cm, 6 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3f51b5")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f5f5f5"), colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ALIGN", (1, 0), (1, -1), "CENTER"),
            ("FONTSIZE", (0, 0), (-1, -1), 11),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.6 * cm))

        # ── Top Incidents ─────────────────────────────────────────────────
        story.append(Paragraph("Top 10 Highest Suspicion Incidents", styles["Heading2"]))
        if top_incidents:
            inc_data = [["#", "Person ID", "Severity", "Score", "Title"]]
            for i, inc in enumerate(top_incidents[:10], 1):
                inc_data.append([
                    str(i),
                    str(inc.get("person_id", ""))[:12],
                    inc.get("severity", ""),
                    f"{inc.get('score', 0):.1f}",
                    str(inc.get("title", ""))[:55],
                ])
            inc_table = Table(inc_data, colWidths=[1 * cm, 3 * cm, 2.5 * cm, 2 * cm, 7.5 * cm])
            sev_colors = {"CRITICAL": colors.HexColor("#b71c1c"), "HIGH": colors.HexColor("#e53935"),
                          "MEDIUM": colors.HexColor("#fb8c00"), "LOW": colors.HexColor("#43a047")}
            inc_style = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37474f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
            inc_table.setStyle(TableStyle(inc_style))
            story.append(inc_table)
        else:
            story.append(Paragraph("No incidents recorded.", styles["Normal"]))

        story.append(Spacer(1, 0.6 * cm))

        # ── Risk Time Windows ─────────────────────────────────────────────
        story.append(Paragraph("High-Risk Time Windows", styles["Heading2"]))
        if risk_windows:
            tw_data = [["Hour", "Alert Count"]]
            for rw in risk_windows:
                tw_data.append([f"{rw['hour']:02d}:00 – {rw['hour']:02d}:59", str(rw["alert_count"])])
            tw_table = Table(tw_data, colWidths=[8 * cm, 8 * cm])
            tw_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#880e4f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#fce4ec"), colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (1, 0), (1, -1), "CENTER"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(tw_table)

        story.append(Spacer(1, 1 * cm))
        footer_style = ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
        story.append(Paragraph(
            f"Generated by RBIS v2.0 on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | "
            "Confidential — For Authorized Personnel Only",
            footer_style,
        ))

        doc.build(story)
        logger.info(f"PDF report saved: {pdf_path}")
        return pdf_path

    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return None
