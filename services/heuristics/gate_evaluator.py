import asyncio
import inspect
import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class GateEvaluator:
    """Combines multi-modal heuristic signals, applies debounce cooldown, and schedules delayed clip jobs."""

    def __init__(
        self,
        on_trigger_dispatch: Optional[Callable[[dict], None]] = None,
        debounce_seconds: float = 90.0,
        post_event_delay_seconds: float = 15.0,
    ):
        self.on_trigger_dispatch = on_trigger_dispatch
        self.debounce_seconds = debounce_seconds
        self.post_event_delay_seconds = post_event_delay_seconds

        self.last_trigger_time: float = 0.0
        self.is_cooling_down: bool = False
        self.total_triggers: int = 0

    def should_trigger(self) -> bool:
        """Determines if the evaluator is outside the debounce cooldown window."""
        now = time.time()
        if now - self.last_trigger_time < self.debounce_seconds:
            return False
        return True

    def calculate_heuristic_score(
        self,
        trigger_source: str,
        chat_ratio: float = 1.0,
        win_mult: float = 1.0,
        audio_delta: float = 0.0,
    ) -> int:
        """Calculates a normalized 1-10 composite excitement score."""
        score = 5

        # Chat ratio impact
        if chat_ratio >= 5.0:
            score += 3
        elif chat_ratio >= 3.0:
            score += 2

        # Win multiplier impact
        if win_mult >= 500.0:
            score += 3
        elif win_mult >= 100.0:
            score += 2

        # Audio volume impact
        if audio_delta >= 18.0:
            score += 2
        elif audio_delta >= 12.0:
            score += 1

        return min(10, max(1, score))

    def evaluate_signals(
        self,
        source: str,
        chat_instant: float = 0.0,
        chat_ratio: float = 1.0,
        win_multiplier: float = 1.0,
        pnl_delta: float = 0.0,
        audio_db: float = -60.0,
        audio_delta: float = 0.0,
    ) -> bool:
        """Evaluates whether incoming heuristics constitute a trigger event."""
        if not self.should_trigger():
            logger.debug(
                "[GateEvaluator] Trigger from %s suppressed by cooldown (%.1fs remaining)",
                source,
                self.debounce_seconds - (time.time() - self.last_trigger_time),
            )
            return False

        self.last_trigger_time = time.time()
        self.total_triggers += 1

        score = self.calculate_heuristic_score(
            source,
            chat_ratio=chat_ratio,
            win_mult=win_multiplier,
            audio_delta=audio_delta,
        )

        event_context = {
            "trigger_source": source,
            "trigger_timestamp": self.last_trigger_time,
            "chat_instant": chat_instant,
            "chat_ratio": chat_ratio,
            "win_multiplier": win_multiplier,
            "pnl_delta": pnl_delta,
            "audio_db": audio_db,
            "audio_delta": audio_delta,
            "score": score,
        }

        logger.info(
            "[GateEvaluator] INTERRUPT FIRED (%s)! Score: %d/10. Scheduling candidate capture with +%ds delay...",
            source,
            score,
            self.post_event_delay_seconds,
        )

        # Schedule post-event delay in event loop if active
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._delayed_dispatch(event_context))
        except RuntimeError:
            pass

        return True

    async def _delayed_dispatch(self, context: dict):
        """Waits for the post-event delay duration so the reaction is captured in the ring buffer."""
        try:
            if self.post_event_delay_seconds > 0:
                await asyncio.sleep(self.post_event_delay_seconds)

            logger.info("[GateEvaluator] Post-event buffer window complete. Dispatching to processor pipeline...")
            if self.on_trigger_dispatch:
                if inspect.iscoroutinefunction(self.on_trigger_dispatch):
                    await self.on_trigger_dispatch(context)
                else:
                    self.on_trigger_dispatch(context)
        except Exception as err:
            logger.error("[GateEvaluator] Delayed dispatch failed: %s", err)
