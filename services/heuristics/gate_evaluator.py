import asyncio
import inspect
import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class GateEvaluator:
    """Fuses multi-modal signals (Chat, Audio, OCR) with post-event delay buffering and 90s cooldown debounce."""

    def __init__(
        self,
        on_trigger_dispatch: Callable[[dict], None],
        on_trigger_activated: Optional[Callable[[dict], None]] = None,
        debounce_seconds: float = 30.0,
        post_event_delay_seconds: float = 10.0,
        event_loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.dispatch = on_trigger_dispatch
        self.on_trigger_activated = on_trigger_activated
        self.debounce_seconds = debounce_seconds
        self.post_event_delay = post_event_delay_seconds
        self.last_trigger_time = 0.0
        self.loop = event_loop

    def calculate_score(
        self,
        chat_instant: float,
        chat_ratio: float,
        win_multiplier: float,
        pnl_delta: float,
        audio_delta: float,
    ) -> int:
        """Computes a heuristic excitement score from 1 to 10."""
        score = 0
        if chat_ratio >= 5.0 or chat_instant >= 30.0:
            score += 5
        elif chat_ratio >= 3.0 or chat_instant >= 12.0:
            score += 4
        elif chat_ratio >= 2.0 or chat_instant >= 8.0:
            score += 2

        if win_multiplier >= 500.0 or pnl_delta >= 5000.0:
            score += 5
        elif win_multiplier >= 100.0 or pnl_delta >= 1000.0:
            score += 4
        elif win_multiplier >= 20.0 or pnl_delta >= 500.0:
            score += 3
        elif win_multiplier >= 5.0:
            score += 1

        if audio_delta >= 18.0:
            score += 5
        elif audio_delta >= 12.0:
            score += 4
        elif audio_delta >= 8.0:
            score += 2

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
    ):
        """Evaluates incoming signal, enforces 90s debounce cooldown, and schedules post-delay dispatch."""
        now = time.time()
        time_since_last = now - self.last_trigger_time

        if time_since_last < self.debounce_seconds:
            logger.debug(
                "[Gate] Suppressed trigger from %s (debouncing: %.1fs remaining)",
                source,
                self.debounce_seconds - time_since_last,
            )
            return

        score = self.calculate_score(chat_instant, chat_ratio, win_multiplier, pnl_delta, audio_delta)
        if score < 4:
            logger.debug("[Gate] Score %d is below threshold (4); skipping trigger.", score)
            return

        self.last_trigger_time = now
        logger.info(
            "[Gate] TRIGGER ACTIVATED: source=%s | score=%d/10 | scheduling dispatch after +%.1fs delay buffer...",
            source,
            score,
            self.post_event_delay,
        )

        context = {
            "trigger_source": source,
            "score": score,
            "trigger_time": now,
            "post_event_delay": self.post_event_delay,
            "chat_instant": chat_instant,
            "chat_ratio": chat_ratio,
            "win_multiplier": win_multiplier,
            "pnl_delta": pnl_delta,
            "audio_db": audio_db,
            "audio_delta": audio_delta,
        }

        # Immediately notify listener that a clipping job has activated
        # 1. Immediately notify listener that a clipping job has activated
        if self.on_trigger_activated:
            try:
                if inspect.iscoroutinefunction(self.on_trigger_activated):
                    try:
                        cur_loop = asyncio.get_running_loop()
                        cur_loop.create_task(self.on_trigger_activated(context))
                    except RuntimeError:
                        if self.loop and self.loop.is_running():
                            asyncio.run_coroutine_threadsafe(self.on_trigger_activated(context), self.loop)
                else:
                    self.on_trigger_activated(context)
            except Exception as e:
                logger.error("[Gate] Error notifying trigger activated: %s", e)

        # 2. Schedule delayed dispatch (thread-safe for worker threads)
        target_loop = None
        try:
            target_loop = asyncio.get_running_loop()
        except RuntimeError:
            target_loop = getattr(self, "loop", None)

        if target_loop and target_loop.is_running():
            try:
                target_loop.create_task(self._delayed_dispatch(context))
            except RuntimeError:
                asyncio.run_coroutine_threadsafe(self._delayed_dispatch(context), target_loop)
        else:
            # Fallback when running outside an active event loop (e.g. synchronous unit test)
            if self.post_event_delay == 0.0:
                if inspect.iscoroutinefunction(self.dispatch):
                    asyncio.run(self.dispatch(context))
                else:
                    self.dispatch(context)

    async def _delayed_dispatch(self, context: dict):
        """Waits for post_event_delay seconds so the ring buffer captures the full streamer reaction."""
        if self.post_event_delay > 0:
            await asyncio.sleep(self.post_event_delay)
        logger.info("[Gate] Post-event delay complete. Dispatching to processor pipeline.")
        try:
            if inspect.iscoroutinefunction(self.dispatch):
                await self.dispatch(context)
            else:
                self.dispatch(context)
        except Exception as e:
            logger.error("[Gate] Error executing clip dispatch: %s", e)
