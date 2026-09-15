"""Stream Spying Keyword Surveillance Heuristic Service for Autonomous Stream Clipper.

Monitors live chat streams and transcribed audio for specified keywords or phrases,
tracking detection velocity and firing discrete downstream trigger pulses upon match.
"""

from collections import deque
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

DEFAULT_KEYWORDS = ["clutch", "ace", "leak", "drama", "ban", "insane", "jackpot"]
DEFAULT_COOLDOWN_SECONDS = 10.0
ALERT_WINDOW_SECONDS = 2.5


class StreamSpyService:
    """Surveillance engine for monitoring keyword appearances in chat and audio streams."""

    def __init__(
        self,
        keywords: Optional[Union[str, List[str]]] = None,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        case_sensitive: bool = False,
        exact_match: bool = False,
        listen_chat: bool = True,
        listen_audio: bool = True,
        enabled: bool = True,
        on_trigger_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.cooldown_seconds = max(0.5, float(cooldown_seconds))
        self.case_sensitive = case_sensitive
        self.exact_match = exact_match
        self.listen_chat = listen_chat
        self.listen_audio = listen_audio
        self.enabled = enabled
        self.on_trigger = on_trigger_callback

        self.keywords: List[str] = []
        self._compiled_regexes: List[re.Pattern] = []
        self.set_keywords(keywords if keywords is not None else DEFAULT_KEYWORDS)

        self.match_count = 0
        self.last_trigger_time = 0.0
        self.last_alert_timestamp = 0.0
        self.last_keyword = ""
        self.last_snippet = ""
        self.last_match_user = ""
        self.last_match_source = ""
        self.last_match_time = 0.0

        # Rolling 60s hit timestamps for calculating keyword velocity (hits/min)
        self.recent_hits = deque()
        # Rolling log of detected events (for UI terminal feed)
        self.recent_matches = deque(maxlen=12)

    def set_keywords(self, keywords: Union[str, List[str]]) -> None:
        """Parses and updates target keywords from a comma-separated string or list."""
        if isinstance(keywords, str):
            raw_list = [k.strip() for k in keywords.split(",") if k.strip()]
        elif isinstance(keywords, (list, tuple, set)):
            raw_list = [str(k).strip() for k in keywords if str(k).strip()]
        else:
            raw_list = list(DEFAULT_KEYWORDS)

        self.keywords = raw_list if raw_list else list(DEFAULT_KEYWORDS)
        self._compile_patterns()
        logger.info("[StreamSpy] Watched keywords updated (%d keywords): %s", len(self.keywords), self.keywords)

    def _compile_patterns(self) -> None:
        """Compiles regex patterns based on case sensitivity and word boundary flags."""
        self._compiled_regexes = []
        flags = 0 if self.case_sensitive else re.IGNORECASE

        for kw in self.keywords:
            escaped = re.escape(kw)
            if self.exact_match:
                pattern = re.compile(rf"\b{escaped}\b", flags)
            else:
                pattern = re.compile(escaped, flags)
            self._compiled_regexes.append(pattern)

    def update_settings(
        self,
        cooldown_seconds: Optional[float] = None,
        case_sensitive: Optional[bool] = None,
        exact_match: Optional[bool] = None,
        listen_chat: Optional[bool] = None,
        listen_audio: Optional[bool] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        """Updates runtime settings and recompiles patterns if matching rules changed."""
        recompile = False
        if cooldown_seconds is not None:
            self.cooldown_seconds = max(0.5, float(cooldown_seconds))
        if case_sensitive is not None and case_sensitive != self.case_sensitive:
            self.case_sensitive = case_sensitive
            recompile = True
        if exact_match is not None and exact_match != self.exact_match:
            self.exact_match = exact_match
            recompile = True
        if listen_chat is not None:
            self.listen_chat = bool(listen_chat)
        if listen_audio is not None:
            self.listen_audio = bool(listen_audio)
        if enabled is not None:
            self.enabled = bool(enabled)

        if recompile:
            self._compile_patterns()

    def check_text(
        self,
        text: str,
        source: str = "chat",
        user: str = "anon",
        timestamp: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Scans arbitrary text for monitored keywords, records hits, and fires triggers if off cooldown."""
        if not self.enabled or not text:
            return None

        # Filter by modality source
        if source == "chat" and not self.listen_chat:
            return None
        if source == "audio" and not self.listen_audio:
            return None

        t = time.time() if timestamp is None else timestamp
        matched_kw: Optional[str] = None

        # Check precompiled patterns
        for i, pattern in enumerate(self._compiled_regexes):
            if pattern.search(text):
                matched_kw = self.keywords[i]
                break

        if not matched_kw:
            return None

        # Match detected!
        self.match_count += 1
        self.recent_hits.append(t)
        self.last_keyword = matched_kw
        self.last_snippet = text[:120].strip()
        self.last_match_user = user
        self.last_match_source = source
        self.last_match_time = t

        # Debounce / Cooldown Check
        elapsed = t - self.last_trigger_time
        is_cooldown = (elapsed < self.cooldown_seconds) and (self.last_trigger_time > 0.0)
        is_trigger = False

        if not is_cooldown:
            self.last_trigger_time = t
            self.last_alert_timestamp = t
            is_trigger = True

        event_data = {
            "keyword": matched_kw,
            "snippet": self.last_snippet,
            "source": source,
            "user": user,
            "timestamp": t,
            "time_str": time.strftime("%H:%M:%S", time.localtime(t)),
            "match_count": self.match_count,
            "is_trigger": is_trigger,
            "is_cooldown": is_cooldown,
        }

        self.recent_matches.append(event_data)

        if is_trigger:
            logger.info(
                "[StreamSpy] KEYWORD DETECTED (%s): '%s' in %s from '%s': \"%s\"",
                source.upper(),
                matched_kw,
                source,
                user,
                self.last_snippet,
            )
            if self.on_trigger:
                try:
                    self.on_trigger(event_data)
                except Exception as err:
                    logger.error("[StreamSpy] Trigger callback error: %s", err)

        return event_data

    def process_chat_message(self, msg: dict) -> Optional[Dict[str, Any]]:
        """Processes a single incoming chat message dictionary ({'user', 'text', 'time'})."""
        text = msg.get("text", "")
        user = msg.get("user", "anon")
        ts = msg.get("time")
        return self.check_text(text, source="chat", user=user, timestamp=ts)

    def process_audio_words(self, words: List[dict]) -> List[Dict[str, Any]]:
        """Processes a sequence of transcribed speech words ({'word', 'start', 'end', ...})."""
        if not self.enabled or not self.listen_audio or not words:
            return []

        matches = []
        phrase = " ".join(w.get("word", "") for w in words).strip()
        if phrase:
            ev = self.check_text(phrase, source="audio", user="streamer")
            if ev:
                matches.append(ev)
        return matches

    def manual_trigger(self, keyword: str = "manual_spy", now: Optional[float] = None) -> Dict[str, Any]:
        """Manually forces an immediate spy alert trigger regardless of cooldown."""
        t = time.time() if now is None else now
        self.match_count += 1
        self.recent_hits.append(t)
        self.last_keyword = keyword
        self.last_snippet = f"Manual Spy Trigger [test:{keyword}]"
        self.last_match_user = "developer"
        self.last_match_source = "manual"
        self.last_match_time = t
        self.last_trigger_time = t
        self.last_alert_timestamp = t

        event_data = {
            "keyword": keyword,
            "snippet": self.last_snippet,
            "source": "manual",
            "user": "developer",
            "timestamp": t,
            "time_str": time.strftime("%H:%M:%S", time.localtime(t)),
            "match_count": self.match_count,
            "is_trigger": True,
            "is_cooldown": False,
        }
        self.recent_matches.append(event_data)
        logger.info("[StreamSpy] Manual spy trigger fired (count=%d)", self.match_count)

        if self.on_trigger:
            try:
                self.on_trigger(event_data)
            except Exception as err:
                logger.error("[StreamSpy] Callback error on manual trigger: %s", err)

        return event_data

    def get_keyword_velocity(self, now: Optional[float] = None) -> float:
        """Calculates keyword appearance velocity (occurrences per minute) over a 60s sliding window."""
        t = time.time() if now is None else now
        cutoff = t - 60.0

        # Purge hits older than 60s
        while self.recent_hits and self.recent_hits[0] < cutoff:
            self.recent_hits.popleft()

        return float(len(self.recent_hits))

    def is_alert_active(self, now: Optional[float] = None) -> bool:
        """Returns True if within the visual pulse/alert window following a trigger."""
        t = time.time() if now is None else now
        return (t - self.last_alert_timestamp) <= ALERT_WINDOW_SECONDS

    def get_telemetry(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Returns real-time telemetry dictionary for visual graphs and monitoring HUDs."""
        t = time.time() if now is None else now
        is_alert = self.is_alert_active(t)
        velocity = self.get_keyword_velocity(t)

        elapsed_since_trig = t - self.last_trigger_time
        in_cooldown = (elapsed_since_trig < self.cooldown_seconds) if self.last_trigger_time > 0 else False
        cooldown_remaining = max(0.0, self.cooldown_seconds - elapsed_since_trig) if in_cooldown else 0.0

        if not self.enabled:
            status = "paused"
        elif is_alert:
            status = "alert"
        elif in_cooldown:
            status = "cooldown"
        else:
            status = "spying"

        return {
            "status": status,
            "enabled": self.enabled,
            "keywords": list(self.keywords),
            "keywords_str": ", ".join(self.keywords),
            "case_sensitive": self.case_sensitive,
            "exact_match": self.exact_match,
            "listen_chat": self.listen_chat,
            "listen_audio": self.listen_audio,
            "cooldown_seconds": self.cooldown_seconds,
            "cooldown_remaining": round(cooldown_remaining, 1),
            "is_cooldown": in_cooldown,
            "is_alert": is_alert,
            "is_trigger": is_alert,
            "match_count": self.match_count,
            "keyword_velocity": round(velocity, 1),
            "last_keyword": self.last_keyword,
            "last_snippet": self.last_snippet,
            "last_match_user": self.last_match_user,
            "last_match_source": self.last_match_source,
            "last_match_time": round(self.last_match_time, 2),
            "recent_matches": list(self.recent_matches),
        }
