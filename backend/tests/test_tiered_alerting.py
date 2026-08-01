"""
test_tiered_alerting.py — confidence-based escalation trigger (independent
of the flat score threshold) and tiered notification routing (SMS only for
CRITICAL + "Escalate — High Confidence", email otherwise).
"""
import pytest

from app.services import confidence
from app.services import notifications
from app.core.config import settings


class FakeAlert:
    def __init__(self, severity, suspicion_score, event_breakdown=None, camera_id="webcam"):
        self.severity = severity
        self.suspicion_score = suspicion_score
        self.title = "Test alert"
        self.description = "test description"
        self.camera_id = camera_id
        self.event_breakdown = event_breakdown


# ── Confidence escalation trigger ─────────────────────────────────────────────

def test_escalation_fires_once_then_never_again():
    pid = "escalation_test_person"
    # Build up enough factors (including the corroboration bonus) to reach
    # the Escalate tier — both signals firing twice each caps their factors
    # near the top of their weighted contribution.
    confidence.record_event(pid, "s1", "PICK_ITEM")
    confidence.record_event(pid, "s1", "CONCEALMENT")
    confidence.record_event(pid, "s1", "CONCEALMENT")
    confidence.record_event(pid, "s1", "COLOR_DISAPPEARANCE")
    confidence.record_event(pid, "s1", "COLOR_DISAPPEARANCE")
    confidence.record_event(pid, "s1", "BYPASS_REGISTER")
    confidence.record_event(pid, "s1", "EXIT_AFTER_PICK")

    breakdown = confidence.get_breakdown(pid)
    assert breakdown["recommendation"] == "Escalate — High Confidence"

    assert confidence.check_and_mark_escalation(pid) is True    # fires once
    assert confidence.check_and_mark_escalation(pid) is False   # never again for this person
    assert confidence.check_and_mark_escalation(pid) is False


def test_escalation_never_fires_below_threshold():
    pid = "low_confidence_person"
    confidence.record_event(pid, "s2", "RAPID_MOVEMENT")
    breakdown = confidence.get_breakdown(pid)
    assert breakdown["recommendation"] != "Escalate — High Confidence"
    assert confidence.check_and_mark_escalation(pid) is False


def test_escalation_returns_false_for_unknown_person():
    assert confidence.check_and_mark_escalation("nonexistent_person_id") is False


# ── Notification tiering ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_critical_plus_escalate_sends_sms_and_email(monkeypatch):
    sms_calls, email_calls = [], []
    monkeypatch.setattr(notifications, "send_sms", lambda to, msg: sms_calls.append((to, msg)) or _true())
    monkeypatch.setattr(notifications, "send_email", lambda to, subj, html: email_calls.append((to, subj)) or _true())
    monkeypatch.setattr(settings, "ALERT_SMS_TO", "+15551234567")
    monkeypatch.setattr(settings, "ALERT_EMAIL_TO", "manager@store.example")

    alert = FakeAlert("CRITICAL", 95.0, event_breakdown={"recommendation": "Escalate — High Confidence"})
    await notifications.dispatch_alert_notifications(alert, "session_1")

    assert len(sms_calls) == 1
    assert sms_calls[0][0] == "+15551234567"
    assert len(email_calls) == 1


@pytest.mark.asyncio
async def test_critical_without_escalate_recommendation_skips_sms(monkeypatch):
    """Severity alone isn't enough — needs the confidence recommendation too."""
    sms_calls, email_calls = [], []
    monkeypatch.setattr(notifications, "send_sms", lambda to, msg: sms_calls.append((to, msg)) or _true())
    monkeypatch.setattr(notifications, "send_email", lambda to, subj, html: email_calls.append((to, subj)) or _true())
    monkeypatch.setattr(settings, "ALERT_SMS_TO", "+15551234567")
    monkeypatch.setattr(settings, "ALERT_EMAIL_TO", "manager@store.example")

    alert = FakeAlert("CRITICAL", 90.0, event_breakdown={"recommendation": "Review Before Escalation"})
    await notifications.dispatch_alert_notifications(alert, "session_2")

    assert len(sms_calls) == 0
    assert len(email_calls) == 1


@pytest.mark.asyncio
async def test_no_sms_recipient_configured_skips_sms_even_for_top_tier(monkeypatch):
    sms_calls, email_calls = [], []
    monkeypatch.setattr(notifications, "send_sms", lambda to, msg: sms_calls.append((to, msg)) or _true())
    monkeypatch.setattr(notifications, "send_email", lambda to, subj, html: email_calls.append((to, subj)) or _true())
    monkeypatch.setattr(settings, "ALERT_SMS_TO", "")  # not configured
    monkeypatch.setattr(settings, "ALERT_EMAIL_TO", "manager@store.example")

    alert = FakeAlert("CRITICAL", 95.0, event_breakdown={"recommendation": "Escalate — High Confidence"})
    await notifications.dispatch_alert_notifications(alert, "session_3")

    assert len(sms_calls) == 0
    assert len(email_calls) == 1


def _true():
    async def _coro():
        return True
    return _coro()
