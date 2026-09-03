import io
import logging
import re
import subprocess
from typing import Callable, Optional
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Fallback regex patterns for win multiplier and balance tracking
MULTIPLIER_REGEX = re.compile(r"(\d+(?:\.\d+)?)\s*[xX]")
CURRENCY_REGEX = re.compile(r"\$\s*([0-9,]+(?:\.[0-9]{2})?)")


class BoundedRegionOCR:
    """Extracts on-screen casino win multipliers and balance shifts from video frames."""

    def __init__(
        self,
        roi: dict,
        win_multiplier_threshold: float = 100.0,
        on_trigger_callback: Optional[Callable[[float, float], None]] = None,
    ):
        self.roi = roi
        self.win_multiplier_threshold = win_multiplier_threshold
        self.on_trigger = on_trigger_callback

        self.last_balance: Optional[float] = None
        self.current_multiplier: float = 1.0
        self.pnl_delta: float = 0.0

        self._init_ocr()

    def _init_ocr(self):
        self.engine_type = "mock"
        try:
            from paddleocr import PaddleOCR
            self.ocr = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)
            self.engine_type = "paddleocr"
            logger.info("[OCR] Initialized PaddleOCR engine.")
        except Exception:
            try:
                import pytesseract
                self.pytesseract = pytesseract
                self.engine_type = "pytesseract"
                logger.info("[OCR] Initialized pytesseract fallback engine.")
            except Exception as e:
                logger.warning("[OCR] Neither PaddleOCR nor pytesseract available (%s). Using mock/regex parser.", e)

    def crop_roi(self, image: Image.Image) -> Image.Image:
        """Crops image to normalized Region of Interest (0.0 - 1.0)."""
        w, h = image.size
        x1 = int(self.roi.get("x", 0.70) * w)
        y1 = int(self.roi.get("y", 0.85) * h)
        box_w = int(self.roi.get("w", 0.28) * w)
        box_h = int(self.roi.get("h", 0.12) * h)
        return image.crop((x1, y1, min(w, x1 + box_w), min(h, y1 + box_h)))

    def extract_text(self, cropped_img: Image.Image) -> str:
        """Runs the active OCR engine on the cropped image area."""
        if self.engine_type == "paddleocr":
            img_np = np.array(cropped_img)
            result = self.ocr.ocr(img_np, cls=False)
            lines = []
            if result and result[0]:
                for res in result[0]:
                    lines.append(res[1][0])
            return " ".join(lines)
        elif self.engine_type == "pytesseract":
            return self.pytesseract.image_to_string(cropped_img)
        return ""

    def process_segment(self, segment_path: str) -> Optional[dict]:
        """Extracts 1 frame per second from TS segment and runs OCR."""
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-i", segment_path,
            "-vf", "fps=1",
            "-vframes", "1",
            "-f", "image2pipe",
            "-vcodec", "png",
            "-",
        ]

        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
            if not p.stdout:
                return None

            img = Image.open(io.BytesIO(p.stdout)).convert("RGB")
            cropped = self.crop_roi(img)
            text = self.extract_text(cropped)

            return self.evaluate_text(text)
        except Exception as e:
            logger.debug("[OCR] Error processing segment %s: %s", segment_path, e)
            return None

    def evaluate_text(self, text: str) -> dict:
        """Parses extracted text for win multipliers and account balance changes."""
        multiplier = 1.0
        balance = None
        delta = 0.0

        # Multiplier parse
        m_match = MULTIPLIER_REGEX.search(text)
        if m_match:
            try:
                multiplier = float(m_match.group(1))
            except ValueError:
                pass

        # Balance parse
        b_match = CURRENCY_REGEX.search(text)
        if b_match:
            try:
                clean_num = b_match.group(1).replace(",", "")
                balance = float(clean_num)
                if self.last_balance is not None:
                    delta = balance - self.last_balance
                self.last_balance = balance
            except ValueError:
                pass

        self.current_multiplier = multiplier
        self.pnl_delta = delta

        # Trigger condition check
        if multiplier >= self.win_multiplier_threshold or delta >= 500.0:
            if self.on_trigger:
                try:
                    self.on_trigger(multiplier, delta)
                except Exception as err:
                    logger.error("[OCR] Callback exception: %s", err)

        return {
            "raw_text": text,
            "multiplier": multiplier,
            "balance": balance,
            "pnl_delta": delta,
        }
