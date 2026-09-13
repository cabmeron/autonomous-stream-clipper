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

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

logger = logging.getLogger(__name__)

EMOTION_CLASSES = ["joy", "shock", "rage", "despair", "neutral"]
FERPLUS_CLASSES = ["neutral", "happiness", "surprise", "sadness", "anger", "disgust", "fear", "contempt"]
MOBILEFACENET_CLASSES = ["angry", "disgust", "fear", "happy", "neutral", "sad", "surprise"]


class StreamerEmotionService:
    """Tracks streamer facial expression over time, calculates valence/arousal and tilt metrics."""

    def __init__(
        self,
        face_roi: Optional[Dict[str, float]] = None,
        tilt_threshold: float = 65.0,
        euphoria_threshold: float = 75.0,
        model_name: str = "ferplus",
        on_tilt_spike: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_euphoria_spike: Optional[Callable[[Dict[str, Any]], None]] = None,
        fer_model_path: Optional[str] = None,
        ferplus_model_path: Optional[str] = None,
        yunet_model_path: Optional[str] = None,
    ):
        # Default: process full input frame directly (cropping handled by upstream VideoCropNode)
        self.face_roi = face_roi or {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
        self.tilt_threshold = tilt_threshold
        self.euphoria_threshold = euphoria_threshold
        self.model_name = (model_name or "ferplus").lower()
        self.on_tilt_spike = on_tilt_spike
        self.on_euphoria_spike = on_euphoria_spike

        # Rolling emotion time-series history (up to 120 samples = ~2 minutes at 1 Hz)
        self.history: deque = deque(maxlen=120)
        self.latest_metrics: Optional[Dict[str, Any]] = None

        # Tilt tracking state
        self.consecutive_negative_frames = 0
        self.loss_streak_context = 0
        self.bet_escalation_factor = 1.0

        # DNN Model Loading (ONNX Model Zoo FERPlus & PINTO MobileFaceNet)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.ferplus_model_path = ferplus_model_path or os.path.join(
            base_dir, "models", "vision", "emotion-ferplus-8.onnx"
        )
        self.fer_model_path = fer_model_path or os.path.join(
            base_dir, "models", "vision", "facial_expression_recognition_mobilefacenet.onnx"
        )
        self.yunet_model_path = yunet_model_path or os.path.join(
            base_dir, "models", "vision", "face_detection_yunet.onnx"
        )

        self.ferplus_net = None
        self.ort_ferplus_session = None
        self.net = None
        self.face_detector = None

        # 1. Load FERPlus ONNX (cv2.dnn or onnxruntime fallback)
        if _CV2_AVAILABLE and os.path.exists(self.ferplus_model_path):
            try:
                self.ferplus_net = cv2.dnn.readNetFromONNX(self.ferplus_model_path)
                logger.info("[StreamerEmotion] Loaded Emotion FERPlus ONNX via cv2.dnn from %s", self.ferplus_model_path)
            except Exception as e:
                logger.warning("[StreamerEmotion] Failed to load FERPlus ONNX via cv2.dnn: %s", e)

        if self.ferplus_net is None and os.path.exists(self.ferplus_model_path):
            try:
                import onnxruntime as ort
                self.ort_ferplus_session = ort.InferenceSession(self.ferplus_model_path, providers=["CPUExecutionProvider"])
                logger.info("[StreamerEmotion] Loaded Emotion FERPlus ONNX via onnxruntime from %s", self.ferplus_model_path)
            except Exception as e:
                logger.warning("[StreamerEmotion] Failed to load FERPlus ONNX via onnxruntime: %s", e)

        # 2. Load MobileFaceNet ONNX
        if _CV2_AVAILABLE and os.path.exists(self.fer_model_path):
            try:
                self.net = cv2.dnn.readNetFromONNX(self.fer_model_path)
                logger.info("[StreamerEmotion] Loaded MobileFaceNet FER from %s", self.fer_model_path)
            except Exception as e:
                logger.warning("[StreamerEmotion] Failed to load FER ONNX: %s", e)

        # 3. Load YuNet Face Detector
        if _CV2_AVAILABLE and os.path.exists(self.yunet_model_path):
            try:
                self.face_detector = cv2.FaceDetectorYN.create(
                    self.yunet_model_path, "", (320, 320), score_threshold=0.6
                )
                logger.info("[StreamerEmotion] Loaded YuNet face detector from %s", self.yunet_model_path)
            except Exception as e:
                logger.warning("[StreamerEmotion] Failed to load YuNet ONNX: %s", e)

    def set_model(self, model_name: str):
        """Switches active emotion recognition model ('ferplus' or 'mobilefacenet')."""
        if model_name:
            self.model_name = str(model_name).strip().lower()
            logger.info("[StreamerEmotion] Switched emotion recognition engine to: %s", self.model_name)

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
        """Crops image to normalized face region if specified, otherwise passes frame through directly."""
        if (
            self.face_roi.get("x", 0.0) == 0.0
            and self.face_roi.get("y", 0.0) == 0.0
            and self.face_roi.get("w", 1.0) == 1.0
            and self.face_roi.get("h", 1.0) == 1.0
        ):
            return frame
        w, h = frame.size
        x1 = int(self.face_roi["x"] * w)
        y1 = int(self.face_roi["y"] * h)
        box_w = int(self.face_roi["w"] * w)
        box_h = int(self.face_roi["h"] * h)
        return frame.crop((x1, y1, min(w, x1 + box_w), min(h, y1 + box_h)))

    def analyze_face(self, face_img: Image.Image) -> Dict[str, float]:
        """Computes discrete emotion probabilities, valence (-1 to +1), and arousal (0 to 1)."""
        # Primary: FERPlus 8-class if selected (or if MobileFaceNet not available)
        if self.model_name in ("ferplus", "emotion_ferplus", "ferplus_8"):
            if self.ferplus_net is not None or self.ort_ferplus_session is not None:
                try:
                    return self._analyze_face_ferplus(face_img)
                except Exception as e:
                    logger.warning("[StreamerEmotion] FERPlus forward pass failed (%s), trying fallback", e)

        # Secondary: MobileFaceNet 7-class if selected
        if self.net is not None and _CV2_AVAILABLE:
            try:
                return self._analyze_face_dnn(face_img)
            except Exception as e:
                logger.warning("[StreamerEmotion] MobileFaceNet DNN forward pass failed (%s), using heuristic", e)

        # If FERPlus was available and MobileFaceNet wasn't
        if self.ferplus_net is not None or self.ort_ferplus_session is not None:
            try:
                return self._analyze_face_ferplus(face_img)
            except Exception:
                pass

        return self._analyze_face_heuristic(face_img)

    def _analyze_face_ferplus(self, face_img: Image.Image) -> Dict[str, float]:
        """Runs Microsoft Emotion FERPlus ONNX (8-class) with optional YuNet face tracking."""
        # Auto-center with YuNet if OpenCV and detector are available
        if _CV2_AVAILABLE and self.face_detector is not None:
            try:
                rgb_img = face_img.convert("RGB")
                img_np = np.array(rgb_img)
                h, w, _ = img_np.shape
                if w >= 20 and h >= 20:
                    self.face_detector.setInputSize((w, h))
                    _, faces = self.face_detector.detect(img_np)
                    if faces is not None and len(faces) > 0:
                        box = faces[0]
                        fx, fy, fw, fh = int(box[0]), int(box[1]), int(box[2]), int(box[3])
                        fx1, fy1 = max(0, fx), max(0, fy)
                        fx2, fy2 = min(w, fx + fw), min(h, fy + fh)
                        if fx2 - fx1 >= 10 and fy2 - fy1 >= 10:
                            face_img = Image.fromarray(img_np[fy1:fy2, fx1:fx2])
            except Exception as e:
                logger.debug("[StreamerEmotion] Face detector pass failed: %s", e)

        # Preprocess for FERPlus: 64x64 Grayscale, raw float32 scale [0..255]
        # PIL handles grayscale conversion and resize cleanly without requiring OpenCV
        gray_img = face_img.convert("L").resize((64, 64), Image.Resampling.BILINEAR)
        blob = np.array(gray_img, dtype=np.float32).reshape(1, 1, 64, 64)

        if self.ferplus_net is not None:
            self.ferplus_net.setInput(blob)
            logits = self.ferplus_net.forward()[0]
        elif self.ort_ferplus_session is not None:
            input_name = self.ort_ferplus_session.get_inputs()[0].name
            logits = self.ort_ferplus_session.run(None, {input_name: blob})[0][0]
        else:
            raise RuntimeError("No FERPlus inference backend available")

        # Softmax over 8 classes
        exp_scores = np.exp(logits - np.max(logits))
        raw_probs = exp_scores / (np.sum(exp_scores) or 1.0)

        # FERPlus classes:
        # 0: neutral, 1: happiness, 2: surprise, 3: sadness, 4: anger, 5: disgust, 6: fear, 7: contempt
        ferplus_dict = {
            FERPLUS_CLASSES[i]: round(float(raw_probs[i]), 4)
            for i in range(len(FERPLUS_CLASSES))
        }

        # Valence (-1.0 negative to +1.0 positive)
        valence = (
            (ferplus_dict["happiness"] * 1.0)
            + (ferplus_dict["surprise"] * 0.3)
            + (ferplus_dict["neutral"] * 0.0)
            - (ferplus_dict["sadness"] * 0.6)
            - (ferplus_dict["contempt"] * 0.7)
            - (ferplus_dict["disgust"] * 0.8)
            - (ferplus_dict["fear"] * 0.8)
            - (ferplus_dict["anger"] * 0.9)
        )
        valence = max(-1.0, min(1.0, round(valence, 3)))

        # Arousal (0.0 calm to 1.0 hyperactive)
        arousal = (
            (ferplus_dict["happiness"] * 0.85)
            + (ferplus_dict["anger"] * 0.95)
            + (ferplus_dict["surprise"] * 0.90)
            + (ferplus_dict["fear"] * 0.80)
            + (ferplus_dict["contempt"] * 0.60)
            + (ferplus_dict["disgust"] * 0.50)
            + (ferplus_dict["sadness"] * 0.35)
            + (ferplus_dict["neutral"] * 0.10)
        )
        arousal = max(0.0, min(1.0, round(arousal, 3)))

        raw_logits_dict = {
            FERPLUS_CLASSES[i]: round(float(logits[i]), 3)
            for i in range(len(FERPLUS_CLASSES))
        }

        res = dict(ferplus_dict)
        res["raw_logits"] = raw_logits_dict
        res["valence"] = valence
        res["arousal"] = arousal
        # Backward-compatible mapped keys for legacy heuristics
        res["joy"] = ferplus_dict["happiness"]
        res["shock"] = ferplus_dict["surprise"]
        res["rage"] = round(ferplus_dict["anger"] + (0.5 * ferplus_dict["contempt"]) + (0.3 * ferplus_dict["disgust"]), 4)
        res["despair"] = round(ferplus_dict["sadness"] + (0.4 * ferplus_dict["fear"]), 4)
        return res

    def _analyze_face_dnn(self, face_img: Image.Image) -> Dict[str, float]:
        """Runs MobileFaceNet FER with YuNet face tracking."""
        rgb_img = face_img.convert("RGB")
        img_np = np.array(rgb_img)
        h, w, _ = img_np.shape

        crop_for_fer = img_np

        # Auto-center with YuNet if available
        if self.face_detector is not None and w >= 20 and h >= 20:
            try:
                self.face_detector.setInputSize((w, h))
                _, faces = self.face_detector.detect(img_np)
                if faces is not None and len(faces) > 0:
                    box = faces[0]
                    fx, fy, fw, fh = int(box[0]), int(box[1]), int(box[2]), int(box[3])
                    fx1, fy1 = max(0, fx), max(0, fy)
                    fx2, fy2 = min(w, fx + fw), min(h, fy + fh)
                    if fx2 - fx1 >= 10 and fy2 - fy1 >= 10:
                        crop_for_fer = img_np[fy1:fy2, fx1:fx2]
            except Exception as e:
                logger.debug("[StreamerEmotion] Face detector pass failed: %s", e)

        # Preprocess for MobileFaceNet FER: 112x112 RGB
        blob = cv2.dnn.blobFromImage(
            crop_for_fer,
            scalefactor=1.0,
            size=(112, 112),
            mean=(0, 0, 0),
            swapRB=False,
            crop=False
        )
        self.net.setInput(blob)
        logits = self.net.forward()[0]
        exp_scores = np.exp(logits - np.max(logits))
        raw_probs = exp_scores / (np.sum(exp_scores) or 1.0)

        # MobileFaceNet classes:
        # 0: angry, 1: disgust, 2: fear, 3: happy, 4: neutral, 5: sad, 6: surprise
        p_angry = float(raw_probs[0])
        p_disgust = float(raw_probs[1])
        p_fear = float(raw_probs[2])
        p_happy = float(raw_probs[3])
        p_neutral = float(raw_probs[4])
        p_sad = float(raw_probs[5])
        p_surprise = float(raw_probs[6])

        # Map to application EMOTION_CLASSES: ["joy", "shock", "rage", "despair", "neutral"]
        probs = {
            "joy": p_happy,
            "shock": p_surprise,
            "rage": p_angry + (0.4 * p_disgust),
            "despair": p_sad + (0.4 * p_fear),
            "neutral": p_neutral,
        }
        total = sum(probs.values()) or 1.0
        probs = {k: round(v / total, 4) for k, v in probs.items()}

        # If flat synthetic or low confidence, blend with optical heuristic
        top_conf = max(probs.values())
        if top_conf < 0.35:
            heur = self._analyze_face_heuristic(face_img)
            for k in EMOTION_CLASSES:
                probs[k] = round(0.5 * probs[k] + 0.5 * heur.get(k, 0.2), 4)
            total = sum(probs.values()) or 1.0
            probs = {k: round(v / total, 4) for k, v in probs.items()}

        valence = (
            (probs["joy"] * 1.0)
            + (probs["neutral"] * 0.0)
            + (probs["shock"] * 0.2)
            - (probs["despair"] * 0.8)
            - (probs["rage"] * 1.0)
        )
        valence = max(-1.0, min(1.0, round(valence, 3)))

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
        probs["raw_logits"] = {
            MOBILEFACENET_CLASSES[i]: round(float(logits[i]), 3)
            for i in range(len(MOBILEFACENET_CLASSES))
        }
        return probs

    def _analyze_face_heuristic(self, face_img: Image.Image) -> Dict[str, float]:
        """Fallback optical feature processing."""
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
        """Computes continuous Tilt Index (0-100) combining anger, contempt, despair, loss streaks, and bet chasing."""
        if "contempt" in emotion_probs or "anger" in emotion_probs:
            anger = emotion_probs.get("anger", 0.0)
            contempt = emotion_probs.get("contempt", 0.0)
            disgust = emotion_probs.get("disgust", 0.0)
            sadness = emotion_probs.get("sadness", 0.0)
            arousal = emotion_probs.get("arousal", 0.0)
            emotion_tilt = (anger * 35.0) + (contempt * 25.0) + (disgust * 15.0) + (sadness * 15.0) + (arousal * 10.0)
        else:
            rage = emotion_probs.get("rage", 0.0)
            despair = emotion_probs.get("despair", 0.0)
            arousal = emotion_probs.get("arousal", 0.0)
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
        happy_prob = probs.get("happiness", probs.get("joy", 0.0))
        euphoria_score = round(min(100.0, happy_prob * 100.0 * probs.get("arousal", 0.5) * 1.2), 1)

        # Top discrete emotion label & distribution based on active model
        if self.model_name in ("ferplus", "emotion_ferplus", "ferplus_8") and "contempt" in probs:
            discrete_emotions = {k: probs[k] for k in FERPLUS_CLASSES if k in probs}
        else:
            discrete_emotions = {k: probs[k] for k in EMOTION_CLASSES if k in probs}
            if not discrete_emotions:
                discrete_emotions = {k: probs[k] for k in FERPLUS_CLASSES if k in probs}

        top_emotion = max(discrete_emotions, key=discrete_emotions.get) if discrete_emotions else "neutral"
        top_confidence = discrete_emotions.get(top_emotion, 0.0)

        t1 = time.perf_counter()
        latency_ms = round((t1 - t0) * 1000.0, 2)

        # Generate base64 thumbnail of the cropped face/ROI for node previews
        face_thumbnail_b64 = ""
        try:
            import io
            import base64
            f_buf = io.BytesIO()
            tw = min(320, face_img.width)
            th = min(240, face_img.height)
            thumb = face_img.resize((tw, th)) if (face_img.width != tw or face_img.height != th) else face_img
            thumb.convert("RGB").save(f_buf, format="JPEG", quality=75)
            face_thumbnail_b64 = "data:image/jpeg;base64," + base64.b64encode(f_buf.getvalue()).decode("utf-8")
        except Exception as e:
            logger.debug("[StreamerEmotion] Failed to encode face thumbnail: %s", e)

        # Determine spike triggers
        is_tilt_spike = tilt_score >= self.tilt_threshold and (
            top_emotion in ("anger", "rage", "contempt", "disgust", "despair", "sadness")
        )
        is_euphoria_spike = euphoria_score >= self.euphoria_threshold and (
            top_emotion in ("happiness", "joy")
        )
        is_shock_spike = (top_emotion in ("surprise", "shock") and top_confidence >= 0.75)
        happy_val = round(float(probs.get("happiness", probs.get("joy", 0.0))), 4)
        angry_val = round(float(probs.get("anger", probs.get("rage", 0.0))), 4)
        surprise_val = round(float(probs.get("surprise", probs.get("shock", 0.0))), 4)
        sad_val = round(float(probs.get("sadness", probs.get("despair", 0.0))), 4)
        fear_val = round(float(probs.get("fear", 0.0)), 4)
        disgust_val = round(float(probs.get("disgust", 0.0)), 4)
        neutral_val = round(float(probs.get("neutral", 0.0)), 4)
        contempt_val = round(float(probs.get("contempt", 0.0)), 4)

        metrics = {
            "top_emotion": top_emotion,
            "confidence": top_confidence,
            "emotions": discrete_emotions,
            "raw_logits": probs.get("raw_logits", {}),
            "valence": probs["valence"],
            "arousal": probs["arousal"],
            "tilt_score": tilt_score,
            "euphoria_score": euphoria_score,
            "happy": happy_val,
            "angry": angry_val,
            "surprise": surprise_val,
            "sad": sad_val,
            "fear": fear_val,
            "disgust": disgust_val,
            "neutral": neutral_val,
            "contempt": contempt_val,
            "is_tilt_spike": is_tilt_spike,
            "is_euphoria_spike": is_euphoria_spike,
            "is_shock_spike": is_shock_spike,
            "latency_ms": latency_ms,
            "face_roi": self.face_roi,
            "face_thumbnail_b64": face_thumbnail_b64,
            "model": self.model_name,
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

    def get_metric_value(self, metric_name: str) -> float:
        """Retrieves a single scalar metric value by port or metric ID."""
        if not self.latest_metrics:
            return 0.0
        m = self.latest_metrics
        key = metric_name.lower().strip()
        if key in m and isinstance(m[key], (int, float)):
            return float(m[key])
        if key in ("happy", "happiness", "joy"):
            return float(m.get("happy", m.get("emotions", {}).get("happiness", m.get("emotions", {}).get("joy", 0.0))))
        if key in ("angry", "anger", "rage"):
            return float(m.get("angry", m.get("emotions", {}).get("anger", m.get("emotions", {}).get("rage", 0.0))))
        if key in ("surprise", "shock"):
            return float(m.get("surprise", m.get("emotions", {}).get("surprise", m.get("emotions", {}).get("shock", 0.0))))
        if key in ("sad", "sadness", "despair"):
            return float(m.get("sad", m.get("emotions", {}).get("sadness", m.get("emotions", {}).get("despair", 0.0))))
        if key in ("fear",):
            return float(m.get("fear", m.get("emotions", {}).get("fear", 0.0)))
        if key in ("disgust",):
            return float(m.get("disgust", m.get("emotions", {}).get("disgust", 0.0)))
        if key in ("neutral",):
            return float(m.get("neutral", m.get("emotions", {}).get("neutral", 0.0)))
        if key in ("contempt",):
            return float(m.get("contempt", m.get("emotions", {}).get("contempt", 0.0)))
        if key in ("tilt_score", "tilt"):
            return float(m.get("tilt_score", 0.0))
        if key in ("euphoria_score", "euphoria"):
            return float(m.get("euphoria_score", 0.0))
        if key in ("valence",):
            return float(m.get("valence", 0.0))
        if key in ("arousal",):
            return float(m.get("arousal", 0.0))
        if key in ("confidence",):
            return float(m.get("confidence", 0.0))
        return 0.0

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
