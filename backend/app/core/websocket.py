import asyncio
import logging
from datetime import datetime
from typing import Dict, Set, Callable, Any
import json

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: Dict[str, Any] = {}
        self.subscriptions: Dict[str, Set[str]] = {
            "detections": set(),
            "alerts": set(),
            "scores": set(),
            "events": set(),
            "heatmap": set(),
            "cameras": set(),
        }
        self._lock = asyncio.Lock()

    async def connect(self, websocket, client_id: str):
        await websocket.accept()
        async with self._lock:
            self.active_connections[client_id] = websocket
        logger.info(f"WebSocket connected: {client_id} | Total: {len(self.active_connections)}")
        await self.send_personal(client_id, {
            "type": "connected",
            "client_id": client_id,
            "timestamp": datetime.utcnow().isoformat()
        })

    async def disconnect(self, client_id: str):
        async with self._lock:
            self.active_connections.pop(client_id, None)
            for topic in self.subscriptions:
                self.subscriptions[topic].discard(client_id)
        logger.info(f"WebSocket disconnected: {client_id}")

    async def subscribe(self, client_id: str, topics: list):
        async with self._lock:
            for topic in topics:
                if topic in self.subscriptions:
                    self.subscriptions[topic].add(client_id)

    async def send_personal(self, client_id: str, data: dict):
        ws = self.active_connections.get(client_id)
        if ws:
            try:
                await ws.send_text(json.dumps(data, default=str))
            except Exception as e:
                logger.error(f"Error sending to {client_id}: {e}")
                await self.disconnect(client_id)

    async def broadcast(self, topic: str, data: dict):
        subscribers = self.subscriptions.get(topic, set()).copy()
        dead = []
        for client_id in subscribers:
            ws = self.active_connections.get(client_id)
            if ws:
                try:
                    await ws.send_text(json.dumps(data, default=str))
                except Exception:
                    dead.append(client_id)
        for cid in dead:
            await self.disconnect(cid)

    async def broadcast_all(self, data: dict):
        for client_id in list(self.active_connections.keys()):
            await self.send_personal(client_id, data)

    @property
    def connection_count(self):
        return len(self.active_connections)


manager = ConnectionManager()
