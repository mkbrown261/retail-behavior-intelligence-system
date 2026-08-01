"""
Core event orchestrator.
Receives raw detections from the video pipeline and:
  1. Creates/retrieves Person records
  2. Logs Events
  3. Updates Suspicion Scores
  4. Records heatmap positions
  5. Triggers Alerts
  6. Pushes updates over WebSocket
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.websocket import manager
from app.core.config import settings
from app.models.person import Person
from app.models.event import Event
from app.models.media import Media
from app.services.scoring import process_event_for_score, get_all_live_scores, remove_person_state
from app.services import confidence as confidence_engine
from app.services.heatmap import record_position
from app.services.alert_service import create_alert
from app.services.storage import save_snapshot, get_file_url
from app.services.notifications import dispatch_alert_notifications
from app.services.repeat_visitor import find_or_create_cluster, record_visit

logger = logging.getLogger(__name__)

# Track in-memory which session_id → person_id
_session_to_person_id: Dict[str, str] = {}
_session_counters: Dict[str, int] = {}


async def handle_detection(detection: Dict):
    """Entry point called by the video pipeline for every detected event."""
    async with AsyncSessionLocal() as db:
        try:
            await _process_detection(db, detection)
        except Exception as e:
            logger.error(f"Detection processing error: {e}", exc_info=True)


async def _process_detection(db: AsyncSession, detection: Dict):
    # Guard: only process dicts that contain the required detection fields.
    # Raw camera frames (FRAME_READY intent payloads) do NOT have these fields
    # and must never reach this function.
    if "session_id" not in detection or "event_type" not in detection:
        logger.debug(
            f"_process_detection: skipped non-detection payload "
            f"(keys={list(detection.keys())[:6]})"
        )
        return

    session_id = detection["session_id"]
    event_type = detection["event_type"]
    # Task 2.4: camera_id is always stored as a STRING throughout the system.
    # The simulation pipeline uses integers (0,1,...); real cameras use string IDs.
    # Normalise to string so heatmap, alerts and events all reference the same key.
    camera_id  = str(detection.get("camera_id", "0"))
    bbox       = detection.get("bounding_box")
    pos_x      = detection.get("position_x", 0.5)
    pos_y      = detection.get("position_y", 0.5)
    confidence = detection.get("confidence", 0.9)
    zone       = detection.get("zone", "UNKNOWN")
    hold_dur   = detection.get("duration_seconds")
    color      = detection.get("dominant_color", "#888888")
    is_staff   = detection.get("is_staff", False)

    # ── 1. Resolve person ────────────────────────────────────────────────────
    person = await _get_or_create_person(db, session_id, color, is_staff, camera_id)

    # One-directional upgrade: a later frame with a clearer uniform-color
    # match (or a Sensor Bus badge scan) can promote CUSTOMER -> STAFF, but
    # never the reverse — demoting away from STAFF based on a noisy later
    # frame would be a trivial evasion vector for an actual suspect.
    if is_staff and person.person_type != "STAFF":
        person.person_type = "STAFF"
        logger.info(f"Person {session_id} upgraded to STAFF (uniform color match)")

    # Staff skip suspicion scoring
    if person.person_type == "STAFF":
        await _log_event(db, person, event_type, camera_id, bbox, pos_x, pos_y, confidence, zone, hold_dur)
        confidence_engine.record_event(person.id, session_id, event_type, is_staff=True)
        await db.commit()
        await manager.broadcast("cameras", {
            "type": "detection",
            "session_id": session_id,
            "event_type": event_type,
            "camera_id": camera_id,
            "bbox": bbox,
            "is_staff": True,
        })
        return

    # ── 2. Log event ─────────────────────────────────────────────────────────
    event = await _log_event(db, person, event_type, camera_id, bbox, pos_x, pos_y, confidence, zone, hold_dur)

    # ── 3. Update suspicion score ─────────────────────────────────────────────
    score_result = await process_event_for_score(
        db, person.id, session_id, event_type, camera_id,
        {"duration_seconds": hold_dur or 0}
    )
    confidence_engine.record_event(person.id, session_id, score_result.get("reason", event_type), is_staff=False)

    # ── 4. Record heatmap ─────────────────────────────────────────────────────
    interaction_weight = 1.0
    if event_type in ("PICK_ITEM", "HOLD_ITEM"):
        interaction_weight = 3.0
    elif score_result["level"] == "HIGH_SUSPICION":
        interaction_weight = 5.0

    await record_position(
        db, person.id, camera_id, pos_x, pos_y,
        interaction_type="INTERACT" if event_type in ("PICK_ITEM", "HOLD_ITEM", "RETURN_ITEM") else "WALK",
        weight=interaction_weight,
    )

    # ── 5. Handle alerts ──────────────────────────────────────────────────────
    alert_payload = None
    current_score = score_result.get("score", 0)

    # The flat score (scoring.py) and the multi-factor Confidence Score
    # (confidence.py) weight the same event stream differently — they can
    # genuinely diverge. confidence_escalated fires independently the first
    # time the multi-factor read reaches "Escalate — High Confidence" (e.g.
    # concealment + color-disappearance corroborating each other), even on a
    # session where the flat score hasn't crossed its own threshold yet.
    confidence_escalated = confidence_engine.check_and_mark_escalation(person.id)

    # BYPASS_REGISTER and EXIT_AFTER_PICK are always high-priority — alert regardless
    # of current score (a quick grab-and-run may not have built up score yet).
    # EXIT_STORE only alerts when suspicion is genuinely HIGH (score >= 61).
    # crossed_threshold fires the first time a person hits HIGH_SUSPICION on ANY event.
    should_alert = (
        score_result.get("crossed_threshold")
        or confidence_escalated
        or event_type in ("BYPASS_REGISTER", "EXIT_AFTER_PICK")
        or (event_type == "EXIT_STORE" and current_score >= 61)
    )
    if should_alert:
        # Task 2.5: try to grab a real JPEG from the live camera.
        # save_snapshot() will pull from camera_manager if no bytes are supplied.
        live_frame: Optional[bytes] = None
        try:
            from app.camera.camera_manager import camera_manager
            live_frame = camera_manager.get_jpeg(camera_id, quality=85)
        except Exception:
            pass
        snap_path = await save_snapshot(
            live_frame, session_id, camera_id, event_type,
            try_live_camera=(live_frame is None),  # skip double-pull if we got it
        )
        alert = await create_alert(
            db, person.id, session_id,
            score_result["score"], event_type, camera_id,
            snapshot_path=snap_path,
            event_breakdown=confidence_engine.get_breakdown(person.id),
        )
        await dispatch_alert_notifications(alert, session_id)
        alert_payload = alert.to_dict()

        # Mark event as suspicious
        event.is_suspicious = True
        event.snapshot_path = snap_path

    await db.commit()

    # ── 6. WebSocket broadcast ────────────────────────────────────────────────
    ws_payload = {
        "type": "detection",
        "session_id": session_id,
        "person_id": person.id,
        "event_type": event_type,
        "camera_id": camera_id,
        "bbox": bbox,
        "zone": zone,
        "score": score_result["score"],
        "level": score_result["level"],
        "confidence": confidence,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "is_staff": False,
    }
    await manager.broadcast("detections", ws_payload)
    await manager.broadcast("cameras", ws_payload)
    await manager.broadcast("scores", {
        "type": "score_update",
        "session_id": session_id,
        "score": score_result["score"],
        "level": score_result["level"],
        "delta": score_result["delta"],
        "reason": score_result["reason"],
    })

    if alert_payload:
        await manager.broadcast("alerts", {"type": "new_alert", "alert": alert_payload})

    # Person has left the frame — drop their live score entry so it stops
    # cluttering /api/persons/live-scores. History stays in the DB (Person/Event rows).
    if event_type == "EXIT_STORE":
        remove_person_state(person.id)
        confidence_engine.remove_tally(person.id)


async def _get_or_create_person(
    db: AsyncSession,
    session_id: str,
    dominant_color: str,
    is_staff: bool,
    camera_id: str,
) -> Person:
    if session_id in _session_to_person_id:
        pid = _session_to_person_id[session_id]
        result = await db.execute(select(Person).where(Person.id == pid))
        p = result.scalar_one_or_none()
        if p:
            return p

    # Check DB
    result = await db.execute(select(Person).where(Person.session_id == session_id))
    p = result.scalar_one_or_none()
    if p:
        _session_to_person_id[session_id] = p.id
        return p

    # Cluster for repeat visitor
    cluster_id = await find_or_create_cluster(db, dominant_color)

    p = Person(
        session_id=session_id,
        dominant_color=dominant_color,
        person_type="STAFF" if is_staff else "CUSTOMER",
        first_camera_id=camera_id,
        last_camera_id=camera_id,
        cameras_seen=[camera_id],
        appearance_cluster_id=cluster_id,
    )
    db.add(p)
    await db.flush()  # get id before commit
    _session_to_person_id[session_id] = p.id
    logger.info(f"New person created: {session_id} (staff={is_staff}, cluster={cluster_id})")
    return p


async def _log_event(
    db: AsyncSession,
    person: Person,
    event_type: str,
    camera_id: str,
    bbox,
    pos_x: float,
    pos_y: float,
    confidence: float,
    zone: str,
    duration_seconds: Optional[float] = None,
) -> Event:
    evt = Event(
        person_id=person.id,
        event_type=event_type,
        camera_id=camera_id,
        bounding_box=bbox,
        position_x=pos_x,
        position_y=pos_y,
        confidence=confidence,
        zone=zone,
        duration_seconds=duration_seconds,
    )
    db.add(evt)
    # Update person's last known position
    person.last_camera_id = camera_id
    person.last_x = pos_x
    person.last_y = pos_y
    person.last_bbox = bbox
    if camera_id not in (person.cameras_seen or []):
        person.cameras_seen = list(set((person.cameras_seen or []) + [camera_id]))

    if event_type == "EXIT_STORE":
        person.is_active = False
        person.exit_time = datetime.now(timezone.utc)

        # ── Record completed visit in repeat-visitor cluster ─────────────────
        if person.appearance_cluster_id:
            # SQLite server_default=func.now() returns naive datetimes; normalise
            # both sides to UTC-aware so subtraction never raises TypeError.
            def _to_utc(dt):
                if dt is None:
                    return None
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt

            entry = _to_utc(person.entry_time)
            exit_ = _to_utc(person.exit_time) or datetime.now(timezone.utc)
            dwell_minutes = (exit_ - entry).total_seconds() / 60.0 if entry else 0.0
            had_incident = person.is_flagged

            # Run in background so we don't block _log_event's caller
            import asyncio
            asyncio.create_task(
                _update_cluster_on_exit(
                    person.appearance_cluster_id,
                    person.current_suspicion_score or 0.0,
                    dwell_minutes,
                    had_incident,
                )
            )

    return evt


async def _update_cluster_on_exit(
    cluster_id: str,
    suspicion_score: float,
    dwell_minutes: float,
    had_incident: bool,
):
    """
    Update repeat-visitor cluster stats when a person exits the store.
    Runs as a background task so it never blocks the main detection path.
    """
    try:
        async with AsyncSessionLocal() as db:
            await record_visit(db, cluster_id, suspicion_score, dwell_minutes, had_incident)
    except Exception as e:
        logger.error(f"_update_cluster_on_exit error for {cluster_id}: {e}", exc_info=True)
