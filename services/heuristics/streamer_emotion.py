"""Streamer Facial Emotion Recognition and Tilt Tracking Engine.

Analyzes streamer facecam frames to track emotional valence, arousal, discrete emotions
(joy, rage, shock, despair, neutral), and computes a continuous Tilt Index (0-100).
"""

from collections import deque
import logging
import math
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

EMOTION_CLASSES = ["joy", "shock", "rage", "despair", "neutral"]


class StreamerEmotionService:
    """Tracks streamer facial expression over time, calculates valence/arousal and tilt metrics."""

    def __init__(
        self,
        face_roi: Optional[Dict[str, float]] = None,
        tilt_threshold: float = 65.0,
        euphoria_threshold: float = 75.0,
        on_tilt_spike: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_euphoria_spike: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        # Default facecam ROI: top-left or bottom-left depending on stream layout
        self.face_roi = face_roi or {"x": 0.02, "y": 0.05, "w": 0.22, "h": 0.28}
        self.tilt_threshold = tilt_threshold
        self.euphoria_threshold = euphoria_threshold
        self.on_tilt_spike = on_tilt_spike
        self.on_euphoria_spike = on_euphoria_spike

        # Rolling emotion time-series history (up to 120 samples = ~2 minutes at 1 Hz)
        self.history: deque = deque(maxlen=120)
        self.latest_metrics: Optional[Dict[str, Any]] = None

        # Tilt tracking state
        self.consecutive_negative_frames = 0
        self.loss_streak_context = 0
        self.bet_escalation_factor = 1.0

    def update_roi(self, x: float, y: float, w: float, h: float):
        """Hot-reloads facecam bounding box coordinates."""
        self.face_roi = {
            "x": max(0.0, min(1.0, float(x))),
            "y": max(0.0, min(1.0, float(y))),
            "w": max(0.05, min(1.0, float(w))),
            "h": max(0.05, min(1.0, float(h))),
        }
        logger.info("[StreamerEmotion] Updated facecam ROI: %s", self.face_roi)

    def crop_face(self, frame: Image.Image) -> Image.Image:
        """Crops image to normalized facecam region."""
        w, h = frame.size
        x1 = int(self.face_roi["x"] * w)
        y1 = int(self.face_roi["y"] * h)
        box_w = int(self.face_roi["w"] * w)
        box_h = int(self.face_roi["h"] * h)
        return frame.crop((x1, y1, min(w, x1 + box_w), min(h, y1 + box_h)))

    def analyze_face(self, face_img: Image.Image) -> Dict[str, float]:
        """Computes discrete emotion probabilities, valence (-1 to +1), and arousal (0 to 1)."""
        # Resize to standardized patch for optical feature processing
        thumb = face_img.resize((64, 64)).convert("RGB")
        arr = np.array(thumb, dtype=np.float32)

        # Extract facial optical features
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        brightness = float(arr.mean())
        color_variance = float(arr.std())
        redness_ratio = float((r.mean() + 1.0) / (g.mean() + b.mean() + 2.0) * 2.0)

        # Vertical slice contrast (mouth opening proxy: lower third gradient)
        lower_third = arr[42:64, 16:48, :]
        mouth_opening_contrast = float(lower_third.std())

        # Upper slice contrast (eyes / eyebrows gradient)
        upper_third = arr[12:30, 16:48, :]
        brow_contrast = float(upper_third.std())

        # Emotion score heuristics
        raw_scores = {
            "neutral": 2.0,
            "joy": 0.5,
            "shock": 0.5,
            "rage": 0.5,
            "despair": 0.5,
        }

        # 1. Joy / Euphoria: bright warm facial illumination, high mouth curvature contrast
        if brightness > 115 and mouth_opening_contrast > 28:
            raw_scores["joy"] += 3.5 + min(2.0, mouth_opening_contrast / 20.0)

        # 2. Shock / Disbelief: high eye-brow contrast, wide mouth opening, rapid contrast shifts
        if mouth_opening_contrast > 35 and brow_contrast > 25:
            raw_scores["shock"] += 4.0 + min(2.5, brow_contrast / 15.0)

        # 3. Rage / Anger: increased facial flush (redness ratio), intense brow furrowing
        if redness_ratio > 1.08 or (brow_contrast > 30 and brightness < 120):
            raw_scores["rage"] += 3.2 + (redness_ratio - 1.0) * 8.0

        # 4. Despair / Sadness: low brightness, slouched/subdued color variance
        if brightness < 90 and mouth_opening_contrast < 20:
            raw_scores["despair"] += 3.5 + (90.0 - brightness) * 0.05

        # 5. Neutral: balanced moderate features
        if 85 <= brightness <= 125 and mouth_opening_contrast < 26:
            raw_scores["neutral"] += 2.5

        # Softmax normalization
        exp_scores = {k: math.exp(v) for k, v in raw_scores.items()}
        total = sum(exp_scores.values()) or 1.0
        probs = {k: round(v / total, 4) for k, v in exp_scores.items()}

        # Compute Valence: (-1.0 negative to +1.0 positive)
        # Positive: Joy (+1.0), Neutral (0.0)
        # Negative: Despair (-0.8), Rage (-1.0), Shock (-0.2 to +0.4 depending on joy)
        valence = (
            (probs["joy"] * 1.0)
            + (probs["neutral"] * 0.0)
            + (probs["shock"] * 0.2)
            - (probs["despair"] * 0.8)
            - (probs["rage"] * 1.0)
        )
        valence = max(-1.0, min(1.0, round(valence, 3)))

        # Compute Arousal: (0.0 calm to 1.0 hyperactive)
        arousal = (
            (probs["joy"] * 0.85)
            + (probs["rage"] * 0.95)
            + (probs["shock"] * 0.90)
            + (probs["despair"] * 0.35)
            + (probs["neutral"] * 0.10)
        )
        arousal = max(0.0, min(1.0, round(arousal, 3)))

        probs["valence"] = valence
        probs["arousal"] = arousal
        return probs

    def update_gambling_context(self, loss_streak: int = 0, bet_escalation: float = 1.0):
        """Supplies live gambling context (loss streaks, bet sizing) to correlate with emotion."""
        self.loss_streak_context = max(0, int(loss_streak))
        self.bet_escalation_factor = max(0.5, float(bet_escalation))

    def compute_tilt_score(self, emotion_probs: Dict[str, float]) -> float:
        """Computes continuous Tilt Index (0-100) combining rage, despair, loss streaks, and bet chasing."""
        rage = emotion_probs.get("rage", 0.0)
        despair = emotion_probs.get("despair", 0.0)
        arousal = emotion_probs.get("arousal", 0.0)

        # Baseline emotional tilt (up to 45 pts)
        emotion_tilt = (rage * 35.0) + (despair * 20.0) + (arousal * 10.0)

        # Loss streak pressure (up to 30 pts: 5 losses = 15 pts, 10+ losses = 30 pts)
        streak_tilt = min(30.0, self.loss_streak_context * 3.0)

        # Bet chasing escalation (up to 25 pts: doubling bet = 15 pts, 3x+ = 25 pts)
        escalation_tilt = 0.0
        if self.bet_escalation_factor > 1.3 and self.loss_streak_context >= 2:
            escalation_tilt = min(25.0, (self.bet_escalation_factor - 1.0) * 15.0)

        tilt_index = round(min(100.0, max(0.0, emotion_tilt + streak_tilt + escalation_tilt)), 1)
        return tilt_index

    def process_frame(self, full_frame: Image.Image) -> Dict[str, Any]:
        """Runs the complete emotion & tilt tracking pipeline on a video frame."""
        t0 = time.perf_counter()
        face_img = self.crop_face(full_frame)
        probs = self.analyze_face(face_img)

        tilt_score = self.compute_tilt_score(probs)
        euphoria_score = round(min(100.0, probs.get("joy", 0.0) * 100.0 * probs.get("arousal", 0.5) * 1.2), 1)

        # Top discrete emotion label
        discrete_emotions = {k: probs[k] for k in EMOTION_CLASSES if k in probs}
        top_emotion = max(discrete_emotions, key=discrete_emotions.get)
        top_confidence = discrete_emotions[top_emotion]

        t1 = time.perf_counter()
        latency_ms = round((t1 - t0) * 1000.0, 2)

        # Determine spike triggers
        is_tilt_spike = tilt_score >= self.tilt_threshold and (top_emotion in ("rage", "despair"))
        is_euphoria_spike = euphoria_score >= self.euphoria_threshold and (top_emotion == "joy")
        is_shock_spike = probs.get("shock", 0.0) >= 0.65

        metrics = {
            "top_emotion": top_emotion,
            "confidence": top_confidence,
            "emotions": discrete_emotions,
            "valence": probs["valence"],
            "arousal": probs["arousal"],
            "tilt_score": tilt_score,
            "euphoria_score": euphoria_score,
            "is_tilt_spike": is_tilt_spike,
            "is_euphoria_spike": is_euphoria_spike,
            "is_shock_spike": is_shock_spike,
            "latency_ms": latency_ms,
            "face_roi": self.face_roi,
            "timestamp": time.time(),
        }

        self.latest_metrics = metrics
        self.history.append({
            "t": metrics["timestamp"],
            "valence": metrics["valence"],
            "arousal": metrics["arousal"],
            "tilt": metrics["tilt_score"],
            "top_emotion": metrics["top_emotion"],
        })

        if is_tilt_spike and self.on_tilt_spike:
            try:
                self.on_tilt_spike(metrics)
            except Exception as e:
                logger.error("[StreamerEmotion] Error in tilt spike callback: %s", e)

        if is_euphoria_spike and self.on_euphoria_spike:
            try:
                self.on_euphoria_spike(metrics)
            except Exception as e:
                logger.error("[StreamerEmotion] Error in euphoria spike callback: %s", e)

        return metrics
