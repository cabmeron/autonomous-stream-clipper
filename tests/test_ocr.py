from PIL import Image
import pytest
from services.heuristics.ocr_engine import BoundedRegionOCR


def test_ocr_parse_multipliers():
    assert BoundedRegionOCR.parse_values("WIN 250x!")[1] == 250.0
    assert BoundedRegionOCR.parse_values("MEGA HIT 1000X AMAZING")[1] == 1000.0
    assert BoundedRegionOCR.parse_values("No multiplier here")[1] == 1.0


def test_ocr_parse_balances():
    b1, _ = BoundedRegionOCR.parse_values("BALANCE: $12,450.00")
    assert b1 == 12450.00

    b2, m2 = BoundedRegionOCR.parse_values("WIN: $500.25 (50x)")
    assert b2 == 500.25
    assert m2 == 50.0


def test_ocr_crop_roi():
    ocr = BoundedRegionOCR(roi={"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5})
    dummy_img = Image.new("RGB", (1000, 1000), color="blue")
    cropped = ocr.crop_roi(dummy_img)
    assert cropped.size == (500, 500)


def test_ocr_trigger_callback():
    triggers = []

    def on_trigger(mult, pnl):
        triggers.append((mult, pnl))

    ocr = BoundedRegionOCR(win_multiplier_threshold=100.0, on_trigger_callback=on_trigger)

    # Frame 1: Balance $1,000, 1x
    ocr.current_balance = 1000.0
    ocr.last_balance = 1000.0

    # Simulate frame processing with high multiplier
    dummy_img = Image.new("RGB", (200, 200))
    ocr.recognize_text = lambda img: "BIG WIN 250x $5,000.00"

    res = ocr.process_frame(dummy_img)
    assert res["multiplier"] == 250.0
    assert res["balance"] == 5000.00
    assert res["pnl_delta"] == 4000.00
    assert res["is_triggered"] is True
    assert len(triggers) == 1
    assert triggers[0][0] == 250.0
