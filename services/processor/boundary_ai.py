import logging
from typing import List

logger = logging.getLogger(__name__)


class BoundaryOptimizer:
    """Calculates optimal in/out cut points (20s-58s) using word timestamps and speech pause detection."""

    def __init__(self, api_key: str = None):
        logger.info("[BoundaryOptimizer] Operating in 100% local heuristic mode (zero external APIs).")

    def find_optimal_cut(
        self,
        words: List[dict],
        event_context: dict,
        total_duration: float = 60.0,
    ) -> dict:
        """Determines tight clip boundaries centered around the trigger moment."""
        # Trigger occurred ~15s before the end of the buffered window
        trigger_time = max(5.0, total_duration - 15.0) if total_duration > 20.0 else (total_duration * 0.7)
        mult = event_context.get("win_multiplier", 1.0)
        pnl = event_context.get("pnl_delta", 0.0)
        source = event_context.get("trigger_source", "chat_spike")

        # Dynamic title & caption generation
        if mult >= 100.0:
            title = f"INSANE {int(mult)}X MULTIPLIER HIT!"
            caption = f" streamer just hit a massive {int(mult)}x win! #twitch #gaming #viral"
        elif pnl >= 1000.0:
            title = f"STREAMER WINS +${pnl:,.0f} LIVE!"
            caption = f"Unreal profit live on stream! #twitch #win"
        elif "audio" in source:
            title = "THE BIGGEST REACTION OF THE STREAM!"
            caption = "Wait for the scream at the end... #streamer #clips"
        else:
            title = "CHAT WENT ABSOLUTELY CRAZY FOR THIS!"
            caption = "Twitch chat was moving too fast to read! #twitchclips #highlight"

        target_start = max(0.0, trigger_time - 28.0)
        target_end = min(total_duration, trigger_time + 12.0)

        # If no words detected, fall back to safe centered window
        if not words:
            best_start = target_start
            best_end = target_end
        else:
            # 1. Identify natural speech pause before the event to place cut_start
            best_start = target_start
            for i in range(len(words) - 1):
                pause_len = words[i + 1]["start"] - words[i]["end"]
                if pause_len >= 0.45 and target_start <= words[i]["end"] <= max(target_start + 1.0, trigger_time - 5.0):
                    best_start = words[i]["end"] + 0.1
                    break

            # 2. Identify post-reaction speech pause to place cut_end
            best_end = target_end
            for i in range(len(words) - 1):
                if words[i]["end"] >= trigger_time + 3.0:
                    pause_len = words[i + 1]["start"] - words[i]["end"]
                    if pause_len >= 0.5:
                        best_end = min(total_duration, words[i]["end"] + 0.5)
                        break

        # Enforce target duration between min_allowed and max_allowed
        max_allowed = min(58.0, total_duration)
        min_allowed = min(20.0, total_duration)
        curr_dur = best_end - best_start

        if curr_dur < min_allowed:
            best_start = max(0.0, best_end - min_allowed)
            if (best_end - best_start) < min_allowed:
                best_end = min(total_duration, best_start + min_allowed)
        elif curr_dur > max_allowed:
            best_start = max(0.0, best_end - max_allowed)

        # Ensure start and end are strictly within [0.0, total_duration]
        best_start = max(0.0, min(best_start, total_duration - 2.0))
        best_end = min(total_duration, max(best_end, best_start + 2.0))

        return {
            "cut_start": round(best_start, 2),
            "cut_end": round(best_end, 2),
            "title": title,
            "caption": caption,
            "score": event_context.get("score", 8 if words else 7),
        }
