"""Unit Tests for Stream Spying Keyword Surveillance Engine and DAG Node."""

import time
from unittest.mock import MagicMock
import pytest

from services.heuristics.stream_spy import StreamSpyService
from services.orchestrator_dag import GraphDAGManager


def test_stream_spy_service_lifecycle():
    """Verify keyword setting, substring vs word boundary regex, cooldown debounce, and velocity."""
    triggers = []
    service = StreamSpyService(
        keywords="clutch, ace, leak, drama",
        cooldown_seconds=10.0,
        case_sensitive=False,
        exact_match=False,
        on_trigger_callback=lambda event: triggers.append(event),
    )

    assert service.keywords == ["clutch", "ace", "leak", "drama"]
    assert service.match_count == 0

    t0 = 1000.0

    # 1. Match detected (substring, case-insensitive)
    ev1 = service.check_text("OMG that CLUTCH was crazy!", source="chat", user="shroud_fan", timestamp=t0)
    assert ev1 is not None
    assert ev1["keyword"] == "clutch"
    assert ev1["is_trigger"] is True
    assert ev1["is_cooldown"] is False
    assert service.match_count == 1
    assert len(triggers) == 1

    # 2. Match within cooldown window (t0 + 4s < t0 + 10s cooldown)
    ev2 = service.check_text("another clutch moment!", source="chat", user="viewer2", timestamp=t0 + 4.0)
    assert ev2 is not None
    assert ev2["keyword"] == "clutch"
    assert ev2["is_trigger"] is False
    assert ev2["is_cooldown"] is True
    assert service.match_count == 2
    assert len(triggers) == 1  # Callback not re-fired during cooldown

    # 3. Match after cooldown elapses (t0 + 11s)
    ev3 = service.check_text("major drama happening right now", source="chat", user="news_bot", timestamp=t0 + 11.0)
    assert ev3 is not None
    assert ev3["keyword"] == "drama"
    assert ev3["is_trigger"] is True
    assert ev3["is_cooldown"] is False
    assert service.match_count == 3
    assert len(triggers) == 2

    # 4. Keyword velocity test (3 hits in 11 seconds -> 3 hits/min in 60s sliding window)
    vel = service.get_keyword_velocity(now=t0 + 12.0)
    assert vel == 3.0

    # 5. Exact match / word-boundary mode test
    service.update_settings(exact_match=True, cooldown_seconds=1.0)
    # "palace" contains "ace" as substring, but not as whole word -> should NOT match
    assert service.check_text("heading to palace", source="chat", timestamp=t0 + 20.0) is None
    # "an ace" has word boundaries -> should match
    ev_exact = service.check_text("he got an ace!", source="chat", timestamp=t0 + 25.0)
    assert ev_exact is not None
    assert ev_exact["keyword"] == "ace"
    assert ev_exact["is_trigger"] is True

    # 6. Case sensitivity test
    service.update_settings(case_sensitive=True, cooldown_seconds=1.0)
    service.set_keywords(["LEAK"])
    assert service.check_text("this is a leak", source="chat", timestamp=t0 + 30.0) is None
    assert service.check_text("MAJOR LEAK ALERT", source="chat", timestamp=t0 + 35.0) is not None

    # 7. Modality toggles
    service.update_settings(listen_chat=False)
    assert service.check_text("LEAK in chat", source="chat", timestamp=t0 + 40.0) is None
    service.update_settings(listen_chat=True, listen_audio=False)
    assert service.check_text("LEAK spoken on mic", source="audio", timestamp=t0 + 41.0) is None

    # 8. Manual trigger
    man_ev = service.manual_trigger("test_alert", now=t0 + 50.0)
    assert man_ev["is_trigger"] is True
    assert man_ev["keyword"] == "test_alert"
    assert service.is_alert_active(now=t0 + 51.0) is True
    assert service.is_alert_active(now=t0 + 60.0) is False


def test_stream_spy_chat_and_audio_processing():
    """Verify chat message dict processing and audio transcript word processing."""
    service = StreamSpyService(keywords=["ban", "secret", "cheat"])

    # Chat message dictionary
    msg = {"user": "moderator", "text": "user has been banned for secret cheat", "time": 12345.0}
    res = service.process_chat_message(msg)
    assert res is not None
    assert res["keyword"] in ("ban", "secret", "cheat")
    assert res["user"] == "moderator"

    # Audio transcribed words sequence
    words = [
        {"word": "do", "start": 0.0, "end": 0.3},
        {"word": "not", "start": 0.3, "end": 0.5},
        {"word": "tell", "start": 0.5, "end": 0.8},
        {"word": "my", "start": 0.8, "end": 1.0},
        {"word": "secret", "start": 1.0, "end": 1.5},
    ]
    service.last_trigger_time = 0.0  # Clear cooldown
    audio_matches = service.process_audio_words(words)
    assert len(audio_matches) == 1
    assert audio_matches[0]["keyword"] == "secret"
    assert audio_matches[0]["source"] == "audio"
    assert audio_matches[0]["user"] == "streamer"


def test_stream_spy_node_in_dag():
    """Verify that StreamSpyNode connects to streams, slicers, and gates, and serializes telemetry."""
    mgr = GraphDAGManager()

    nodes = {
        "node_stream": {
            "id": "node_stream",
            "type": "StreamSourceNode",
            "title": "Twitch Source: #tarik",
            "properties": {"channel": "tarik", "platform": "twitch"},
            "outputs": [
                {"id": "video", "name": "Video Stream", "type": "video"},
                {"id": "audio", "name": "Audio Stream", "type": "audio"},
                {"id": "chat", "name": "Chat Stream", "type": "chat"},
            ],
            "inputs": [],
        },
        "node_spy": {
            "id": "node_spy",
            "type": "StreamSpyNode",
            "title": "Stream Keyword Spy",
            "properties": {
                "keywords": "clutch, ace, 1v5, drama",
                "cooldown_seconds": 5.0,
                "exact_match": True,
                "listen_chat": True,
                "listen_audio": True,
                "enabled": True,
            },
            "inputs": [
                {"id": "chat_in", "name": "Chat In", "type": "chat"},
                {"id": "audio_in", "name": "Audio In", "type": "audio"},
                {"id": "text_in", "name": "Text In", "type": "text"},
            ],
            "outputs": [
                {"id": "spy_trigger", "name": "Keyword Pulse", "type": "trigger"},
                {"id": "match_count", "name": "Total Matches", "type": "scalar"},
                {"id": "keyword_velocity", "name": "Velocity (/min)", "type": "scalar"},
                {"id": "last_keyword", "name": "Last Keyword", "type": "text"},
            ],
        },
        "node_slicer": {
            "id": "node_slicer",
            "type": "SegmentSlicerNode",
            "title": "Rolling Slicer",
            "properties": {"window_seconds": 60},
            "inputs": [
                {"id": "video_in", "name": "Video In", "type": "video"},
                {"id": "trigger_in", "name": "Trigger In", "type": "trigger"},
            ],
            "outputs": [
                {"id": "candidate_slice", "name": "Candidate Slice", "type": "video"},
            ],
        },
        "node_gate": {
            "id": "node_gate",
            "type": "ThresholdGateNode",
            "title": "Threshold Gate",
            "properties": {
                "logic_mode": "ALL",
                "debounce_seconds": 5.0,
                "rules": {
                    "val_1": {"operator": ">=", "threshold": 2.0},
                },
            },
            "inputs": [
                {"id": "val_1", "name": "Velocity In", "type": "scalar"},
            ],
            "outputs": [
                {"id": "trigger_out", "name": "Gate Trigger Out", "type": "trigger"},
            ],
        },
    }

    wires = [
        # Stream chat and audio into StreamSpyNode
        {"id": "w1", "from": "node_stream:chat", "to": "node_spy:chat_in", "type": "chat"},
        {"id": "w2", "from": "node_stream:audio", "to": "node_spy:audio_in", "type": "audio"},
        # Stream video into Slicer
        {"id": "w3", "from": "node_stream:video", "to": "node_slicer:video_in", "type": "video"},
        # Spy trigger fires Slicer directly!
        {"id": "w4", "from": "node_spy:spy_trigger", "to": "node_slicer:trigger_in", "type": "trigger"},
        # Spy velocity feeds ThresholdGateNode
        {"id": "w5", "from": "node_spy:keyword_velocity", "to": "node_gate:val_1", "type": "scalar"},
    ]

    # Validate DAG
    valid, reason = mgr.validate_dag(nodes, wires)
    assert valid is True, f"DAG validation failed: {reason}"

    # Load into manager
    mgr.nodes = nodes
    mgr.wires = wires

    # Test update_node_param
    mgr.update_node_param("node_spy", "keywords", "insane, unreal, 360")
    spy_service = mgr.get_or_create_stream_spy("node_spy")
    assert spy_service.keywords == ["insane", "unreal", "360"]

    mgr.update_node_param("node_spy", "cooldown_seconds", 8.0)
    assert spy_service.cooldown_seconds == 8.0

    mgr.update_node_param("node_spy", "pulse", True)
    assert spy_service.match_count == 1
    assert spy_service.last_keyword == "manual_spy"

    # Verify telemetry serialization
    payload = mgr.get_node_telemetry_payload()
    assert "node_spy" in payload
    spy_tel = payload["node_spy"]
    assert spy_tel["keywords"] == ["insane", "unreal", "360"]
    assert spy_tel["match_count"] == 1
    assert spy_tel["has_chat"] is True
    assert spy_tel["has_audio"] is True
    assert spy_tel["has_text"] is False

    # Verify upstream session resolution traces through StreamSpyNode
    mock_session = MagicMock()
    mock_session.channel = "tarik"
    mgr.orchestrator = MagicMock()
    mgr.orchestrator.sessions = {"tarik": mock_session}

    resolved = mgr.get_node_source_session("node_spy")
    assert resolved == mock_session
