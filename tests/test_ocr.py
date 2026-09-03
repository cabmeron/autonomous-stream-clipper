from PIL import Image
from services.heuristics.ocr_engine import BoundedRegionOCR


def test_ocr_parse_multipliers():
    ocr = BoundedRegionOCR(roi={})
    res1 = ocr.evaluate_text("BIG WIN 150.5x !!")
    assert res1["multiplier"] == 150.5

    res2 = ocr.evaluate_text("WIN 2000X MEGA")
    assert res2["multiplier"] == 2000.0


def test_ocr_parse_balances():
    ocr = BoundedRegionOCR(roi={})
    res1 = ocr.evaluate_text("BALANCE: $1,250.00")
    assert res1["balance"] == 1250.0

    res2 = ocr.evaluate_text("BALANCE: $4,500.50")
    assert res2["balance"] == 4500.50
    assert res2["pnl_delta"] == 3250.50


def test_ocr_crop_roi():
    ocr = BoundedRegionOCR(roi={"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5})
    img = Image.new("RGB", (1000, 1000), color="white")
    cropped = ocr.crop_roi(img)
    assert cropped.size == (500, 500)


def test_ocr_trigger_callback():
    triggers = []

    def on_trigger(mult, delta):
        triggers.append((mult, delta))

    ocr = BoundedRegionOCR(roi={}, win_multiplier_threshold=100.0, on_trigger_callback=on_trigger)
    ocr.evaluate_text("HUGE 250x MULTIPLIER HIT!")
    assert len(triggers) == 1
    assert triggers[0][0] == 250.0
