"""Timer Trigger Service for Autonomous Stream Clipper.

Generates periodic heartbeat triggers and manages countdown timers to trigger
downstream heavy processing (such as computer vision or geolocation) at user-defined intervals.
"""

import logging
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 30.0
PULSE_WINDOW_SECONDS = 1.5


class TimerTriggerService:
    """Manages periodic clock pulses and countdown telemetry."""

    def __init__(
        self,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        enabled: bool = True,
        on_trigger_callback: Optional[Callable[[int, float], None]] = None,
    ):
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.enabled = enabled
        self.on_trigger = on_trigger_callback

        now = time.time()
        self.last_trigger_time = now
        self.trigger_count = 0
        self.last_pulse_timestamp = 0.0
        self.manual_pulse_requested = False

    def update_interval(self, interval_seconds: float) -> None:
        """Updates the trigger interval while preserving current progress."""
        new_interval = max(1.0, float(interval_seconds))
        if new_interval != self.interval_seconds:
            logger.info("[TimerTrigger] Interval updated to %.1fs", new_interval)
            self.interval_seconds = new_interval

    def manual_pulse(self, now: Optional[float] = None) -> bool:
        """Manually forces an immediate trigger event."""
        t = time.time() if now is None else now
        self.manual_pulse_requested = True
        self.last_trigger_time = t
        self.last_pulse_timestamp = t
        self.trigger_count += 1
        logger.info("[TimerTrigger] Manual pulse fired (count=%d)", self.trigger_count)

        if self.on_trigger:
            try:
                self.on_trigger(self.trigger_count, t)
            except Exception as e:
                logger.error("[TimerTrigger] Callback error on manual pulse: %s", e)
        return True

    def check_trigger(self, now: Optional[float] = None) -> bool:
        """Checks if interval has elapsed since last trigger, and pulses if so."""
        t = time.time() if now is None else now

        if self.manual_pulse_requested:
            self.manual_pulse_requested = False
            return True

        if not self.enabled:
            return False

        elapsed = t - self.last_trigger_time
        if elapsed >= self.interval_seconds:
            self.last_trigger_time = t
            self.last_pulse_timestamp = t
            self.trigger_count += 1
            logger.debug("[TimerTrigger] Periodic pulse fired (count=%d, elapsed=%.1fs)", self.trigger_count, elapsed)

            if self.on_trigger:
                try:
                    self.on_trigger(self.trigger_count, t)
                except Exception as e:
                    logger.error("[TimerTrigger] Callback error: %s", e)
            return True

        return False

    def is_currently_pulsing(self, now: Optional[float] = None) -> bool:
        """Returns True if within the active pulse visual window."""
        t = time.time() if now is None else now
        return (t - self.last_pulse_timestamp) <= PULSE_WINDOW_SECONDS

    def get_telemetry(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Calculates current countdown, progress ratio, and firing state."""
        t = time.time() if now is None else now
        elapsed = max(0.0, t - self.last_trigger_time)
        remaining = max(0.0, self.interval_seconds - elapsed)
        progress = min(1.0, elapsed / self.interval_seconds) if self.interval_seconds > 0 else 1.0

        is_pulsing = self.is_currently_pulsing(t)

        return {
            "interval_seconds": round(self.interval_seconds, 1),
            "countdown": round(remaining, 1),
            "progress": round(progress, 3),
            "is_firing": is_pulsing,
            "trigger_count": self.trigger_count,
            "enabled": self.enabled,
            "status": "pulsing" if is_pulsing else ("running" if self.enabled else "paused"),
        }
