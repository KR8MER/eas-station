"""
WebSocket Router - Real-time updates via native FastAPI WebSocket
Replaces Flask-SocketIO with native async WebSocket support
"""

import asyncio
import logging
import json
from typing import Set
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

logger = logging.getLogger(__name__)

router = APIRouter()

# Active WebSocket connections
active_connections: Set[WebSocket] = set()


class ConnectionManager:
    """Manages WebSocket connections and broadcasts"""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        """Accept and register a new WebSocket connection"""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket client connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection"""
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket client disconnected. Total connections: {len(self.active_connections)}")

    async def send_personal(self, message: dict, websocket: WebSocket):
        """Send message to a specific client"""
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        disconnected = []
        for connection in self.active_connections:
            try:
                if connection.client_state == WebSocketState.CONNECTED:
                    await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                disconnected.append(connection)

        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)


# Global connection manager
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates.

    Clients can connect to this endpoint to receive:
    - Real-time audio metrics
    - Alert notifications
    - System status updates
    - EAS monitor events

    Example client code (JavaScript):
    ```javascript
    const ws = new WebSocket('ws://localhost:8001/ws');
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('Received:', data);
    };
    ```
    """
    await manager.connect(websocket)

    try:
        # Send welcome message
        await manager.send_personal({
            "type": "connected",
            "message": "Connected to EAS Station WebSocket",
            "timestamp": datetime.utcnow().isoformat()
        }, websocket)

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Receive messages from client
                data = await websocket.receive_text()
                message = json.loads(data)

                # Handle different message types
                msg_type = message.get("type")

                if msg_type == "ping":
                    # Respond to ping with pong
                    await manager.send_personal({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    }, websocket)

                elif msg_type == "subscribe":
                    # Handle subscription requests
                    topics = message.get("topics", [])
                    logger.info(f"Client subscribed to: {topics}")
                    await manager.send_personal({
                        "type": "subscribed",
                        "topics": topics,
                        "timestamp": datetime.utcnow().isoformat()
                    }, websocket)

                else:
                    # Echo unknown messages back
                    logger.debug(f"Received message: {message}")
                    await manager.send_personal({
                        "type": "echo",
                        "data": message,
                        "timestamp": datetime.utcnow().isoformat()
                    }, websocket)

            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await manager.send_personal({
                    "type": "error",
                    "message": "Invalid JSON",
                    "timestamp": datetime.utcnow().isoformat()
                }, websocket)
            except Exception as e:
                logger.error(f"Error handling WebSocket message: {e}")
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        manager.disconnect(websocket)


async def broadcast_audio_metrics(metrics: dict):
    """
    Broadcast audio metrics to all connected clients.

    Called by background tasks when new metrics are available.
    """
    await manager.broadcast({
        "type": "audio_metrics",
        "data": metrics,
        "timestamp": datetime.utcnow().isoformat()
    })


async def broadcast_alert(alert: dict):
    """
    Broadcast new alert to all connected clients.

    Called when a new emergency alert is received.
    """
    await manager.broadcast({
        "type": "alert",
        "data": alert,
        "timestamp": datetime.utcnow().isoformat()
    })


async def broadcast_system_status(status: dict):
    """
    Broadcast system status update to all connected clients.
    """
    await manager.broadcast({
        "type": "system_status",
        "data": status,
        "timestamp": datetime.utcnow().isoformat()
    })


# Export functions for use in other modules
__all__ = ["router", "broadcast_audio_metrics", "broadcast_alert", "broadcast_system_status"]
