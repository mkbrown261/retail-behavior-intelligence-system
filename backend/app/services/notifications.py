"""
Notification service — SMS, email, push.
All channels are no-ops when credentials are not configured.
"""
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_sms(to: str, message: str) -> bool:
    if not settings.TWILIO_ACCOUNT_SID:
        logger.info(f"[SMS STUB] To: {to} | {message[:80]}")
        return True
    try:
        from twilio.rest import Client
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(body=message, from_=settings.TWILIO_FROM_NUMBER, to=to)
        logger.info(f"SMS sent to {to}")
        return True
    except Exception as e:
        logger.error(f"SMS failed: {e}")
        return False


async def send_email(to: str, subject: str, html_body: str) -> bool:
    if not settings.SENDGRID_API_KEY:
        logger.info(f"[EMAIL STUB] To: {to} | Subject: {subject}")
        return True
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail
        sg = sendgrid.SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
        mail = Mail(
            from_email=settings.ALERT_EMAIL_FROM,
            to_emails=to,
            subject=subject,
            html_content=html_body,
        )
        sg.send(mail)
        logger.info(f"Email sent to {to}")
        return True
    except Exception as e:
        logger.error(f"Email failed: {e}")
        return False


def _recommendation(alert) -> str:
    breakdown = alert.event_breakdown or {}
    return breakdown.get("recommendation", "")


async def dispatch_alert_notifications(alert, person_session_id: str):
    """
    Dispatch notification channels, tiered by severity AND the Confidence
    Score's recommendation (not just severity alone — a CRITICAL alert with
    a "Review Before Escalation" read, e.g. only one weak corroborating
    signal, shouldn't page someone at 2am the same way a genuinely
    corroborated "Escalate" read should):

      CRITICAL + "Escalate — High Confidence"  -> SMS (if configured) + email
      everything else that alerts at all       -> email only
      (LOW-severity/never-alerting cases never reach this function)

    This is what "relay it to the proper person" actually means in practice —
    the routing decision, not just whether a notification fires at all.
    """
    score = alert.suspicion_score
    title = alert.title
    desc = alert.description or ""
    recommendation = _recommendation(alert)
    is_top_tier = alert.severity == "CRITICAL" and recommendation == "Escalate — High Confidence"

    if is_top_tier and settings.ALERT_SMS_TO:
        sms_msg = f"RBIS URGENT [{alert.severity}]: {title} | Score: {score:.0f}/100 | {recommendation}"
        await send_sms(settings.ALERT_SMS_TO, sms_msg)

    if settings.ALERT_EMAIL_TO:
        urgency_banner = (
            "🚨 IMMEDIATE ATTENTION — corroborated by multiple independent signals"
            if is_top_tier else "Review when convenient"
        )
        html = f"""
        <h2 style='color:#b71c1c'>🚨 {title}</h2>
        <p style='color:#b71c1c'><b>{urgency_banner}</b></p>
        <p><b>Severity:</b> {alert.severity}</p>
        <p><b>Suspicion Score:</b> {score:.1f}/100</p>
        <p><b>Confidence Recommendation:</b> {recommendation or 'N/A'}</p>
        <p><b>Person:</b> {person_session_id}</p>
        <p><b>Camera:</b> {alert.camera_id}</p>
        <p>{desc}</p>
        <hr>
        <small>Retail Behavior Intelligence System v2.0</small>
        """
        await send_email(settings.ALERT_EMAIL_TO, f"[RBIS] {title}", html)

    logger.info(f"Alert notifications dispatched for: {title} (tier={'SMS+email' if is_top_tier else 'email'})")
