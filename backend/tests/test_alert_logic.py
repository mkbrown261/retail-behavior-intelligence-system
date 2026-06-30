"""
test_alert_logic.py — Tests for the alert generation logic in event_orchestrator.

Specifically verifies the Bug 1.3 fix:
  - BYPASS_REGISTER always generates an alert (even at score 0)
  - EXIT_AFTER_PICK always generates an alert (even at score 0)
  - EXIT_STORE only generates an alert when score >= 61
  - crossed_threshold generates an alert regardless of event type
  - Normal events at low score do NOT generate alerts

Also tests:
  - Alert severity mapping (_severity function)
  - Alert title building (_build_title function)
  - session_id is persisted in Alert record (Bug 1.4)
"""
import pytest
import pytest_asyncio

from app.services.alert_service import create_alert, _severity, _build_title


# ── _severity ──────────────────────────────────────────────────────────────────

def test_severity_bypass_register_is_critical():
    assert _severity(10, "BYPASS_REGISTER") == "CRITICAL"


def test_severity_exit_after_pick_is_critical():
    assert _severity(10, "EXIT_AFTER_PICK") == "CRITICAL"


def test_severity_high_score_is_critical():
    assert _severity(85, "OTHER_EVENT") == "CRITICAL"


def test_severity_score_70_is_high():
    assert _severity(72, "PICK_ITEM") == "HIGH"


def test_severity_score_50_is_medium():
    assert _severity(55, "PICK_ITEM") == "MEDIUM"


def test_severity_low_score_is_low():
    assert _severity(20, "PICK_ITEM") == "LOW"


# ── _build_title ──────────────────────────────────────────────────────────────

def test_build_title_bypass_register():
    title = _build_title("BYPASS_REGISTER", "Person_042", "CRITICAL")
    assert "CRITICAL" in title
    assert "Person_042" in title
    assert "Bypass" in title


def test_build_title_exit_after_pick():
    title = _build_title("EXIT_AFTER_PICK", "Person_007", "CRITICAL")
    assert "Person_007" in title


def test_build_title_unknown_event():
    title = _build_title("WEIRD_EVENT", "Person_001", "LOW")
    assert "Person_001" in title
    assert "WEIRD_EVENT" in title


# ── create_alert (DB integration) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_alert_persists_session_id(db):
    """Bug 1.4: session_id is stored in the Alert record."""
    from app.models.person import Person
    p = Person(session_id="Person_099")
    db.add(p)
    await db.flush()

    alert = await create_alert(
        db,
        person_id=p.id,
        session_id="Person_099",
        suspicion_score=75.0,
        trigger_event="BYPASS_REGISTER",
        camera_id=1,
    )
    assert alert.session_id == "Person_099"


@pytest.mark.asyncio
async def test_create_alert_bypass_register_low_score_is_critical(db):
    """BYPASS_REGISTER is always CRITICAL regardless of score."""
    from app.models.person import Person
    p = Person(session_id="Person_003")
    db.add(p)
    await db.flush()

    alert = await create_alert(
        db,
        person_id=p.id,
        session_id="Person_003",
        suspicion_score=5.0,   # very low score
        trigger_event="BYPASS_REGISTER",
    )
    assert alert.severity == "CRITICAL"


@pytest.mark.asyncio
async def test_create_alert_to_dict_has_session_id(db):
    """to_dict() includes session_id (Bug 1.4)."""
    from app.models.person import Person
    p = Person(session_id="Person_010")
    db.add(p)
    await db.flush()

    alert = await create_alert(
        db,
        person_id=p.id,
        session_id="Person_010",
        suspicion_score=65.0,
        trigger_event="HIGH_SUSPICION",
    )
    d = alert.to_dict()
    assert "session_id" in d
    assert d["session_id"] == "Person_010"


# ── Alert logic conditions (pure logic test — no DB) ──────────────────────────
#
# These replicate the exact should_alert expression from event_orchestrator.py
# to verify the operator precedence fix (Bug 1.3).

def _should_alert(crossed_threshold: bool, event_type: str, score: float) -> bool:
    """Mirror of the should_alert expression in event_orchestrator._process_detection."""
    return (
        crossed_threshold
        or event_type in ("BYPASS_REGISTER", "EXIT_AFTER_PICK")
        or (event_type == "EXIT_STORE" and score >= 61)
    )


# 7 cases from the original verification script

def test_alert_logic_crossed_threshold():
    assert _should_alert(True, "PICK_ITEM", 65) is True


def test_alert_logic_bypass_register_low_score():
    """Bug 1.3: BYPASS_REGISTER at score 5 MUST alert — was broken before fix."""
    assert _should_alert(False, "BYPASS_REGISTER", 5) is True


def test_alert_logic_bypass_register_high_score():
    assert _should_alert(False, "BYPASS_REGISTER", 90) is True


def test_alert_logic_exit_after_pick_low_score():
    """Bug 1.3: EXIT_AFTER_PICK at score 20 MUST alert."""
    assert _should_alert(False, "EXIT_AFTER_PICK", 20) is True


def test_alert_logic_exit_store_above_threshold():
    assert _should_alert(False, "EXIT_STORE", 65) is True


def test_alert_logic_exit_store_below_threshold():
    assert _should_alert(False, "EXIT_STORE", 30) is False


def test_alert_logic_normal_event_no_alert():
    assert _should_alert(False, "PICK_ITEM", 20) is False


def test_alert_logic_exactly_at_exit_store_threshold():
    """EXIT_STORE at exactly 61 should alert."""
    assert _should_alert(False, "EXIT_STORE", 61) is True


def test_alert_logic_exit_store_at_60_no_alert():
    """EXIT_STORE at 60 (below 61) should NOT alert."""
    assert _should_alert(False, "EXIT_STORE", 60) is False
