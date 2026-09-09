"""Unit tests for DynamicOCRExtractorService and Dynamic Multi-Area OCR integration."""

import pytest
from PIL import Image
from services.heuristics.dynamic_ocr import DynamicOCRExtractorService
from orchestrator import StreamSession


def test_dynamic_ocr_service_init_and_defaults():
    service = DynamicOCRExtractorService()
    areas = service.get_areas()
    assert len(areas) == 2
    assert any(a["id"] == "area_1" for a in areas)
    assert any(a["id"] == "area_2" for a in areas)
    assert areas[0]["label"] == "Balance"
    assert areas[1]["label"] == "Multiplier / Win"


def test_dynamic_ocr_add_update_remove_area():
    service = DynamicOCRExtractorService(initial_areas=[])
    assert len(service.get_areas()) == 0

    # Add area
    new_area = service.add_area(label="Jackpot", roi={"x": 0.2, "y": 0.3, "w": 0.4, "h": 0.1})
    assert new_area["id"] in service.areas
    assert new_area["label"] == "Jackpot"
    assert new_area["roi"]["x"] == 0.2
    assert len(service.get_areas()) == 1

    # Update ROI
    service.update_area_roi(new_area["id"], 0.25, 0.35, 0.5, 0.15)
    assert service.areas[new_area["id"]]["roi"]["x"] == 0.25
    assert service.areas[new_area["id"]]["roi"]["w"] == 0.5

    # Update label
    service.update_area_label(new_area["id"], "Mega Jackpot")
    assert service.areas[new_area["id"]]["label"] == "Mega Jackpot"

    # Remove area
    removed = service.remove_area(new_area["id"])
    assert removed is True
    assert len(service.get_areas()) == 0
    assert service.remove_area("nonexistent_id") is False


def test_dynamic_ocr_set_areas():
    service = DynamicOCRExtractorService()
    custom_areas = [
        {"id": "c1", "label": "Score", "color": "#10b981", "roi": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05}},
        {"id": "c2", "label": "Lives", "color": "#f43f5e", "roi": {"x": 0.8, "y": 0.1, "w": 0.15, "h": 0.05}},
    ]
    service.set_areas(custom_areas)
    areas = service.get_areas()
    assert len(areas) == 2
    assert service.areas["c1"]["label"] == "Score"
    assert service.areas["c2"]["label"] == "Lives"


def test_dynamic_ocr_crop_area():
    service = DynamicOCRExtractorService()
    frame = Image.new("RGB", (1000, 500), color="blue")
    roi = {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
    crop = service.crop_area(frame, roi)
    # Expected: x1 = 100, y1 = 100, w = 300, h = 200
    assert crop.size == (300, 200)

    # Clamped boundary test
    out_of_bounds_roi = {"x": 0.9, "y": 0.9, "w": 0.5, "h": 0.5}
    crop_clamped = service.crop_area(frame, out_of_bounds_roi)
    assert crop_clamped.size[0] <= 100
    assert crop_clamped.size[1] <= 50


def test_dynamic_ocr_numeric_parsing():
    service = DynamicOCRExtractorService()

    # Currency tests
    assert service.parse_numeric("$12,345.67") == 12345.67
    assert service.parse_numeric("€500.00") == 500.0
    assert service.parse_numeric("£99.90") == 99.90
    assert service.parse_numeric("1,500") == 1500.0

    # Multiplier tests
    assert service.parse_numeric("25.5x") == 25.5
    assert service.parse_numeric("x100") == 100.0
    assert service.parse_numeric("BIG WIN 150X!!") == 150.0

    # Suffix notation
    assert service.parse_numeric("15.5k") == 15500.0
    assert service.parse_numeric("2.5M") == 2500000.0

    # Non-numeric text
    assert service.parse_numeric("FREE SPINS BONUS") is None
    assert service.parse_numeric("") is None


def test_dynamic_ocr_process_frame_synthetic():
    service = DynamicOCRExtractorService(initial_areas=[
        {"id": "a1", "label": "Area A", "roi": {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.2}},
        {"id": "a2", "label": "Area B", "roi": {"x": 0.5, "y": 0.5, "w": 0.3, "h": 0.2}},
    ])
    img = Image.new("RGB", (640, 360), color="white")
    results = service.process_frame(img)

    assert len(results) == 2
    assert results[0]["id"] == "a1"
    assert results[1]["id"] == "a2"
    assert "latency_ms" in results[0]
    assert "text" in results[0]
    assert "numeric_val" in results[0]


def test_stream_session_dynamic_ocr_integration():
    session = StreamSession(channel="testchannel", orchestrator=None, simulate=True)
    assert hasattr(session, "dynamic_ocr")
    assert isinstance(session.dynamic_ocr, DynamicOCRExtractorService)

    telemetry = session.get_telemetry()
    assert "ocr_extracted_areas" in telemetry
    assert "dynamic_ocr_areas" in telemetry
    assert len(telemetry["dynamic_ocr_areas"]) == 2


@pytest.mark.asyncio
async def test_ocr_areas_api_endpoints():
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from orchestrator import StreamClipperOrchestrator

    orch = StreamClipperOrchestrator()
    session = StreamSession(channel="streamerx", orchestrator=orch, simulate=True)
    orch.sessions["streamerx"] = session

    # Mount endpoints
    app = web.Application()

    async def get_ocr_areas_handler(request):
        channel = request.match_info.get("channel", "").lower()
        if channel not in orch.sessions:
            return web.json_response({"error": "Session not found"}, status=404)
        s = orch.sessions[channel]
        return web.json_response({
            "channel": channel,
            "areas": s.dynamic_ocr.get_areas(),
            "latest_extractions": getattr(s.dynamic_ocr, "latest_extractions", []),
        })

    async def post_ocr_areas_handler(request):
        channel = request.match_info.get("channel", "").lower()
        if channel not in orch.sessions:
            return web.json_response({"error": "Session not found"}, status=404)
        s = orch.sessions[channel]
        data = await request.json()
        action = data.get("action")
        if action == "add":
            area = s.dynamic_ocr.add_area(label=data.get("label", "Area"), roi=data.get("roi"))
            return web.json_response({"success": True, "action": "add", "area": area, "areas": s.dynamic_ocr.get_areas()})
        elif action == "update_roi":
            aid = data.get("id")
            roi = data.get("roi", {})
            s.dynamic_ocr.update_area_roi(aid, float(roi.get("x", 0)), float(roi.get("y", 0)), float(roi.get("w", 0.1)), float(roi.get("h", 0.1)))
            return web.json_response({"success": True, "action": "update_roi", "areas": s.dynamic_ocr.get_areas()})
        elif action == "remove":
            res = s.dynamic_ocr.remove_area(data.get("id"))
            return web.json_response({"success": res, "action": "remove", "areas": s.dynamic_ocr.get_areas()})
        return web.json_response({"error": "Invalid action"}, status=400)

    app.router.add_get("/api/sessions/{channel}/ocr-areas", get_ocr_areas_handler)
    app.router.add_post("/api/sessions/{channel}/ocr-areas", post_ocr_areas_handler)

    client = TestClient(TestServer(app))
    await client.start_server()

    try:
        # 1. GET initial areas
        resp = await client.get("/api/sessions/streamerx/ocr-areas")
        assert resp.status == 200
        body = await resp.json()
        assert len(body["areas"]) == 2

        # 2. POST add new area
        post_resp = await client.post("/api/sessions/streamerx/ocr-areas", json={"action": "add", "label": "Jackpot Box"})
        assert post_resp.status == 200
        post_body = await post_resp.json()
        assert post_body["success"] is True
        assert len(post_body["areas"]) == 3
        added_id = post_body["area"]["id"]

        # 3. POST update ROI
        upd_resp = await client.post("/api/sessions/streamerx/ocr-areas", json={
            "action": "update_roi",
            "id": added_id,
            "roi": {"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.15},
        })
        assert upd_resp.status == 200
        upd_body = await upd_resp.json()
        assert upd_body["success"] is True
        target_area = next(a for a in upd_body["areas"] if a["id"] == added_id)
        assert target_area["roi"]["x"] == 0.4

        # 4. POST remove area
        del_resp = await client.post("/api/sessions/streamerx/ocr-areas", json={"action": "remove", "id": added_id})
        assert del_resp.status == 200
        del_body = await del_resp.json()
        assert del_body["success"] is True
        assert len(del_body["areas"]) == 2
    finally:
        await client.close()
