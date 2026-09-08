"""Multi-Region Gambling OCR and Slot HUD Optical Engine.

Extracts live balance, bet size, win amount, and spin states (spinning, idle, bonus)
from video frames using concurrent Region-of-Interest (ROI) optical parsing.
"""

import io
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Numeric extraction regexes
CURRENCY_CLEAN_REGEX = re.compile(r"[^\d.,kmKM]")
MULTIPLIER_REGEX = re.compile(r"(\d+(?:\.\d+)?)\s*[xX]|[xX]\s*(\d+(?:\.\d+)?)")

# Preset layouts for popular casino games (normalized x, y, w, h coordinates)
CASINO_PRESETS = {
    "pragmatic_standard": {
        "balance": {"x": 0.05, "y": 0.92, "w": 0.18, "h": 0.06},
        "bet": {"x": 0.42, "y": 0.92, "w": 0.16, "h": 0.06},
        "win": {"x": 0.35, "y": 0.50, "w": 0.30, "h": 0.14},
        "reels": {"x": 0.20, "y": 0.15, "w": 0.60, "h": 0.70},
    },
    "hacksaw_standard": {
        "balance": {"x": 0.03, "y": 0.93, "w": 0.20, "h": 0.05},
        "bet": {"x": 0.75, "y": 0.93, "w": 0.15, "h": 0.05},
        "win": {"x": 0.30, "y": 0.45, "w": 0.40, "h": 0.16},
        "reels": {"x": 0.22, "y": 0.18, "w": 0.56, "h": 0.68},
    },
    "stake_originals": {
        "balance": {"x": 0.40, "y": 0.02, "w": 0.20, "h": 0.05},
        "bet": {"x": 0.05, "y": 0.30, "w": 0.18, "h": 0.06},
        "win": {"x": 0.35, "y": 0.48, "w": 0.30, "h": 0.12},
        "reels": {"x": 0.28, "y": 0.15, "w": 0.65, "h": 0.75},
    },
}


class GamblingOCREngine:
    """Multi-region optical extractor for casino HUDs (Balance, Bet, Win, Spin Motion)."""

    def __init__(
        self,
        preset: str = "pragmatic_standard",
        custom_rois: Optional[Dict[str, Dict[str, float]]] = None,
    ):
        base_rois = CASINO_PRESETS.get(preset, CASINO_PRESETS["pragmatic_standard"])
        self.rois: Dict[str, Dict[str, float]] = {
            "balance": dict(base_rois["balance"]),
            "bet": dict(base_rois["bet"]),
            "win": dict(base_rois["win"]),
            "reels": dict(base_rois["reels"]),
        }
        if custom_rois:
            self.rois.update(custom_rois)

        self._init_ocr()

        # State tracking
        self.last_balance: Optional[float] = None
        self.last_bet: Optional[float] = None
        self.last_win: Optional[float] = None
        self.last_reels_patch: Optional[np.ndarray] = None
        self.spin_state: str = "IDLE"  # IDLE, SPINNING, WIN_CELEBRATION, BONUS_FEATURE

    def _init_ocr(self):
        self.pytesseract = None
        try:
            import pytesseract
            self.pytesseract = pytesseract
            logger.info("[GamblingOCR] Initialized pytesseract OCR engine.")
        except Exception as e:
            logger.warning("[GamblingOCR] pytesseract not available (%s). Using regex fallback parser.", e)

    def set_preset(self, preset_name: str):
        """Switches to a preconfigured coordinate preset."""
        if preset_name in CASINO_PRESETS:
            preset_data = CASINO_PRESETS[preset_name]
            self.rois = {k: dict(v) for k, v in preset_data.items()}
            logger.info("[GamblingOCR] Switched to preset: %s", preset_name)

    def update_roi(self, region_key: str, x: float, y: float, w: float, h: float):
        """Updates a specific region of interest (balance, bet, win, reels)."""
        if region_key in self.rois:
            self.rois[region_key] = {
                "x": max(0.0, min(1.0, float(x))),
                "y": max(0.0, min(1.0, float(y))),
                "w": max(0.02, min(1.0, float(w))),
                "h": max(0.02, min(1.0, float(h))),
            }
            logger.info("[GamblingOCR] Updated ROI for %s: %s", region_key, self.rois[region_key])

    def crop_region(self, frame: Image.Image, region_key: str) -> Image.Image:
        """Crops image to the specified normalized region."""
        roi = self.rois.get(region_key, {"x": 0, "y": 0, "w": 1, "h": 1})
        w, h = frame.size
        x1 = int(roi["x"] * w)
        y1 = int(roi["y"] * h)
        bw = int(roi["w"] * w)
        bh = int(roi["h"] * h)
        return frame.crop((x1, y1, min(w, x1 + bw), min(h, y1 + bh)))

    def parse_currency(self, text: str) -> Optional[float]:
        """Cleans and parses currency strings into floating point dollar values."""
        if not text:
            return None
        clean = text.strip()
        # Look for multiplier indicator (e.g. 250x or 15.5k)
        mult_match = re.search(r"([\d.,]+)\s*([kKmMbB])", clean)
        if mult_match:
            num_str = mult_match.group(1).replace(",", "")
            unit = mult_match.group(2).lower()
            try:
                val = float(num_str)
                if unit == "k":
                    return val * 1000.0
                elif unit == "m":
                    return val * 1000000.0
            except ValueError:
                pass

        # Standard currency string: find numeric sequences with dots/commas
        num_match = re.search(r"[\$€£]?\s*([0-9]{1,3}(?:[,.][0-9]{3})*(?:[,.][0-9]{2})|[0-9]+(?:\.[0-9]+)?)", clean)
        if num_match:
            raw_num = num_match.group(1)
            # Normalize comma vs decimal point
            if "," in raw_num and "." in raw_num:
                if raw_num.rfind(",") > raw_num.rfind("."):
                    raw_num = raw_num.replace(".", "").replace(",", ".")
                else:
                    raw_num = raw_num.replace(",", "")
            elif "," in raw_num:
                # e.g. 1,500 vs 1,50
                parts = raw_num.split(",")
                if len(parts[-1]) == 2:
                    raw_num = "".join(parts[:-1]) + "." + parts[-1]
                else:
                    raw_num = raw_num.replace(",", "")
            try:
                return float(raw_num)
            except ValueError:
                return None
        return None

    def parse_multiplier(self, text: str) -> Optional[float]:
        """Extracts win multipliers (e.g. '125.5x' or 'x50')."""
        if not text:
            return None
        match = MULTIPLIER_REGEX.search(text)
        if match:
            val_str = match.group(1) or match.group(2)
            try:
                return float(val_str)
            except (ValueError, TypeError):
                return None
        return None

    def detect_spin_state(self, reels_crop: Image.Image) -> str:
        """Determines if the slot reels are IDLE, SPINNING, or in WIN_CELEBRATION using motion variance."""
        thumb = reels_crop.resize((64, 48)).convert("L")
        current_patch = np.array(thumb, dtype=np.float32)

        if self.last_reels_patch is None:
            self.last_reels_patch = current_patch
            return "IDLE"

        # Frame difference across reels region
        diff = np.abs(current_patch - self.last_reels_patch)
        motion_score = float(diff.mean())
        self.last_reels_patch = current_patch

        # Thresholds for motion classification
        if motion_score > 18.0:
            return "SPINNING"
        elif motion_score > 7.0:
            return "WIN_CELEBRATION"
        return "IDLE"

    def extract_text(self, img_crop: Image.Image) -> str:
        """Runs OCR on cropped ROI image with contrast enhancement."""
        if not self.pytesseract:
            return ""
        try:
            # Grayscale & threshold enhancement for crisp digits
            gray = img_crop.convert("L")
            text = self.pytesseract.image_to_string(
                gray,
                config="--psm 7 -c tessedit_char_whitelist=0123456789.,$€£xXkKmM -c tessedit_do_invert=0",
            )
            return text.strip()
        except Exception:
            return ""

    def process_frame(self, full_frame: Image.Image) -> Dict[str, Any]:
        """Extracts and parses all gambling HUD elements from a live video frame."""
        t0 = time.perf_counter()

        # 1. Balance
        balance_crop = self.crop_region(full_frame, "balance")
        raw_balance_text = self.extract_text(balance_crop)
        balance_val = self.parse_currency(raw_balance_text)

        # 2. Bet Size
        bet_crop = self.crop_region(full_frame, "bet")
        raw_bet_text = self.extract_text(bet_crop)
        bet_val = self.parse_currency(raw_bet_text)

        # 3. Win / Multiplier
        win_crop = self.crop_region(full_frame, "win")
        raw_win_text = self.extract_text(win_crop)
        win_val = self.parse_currency(raw_win_text)
        multiplier_val = self.parse_multiplier(raw_win_text)

        # 4. Reel Motion & Spin State
        reels_crop = self.crop_region(full_frame, "reels")
        spin_state = self.detect_spin_state(reels_crop)
        self.spin_state = spin_state

        # Apply noise filtering / fallback preservation
        if balance_val is not None:
            self.last_balance = balance_val
        if bet_val is not None:
            self.last_bet = bet_val
        if win_val is not None:
            self.last_win = win_val

        t1 = time.perf_counter()
        latency_ms = round((t1 - t0) * 1000.0, 2)

        return {
            "balance": self.last_balance,
            "bet": self.last_bet,
            "win": self.last_win,
            "multiplier": multiplier_val,
            "spin_state": self.spin_state,
            "raw_texts": {
                "balance": raw_balance_text,
                "bet": raw_bet_text,
                "win": raw_win_text,
            },
            "rois": self.rois,
            "latency_ms": latency_ms,
            "timestamp": time.time(),
        }
