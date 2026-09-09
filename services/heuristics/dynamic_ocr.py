"""Dynamic Multi-Area OCR Extractor Service.

Allows users to define, move, resize, and manage arbitrary extraction areas on the live stream.
Crops each region, applies contrast enhancement, and extracts text/numbers using Tesseract
without restrictive character whitelists, reporting all extracted values in real time.
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

COLOR_PALETTE = [
    "#38bdf8",  # Sky Blue
    "#10b981",  # Emerald Green
    "#f59e0b",  # Amber Orange
    "#ec4899",  # Rose Pink
    "#a855f7",  # Purple
    "#06b6d4",  # Cyan
    "#f97316",  # Bright Orange
]

# Numeric extraction regexes
NUMERIC_CLEAN_REGEX = re.compile(r"[\$€£]?\s*([0-9]{1,3}(?:[,.][0-9]{3})*(?:[,.][0-9]{2})|[0-9]+(?:\.[0-9]+)?)")
MULTIPLIER_REGEX = re.compile(r"(\d+(?:\.\d+)?)\s*[xX]|[xX]\s*(\d+(?:\.\d+)?)")
SUFFIX_REGEX = re.compile(r"([\d.,]+)\s*([kKmMbB])")


class DynamicOCRExtractorService:
    """Manages arbitrary user-defined OCR extraction areas and runs live text/numeric extraction."""

    def __init__(self, initial_areas: Optional[List[Dict[str, Any]]] = None):
        self._init_ocr()
        self.areas: Dict[str, Dict[str, Any]] = {}

        if initial_areas is not None:
            self.set_areas(initial_areas)
        else:
            # 2 Default sensible areas that users can immediately drag
            self.areas = {
                "area_1": {
                    "id": "area_1",
                    "label": "Balance",
                    "color": COLOR_PALETTE[0],
                    "roi": {"x": 0.05, "y": 0.88, "w": 0.22, "h": 0.08},
                },
                "area_2": {
                    "id": "area_2",
                    "label": "Multiplier / Win",
                    "color": COLOR_PALETTE[2],
                    "roi": {"x": 0.38, "y": 0.48, "w": 0.24, "h": 0.12},
                },
            }

        self.latest_extractions: List[Dict[str, Any]] = []
        self.initial_balance: Optional[float] = None
        self.current_preset: Optional[str] = None

    @property
    def active_preset(self) -> Optional[str]:
        return self.current_preset

    def _init_ocr(self):
        self.pytesseract = None
        try:
            import pytesseract
            self.pytesseract = pytesseract
            logger.info("[DynamicOCR] Initialized pytesseract OCR engine.")
        except Exception as e:
            logger.warning("[DynamicOCR] pytesseract not available (%s).", e)

    def add_area(self, label: str = "Area", roi: Optional[Dict[str, float]] = None, color: Optional[str] = None) -> Dict[str, Any]:
        """Creates a new extraction area with an auto-assigned color and ID."""
        area_idx = len(self.areas) + 1
        area_id = f"area_{int(time.time() * 1000) % 1000000}"
        assigned_color = color or COLOR_PALETTE[len(self.areas) % len(COLOR_PALETTE)]
        default_roi = roi or {"x": 0.30, "y": 0.30, "w": 0.20, "h": 0.10}

        area = {
            "id": area_id,
            "label": label if label != "Area" else f"Area {area_idx}",
            "color": assigned_color,
            "roi": {
                "x": max(0.0, min(1.0, float(default_roi.get("x", 0.3)))),
                "y": max(0.0, min(1.0, float(default_roi.get("y", 0.3)))),
                "w": max(0.02, min(1.0, float(default_roi.get("w", 0.2)))),
                "h": max(0.02, min(1.0, float(default_roi.get("h", 0.1)))),
            },
        }
        self.areas[area_id] = area
        logger.info("[DynamicOCR] Added extraction area: %s (%s)", area_id, area["label"])
        return area

    def update_area_roi(self, area_id: str, x: float, y: float, w: float, h: float):
        """Updates normalized coordinates for a specific extraction area."""
        if area_id in self.areas:
            self.areas[area_id]["roi"] = {
                "x": max(0.0, min(1.0, float(x))),
                "y": max(0.0, min(1.0, float(y))),
                "w": max(0.02, min(1.0, float(w))),
                "h": max(0.02, min(1.0, float(h))),
            }

    def update_area_label(self, area_id: str, new_label: str):
        """Renames an extraction area."""
        if area_id in self.areas:
            self.areas[area_id]["label"] = str(new_label).strip() or "Untitled Area"

    def remove_area(self, area_id: str) -> bool:
        """Removes an extraction area."""
        if area_id in self.areas:
            del self.areas[area_id]
            logger.info("[DynamicOCR] Removed extraction area: %s", area_id)
            return True
        return False

    def set_areas(self, areas_data: Any):
        """Replaces current areas with a new list or dict of areas."""
        new_dict = {}
        if isinstance(areas_data, list):
            for a in areas_data:
                aid = str(a.get("id") or f"area_{len(new_dict)+1}")
                new_dict[aid] = {
                    "id": aid,
                    "label": str(a.get("label", "Area")),
                    "color": str(a.get("color") or COLOR_PALETTE[len(new_dict) % len(COLOR_PALETTE)]),
                    "roi": {
                        "x": max(0.0, min(1.0, float(a.get("roi", {}).get("x", 0.1)))),
                        "y": max(0.0, min(1.0, float(a.get("roi", {}).get("y", 0.1)))),
                        "w": max(0.02, min(1.0, float(a.get("roi", {}).get("w", 0.2)))),
                        "h": max(0.02, min(1.0, float(a.get("roi", {}).get("h", 0.1)))),
                    },
                }
        elif isinstance(areas_data, dict):
            for aid, a in areas_data.items():
                new_dict[str(aid)] = {
                    "id": str(aid),
                    "label": str(a.get("label", "Area")),
                    "color": str(a.get("color") or COLOR_PALETTE[len(new_dict) % len(COLOR_PALETTE)]),
                    "roi": {
                        "x": max(0.0, min(1.0, float(a.get("roi", {}).get("x", 0.1)))),
                        "y": max(0.0, min(1.0, float(a.get("roi", {}).get("y", 0.1)))),
                        "w": max(0.02, min(1.0, float(a.get("roi", {}).get("w", 0.2)))),
                        "h": max(0.02, min(1.0, float(a.get("roi", {}).get("h", 0.1)))),
                    },
                }
        self.areas = new_dict

    def get_areas(self) -> List[Dict[str, Any]]:
        """Returns all configured areas as a list."""
        return list(self.areas.values())

    def crop_area(self, frame: Image.Image, roi: Dict[str, float]) -> Image.Image:
        """Crops image to normalized region with boundary clamping."""
        w, h = frame.size
        x1 = max(0, min(w - 2, int(roi.get("x", 0.0) * w)))
        y1 = max(0, min(h - 2, int(roi.get("y", 0.0) * h)))
        box_w = max(2, min(w - x1, int(roi.get("w", 0.1) * w)))
        box_h = max(2, min(h - y1, int(roi.get("h", 0.1) * h)))
        return frame.crop((x1, y1, x1 + box_w, y1 + box_h))

    def parse_numeric(self, text: str) -> Optional[float]:
        """Extracts currency numbers, multipliers, or floats from raw text."""
        if not text:
            return None
        clean = text.strip()

        # Check multiplier format first (e.g. 25.5x, x100)
        m = MULTIPLIER_REGEX.search(clean)
        if m:
            val_str = m.group(1) or m.group(2)
            try:
                return float(val_str)
            except (ValueError, TypeError):
                pass

        # Check for K/M suffix (e.g. 25.5k -> 25500.0)
        sm = SUFFIX_REGEX.search(clean)
        if sm:
            num_str = sm.group(1).replace(",", "")
            unit = sm.group(2).lower()
            try:
                val = float(num_str)
                return val * 1000.0 if unit == "k" else val * 1000000.0
            except ValueError:
                pass

        # Standard currency / numbers (handles $12,345.67, 1,500, 500.00, 42, etc.)
        clean_no_curr = re.sub(r"[\$€£¥]", "", clean)
        match = re.search(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?", clean_no_curr)
        if match:
            raw = match.group(0).replace(",", "")
            try:
                return float(raw)
            except ValueError:
                return None
        return None

    def extract_text_from_crop(self, crop: Image.Image) -> str:
        """Applies adaptive preprocessing and runs Tesseract OCR."""
        if not self.pytesseract:
            return ""

        try:
            # Scale up small crops (< 50px height) to ensure sharp character recognition
            w, h = crop.size
            if h < 50:
                scale = max(2, int(60 / max(1, h)))
                crop = crop.resize((w * scale, h * scale), Image.Resampling.BILINEAR)

            # Convert to grayscale and apply contrast normalization
            gray = crop.convert("L")
            enhanced = ImageOps.autocontrast(gray, cutoff=2)

            # Run OCR assuming uniform block of text with fast PSM 6
            text = self.pytesseract.image_to_string(
                enhanced,
                config="--psm 6",
            )
            clean_text = text.strip()

            # If empty, attempt fallback PSM 11 (sparse text)
            if not clean_text:
                fallback_text = self.pytesseract.image_to_string(
                    enhanced,
                    config="--psm 11",
                )
                clean_text = fallback_text.strip()

            return clean_text
        except Exception as e:
            logger.debug("[DynamicOCR] Error in OCR extraction: %s", e)
            return ""

    def process_frame(self, frame: Image.Image) -> List[Dict[str, Any]]:
        """Extracts text and values from all defined areas in a single pass."""
        results = []
        t_start = time.perf_counter()

        for area_id, area in self.areas.items():
            t0 = time.perf_counter()
            crop = self.crop_area(frame, area["roi"])
            raw_text = self.extract_text_from_crop(crop)
            num_val = self.parse_numeric(raw_text)
            latency = round((time.perf_counter() - t0) * 1000.0, 2)

            results.append({
                "id": area["id"],
                "label": area["label"],
                "color": area["color"],
                "text": raw_text if raw_text else "—",
                "numeric_val": num_val,
                "roi": area["roi"],
                "latency_ms": latency,
            })

        self.latest_extractions = results
        total_time = round((time.perf_counter() - t_start) * 1000.0, 2)
        return results

    def apply_slot_preset(self, preset_name: str) -> List[Dict[str, Any]]:
        """Loads extraction area bounding boxes for a specific slot provider."""
        from services.heuristics.slot_presets import get_slot_preset
        preset_areas = get_slot_preset(preset_name)
        self.set_areas(preset_areas)
        self.current_preset = preset_name
        logger.info("[DynamicOCR] Applied slot preset: %s (%d areas)", preset_name, len(preset_areas))
        return self.get_areas()

    def compute_slot_metrics(self, extractions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Calculates derived slot intelligence (Win Multiplier, Session Net PnL, Win Tier)."""
        metrics: Dict[str, Any] = {
            "current_balance": None,
            "current_bet": None,
            "current_win": None,
            "bonus_info": None,
            "multiplier": 0.0,
            "win_tier": "BASE",
            "is_big_win": False,
            "net_pnl": 0.0,
            "preset": getattr(self, "current_preset", "default_slots") or "default_slots",
        }

        source = extractions if extractions is not None else self.latest_extractions
        has_direct_mult = False

        # Scan extractions for balance, bet, win, and bonus
        for item in source:
            lbl = (item.get("label") or "").lower()
            num = item.get("numeric_val")
            txt = str(item.get("text", "")).lower()

            if "balance" in lbl or "credit" in lbl:
                if num is not None and num > 0:
                    metrics["current_balance"] = float(num)
                    if self.initial_balance is None:
                        self.initial_balance = float(num)
            elif "bet" in lbl or "wager" in lbl:
                if num is not None and num > 0:
                    metrics["current_bet"] = float(num)
            elif "win" in lbl or "payout" in lbl or "multiplier" in lbl:
                if "x" in txt and num is not None:
                    metrics["multiplier"] = float(num)
                    has_direct_mult = True
                elif num is not None:
                    metrics["current_win"] = float(num)
            elif "bonus" in lbl or "free" in lbl or "spin" in lbl:
                if txt and txt != "—":
                    metrics["bonus_info"] = item.get("text", "")

        # Calculate multiplier = win / bet if win & bet exist and not directly extracted
        win_val = metrics["current_win"]
        bet_val = metrics["current_bet"]
        if not has_direct_mult:
            if win_val is not None and bet_val is not None and bet_val > 0:
                metrics["multiplier"] = round(win_val / bet_val, 2)
            elif win_val is not None:
                metrics["multiplier"] = round(win_val, 2)
            else:
                metrics["multiplier"] = 1.0

        # Net PnL
        curr_bal = metrics["current_balance"]
        if curr_bal is not None and self.initial_balance is not None:
            metrics["net_pnl"] = round(curr_bal - self.initial_balance, 2)

        # Win Tier Classification
        mult = metrics["multiplier"]
        if mult >= 1000.0:
            metrics["win_tier"] = "MAX_WIN"
            metrics["is_big_win"] = True
        elif mult >= 200.0:
            metrics["win_tier"] = "MEGA_WIN"
            metrics["is_big_win"] = True
        elif mult >= 50.0:
            metrics["win_tier"] = "BIG_WIN"
            metrics["is_big_win"] = True
        elif mult >= 2.0:
            metrics["win_tier"] = "WIN"
            metrics["is_big_win"] = False
        else:
            metrics["win_tier"] = "BASE"
            metrics["is_big_win"] = False

        return metrics

