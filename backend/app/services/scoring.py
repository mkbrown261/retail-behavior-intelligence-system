"""
Suspicion Scoring Engine
Maintains in-memory scores per person and persists snapshots to the DB.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.core.config import settings
from app.models.person import Person
from app.models.suspicion import SuspicionScore

logger = logging.getLogger(__name__)

# ── Score rules ───────────────────────────────────────────────────────────────
SCORE_RULES = {
    "PICK_ITEM":          settings.SCORE_PICK_ITEM,
    "HOLD_ITEM_10S":      settings.SCORE_HOLD_ITEM_PER_10S,
    "MULTI_ITEM":         settings.SCORE_MULTI_ITEM,
    "AVOID_REGISTER":     settings.SCORE_AVOID_REGISTER,
    "MOVE_TO_EXIT":       settings.SCORE_MOVE_TO_EXIT,
    "RETURN_ITEM":        settings.SCORE_RETURN_ITEM,
    "COMPLETE_CHECKOUT":  settings.SCORE_COMPLETE_CHECKOUT,
    "IDLE_10S":           settings.SCORE_IDLE_PER_10S,
    "BYPASS_REGISTER":    25,
    "EXIT_AFTER_PICK":    20,
    "RAPID_EXIT":         15,
}

# ── Level thresholds ──────────────────────────────────────────────────────────
def score_to_level(score: float) -> str:
    if score >= settings.THRESHOLD_HIGH:
        return "HIGH_SUSPICION"
    elif score >= settings.THRESHOLD_WATCH:
        return "WATCH"
    return "NORMAL"


# ── In-memory live state ──────────────────────────────────────────────────────
class LivePersonState:
    def __init__(self, person_id: str, session_id: str):
        self.person_id = person_id
        self.session_id = session_id
        self.score: float = 0.0
        self.level: str = "NORMAL"
        self.items_held: int = 0
        self.holding_since: Optional[datetime] = None
        self.last_event: Optional[str] = None
        self.last_update: datetime = datetime.now(timezone.utc)
        self.idle_since: Optional[datetime] = None
        self.has_interacted_with_item: bool = False
        self.visited_register: bool = False


_live_states: Dict[str, LivePersonState] = {}
_lock = asyncio.Lock()


async def get_or_create_state(person_id: str, session_id: str) -> LivePersonState:
    async with _lock:
        if person_id not in _live_states:
            _live_states[person_id] = LivePersonState(person_id, session_id)
        return _live_states[person_id]


async def apply_score_delta(
    db: AsyncSession,
    person_id: str,
    session_id: str,
    reason: str,
    camera_id: Optional[int] = None,
    extra_delta: float = 0.0,
) -> Dict:
    state = await get_or_create_state(person_id, session_id)

    delta = SCORE_RULES.get(reason, 0.0) + extra_delta

    # Clamp score between 0 and 100
    new_score = max(0.0, min(100.0, state.score + delta))
    old_level = state.level
    new_level = score_to_level(new_score)

    state.score = new_score
    state.level = new_level
    state.last_update = datetime.now(timezone.utc)

    # Persist score snapshot
    snap = SuspicionScore(
        person_id=person_id,
        score=new_score,
        delta=delta,
        reason=reason,
        level=new_level,
        camera_id=camera_id,
    )
    db.add(snap)

    # Update person record — use SQLAlchemy case() for max_suspicion_score
    from sqlalchemy import case as sa_case
    await db.execute(
        update(Person)
        .where(Person.id == person_id)
        .values(
            current_suspicion_score=new_score,
            suspicion_level=new_level,
            is_flagged=(new_level == "HIGH_SUSPICION"),
            max_suspicion_score=sa_case(
                (Person.max_suspicion_score >= new_score, Person.max_suspicion_score),
                else_=new_score,
            ),
        )
    )
    await db.commit()

    result = {
        "person_id": person_id,
        "session_id": session_id,
        "score": new_score,
        "delta": delta,
        "reason": reason,
        "level": new_level,
        "level_changed": old_level != new_level,
        "crossed_threshold": new_level == "HIGH_SUSPICION" and old_level != "HIGH_SUSPICION",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(f"Score update [{session_id}]: {reason} → {new_score:.1f} ({new_level})")
    return result


async def process_event_for_score(
    db: AsyncSession,
    person_id: str,
    session_id: str,
    event_type: str,
    camera_id: Optional[int] = None,
    metadata: dict = None,
) -> Dict:
    """Map event types to score adjustments."""
    metadata = metadata or {}

    if event_type == "PICK_ITEM":
        state = await get_or_create_state(person_id, session_id)
        if state.items_held > 0:
            result = await apply_score_delta(db, person_id, session_id, "MULTI_ITEM", camera_id)
        else:
            result = await apply_score_delta(db, person_id, session_id, "PICK_ITEM", camera_id)
        state.items_held += 1
        state.holding_since = datetime.now(timezone.utc)
        state.has_interacted_with_item = True
        state.idle_since = None
        return result

    elif event_type == "HOLD_ITEM":
        hold_seconds = metadata.get("duration_seconds", 0)
        increments = int(hold_seconds // 10)
        extra = increments * settings.SCORE_HOLD_ITEM_PER_10S
        return await apply_score_delta(db, person_id, session_id, "HOLD_ITEM_10S", camera_id, extra - settings.SCORE_HOLD_ITEM_PER_10S)

    elif event_type == "RETURN_ITEM":
        state = await get_or_create_state(person_id, session_id)
        state.items_held = max(0, state.items_held - 1)
        state.holding_since = None
        return await apply_score_delta(db, person_id, session_id, "RETURN_ITEM", camera_id)

    elif event_type == "COMPLETE_CHECKOUT":
        state = await get_or_create_state(person_id, session_id)
        state.visited_register = True
        state.items_held = 0
        return await apply_score_delta(db, person_id, session_id, "COMPLETE_CHECKOUT", camera_id)

    elif event_type == "APPROACH_REGISTER":
        state = await get_or_create_state(person_id, session_id)
        state.visited_register = True
        return {"person_id": person_id, "score": state.score, "delta": 0, "reason": "APPROACH_REGISTER", "level": state.level}

    elif event_type == "BYPASS_REGISTER":
        state = await get_or_create_state(person_id, session_id)
        if state.has_interacted_with_item and not state.visited_register:
            result = await apply_score_delta(db, person_id, session_id, "BYPASS_REGISTER", camera_id)
        else:
            result = await apply_score_delta(db, person_id, session_id, "AVOID_REGISTER", camera_id)
        return result

    elif event_type == "EXIT_STORE":
        state = await get_or_create_state(person_id, session_id)
        if state.has_interacted_with_item and not state.visited_register and state.items_held > 0:
            return await apply_score_delta(db, person_id, session_id, "EXIT_AFTER_PICK", camera_id)
        return {"person_id": person_id, "score": state.score, "delta": 0, "reason": "EXIT_STORE", "level": state.level}

    elif event_type == "ENTER_STORE":
        state = await get_or_create_state(person_id, session_id)
        state.idle_since = datetime.now(timezone.utc)
        return {"person_id": person_id, "score": state.score, "delta": 0, "reason": "ENTER_STORE", "level": state.level}

    return {"person_id": person_id, "score": 0, "delta": 0, "reason": event_type, "level": "NORMAL"}


def get_all_live_scores() -> list:
    return [
        {
            "person_id": s.person_id,
            "session_id": s.session_id,
            "score": s.score,
            "level": s.level,
            "items_held": s.items_held,
            "has_interacted": s.has_interacted_with_item,
            "visited_register": s.visited_register,
        }
        for s in _live_states.values()
    ]


def remove_person_state(person_id: str):
    _live_states.pop(person_id, None)
