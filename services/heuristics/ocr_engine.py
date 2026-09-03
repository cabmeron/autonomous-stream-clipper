import io
import logging
import re
import subprocess
import time
from typing import Callable, Optional, Tuple
from PIL import Image

logger = logging.getLogger(__name__)


class BoundedRegionOCR:
    """Extracts video frames at 1 FPS, crops to a region of interest, and parses win/PnL telemetry."""

    def __init__(
        self,
        roi: Optional[dict] = None,
        win_multiplier_threshold: float = 100.0,
        on_trigger_callback: Optional[Callable[[float, float], None]] = None,
    ):
        # Normalized coordinates: x, y, width, height (values between 0.0 and 1.0)
        self.roi = roi or {"x": 0.70, "y": 0.85, "w": 0.28, "h": 0.12}
        self.win_multiplier_threshold = win_multiplier_threshold
        self.on_trigger = on_trigger_callback

        self.last_balance: Optional[float] = None
        self.current_balance: Optional[float] = None
        self.pnl_delta: float = 0.0
        self.current_multiplier: float = 1.0
        self.is_triggered: bool = False
        self.last_run_time: float = 0.0

        # Lazy-loaded OCR engine
        self._ocr_engine = None
        self._engine_type = "none"
        self._init_engine()

    def _init_engine(self):
        """Attempts to load PaddleOCR or falls back gracefully."""
        try:
            from paddleocr import PaddleOCR
            self._ocr_engine = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)
            self._engine_type = "paddleocr"
            logger.info("[OCR] Initialized PaddleOCR engine successfully.")
            return
        except Exception as e:
            logger.debug("[OCR] PaddleOCR not available (%s), trying pytesseract...", e)

        try:
            import pytesseract
            self._ocr_engine = pytesseract
            self._engine_type = "tesseract"
            logger.info("[OCR] Initialized pytesseract fallback engine.")
            return
        except Exception as e:
            logger.warning("[OCR] Neither PaddleOCR nor pytesseract available (%s). Using mock/regex parser.", e)
            self._engine_type = "regex_only"

    def extract_frame(self, media_path: str, offset_from_end: float = 1.0) -> Optional[Image.Image]:
        """Extracts a single frame from media as a PIL Image."""
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-sseof", f"-{offset_from_end}",
            "-i", media_path,
            "-vframes", "1",
            "-f", "image2pipe",
            "-vcodec", "png",
            "-"
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True)
            if res.stdout:
                return Image.open(io.BytesIO(res.stdout)).convert("RGB")
        except Exception as err:
            logger.debug("[OCR] Frame extraction failed on %s: %s", media_path, err)
        return None

    def crop_roi(self, image: Image.Image) -> Image.Image:
        """Crops image to the configured Region of Interest."""
        w, h = image.size
        x1 = int(self.roi.get("x", 0.0) * w)
        y1 = int(self.roi.get("y", 0.0) * h)
        x2 = min(w, x1 + int(self.roi.get("w", 1.0) * w))
        y2 = min(h, y1 + int(self.roi.get("h", 1.0) * h))
        return image.crop((x1, y1, x2, y2))

    def recognize_text(self, cropped_image: Image.Image) -> str:
        """Runs OCR on cropped image and returns extracted string."""
        if self._engine_type == "paddleocr":
            try:
                import numpy as np
                img_np = np.array(cropped_image)
                results = self._ocr_engine.ocr(img_np, cls=False)
                texts = []
                if results and results[0]:
                    for line in results[0]:
                        texts.append(line[1][0])
                return " ".join(texts)
            except Exception as e:
                logger.error("[OCR] PaddleOCR recognition error: %s", e)
                return ""
        elif self._engine_type == "tesseract":
            try:
                return self._ocr_engine.image_to_string(cropped_image)
            except Exception as e:
                logger.error("[OCR] Tesseract recognition error: %s", e)
                return ""
        return ""

    @staticmethod
    def parse_values(text: str) -> Tuple[Optional[float], float]:
        """Extracts balance/pnl and multiplier values from text.

        Returns (balance, multiplier).
        """
        multiplier = 1.0
        balance = None

        # Look for multipliers like 250x, 1000X, x50
        mult_match = re.search(r'(?:x|\b)(\d+(?:\.\d+)?)\s*x\b', text, re.IGNORECASE)
        if mult_match:
            try:
                multiplier = float(mult_match.group(1))
            except ValueError:
                pass

        # Clean out multiplier string to prevent number collision with currency
        cleaned_text = re.sub(r'(?:x|\b)(\d+(?:\.\d+)?)\s*x\b', '', text, flags=re.IGNORECASE)

        # Look for explicit currency with $ like $1,250.00
        curr_match = re.search(r'\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)', cleaned_text)
        if curr_match:
            try:
                clean_num = curr_match.group(1).replace(",", "")
                balance = float(clean_num)
            except ValueError:
                pass
        else:
            # Fallback to plain numbers like 1,250.00 or 500.25
            num_match = re.search(r'\b([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)\b', cleaned_text)
            if num_match:
                try:
                    clean_num = num_match.group(1).replace(",", "")
                    balance = float(clean_num)
                except ValueError:
                    pass

        return balance, multiplier

    def process_frame(self, image: Image.Image) -> dict:
        """Processes a single image frame, updating balance and multiplier heuristics."""
        cropped = self.crop_roi(image)
        raw_text = self.recognize_text(cropped)
        balance, multiplier = self.parse_values(raw_text)

        self.current_multiplier = multiplier
        if balance is not None:
            if self.last_balance is not None:
                self.pnl_delta = round(balance - self.last_balance, 2)
            self.last_balance = self.current_balance
            self.current_balance = balance

        spike_flag = self.current_multiplier >= self.win_multiplier_threshold

        if spike_flag and not self.is_triggered:
            self.is_triggered = True
            logger.info(
                "[OCR] WIN MULTIPLIER SPIKE DETECTED: %.1fx (balance=$%.2f, delta=$%.2f)",
                self.current_multiplier,
                self.current_balance or 0.0,
                self.pnl_delta,
            )
            if self.on_trigger:
                try:
                    self.on_trigger(self.current_multiplier, self.pnl_delta)
                except Exception as e:
                    logger.error("[OCR] on_trigger callback error: %s", e)
        elif not spike_flag:
            self.is_triggered = False

        return {
            "balance": self.current_balance,
            "pnl_delta": self.pnl_delta,
            "multiplier": self.current_multiplier,
            "raw_text": raw_text.strip(),
            "is_triggered": self.is_triggered,
        }

    def process_segment(self, segment_path: str) -> Optional[dict]:
        """Rate-limited processing of media segments at ~1 FPS."""
        now = time.time()
        if now - self.last_run_time < 0.9:
            return None
        self.last_run_time = now

        frame = self.extract_frame(segment_path)
        if frame is not None:
            return self.process_frame(frame)
        return None
