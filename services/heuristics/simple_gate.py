"""Simple Timed Stream Gate Service for Autonomous Stream Clipper.

Provides a purely time-based stream gate taking video, audio, and chat streams
and passing them downstream when the timed output connections fire on a scheduled interval.
"""

import logging
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 30.0
DEFAULT_GATE_DURATION_SECONDS = 2.0


class SimpleGateService:
    """Manages purely time-based stream gating and output firing schedules."""

    def __init__(
        self,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        gate_duration: float = DEFAULT_GATE_DURATION_SECONDS,
        enabled: bool = True,
        on_fire_callback: Optional[Callable[[int, float], None]] = None,
    ):
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.gate_duration = max(0.2, float(gate_duration))
        self.enabled = enabled
        self.on_fire = on_fire_callback

        now = time.time()
        self.last_fire_time = now
        self.fire_count = 0
        self.last_pulse_timestamp = 0.0
        self.manual_fire_requested = False

    def update_interval(self, interval_seconds: float) -> None:
        """Updates the gate firing interval."""
        new_interval = max(1.0, float(interval_seconds))
        if new_interval != self.interval_seconds:
            logger.info("[SimpleGate] Interval updated to %.1fs", new_interval)
            self.interval_seconds = new_interval

    def update_duration(self, gate_duration: float) -> None:
        """Updates the duration the gate remains actively open during a fire event."""
        new_duration = max(0.2, float(gate_duration))
        if new_duration != self.gate_duration:
            logger.info("[SimpleGate] Open duration updated to %.1fs", new_duration)
            self.gate_duration = new_duration

    def manual_fire(self, now: Optional[float] = None) -> bool:
        """Manually forces an immediate gate firing event."""
        t = time.time() if now is None else now
        self.manual_fire_requested = True
        self.last_fire_time = t
        self.last_pulse_timestamp = t
        self.fire_count += 1
        logger.info("[SimpleGate] Manual gate fire triggered (count=%d)", self.fire_count)

        if self.on_fire:
            try:
                self.on_fire(self.fire_count, t)
            except Exception as e:
                logger.error("[SimpleGate] Callback error on manual fire: %s", e)
        return True

    def check_trigger(self, now: Optional[float] = None) -> bool:
        """Checks if interval has elapsed since last fire, and triggers if so."""
        t = time.time() if now is None else now

        if not self.enabled:
            return False

        if self.manual_fire_requested:
            self.manual_fire_requested = False
            return True

        elapsed = t - self.last_fire_time
        if elapsed >= self.interval_seconds:
            self.last_fire_time = t
            self.last_pulse_timestamp = t
            self.fire_count += 1
            logger.debug("[SimpleGate] Periodic gate fire (count=%d, elapsed=%.1fs)", self.fire_count, elapsed)

            if self.on_fire:
                try:
                    self.on_fire(self.fire_count, t)
                except Exception as e:
                    logger.error("[SimpleGate] Callback error: %s", e)
            return True

        return False

    def is_gate_open(self, now: Optional[float] = None) -> bool:
        """Returns True if the gate is actively open and passing stream data."""
        t = time.time() if now is None else now
        return (t - self.last_pulse_timestamp) <= self.gate_duration

    def get_telemetry(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Calculates current countdown, progress ratio, open state, and fire count."""
        t = time.time() if now is None else now
        elapsed = max(0.0, t - self.last_fire_time)
        remaining = max(0.0, self.interval_seconds - elapsed)
        progress = min(1.0, elapsed / self.interval_seconds) if self.interval_seconds > 0 else 1.0

        is_open = self.is_gate_open(t)

        return {
            "interval_seconds": round(self.interval_seconds, 1),
            "gate_duration": round(self.gate_duration, 1),
            "countdown": round(remaining, 1),
            "progress": round(progress, 3),
            "is_open": is_open,
            "is_firing": is_open,
            "fire_count": self.fire_count,
            "enabled": self.enabled,
            "status": "firing" if is_open else ("armed" if self.enabled else "paused"),
        }
