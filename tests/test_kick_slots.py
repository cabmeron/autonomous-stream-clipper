"""Unit tests for Kick.com live slots radar, slot provider presets, and slot intelligence metrics."""

import time
import pytest
from unittest.mock import patch, MagicMock
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from services.heuristics.slot_presets import get_slot_preset, list_available_presets, SLOT_PRESETS
from services.heuristics.kick_slot_radar import KickSlotRadarService
from services.heuristics.dynamic_ocr import DynamicOCRExtractorService
from orchestrator import StreamClipperOrchestrator, StreamSession, clean_channel_name


def test_slot_presets_definition_and_access():
    presets = list_available_presets()
    assert len(presets) >= 4
    preset_keys = [p["key"] for p in presets]
    assert "pragmatic_play" in preset_keys
    assert "hacksaw_gaming" in preset_keys
    assert "nolimit_city" in preset_keys
    assert "default_slots" in preset_keys

    # Test get_slot_preset valid
    pragmatic = get_slot_preset("pragmatic_play")
    assert pragmatic is not None
    assert len(pragmatic) >= 3
    labels = [p["label"] for p in pragmatic]
    assert "Balance" in labels
    assert "Bet" in labels
    assert "Win" in labels

    # Test fallback on unknown preset
    fallback = get_slot_preset("unknown_provider")
    assert fallback is not None
    assert len(fallback) == len(SLOT_PRESETS["default_slots"]["areas"])


def test_dynamic_ocr_apply_slot_preset():
    service = DynamicOCRExtractorService()
    assert service.active_preset is None

    areas = service.apply_slot_preset("hacksaw_gaming")
    assert service.active_preset == "hacksaw_gaming"
    assert len(areas) >= 3
    labels = [a["label"] for a in areas]
    assert "Balance" in labels
    assert "Bet" in labels
    assert "Win" in labels

    # Verify ROI values are normalized floats
    for a in areas:
        roi = a["roi"]
        assert 0.0 <= roi["x"] <= 1.0
        assert 0.0 <= roi["y"] <= 1.0
        assert 0.0 < roi["w"] <= 1.0
        assert 0.0 < roi["h"] <= 1.0


def test_slot_metrics_multiplier_and_win_tiers():
    service = DynamicOCRExtractorService()
    service.apply_slot_preset("pragmatic_play")

    # 1. Base spin: Bet $10, Win $0
    metrics_base = service.compute_slot_metrics([
        {"id": "slot_bet", "label": "Current Bet", "numeric_val": 10.0},
        {"id": "slot_win", "label": "Win / Multiplier", "numeric_val": 0.0},
        {"id": "slot_balance", "label": "Balance", "numeric_val": 1000.0},
    ])
    assert metrics_base["multiplier"] == 0.0
    assert metrics_base["win_tier"] == "BASE"
    assert metrics_base["is_big_win"] is False
    assert metrics_base["net_pnl"] == 0.0  # initial balance established at 1000

    # 2. Regular win: Bet $10, Win $50 (5x)
    metrics_win = service.compute_slot_metrics([
        {"id": "slot_bet", "label": "Current Bet", "numeric_val": 10.0},
        {"id": "slot_win", "label": "Win / Multiplier", "numeric_val": 50.0},
        {"id": "slot_balance", "label": "Balance", "numeric_val": 1040.0},
    ])
    assert metrics_win["multiplier"] == 5.0
    assert metrics_win["win_tier"] == "WIN"
    assert metrics_win["is_big_win"] is False
    assert metrics_win["net_pnl"] == 40.0

    # 3. Big win: Bet $10, Win $750 (75x >= 50x)
    metrics_big = service.compute_slot_metrics([
        {"id": "slot_bet", "label": "Current Bet", "numeric_val": 10.0},
        {"id": "slot_win", "label": "Win / Multiplier", "numeric_val": 750.0},
        {"id": "slot_balance", "label": "Balance", "numeric_val": 1740.0},
    ])
    assert metrics_big["multiplier"] == 75.0
    assert metrics_big["win_tier"] == "BIG_WIN"
    assert metrics_big["is_big_win"] is True
    assert metrics_big["net_pnl"] == 740.0

    # 4. Mega win: Bet $5, Win $1,250 (250x >= 200x)
    metrics_mega = service.compute_slot_metrics([
        {"id": "slot_bet", "label": "Current Bet", "numeric_val": 5.0},
        {"id": "slot_win", "label": "Win / Multiplier", "numeric_val": 1250.0},
        {"id": "slot_balance", "label": "Balance", "numeric_val": 2985.0},
    ])
    assert metrics_mega["multiplier"] == 250.0
    assert metrics_mega["win_tier"] == "MEGA_WIN"
    assert metrics_mega["is_big_win"] is True

    # 5. Max win: Bet $2, Win $10,000 (5000x >= 1000x)
    metrics_max = service.compute_slot_metrics([
        {"id": "slot_bet", "label": "Current Bet", "numeric_val": 2.0},
        {"id": "slot_win", "label": "Win / Multiplier", "numeric_val": 10000.0},
    ])
    assert metrics_max["multiplier"] == 5000.0
    assert metrics_max["win_tier"] == "MAX_WIN"
    assert metrics_max["is_big_win"] is True


def test_slot_metrics_direct_multiplier_extraction():
    service = DynamicOCRExtractorService()
    # When multiplier is directly extracted (e.g. OCR detected "125x")
    metrics = service.compute_slot_metrics([
        {"id": "slot_win", "label": "Win / Multiplier", "numeric_val": 125.0},
    ])
    assert metrics["multiplier"] == 125.0
    assert metrics["win_tier"] == "BIG_WIN"
    assert metrics["is_big_win"] is True


@pytest.mark.asyncio
async def test_kick_slot_radar_service():
    radar = KickSlotRadarService(cache_ttl_seconds=30.0)
    assert radar.get_cached_streams() == []

    mock_featured = [
        {
            "channel": "roshtein",
            "channel_slug": "roshtein",
            "title": "1,000,000 BONUS HUNT OPENING ON PRAGMATIC & HACKSAW",
            "session_title": "1,000,000 BONUS HUNT OPENING ON PRAGMATIC & HACKSAW",
            "viewer_count": 14200,
            "category": "Slots & Casino",
            "profile_pic": "https://img.kick.com/rosh.jpg",
            "playback_url": "https://stream.kick.com/live/rosh.m3u8",
            "is_live": True,
        }
    ]

    with patch.object(radar, "_fetch_featured_streams", return_value=mock_featured), \
         patch.object(radar, "_fetch_subcategory_slots", return_value=[]), \
         patch.object(radar, "_check_channels_status", return_value=[]):
        # 1. First fetch
        streams = await radar.discover_live_slots(force_refresh=True)
        assert len(streams) == 1
        assert streams[0]["channel"] == "roshtein"
        assert streams[0]["viewer_count"] == 14200
        assert streams[0]["is_live"] is True
        assert streams[0]["category"] == "Slots & Casino"

        # 2. Second fetch within TTL returns cached result without re-calling _fetch_featured_streams
        with patch.object(radar, "_fetch_featured_streams", side_effect=RuntimeError("Should not call")):
            cached_streams = await radar.discover_live_slots(force_refresh=False)
            assert len(cached_streams) == 1
            assert cached_streams[0]["channel"] == "roshtein"


@pytest.mark.asyncio
async def test_kick_slot_api_routes():
    orch = StreamClipperOrchestrator()
    session = StreamSession(channel="kickgambler", orchestrator=orch, platform="kick", simulate=True)
    orch.sessions["kickgambler"] = session

    app = web.Application()

    async def get_kick_slots_streams_handler(request):
        force = request.query.get("refresh", "false").lower() == "true"
        streams = await orch.kick_slot_radar.discover_live_slots(force_refresh=force)
        return web.json_response({
            "streams": streams,
            "count": len(streams),
            "timestamp": time.time(),
        })

    async def post_slot_preset_handler(request):
        channel = clean_channel_name(request.match_info.get("channel", ""))
        if not channel or channel not in orch.sessions:
            return web.json_response({"error": "Session not found"}, status=404)
        s = orch.sessions[channel]
        data = await request.json()
        preset = data.get("preset", "default_slots")
        areas = s.dynamic_ocr.apply_slot_preset(preset)
        if not hasattr(s, "extra_telemetry") or not isinstance(s.extra_telemetry, dict):
            s.extra_telemetry = {}
        s.extra_telemetry["slot_metrics"] = {"preset": preset}
        return web.json_response({
            "success": True,
            "channel": channel,
            "preset": preset,
            "areas": areas,
        })

    async def get_slot_presets_handler(request):
        return web.json_response({"presets": list_available_presets()})

    app.router.add_get("/api/kick/slots-streams", get_kick_slots_streams_handler)
    app.router.add_post("/api/sessions/{channel}/slot-preset", post_slot_preset_handler)
    app.router.add_get("/api/slot-presets", get_slot_presets_handler)

    client = TestClient(TestServer(app))
    await client.start_server()

    try:
        # 1. Test GET /api/slot-presets
        resp = await client.get("/api/slot-presets")
        assert resp.status == 200
        data = await resp.json()
        assert "presets" in data
        assert len(data["presets"]) >= 4

        # 2. Test POST /api/sessions/{channel}/slot-preset
        post_resp = await client.post("/api/sessions/kickgambler/slot-preset", json={"preset": "nolimit_city"})
        assert post_resp.status == 200
        post_data = await post_resp.json()
        assert post_data["success"] is True
        assert post_data["preset"] == "nolimit_city"
        assert len(post_data["areas"]) >= 3

        # Verify session state updated
        assert session.dynamic_ocr.active_preset == "nolimit_city"
        assert session.extra_telemetry["slot_metrics"]["preset"] == "nolimit_city"

        # 3. Test GET /api/kick/slots-streams with mocked radar
        with patch.object(orch.kick_slot_radar, "discover_live_slots", return_value=[
            {
                "channel": "trainwreckstv",
                "channel_slug": "trainwreckstv",
                "title": "🚨 CRAZY SLOTS BONUS BUY SESSION 🚨",
                "session_title": "🚨 CRAZY SLOTS BONUS BUY SESSION 🚨",
                "viewer_count": 22500,
                "is_live": True,
                "profile_pic": "https://img.kick.com/train.jpg",
                "category": "Slots & Casino"
            }
        ]):
            radar_resp = await client.get("/api/kick/slots-streams")
            assert radar_resp.status == 200
            radar_data = await radar_resp.json()
            assert radar_data["count"] == 1
            assert radar_data["streams"][0]["channel_slug"] == "trainwreckstv"
            assert radar_data["streams"][0]["viewer_count"] == 22500
    finally:
        await client.close()
