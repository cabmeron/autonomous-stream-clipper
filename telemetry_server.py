import asyncio
import json
import logging
import os
import time
from typing import Optional, Set
from dotenv import load_dotenv
import websockets

from services.ingest.twitch_irc import TwitchChatVelocityEngine

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("telemetry")

PORT = int(os.getenv("TELEMETRY_PORT", 8765))
CLIENTS: Set[websockets.WebSocketServerProtocol] = set()

# Channel engine is None on startup until user configures it from Web UI
engine: Optional[TwitchChatVelocityEngine] = None

# Shared telemetry state
extra_telemetry = {
    "audio_rms_db": -60.0,
    "audio_spike": False,
    "ocr_balance": "$0.00",
    "ocr_multiplier": "1.0x",
    "ocr_pnl_delta": 0.0,
    "recent_clip": None,
}


def update_audio_telemetry(current_db: float, is_spiking: bool):
    """Updates the live audio metric state for HUD broadcast."""
    extra_telemetry["audio_rms_db"] = round(current_db, 1)
    extra_telemetry["audio_spike"] = is_spiking


def update_ocr_telemetry(balance: Optional[float], multiplier: float, pnl_delta: float):
    """Updates the live OCR metric state for HUD broadcast."""
    if balance is not None:
        extra_telemetry["ocr_balance"] = f"${balance:,.2f}"
    extra_telemetry["ocr_multiplier"] = f"{multiplier:.1f}x"
    extra_telemetry["ocr_pnl_delta"] = round(pnl_delta, 2)


def notify_new_clip(clip_summary: dict):
    """Sets a recent clip notification for the HUD."""
    extra_telemetry["recent_clip"] = clip_summary


def reset_telemetry():
    """Resets metrics when switching or clearing channels."""
    extra_telemetry["audio_rms_db"] = -60.0
    extra_telemetry["audio_spike"] = False
    extra_telemetry["ocr_balance"] = "$0.00"
    extra_telemetry["ocr_multiplier"] = "1.0x"
    extra_telemetry["ocr_pnl_delta"] = 0.0
    extra_telemetry["recent_clip"] = None


async def broadcast_loop():
    """Runs calculation and broadcasts metrics to all connected clients at 10 Hz (100ms)."""
    while True:
        try:
            if engine and engine.running:
                calc = engine.recalculate()
                channel_name = engine.channel
                v_instant = calc["v_instant"]
                v_baseline = calc["v_baseline"]
                spike_ratio = calc["spike_ratio"]
                is_spiking = calc["is_spiking"]
                buffered_msgs = calc["buffered_messages"]
                status = "monitoring"
            else:
                channel_name = engine.channel if engine else None
                v_instant = 0.0
                v_baseline = 0.0
                spike_ratio = 1.0
                is_spiking = False
                buffered_msgs = 0
                status = "idle"

            payload = json.dumps({
                "channel": channel_name,
                "status": status,
                "v_instant": v_instant,
                "v_baseline": v_baseline,
                "spike_ratio": spike_ratio,
                "is_spiking": is_spiking,
                "audio_rms_db": extra_telemetry["audio_rms_db"],
                "audio_spike": extra_telemetry["audio_spike"],
                "ocr_balance": extra_telemetry["ocr_balance"],
                "ocr_multiplier": extra_telemetry["ocr_multiplier"],
                "ocr_pnl_delta": extra_telemetry["ocr_pnl_delta"],
                "recent_clip": extra_telemetry["recent_clip"],
                "buffered_messages": buffered_msgs,
                "timestamp": time.time(),
            })

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
    logger.info("[Telemetry] Starting WebSocket server on ws://0.0.0.0:%d (idle on startup)", PORT)
    async with websockets.serve(ws_handler, "0.0.0.0", PORT):
        await broadcast_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("[Telemetry] Shutting down.")
