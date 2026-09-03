import asyncio
import json
import logging
import os
import time
from typing import Callable, Dict, Optional, Set
from dotenv import load_dotenv
import websockets

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("telemetry")

PORT = int(os.getenv("TELEMETRY_PORT", 8765))
CLIENTS: Set[websockets.WebSocketServerProtocol] = set()

# Global provider function registered by Orchestrator: returns Dict[str, dict]
sessions_telemetry_provider: Optional[Callable[[], Dict[str, dict]]] = None
active_jobs_provider: Optional[Callable[[], Dict[str, dict]]] = None

# Fallback for single engine (backward compatibility)
engine = None
extra_telemetry: Dict[str, dict] = {}
recent_clip_notification = None


def notify_new_clip(clip_summary: dict):
    """Sets a recent clip notification for all HUD tabs."""
    global recent_clip_notification
    recent_clip_notification = clip_summary


async def broadcast_loop():
    """Broadcasts multi-session telemetry metrics to all connected clients at 10 Hz (100ms)."""
    global recent_clip_notification
    while True:
        try:
            sessions_data = {}
            if sessions_telemetry_provider:
                try:
                    sessions_data = sessions_telemetry_provider()
                except Exception as err:
                    logger.debug("[Telemetry] Provider exception: %s", err)

            jobs_data = {}
            if active_jobs_provider:
                try:
                    jobs_data = active_jobs_provider()
                except Exception as err:
                    logger.debug("[Telemetry] Jobs provider exception: %s", err)

            payload = json.dumps({
                "type": "telemetry",
                "sessions": sessions_data,
                "session_count": len(sessions_data),
                "active_jobs": jobs_data,
                "recent_clip": recent_clip_notification,
                "timestamp": time.time(),
            })

            # Clear one-time notification after broadcasting to active clients
            if CLIENTS and recent_clip_notification:
                recent_clip_notification = None

            if CLIENTS:
                await asyncio.gather(
                    *[c.send(payload) for c in list(CLIENTS)],
                    return_exceptions=True,
                )
        except Exception as e:
            logger.debug("[Telemetry] Broadcast loop exception: %s", e)

        await asyncio.sleep(0.1)


async def ws_handler(websocket):
    """Handles incoming client WebSocket connections."""
    CLIENTS.add(websocket)
    logger.info("[Telemetry] Client connected (%d total)", len(CLIENTS))
    try:
        await websocket.wait_closed()
    finally:
        CLIENTS.remove(websocket)
        logger.info("[Telemetry] Client disconnected (%d total)", len(CLIENTS))


async def main():
    logger.info("[Telemetry] Starting WebSocket server on ws://0.0.0.0:%d (multi-session mode)", PORT)
    async with websockets.serve(ws_handler, "0.0.0.0", PORT):
        await broadcast_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[Telemetry] Shutting down.")
