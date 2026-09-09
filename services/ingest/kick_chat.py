"""Kick.com Pusher WebSocket Chat Ingestion and Chat Velocity Engine.

Connects to Kick's Pusher cluster over WebSockets, resolves chatroom IDs,
subscribes to live channel chatrooms, and tracks real-time chat density and spike events.
"""

import asyncio
from collections import deque
import inspect
import json
import logging
import random
import time
from typing import Callable, Dict, List, Optional
import urllib.request
import websockets

logger = logging.getLogger(__name__)

# Kick Pusher WebSocket configuration
KICK_PUSHER_CLUSTER = "us2"
KICK_PUSHER_KEY = "32cbd69e4b950bf97679"
KICK_PUSHER_URI = (
    f"wss://ws-{KICK_PUSHER_CLUSTER}.pusher.com/app/{KICK_PUSHER_KEY}"
    "?protocol=7&client=js&version=8.4.0-rc2&flash=false"
)


def parse_kick_chat_event(raw_event_data: str) -> Optional[dict]:
    """Parses raw JSON string from Kick's App\\Events\\ChatMessageEvent payload."""
    try:
        data = json.loads(raw_event_data) if isinstance(raw_event_data, str) else raw_event_data
        sender = data.get("sender") or {}
        username = sender.get("username", "anonymous")
        content = data.get("content", "")
        return {
            "user": username,
            "text": str(content).strip(),
            "time": time.time(),
        }
    except Exception as e:
        logger.debug("[KickChat] Failed to parse event payload: %s", e)
        return None


class KickChatVelocityEngine:
    """Maintains a WebSocket connection to Kick's Pusher cluster and tracks real-time chat density."""

    def __init__(
        self,
        channel: str,
        on_spike_callback: Optional[Callable[[float, float], None]] = None,
        spike_ratio_threshold: float = 3.0,
        instant_min_threshold: float = 10.0,
        chatroom_id: Optional[int] = None,
    ):
        self.channel = channel.lower().strip()
        self.on_spike = on_spike_callback
        self.spike_ratio_threshold = spike_ratio_threshold
        self.instant_min_threshold = instant_min_threshold
        self.chatroom_id = chatroom_id

        self.timestamps = deque()
        self.recent_messages = deque(maxlen=50)
        self.window_messages = []
        self.total_messages = 0
        self.running = False
        self.ws = None

        # Dynamic telemetry metrics matching TwitchChatVelocityEngine contract
        self.v_instant = 0.0    # 5-second window (msgs/sec)
        self.v_baseline = 0.0   # 60-second window (msgs/sec)
        self.spike_ratio = 1.0
        self.is_spiking = False

    async def resolve_chatroom_id(self) -> Optional[int]:
        """Queries Kick API v2 to retrieve the channel's chatroom ID."""
        if self.chatroom_id:
            return self.chatroom_id

        url = f"https://kick.com/api/v2/channels/{self.channel}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
        }

        def _fetch():
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        cid = data.get("chatroom", {}).get("id") or data.get("id")
                        return int(cid) if cid else None
            except Exception as e:
                logger.warning("[KickChat:%s] Error resolving chatroom ID from API: %s", self.channel, e)
            return None

        cid = await asyncio.to_thread(_fetch)
        if cid:
            self.chatroom_id = cid
            logger.info("[KickChat:%s] Resolved chatroom ID: %d", self.channel, cid)
        return cid

    async def listen(self):
        """Asynchronous listener maintaining connection to Kick Pusher WebSocket."""
        self.running = True
        reconnect_delay = 3.0
        max_reconnect_delay = 60.0

        while self.running:
            try:
                cid = await self.resolve_chatroom_id()
                if not cid:
                    logger.warning("[KickChat:%s] Could not resolve chatroom ID. Retrying in %.1fs...", self.channel, reconnect_delay)
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 1.5, max_reconnect_delay)
                    continue

                channel_sub_name = f"chatrooms.{cid}.v2"
                logger.info("[KickChat:%s] Connecting to Pusher (%s) for chatroom %d...", self.channel, KICK_PUSHER_CLUSTER, cid)

                async with websockets.connect(KICK_PUSHER_URI, ping_interval=25, ping_timeout=20) as ws:
                    self.ws = ws
                    reconnect_delay = 3.0

                    # Subscribe to channel
                    sub_payload = json.dumps({
                        "event": "pusher:subscribe",
                        "data": {"auth": "", "channel": channel_sub_name},
                    })
                    await ws.send(sub_payload)
                    logger.info("[KickChat:%s] Subscribed to Pusher channel %s", self.channel, channel_sub_name)

                    async for raw_message in ws:
                        if not self.running:
                            break

                        try:
                            msg_json = json.loads(raw_message)
                        except Exception:
                            continue

                        event = msg_json.get("event", "")

                        # Handle Pusher protocol ping/pong
                        if event == "pusher:ping":
                            await ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
                            continue
                        elif event == "pusher:error":
                            logger.warning("[KickChat:%s] Pusher error: %s", self.channel, msg_json.get("data"))
                            break

                        # Handle live chat messages
                        if "ChatMessageEvent" in event or event == "App\\Events\\ChatMessageEvent":
                            parsed = parse_kick_chat_event(msg_json.get("data", ""))
                            if parsed:
                                self._record_message(parsed["user"], parsed["text"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[KickChat:%s] WebSocket connection error: %s. Reconnecting in %.1fs...", self.channel, e, reconnect_delay)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 1.5, max_reconnect_delay)

    def _record_message(self, user: str, text: str):
        now = time.time()
        self.timestamps.append(now)
        self.total_messages += 1

        msg_obj = {"user": user, "text": text, "time": now}
        self.recent_messages.append(msg_obj)
        self.window_messages.append(msg_obj)

        self._update_metrics(now)

    def _update_metrics(self, now: float):
        # Evict timestamps older than 60 seconds
        cutoff_60 = now - 60.0
        while self.timestamps and self.timestamps[0] < cutoff_60:
            self.timestamps.popleft()

        cutoff_5 = now - 5.0
        idx_5 = 0
        for t in self.timestamps:
            if t >= cutoff_5:
                break
            idx_5 += 1

        count_5 = len(self.timestamps) - idx_5
        count_60 = len(self.timestamps)

        self.v_instant = round(count_5 / 5.0, 2)
        self.v_baseline = round(count_60 / 60.0, 2)

        baseline_clamped = max(self.v_baseline, 0.5)
        self.spike_ratio = round(self.v_instant / baseline_clamped, 2)

        # Check for spike trigger condition
        if self.v_instant >= self.instant_min_threshold and self.spike_ratio >= self.spike_ratio_threshold:
            if not self.is_spiking:
                self.is_spiking = True
                logger.info("[KickChat:%s] CHAT SPIKE TRIGGERED! instant=%.2f, ratio=%.2fx", self.channel, self.v_instant, self.spike_ratio)
                if self.on_spike:
                    try:
                        res = self.on_spike(self.v_instant, self.spike_ratio)
                        if inspect.isawaitable(res):
                            asyncio.create_task(res)
                    except Exception as e:
                        logger.error("[KickChat:%s] Error in on_spike callback: %s", self.channel, e)
        else:
            self.is_spiking = False

    def recalculate(self) -> dict:
        """Prunes historical timestamps and calculates current instant/baseline velocity and spike state."""
        now = time.time()
        self._update_metrics(now)
        count_60 = len(self.timestamps)

        return {
            "v_instant": self.v_instant,
            "v_baseline": self.v_baseline,
            "spike_ratio": self.spike_ratio,
            "is_spiking": self.is_spiking,
            "buffered_messages": count_60,
            "total_messages": self.total_messages,
            "recent_messages": list(self.recent_messages),
        }

    def drain_window_messages(self) -> List[dict]:
        """Extracts and clears the messages accumulated during the active window."""
        msgs = list(self.window_messages)
        self.window_messages.clear()
        return msgs

    def stop(self):
        """Stops the chat velocity engine."""
        self.running = False
        if self.ws and not self.ws.closed:
            asyncio.create_task(self.ws.close())
        logger.info("[KickChat:%s] Stopped Kick chat velocity engine.", self.channel)
