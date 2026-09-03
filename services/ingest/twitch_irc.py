import asyncio
from collections import deque
import inspect
import logging
import random
import time
from typing import Callable, Optional
import websockets

logger = logging.getLogger(__name__)


class TwitchChatVelocityEngine:
    """Maintains an anonymous WebSocket connection to Twitch IRC and tracks real-time chat density."""

    def __init__(
        self,
        channel: str,
        on_spike_callback: Optional[Callable[[float, float], None]] = None,
        spike_ratio_threshold: float = 3.0,
        instant_min_threshold: float = 10.0,
    ):
        self.channel = channel.lower().lstrip("#")
        self.on_spike = on_spike_callback
        self.spike_ratio_threshold = spike_ratio_threshold
        self.instant_min_threshold = instant_min_threshold

        self.timestamps = deque()
        self.running = False
        self.ws = None

        # Dynamic telemetry metrics
        self.v_instant = 0.0    # 5-second window (msgs/sec)
        self.v_baseline = 0.0   # 60-second window (msgs/sec)
        self.spike_ratio = 1.0
        self.is_spiking = False

    async def listen(self):
        """Asynchronous listener maintaining an anonymous IRC connection."""
        uri = "wss://irc-ws.chat.twitch.tv:443"
        self.running = True

        while self.running:
            try:
                random_id = random.randint(10000, 99999)
                nick = f"justinfan{random_id}"

                async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as ws:
                    self.ws = ws
                    await ws.send("PASS oauth:SCHMOOPIIE")
                    await ws.send(f"NICK {nick}")
                    await ws.send(f"JOIN #{self.channel}")
                    logger.info("[Chat] Connected to Twitch IRC #%s as %s", self.channel, nick)

                    while self.running:
                        raw_msg = await ws.recv()
                        if "PRIVMSG" in raw_msg:
                            now = time.time()
                            self.timestamps.append(now)
                        elif raw_msg.startswith("PING"):
                            await ws.send("PONG :tmi.twitch.tv")
            except asyncio.CancelledError:
                break
            except Exception as err:
                if self.running:
                    logger.warning("[Chat] Connection dropped: %s. Reconnecting in 3s...", err)
                    await asyncio.sleep(3)

    def recalculate(self) -> dict:
        """Prunes historical timestamps and calculates current instant/baseline velocity and spike state."""
        now = time.time()
        cutoff_60 = now - 60.0
        cutoff_5 = now - 5.0

        # Discard messages older than 60 seconds
        while self.timestamps and self.timestamps[0] < cutoff_60:
            self.timestamps.popleft()

        count_60 = len(self.timestamps)
        count_5 = sum(1 for t in self.timestamps if t >= cutoff_5)

        self.v_instant = round(count_5 / 5.0, 2)
        self.v_baseline = round(count_60 / 60.0, 2)
        self.spike_ratio = round(self.v_instant / max(0.1, self.v_baseline), 2)

        spike_flag = (
            self.spike_ratio >= self.spike_ratio_threshold
            and self.v_instant >= self.instant_min_threshold
        )

        if spike_flag and not self.is_spiking:
            self.is_spiking = True
            logger.info(
                "[Chat] SPIKE TRIGGERED on #%s: instant=%.2f msgs/s, baseline=%.2f msgs/s, ratio=%.2fx",
                self.channel,
                self.v_instant,
                self.v_baseline,
                self.spike_ratio,
            )
            if self.on_spike:
                self._dispatch_spike(self.v_instant, self.spike_ratio)
        elif not spike_flag:
            self.is_spiking = False

        return {
            "v_instant": self.v_instant,
            "v_baseline": self.v_baseline,
            "spike_ratio": self.spike_ratio,
            "is_spiking": self.is_spiking,
            "buffered_messages": len(self.timestamps),
        }

    def _dispatch_spike(self, instant: float, ratio: float):
        """Dispatches callback supporting either synchronous or asynchronous handlers."""
        try:
            if inspect.iscoroutinefunction(self.on_spike):
                asyncio.create_task(self.on_spike(instant, ratio))
            else:
                self.on_spike(instant, ratio)
        except Exception as e:
            logger.error("[Chat] Error executing on_spike callback: %s", e)

    def stop(self):
        """Halts the engine and closes the socket."""
        self.running = False
        if self.ws:
            asyncio.create_task(self.ws.close())
