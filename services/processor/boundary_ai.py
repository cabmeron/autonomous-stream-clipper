import json
import logging
import os
import re
from typing import List, Optional

logger = logging.getLogger(__name__)


class BoundaryOptimizer:
    """100% Local Boundary Optimizer.

    Uses word timestamps, acoustic trigger centering, and natural speech pauses
    to find high-retention hook-and-payoff boundaries without external AI APIs.
    """

    def __init__(self, ollama_url: Optional[str] = None):
        # Optional local Ollama endpoint (e.g. http://localhost:11434)
        self.ollama_url = ollama_url or os.getenv("OLLAMA_URL")

    def find_optimal_cut(
        self,
        words: List[dict],
        telemetry_context: Optional[dict] = None,
        total_duration: float = 60.0,
    ) -> dict:
        """Calculates optimal start and end cut points locally using pause detection and trigger centering."""
        telemetry_context = telemetry_context or {}

        # Candidate window is -45s to +15s of trigger.
        # Therefore, the focal climax event is situated around t ≈ 45.0s in the 60s slice.
        event_time = min(total_duration - 10.0, max(15.0, total_duration - 15.0))

        # 1. Target start: between 15s and 30s before the event
        ideal_start = max(0.0, event_time - 25.0)

        # 2. Target end: between 5s and 12s after the event
        ideal_end = min(total_duration, event_time + 10.0)

        cut_start = ideal_start
        cut_end = ideal_end

        # Refine boundaries using word timestamps and speech pauses
        if words and len(words) >= 2:
            # Find closest natural speech boundary before the hook
            best_start_diff = float("inf")
            for i, w in enumerate(words):
                w_start = w.get("start", 0.0)
                # Check for pause before this word
                prev_end = words[i - 1].get("end", 0.0) if i > 0 else 0.0
                pause = w_start - prev_end

                # Prefer starting after a pause (>0.35s) near the ideal start window
                if 5.0 <= w_start <= event_time - 12.0:
                    diff = abs(w_start - ideal_start) - (1.5 if pause >= 0.35 else 0.0)
                    if diff < best_start_diff:
                        best_start_diff = diff
                        cut_start = max(0.0, w_start - 0.2)

            # Find closest natural speech boundary after the reaction
            best_end_diff = float("inf")
            for i, w in enumerate(words):
                w_end = w.get("end", 0.0)
                next_start = words[i + 1].get("start", total_duration) if i < len(words) - 1 else total_duration
                pause = next_start - w_end

                # Prefer ending on a pause (>0.35s) after the event payoff
                if event_time + 3.0 <= w_end <= total_duration:
                    diff = abs(w_end - ideal_end) - (1.5 if pause >= 0.35 else 0.0)
                    if diff < best_end_diff:
                        best_end_diff = diff
                        cut_end = min(total_duration, w_end + 0.4)

        # Enforce duration constraints (20s <= duration <= 58s)
        duration = cut_end - cut_start
        if duration < 20.0:
            deficit = 20.0 - duration
            cut_start = max(0.0, cut_start - (deficit / 2.0))
            cut_end = min(total_duration, cut_end + (deficit / 2.0))
            if cut_end - cut_start < 20.0:
                cut_end = min(total_duration, cut_start + 22.0)

        if cut_end - cut_start > 58.0:
            cut_end = cut_start + 58.0

        cut_start = round(cut_start, 2)
        cut_end = round(cut_end, 2)
        final_duration = round(cut_end - cut_start, 2)

        # Generate localized viral metadata
        meta = self._generate_local_metadata(words, telemetry_context, cut_start, cut_end)

        logger.info(
            "[BoundaryOptimizer:Local] Cut: [%.1fs -> %.1fs] (%.1fs) | Title: %s",
            cut_start,
            cut_end,
            final_duration,
            meta["title"],
        )

        return {
            "cut_start": cut_start,
            "cut_end": cut_end,
            "title": meta["title"],
            "caption": meta["caption"],
            "score": meta["score"],
        }

    def _generate_local_metadata(
        self,
        words: List[dict],
        context: dict,
        cut_start: float,
        cut_end: float,
    ) -> dict:
        """Generates viral titles, captions, and heuristic score locally."""
        multiplier = context.get("win_multiplier", 1.0)
        pnl = context.get("pnl_delta", 0.0)
        source = context.get("trigger_source", "Hype Spike")
        chat_peak = context.get("chat_instant", 0.0)
        audio_jump = context.get("audio_delta", 0.0)

        # Extract words in the clip window
        clip_words = [
            w.get("word", "").upper()
            for w in words
            if cut_start <= w.get("start", 0) <= cut_end
        ]
        text_content = " ".join(clip_words)

        # Detect high-engagement keywords
        hype_detected = bool(re.search(r'\b(OMG|UNREAL|NO WAY|INSANE|LOOK|WHAT|LET\'?S GO|HOLY|HUGE|MASSIVE)\b', text_content))

        # Title formatting logic
        if multiplier >= 100.0:
            title = f"INSANE {int(multiplier)}X WIN ON STREAM! 🤯"
        elif pnl >= 1000.0:
            title = f"+${pnl:,.0f} MASSIVE WIN ON STREAM! 💰"
        elif audio_jump >= 15.0:
            title = "STREAMER COMPLETELY LOST IT HERE! 🔊"
        elif chat_peak >= 25.0:
            title = "CHAT WENT COMPLETELY WILD! 🚀"
        elif hype_detected:
            title = "NO WAY THIS ACTUALLY JUST HAPPENED! 😱"
        else:
            title = f"CRAZY STREAM MOMENT ({source.replace('_', ' ').upper()}) 🔥"

        caption = f"{title} Clip captured live with velocity tracking. #twitch #streamer #clips #viral"
        score = context.get("score", 8)

        return {
            "title": title,
            "caption": caption,
            "score": score,
        }
