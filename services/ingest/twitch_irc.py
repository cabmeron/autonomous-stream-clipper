import asyncio
from collections import deque
import inspect
import logging
import random
import time
from typing import Callable, List, Optional
import websockets

logger = logging.getLogger(__name__)


def parse_irc_privmsg(raw_line: str) -> Optional[dict]:
    """Extracts username and clean text from Twitch IRC PRIVMSG line."""
    if " PRIVMSG #" not in raw_line:
        return None
    try:
        prefix, rest = raw_line.split(" PRIVMSG #", 1)
        if prefix.startswith("@") and " :" in prefix:
            prefix = prefix.split(" :", 1)[1]
        user = prefix.lstrip(":").split("!")[0]
        if " :" in rest:
            msg = rest.split(" :", 1)[1]
        else:
            msg = rest
        return {"user": user, "text": msg.strip(), "time": time.time()}
    except Exception:
        return None


class TwitchChatVelocityEngine:
    """Maintains an anonymous WebSocket connection to Twitch IRC and tracks real-time chat density and messages."""

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
        self.recent_messages = deque(maxlen=50)
        self.window_messages: list = []
        self.total_messages = 0
        self.running = False
        self.ws = None

        # Dynamic telemetry metrics
        self.v_instant = 0.0    # 5-second window (msgs/sec)
        self.v_baseline = 0.0   # 60-second window (msgs/sec)
        self.spike_ratio = 1.0
        self.is_spiking = False

    def drain_window_messages(self) -> List[dict]:
        """Returns and resets the messages collected for the 60-second sentiment analysis window."""
        msgs = self.window_messages
        self.window_messages = []
        return msgs

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
                    logger.info("[Chat:%s] Connected to Twitch IRC as %s", self.channel, nick)

                    while self.running:
                        raw_msg = await ws.recv()
                        # Split by \r\n to handle multiple IRC commands delivered in a single TCP/WS frame
                        lines = raw_msg.split("\r\n") if isinstance(raw_msg, str) else [raw_msg]
                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                            if line.startswith("PING"):
                                await ws.send("PONG :tmi.twitch.tv")
                            elif "PRIVMSG" in line:
                                now = time.time()
                                self.timestamps.append(now)
                                parsed = parse_irc_privmsg(line)
                                if parsed:
                                    self.total_messages += 1
                                    parsed["id"] = self.total_messages
                                    self.recent_messages.append(parsed)
                                    self.window_messages.append(parsed)
                                    if len(self.window_messages) > 2000:
                                        self.window_messages = self.window_messages[-2000:]
            except asyncio.CancelledError:
                break
            except Exception as err:
                if self.running:
                    logger.warning("[Chat:%s] Dropped connection: %s. Reconnecting in 3s...", self.channel, err)
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
                "[Chat:%s] SPIKE TRIGGERED: instant=%.2f msgs/s, baseline=%.2f msgs/s, ratio=%.2fx",
                self.channel,
                self.v_instant,
                self.v_baseline,
                self.spike_ratio,
            )
            if self.on_spike:
                if inspect.iscoroutinefunction(self.on_spike):
                    asyncio.create_task(self.on_spike(self.v_instant, self.spike_ratio))
                else:
                    self.on_spike(self.v_instant, self.spike_ratio)
        elif not spike_flag and self.is_spiking:
            self.is_spiking = False

        return {
            "v_instant": self.v_instant,
            "v_baseline": self.v_baseline,
            "spike_ratio": self.spike_ratio,
            "is_spiking": self.is_spiking,
            "buffered_messages": count_60,
            "total_messages": self.total_messages,
            "recent_messages": list(self.recent_messages),
        }

    def stop(self):
        self.running = False
        if self.ws:
            asyncio.create_task(self.ws.close())
