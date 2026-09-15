import time
import pytest
from unittest.mock import MagicMock

from services.heuristics.simple_gate import SimpleGateService
from services.orchestrator_dag import GraphDAGManager


def test_simple_gate_service_lifecycle():
    """Verify SimpleGateService interval updates, countdown calculation, firing windows, and manual triggers."""
    fires = []
    service = SimpleGateService(
        interval_seconds=10.0,
        gate_duration=2.0,
        on_fire_callback=lambda count, ts: fires.append((count, ts))
    )

    t0 = 1000.0
    service.last_fire_time = t0

    # At t = 1004.0 (4 seconds elapsed, 6s remaining)
    telemetry = service.get_telemetry(now=1004.0)
    assert telemetry["interval_seconds"] == 10.0
    assert telemetry["gate_duration"] == 2.0
    assert telemetry["countdown"] == 6.0
    assert telemetry["progress"] == 0.4
    assert telemetry["is_open"] is False
    assert telemetry["is_firing"] is False
    assert telemetry["fire_count"] == 0
    assert telemetry["status"] == "armed"
    assert service.check_trigger(now=1004.0) is False

    # At t = 1010.5 (10.5 seconds elapsed -> should fire)
    assert service.check_trigger(now=1010.5) is True
    assert service.fire_count == 1
    assert len(fires) == 1
    assert fires[0][0] == 1

    # Within 2.0s open window (t = 1011.5 -> 1.0s elapsed of 2.0s window)
    assert service.is_gate_open(now=1011.5) is True
    telemetry_open = service.get_telemetry(now=1011.5)
    assert telemetry_open["is_open"] is True
    assert telemetry_open["is_firing"] is True
    assert telemetry_open["status"] == "firing"

    # After 2.0s open window (t = 1013.0 -> 2.5s elapsed)
    assert service.is_gate_open(now=1013.0) is False
    telemetry_closed = service.get_telemetry(now=1013.0)
    assert telemetry_closed["is_open"] is False
    assert telemetry_closed["status"] == "armed"

    # Test manual fire
    assert service.manual_fire(now=1015.0) is True
    assert service.fire_count == 2
    assert len(fires) == 2
    assert service.is_gate_open(now=1016.0) is True

    # Test updating interval and gate duration
    service.update_interval(60.0)
    service.update_duration(5.0)
    assert service.interval_seconds == 60.0
    assert service.gate_duration == 5.0
    telemetry_updated = service.get_telemetry(now=1016.0)
    assert telemetry_updated["interval_seconds"] == 60.0
    assert telemetry_updated["gate_duration"] == 5.0

    # Test disabled state
    service.enabled = False
    assert service.check_trigger(now=1080.0) is False
    assert service.get_telemetry(now=1080.0)["status"] == "paused"


def test_simple_gate_node_in_dag():
    """Verify that SimpleGateNode accepts video/audio/chat streams, routes upstream sessions, and fires outputs."""
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
        "node_gate": {
            "id": "node_gate",
            "type": "SimpleGateNode",
            "title": "Timed Gate: 30s",
            "properties": {"interval_seconds": 30.0, "gate_duration": 2.0, "enabled": True},
            "inputs": [
                {"id": "video_in", "name": "Video In", "type": "video"},
                {"id": "audio_in", "name": "Audio In", "type": "audio"},
                {"id": "chat_in", "name": "Chat In", "type": "chat"},
                {"id": "sync_in", "name": "Sync / Reset In", "type": "trigger"},
            ],
            "outputs": [
                {"id": "video_out", "name": "Gated Video Out", "type": "video"},
                {"id": "audio_out", "name": "Gated Audio Out", "type": "audio"},
                {"id": "chat_out", "name": "Gated Chat Out", "type": "chat"},
                {"id": "gate_trigger", "name": "Gate Fired Pulse", "type": "trigger"},
                {"id": "countdown", "name": "Countdown (s)", "type": "scalar"},
                {"id": "is_open", "name": "Gate Open (0/1)", "type": "scalar"},
            ],
        },
        "node_slicer": {
            "id": "node_slicer",
            "type": "SegmentSlicerNode",
            "title": "Segment Slicer",
            "inputs": [
                {"id": "video_in", "name": "Video In", "type": "video"},
                {"id": "trigger_in", "name": "Trigger In", "type": "trigger"},
            ],
            "outputs": [
                {"id": "candidate_slice", "name": "Candidate Slice", "type": "video"},
            ],
        },
        "node_evaluator": {
            "id": "node_evaluator",
            "type": "GateEvaluatorNode",
            "title": "Gate Evaluator",
            "inputs": [
                {"id": "trigger_1", "name": "Trigger In 1", "type": "trigger"},
            ],
            "outputs": [
                {"id": "clip_trigger", "name": "Clip Trigger Out", "type": "trigger"},
            ],
        },
    }

    wires = [
        # Stream -> SimpleGate video, audio, chat
        {"id": "w1", "from": "node_stream:video", "to": "node_gate:video_in", "type": "video"},
        {"id": "w2", "from": "node_stream:audio", "to": "node_gate:audio_in", "type": "audio"},
        {"id": "w3", "from": "node_stream:chat", "to": "node_gate:chat_in", "type": "chat"},
        # SimpleGate video_out -> Slicer video_in
        {"id": "w4", "from": "node_gate:video_out", "to": "node_slicer:video_in", "type": "video"},
        # SimpleGate gate_trigger -> Slicer trigger_in
        {"id": "w5", "from": "node_gate:gate_trigger", "to": "node_slicer:trigger_in", "type": "trigger"},
        # SimpleGate gate_trigger -> Evaluator trigger_1
        {"id": "w6", "from": "node_gate:gate_trigger", "to": "node_evaluator:trigger_1", "type": "trigger"},
    ]

    # Validate DAG connections
    valid, msg = mgr.validate_dag(nodes, wires)
    assert valid is True, msg

    # Sync DAG into manager
    success, sync_msg = mgr.sync_graph({"nodes": list(nodes.values()), "wires": wires})
    assert success is True, sync_msg

    # Mock orchestrator and stream session
    mock_session = MagicMock()
    mock_session.channel = "tarik"
    mock_session.extra_telemetry = {"stream_frame_b64": "data:image/jpeg;base64,mockframe"}
    mock_orchestrator = MagicMock()
    mock_orchestrator.sessions = {"tarik": mock_session}
    mgr.orchestrator = mock_orchestrator

    # Verify upstream session resolution traces through SimpleGateNode to StreamSourceNode
    resolved_slicer_sess = mgr.get_node_source_session("node_slicer")
    assert resolved_slicer_sess is not None
    assert resolved_slicer_sess.channel == "tarik"

    # Mutate parameters via update_node_param
    mgr.update_node_param("node_gate", "interval_seconds", 20.0)
    assert mgr.nodes["node_gate"]["properties"]["interval_seconds"] == 20.0
    assert "20s" in mgr.nodes["node_gate"]["title"]

    mgr.update_node_param("node_gate", "gate_duration", 4.0)
    gate_obj = mgr.node_simple_gates["node_gate"]
    assert gate_obj.interval_seconds == 20.0
    assert gate_obj.gate_duration == 4.0

    # Trigger manual pulse via update_node_param
    mgr.update_node_param("node_gate", "pulse", True)
    assert gate_obj.fire_count >= 1

    # Verify telemetry payload
    payload = mgr.get_node_telemetry_payload()
    assert "node_gate" in payload
    gate_payload = payload["node_gate"]
    assert gate_payload["interval_seconds"] == 20.0
    assert gate_payload["gate_duration"] == 4.0
    assert gate_payload["has_video"] is True
    assert gate_payload["has_audio"] is True
    assert gate_payload["has_chat"] is True
    assert gate_payload["enabled"] is True
    assert gate_payload["fire_count"] >= 1
    assert "countdown" in gate_payload
