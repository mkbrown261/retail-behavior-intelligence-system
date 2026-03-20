from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.core.websocket import manager
from app.services.video_pipeline import pipeline
import uuid
import logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WebSocket & Cameras"])


@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "subscribe":
                topics = data.get("topics", ["detections", "alerts", "scores", "cameras"])
                await manager.subscribe(client_id, topics)
                await manager.send_personal(client_id, {
                    "type": "subscribed",
                    "topics": topics,
                })
    except WebSocketDisconnect:
        await manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error [{client_id}]: {e}")
        await manager.disconnect(client_id)


@router.websocket("/ws")
async def websocket_anon(websocket: WebSocket):
    client_id = f"anon_{uuid.uuid4().hex[:8]}"
    await websocket_endpoint(websocket, client_id)


@router.get("/cameras/feeds")
async def camera_feeds():
    return {"feeds": pipeline.get_camera_frames(), "active_persons": pipeline.get_active_count()}


@router.get("/cameras/{camera_id}/feed")
async def single_camera_feed(camera_id: int):
    frames = pipeline.get_camera_frames()
    for f in frames:
        if f["camera_id"] == camera_id:
            return f
    return {"camera_id": camera_id, "persons": [], "person_count": 0}


@router.get("/ws/status")
async def ws_status():
    return {
        "connected_clients": manager.connection_count,
        "pipeline_active": pipeline._running,
        "active_persons": pipeline.get_active_count(),
    }
