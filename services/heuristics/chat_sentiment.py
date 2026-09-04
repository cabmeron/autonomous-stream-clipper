import datetime
import re
import time
from collections import Counter
from typing import Dict, List, Optional
import uuid


# Twitch emote and slang lexicon mapped to vibe categories
EMOTE_VIBES: Dict[str, List[str]] = {
    "HYPE": [
        "pog", "pogchamp", "poggers", "pogu", "w", "letsgo", "let's go",
        "hypers", "holy", "insane", "sheesh", "clutch", "goat", "ez",
        "gigachad", "hype", "banger"
    ],
    "LAUGHTER": [
        "kekw", "lul", "lulw", "omegalul", "lol", "lmao", "haha", "hahaha",
        "icant", "i can't", "rofl", "xd", "lmfao", "pepelaugh", "kek"
    ],
    "SUSPENSE": [
        "monkas", "monkaw", "panic", "yikes", "wtf", "what", "wut", "huh",
        "omg", "no way", "wait", "stress", "chills"
    ],
    "TILT": [
        "babyrage", "rage", "trash", "throwing", "so bad", "unlucky", "rigged",
        "choke", "malding", "diff", "tilted", "horrible", "dogwater"
    ],
    "DEFEAT": [
        "sadge", "biblethump", "feelsbadman", "nooo", "rip", "f", "pain",
        "down bad", "l", "over", "it's over", "cooked"
    ],
    "WHOLESOME": [
        "feelsgoodman", "<3", "heart", "gg", "ggs", "w streamer", "ayaya", "love",
        "wholesome", "smile", "salute"
    ]
}

VIBE_CONFIG: Dict[str, Dict[str, str]] = {
    "HYPE": {"emoji": "🔥", "color": "#22c55e", "label": "Hype & Excitement"},
    "LAUGHTER": {"emoji": "😂", "color": "#eab308", "label": "Chat in Hysterics"},
    "SUSPENSE": {"emoji": "😬", "color": "#a855f7", "label": "High Tension / Panic"},
    "TILT": {"emoji": "🤬", "color": "#ef4444", "label": "Salt & Malding"},
    "DEFEAT": {"emoji": "💀", "color": "#64748b", "label": "Defeat & Choke"},
    "WHOLESOME": {"emoji": "💖", "color": "#ec4899", "label": "Wholesome & Support"},
    "CHATTING": {"emoji": "💬", "color": "#38bdf8", "label": "Casual Discussion"},
    "QUIET": {"emoji": "💤", "color": "#475569", "label": "Quiet / Low Traffic"},
}


class ChatSentimentAnalyzer:
    """Analyzes a 60-second window of Twitch chat messages to produce sentiment descriptors and metrics."""

    def __init__(self):
        # Inverted index for fast O(1) keyword-to-vibe lookup
        self._keyword_to_vibe: Dict[str, str] = {}
        for vibe, keywords in EMOTE_VIBES.items():
            for kw in keywords:
                self._keyword_to_vibe[kw.lower()] = vibe

    def analyze_window(
        self,
        messages: List[Dict],
        channel: str,
        window_start: Optional[float] = None,
        window_end: Optional[float] = None,
    ) -> Dict:
        """Analyzes a list of raw message dicts from a 60-second window."""
        now = time.time()
        w_end = window_end or now
        w_start = window_start or (w_end - 60.0)

        dt = datetime.datetime.fromtimestamp(w_end)
        timestamp_str = dt.strftime("%H:%M:%S")

        total_msgs = len(messages)
        velocity = round(total_msgs / 60.0, 2)

        if total_msgs == 0:
            config = VIBE_CONFIG["QUIET"]
            return {
                "id": str(uuid.uuid4()),
                "channel": channel.lower(),
                "window_start": w_start,
                "window_end": w_end,
                "timestamp_str": timestamp_str,
                "vibe": "QUIET",
                "emoji": config["emoji"],
                "descriptor": f"{config['emoji']} Quiet / Inactive · 0.0 msg/s",
                "score": 0.0,
                "velocity": 0.0,
                "message_count": 0,
                "top_emotes": [],
                "color": config["color"],
            }

        # Track category frequencies & emote frequencies
        vibe_counts: Counter = Counter()
        emote_counts: Counter = Counter()

        total_caps = 0
        total_alpha = 0
        exclamation_count = 0
        question_count = 0

        for m in messages:
            text = m.get("text", "")
            exclamation_count += text.count("!")
            question_count += text.count("?")

            for char in text:
                if char.isalpha():
                    total_alpha += 1
                    if char.isupper():
                        total_caps += 1

            lower_text = text.lower()
            tokens = re.findall(r"[\w'<3]+|[?!]+", lower_text)

            # Check individual tokens and two-word phrases
            matched_vibes_in_msg = set()
            for token in tokens:
                if token in self._keyword_to_vibe:
                    vb = self._keyword_to_vibe[token]
                    matched_vibes_in_msg.add(vb)
                    emote_counts[token.upper()] += 1

            # Check multi-word phrases (e.g. "let's go", "no way", "so bad", "down bad")
            for kw, vb in self._keyword_to_vibe.items():
                if " " in kw and kw in lower_text:
                    matched_vibes_in_msg.add(vb)
                    emote_counts[kw.upper()] += 1

            for vb in matched_vibes_in_msg:
                vibe_counts[vb] += 1

        caps_ratio = (total_caps / max(1, total_alpha)) if total_alpha > 0 else 0.0

        # Determine dominant vibe
        top_vibe = "CHATTING"
        vibe_score = 0.5  # Neutral baseline

        if vibe_counts:
            dominant_category, highest_count = vibe_counts.most_common(1)[0]
            # Minimum prevalence required for emotional category (at least 15% or >= 3 occurrences)
            if highest_count >= 3 or (highest_count / total_msgs) >= 0.15:
                top_vibe = dominant_category

        # Intensity scoring combining velocity and typography
        arousal = min(1.0, (velocity / 10.0) * 0.5 + caps_ratio * 0.3 + min(1.0, exclamation_count / max(1, total_msgs)) * 0.2)
        score = round(arousal, 2)

        config = VIBE_CONFIG.get(top_vibe, VIBE_CONFIG["CHATTING"])
        top_emotes = [emote for emote, _ in emote_counts.most_common(3)]
        emotes_str = f" ({', '.join(top_emotes)})" if top_emotes else ""

        # Craft human-readable descriptor
        if top_vibe == "HYPE":
            descriptor = f"🔥 {config['label']}{emotes_str} · {velocity:.1f} msg/s"
        elif top_vibe == "LAUGHTER":
            descriptor = f"😂 {config['label']}{emotes_str} · {velocity:.1f} msg/s"
        elif top_vibe == "SUSPENSE":
            descriptor = f"😬 {config['label']}{emotes_str} · {velocity:.1f} msg/s"
        elif top_vibe == "TILT":
            descriptor = f"🤬 {config['label']}{emotes_str} · {velocity:.1f} msg/s"
        elif top_vibe == "DEFEAT":
            descriptor = f"💀 {config['label']}{emotes_str} · {velocity:.1f} msg/s"
        elif top_vibe == "WHOLESOME":
            descriptor = f"💖 {config['label']}{emotes_str} · {velocity:.1f} msg/s"
        else:
            descriptor = f"💬 Casual Chat · {velocity:.1f} msg/s ({total_msgs} msgs)"

        return {
            "id": str(uuid.uuid4()),
            "channel": channel.lower(),
            "window_start": w_start,
            "window_end": w_end,
            "timestamp_str": timestamp_str,
            "vibe": top_vibe,
            "emoji": config["emoji"],
            "descriptor": descriptor,
            "score": score,
            "velocity": velocity,
            "message_count": total_msgs,
            "top_emotes": top_emotes,
            "color": config["color"],
        }
