import os
import time
import pytest
from PIL import Image
from unittest.mock import MagicMock

from services.heuristics.geo_estimation import GeoEstimationService
from services.orchestrator_dag import GraphDAGManager


def test_geo_estimation_service_initialization_and_lookup():
    """Verify S2 cell tables load properly and country resolver functions."""
    service = GeoEstimationService()
    assert service.num_classes >= 7000, f"Expected >= 7000 classes, got {service.num_classes}"
    assert service.lats is not None
    assert service.lngs is not None

    # Test coordinate country resolver
    us_name, us_code, us_flag = service.resolve_country(37.7749, -122.4194)  # San Francisco
    assert us_code == "US"
    assert "United States" in us_name
    assert us_flag == "🇺🇸"

    jp_name, jp_code, jp_flag = service.resolve_country(35.6762, 139.6503)  # Tokyo
    assert jp_code == "JP"
    assert jp_flag == "🇯🇵"

    gb_name, gb_code, gb_flag = service.resolve_country(51.5074, -0.1278)  # London
    assert gb_code == "GB"
    assert gb_flag == "🇬🇧"

    # Test fallback
    fall_name, fall_code, fall_flag = service.resolve_country(-15.0, 130.0)  # Australia/Oceania
    assert fall_code in ("AU", "OC")


def test_geo_estimation_frame_prediction():
    """Verify frame prediction returns valid coordinates, country, and OpenStreetMap URL."""
    service = GeoEstimationService()

    # Create synthetic test image (e.g. 320x240 RGB landscape)
    test_img = Image.new("RGB", (320, 240), color=(73, 109, 137))

    res = service.predict_frame(test_img)
    assert "lat" in res
    assert "lng" in res
    assert "confidence" in res
    assert "country" in res
    assert "country_code" in res
    assert "flag" in res
    assert "latency_ms" in res
    assert "status" in res
    assert "osm_url" in res
    assert "geo_trigger" in res
    assert "https://www.openstreetmap.org" in res["osm_url"]
    assert -90.0 <= res["lat"] <= 90.0
    assert -180.0 <= res["lng"] <= 180.0

    # Test with ROI crop
    roi = {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}
    res_roi = service.predict_frame(test_img, roi=roi)
    assert res_roi["lat"] is not None


def test_geo_estimation_scheduling_and_pulse():
    """Verify should_run logic with interval timing and manual/timer triggers."""
    service = GeoEstimationService()
    service.interval_seconds = 20.0
    service.last_run_time = time.time()

    # Right after running, should not run without pulse
    assert service.should_run(timer_pulse=False, force=False) is False

    # When timer pulse arrives from upstream TimerTriggerNode
    assert service.should_run(timer_pulse=True, force=False) is True

    # When manual pulse requested from UI
    service.manual_pulse()
    assert service.should_run(timer_pulse=False, force=False) is True

    # After predict_frame runs, manual pulse flag is cleared
    test_img = Image.new("RGB", (64, 64), color=(100, 100, 100))
    service.predict_frame(test_img)
    assert service.manual_pulse_flag is False

    # Test disabled state
    service.enabled = False
    assert service.should_run(timer_pulse=True, force=False) is False


def test_geo_estimation_node_in_dag():
    """Verify GeoEstimationNode can be wired in DAG downstream of TimerTriggerNode and upstream of ThresholdGateNode."""
    mgr = GraphDAGManager()

    nodes = {
        "node_stream": {
            "id": "node_stream",
            "type": "StreamSourceNode",
            "title": "Twitch Source: #geoguessr",
            "properties": {"channel": "geoguessr", "platform": "twitch"},
            "outputs": [
                {"id": "video", "name": "Video Stream", "type": "video"},
            ],
            "inputs": [],
        },
        "node_timer": {
            "id": "node_timer",
            "type": "TimerTriggerNode",
            "title": "Timer Trigger: 30s",
            "properties": {"interval_seconds": 30.0, "enabled": True},
            "inputs": [
                {"id": "video_in", "name": "Video In", "type": "video"},
            ],
            "outputs": [
                {"id": "trigger_out", "name": "Timer Pulse Out", "type": "trigger"},
                {"id": "video_out", "name": "Triggered Video Out", "type": "video"},
            ],
        },
        "node_geo": {
            "id": "node_geo",
            "type": "GeoEstimationNode",
            "title": "GeoEstimation Worldwide",
            "properties": {"interval_seconds": 30.0, "confidence_threshold": 60.0, "enabled": True},
            "inputs": [
                {"id": "video_in", "name": "Video In", "type": "video"},
                {"id": "trigger_in", "name": "Trigger In", "type": "trigger"},
            ],
            "outputs": [
                {"id": "lat", "name": "Latitude", "type": "scalar"},
                {"id": "lng", "name": "Longitude", "type": "scalar"},
                {"id": "confidence", "name": "Confidence %", "type": "scalar"},
                {"id": "geo_trigger", "name": "Geo Match Trigger", "type": "trigger"},
                {"id": "location_name", "name": "Country / Region", "type": "text"},
            ],
        },
        "node_gate": {
            "id": "node_gate",
            "type": "ThresholdGateNode",
            "title": "Confidence Gate",
            "properties": {
                "rules": {
                    "val_1": {"threshold": 50.0, "operator": ">=", "label": "Confidence %"}
                },
                "logic_mode": "ALL",
            },
            "inputs": [
                {"id": "val_1", "name": "Value In 1", "type": "scalar"},
            ],
            "outputs": [
                {"id": "trigger_out", "name": "Gate Trigger Out", "type": "trigger"},
            ],
        },
    }

    wires = [
        # Stream -> Timer
        {"id": "w1", "from": "node_stream:video", "to": "node_timer:video_in", "type": "video"},
        # Timer video out -> GeoEstimation video in
        {"id": "w2", "from": "node_timer:video_out", "to": "node_geo:video_in", "type": "video"},
        # Timer trigger out -> GeoEstimation trigger in
        {"id": "w3", "from": "node_timer:trigger_out", "to": "node_geo:trigger_in", "type": "trigger"},
        # GeoEstimation confidence -> Gate val_1
        {"id": "w4", "from": "node_geo:confidence", "to": "node_gate:val_1", "type": "scalar"},
    ]

    valid, msg = mgr.validate_dag(nodes, wires)
    assert valid is True, msg

    # Sync DAG
    success, sync_msg = mgr.sync_graph({"nodes": list(nodes.values()), "wires": wires})
    assert success is True, sync_msg

    # Create mock session
    mock_session = MagicMock()
    mock_session.channel = "geoguessr"
    mock_session.geo_service = GeoEstimationService()
    mock_session.extra_telemetry = {
        "geo_lat": 48.8566,
        "geo_lng": 2.3522,
        "geo_confidence": 88.5,
        "geo_country": "France",
        "geo_country_code": "FR",
        "geo_flag": "🇫🇷",
        "geo_location_name": "France",
        "geo_latency_ms": 15.2,
        "geo_status": "locked",
        "geo_trigger": True,
        "geo_osm_url": "https://www.openstreetmap.org/?mlat=48.8566&mlon=2.3522#map=10/48.8566/2.3522",
        "stream_frame_b64": "",
    }

    mock_orchestrator = MagicMock()
    mock_orchestrator.sessions = {"geoguessr": mock_session}
    mgr.orchestrator = mock_orchestrator

    # Test update_node_param
    mgr.update_node_param("node_geo", "confidence_threshold", 75.0)
    assert mgr.nodes["node_geo"]["properties"]["confidence_threshold"] == 75.0
    assert mock_session.geo_service.confidence_threshold == 75.0

    mgr.update_node_param("node_geo", "interval_seconds", 45.0)
    assert mock_session.geo_service.interval_seconds == 45.0

    mgr.update_node_param("node_geo", "pulse", True)
    assert mock_session.geo_service.manual_pulse_flag is True

    # Test telemetry payload serialization
    payload = mgr.get_node_telemetry_payload()
    assert "node_geo" in payload
    geo_payload = payload["node_geo"]
    assert geo_payload["lat"] == 48.8566
    assert geo_payload["lng"] == 2.3522
    assert geo_payload["confidence"] == 88.5
    assert geo_payload["country"] == "France"
    assert geo_payload["flag"] == "🇫🇷"
    assert geo_payload["status"] == "locked"
    assert geo_payload["geo_trigger"] is True
    assert "openstreetmap.org" in geo_payload["osm_url"]

    # Test ThresholdGateNode evaluation using GeoEstimationNode confidence
    assert "node_gate" in payload
    gate_payload = payload["node_gate"]
    assert gate_payload["total_connected"] == 1
    assert gate_payload["passed_count"] == 1  # 88.5 >= 50.0 threshold
    assert gate_payload["inputs"]["val_1"]["value"] == 88.5
    assert gate_payload["inputs"]["val_1"]["passed"] is True
