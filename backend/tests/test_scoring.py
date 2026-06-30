"""
test_scoring.py — Unit tests for the suspicion scoring engine.

Tests cover:
  - Every SCORE_RULES event type
  - Score clamping (floor at 0, ceiling at 100)
  - Level transitions (NORMAL → WATCH → HIGH_SUSPICION)
  - crossed_threshold flag fires exactly once per person
  - MULTI_ITEM path vs PICK_ITEM path
  - HOLD_ITEM increments by 10-second buckets
  - RETURN_ITEM reduces score and item counter
  - COMPLETE_CHECKOUT resets score heavily (negative delta)
  - APPROACH_REGISTER sets visited_register flag without score change
  - BYPASS_REGISTER with and without item interaction
  - EXIT_STORE with and without item held
"""
import pytest
import pytest_asyncio

from app.services.scoring import (
    apply_score_delta,
    process_event_for_score,
    get_or_create_state,
    _live_states,
    SCORE_RULES,
    score_to_level,
)
from app.core.config import settings


# ── Helpers ───────────────────────────────────────────────────────────────────

def fresh_sid():
    """Generate a unique session ID so each test gets isolated live state."""
    import uuid
    return f"test_{uuid.uuid4().hex[:8]}"


# ── score_to_level ─────────────────────────────────────────────────────────────

def test_score_to_level_normal():
    assert score_to_level(0) == "NORMAL"
    assert score_to_level(settings.THRESHOLD_WATCH - 1) == "NORMAL"


def test_score_to_level_watch():
    assert score_to_level(settings.THRESHOLD_WATCH) == "WATCH"
    assert score_to_level(settings.THRESHOLD_HIGH - 1) == "WATCH"


def test_score_to_level_high():
    assert score_to_level(settings.THRESHOLD_HIGH) == "HIGH_SUSPICION"
    assert score_to_level(100) == "HIGH_SUSPICION"


# ── apply_score_delta ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_score_delta_basic(db):
    """PICK_ITEM adds SCORE_PICK_ITEM points."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    # Need a Person row so the UPDATE doesn't fail FK constraints
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    result = await apply_score_delta(db, pid, sid, "PICK_ITEM")
    assert result["delta"] == settings.SCORE_PICK_ITEM
    assert result["score"] == settings.SCORE_PICK_ITEM
    assert result["level"] == "NORMAL"
    assert result["crossed_threshold"] is False


@pytest.mark.asyncio
async def test_apply_score_delta_clamp_floor(db):
    """Score should never go below 0."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    # RETURN_ITEM has a negative delta; starting at 0 should clamp to 0
    result = await apply_score_delta(db, pid, sid, "RETURN_ITEM")
    assert result["score"] == 0.0


@pytest.mark.asyncio
async def test_apply_score_delta_clamp_ceiling(db):
    """Score should never exceed 100."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    # Force score to 95, then add a large delta
    state = await get_or_create_state(pid, sid)
    state.score = 95.0

    result = await apply_score_delta(db, pid, sid, "BYPASS_REGISTER")
    # BYPASS_REGISTER delta is 25; 95+25=120 → clamped to 100
    assert result["score"] == 100.0


@pytest.mark.asyncio
async def test_level_transition_normal_to_watch(db):
    """Score crossing THRESHOLD_WATCH triggers level change but NOT crossed_threshold."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    state = await get_or_create_state(pid, sid)
    state.score = settings.THRESHOLD_WATCH - settings.SCORE_PICK_ITEM  # just below WATCH
    state.level = "NORMAL"

    result = await apply_score_delta(db, pid, sid, "PICK_ITEM")
    assert result["level"] == "WATCH"
    assert result["level_changed"] is True
    assert result["crossed_threshold"] is False  # HIGH_SUSPICION not reached yet


@pytest.mark.asyncio
async def test_level_transition_to_high_suspicion(db):
    """First time score crosses THRESHOLD_HIGH → crossed_threshold = True."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    state = await get_or_create_state(pid, sid)
    state.score = settings.THRESHOLD_HIGH - 10  # 10 below threshold
    state.level = "WATCH"

    result = await apply_score_delta(db, pid, sid, "BYPASS_REGISTER")
    # BYPASS_REGISTER = 25, so score goes from (61-10)=51 to 76 → HIGH_SUSPICION
    assert result["crossed_threshold"] is True
    assert result["level"] == "HIGH_SUSPICION"


@pytest.mark.asyncio
async def test_level_stays_high_no_re_cross(db):
    """Already HIGH_SUSPICION → crossed_threshold stays False on next update."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    state = await get_or_create_state(pid, sid)
    state.score = 70.0
    state.level = "HIGH_SUSPICION"

    result = await apply_score_delta(db, pid, sid, "PICK_ITEM")
    assert result["crossed_threshold"] is False


# ── process_event_for_score ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pick_item_first_time(db):
    """First PICK_ITEM → uses PICK_ITEM rule (not MULTI_ITEM)."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    result = await process_event_for_score(db, pid, sid, "PICK_ITEM")
    assert result["delta"] == settings.SCORE_PICK_ITEM


@pytest.mark.asyncio
async def test_pick_item_second_time_multi(db):
    """Second PICK_ITEM (items_held > 0) → uses MULTI_ITEM rule."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    await process_event_for_score(db, pid, sid, "PICK_ITEM")  # 1st pick
    result = await process_event_for_score(db, pid, sid, "PICK_ITEM")  # 2nd pick
    assert result["delta"] == settings.SCORE_MULTI_ITEM


@pytest.mark.asyncio
async def test_return_item_decrements_counter(db):
    """RETURN_ITEM reduces items_held and applies negative delta."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    await process_event_for_score(db, pid, sid, "PICK_ITEM")
    state = await get_or_create_state(pid, sid)
    assert state.items_held == 1

    await process_event_for_score(db, pid, sid, "RETURN_ITEM")
    assert state.items_held == 0


@pytest.mark.asyncio
async def test_complete_checkout_heavy_negative(db):
    """COMPLETE_CHECKOUT applies a large negative delta."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    # Build up some score first
    state = await get_or_create_state(pid, sid)
    state.score = 40.0

    result = await process_event_for_score(db, pid, sid, "COMPLETE_CHECKOUT")
    assert result["delta"] == settings.SCORE_COMPLETE_CHECKOUT  # negative
    assert result["score"] == 0.0  # clamped at floor


@pytest.mark.asyncio
async def test_approach_register_no_score_change(db):
    """APPROACH_REGISTER sets visited_register but returns 0 delta."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    state = await get_or_create_state(pid, sid)
    state.score = 20.0

    result = await process_event_for_score(db, pid, sid, "APPROACH_REGISTER")
    assert result["delta"] == 0
    assert result["score"] == 20.0
    assert state.visited_register is True


@pytest.mark.asyncio
async def test_bypass_register_with_item_uses_bypass_rule(db):
    """BYPASS_REGISTER when holding an item → BYPASS_REGISTER rule (score +25)."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    await process_event_for_score(db, pid, sid, "PICK_ITEM")  # sets has_interacted_with_item
    result = await process_event_for_score(db, pid, sid, "BYPASS_REGISTER")
    assert result["delta"] == SCORE_RULES["BYPASS_REGISTER"]  # 25


@pytest.mark.asyncio
async def test_bypass_register_without_item_uses_avoid_rule(db):
    """BYPASS_REGISTER when NOT holding any item → AVOID_REGISTER rule."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    # Don't pick anything — has_interacted_with_item stays False
    result = await process_event_for_score(db, pid, sid, "BYPASS_REGISTER")
    assert result["delta"] == settings.SCORE_AVOID_REGISTER


@pytest.mark.asyncio
async def test_exit_store_with_item_applies_exit_after_pick(db):
    """EXIT_STORE while still holding an item → EXIT_AFTER_PICK rule (+20)."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    await process_event_for_score(db, pid, sid, "PICK_ITEM")
    result = await process_event_for_score(db, pid, sid, "EXIT_STORE")
    assert result["delta"] == SCORE_RULES["EXIT_AFTER_PICK"]  # 20


@pytest.mark.asyncio
async def test_exit_store_clean_no_score_change(db):
    """EXIT_STORE after checkout → no additional score."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    # Checkout first (items_held drops to 0)
    await process_event_for_score(db, pid, sid, "COMPLETE_CHECKOUT")
    result = await process_event_for_score(db, pid, sid, "EXIT_STORE")
    assert result["delta"] == 0


@pytest.mark.asyncio
async def test_hold_item_increments_per_10s(db):
    """HOLD_ITEM with 30 seconds → 3 × SCORE_HOLD_ITEM_PER_10S delta."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    result = await process_event_for_score(
        db, pid, sid, "HOLD_ITEM", metadata={"duration_seconds": 30}
    )
    expected_delta = settings.SCORE_HOLD_ITEM_PER_10S * 3
    assert result["delta"] == expected_delta


@pytest.mark.asyncio
async def test_unknown_event_type_returns_zero(db):
    """Unknown event types return 0 delta without crashing."""
    sid = fresh_sid()
    pid = f"person_{sid}"
    from app.models.person import Person
    p = Person(id=pid, session_id=sid)
    db.add(p)
    await db.flush()

    result = await process_event_for_score(db, pid, sid, "TOTALLY_MADE_UP_EVENT")
    assert result["delta"] == 0
    assert result["score"] == 0


# ── SCORE_RULES completeness ──────────────────────────────────────────────────

def test_all_score_rules_defined():
    """Every SCORE_RULES key maps to a non-None numeric value."""
    for key, val in SCORE_RULES.items():
        assert isinstance(val, (int, float)), f"SCORE_RULES[{key!r}] is not numeric"
