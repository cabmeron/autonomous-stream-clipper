import pytest
import time
from services.heuristics.timer_trigger import TimerTriggerService
from services.orchestrator_dag import GraphDAGManager


def test_timer_trigger_service_lifecycle():
    """Verify TimerTriggerService interval updates, countdown calculation, and pulses."""
    pulses = []
    service = TimerTriggerService(
        interval_seconds=10.0,
        on_trigger_callback=lambda count, ts: pulses.append((count, ts))
    )

    t0 = 1000.0
    service.last_trigger_time = t0

    # At t = 1004.0 (4 seconds elapsed, 6s remaining)
    telemetry = service.get_telemetry(now=1004.0)
    assert telemetry["interval_seconds"] == 10.0
    assert telemetry["countdown"] == 6.0
    assert telemetry["progress"] == 0.4
    assert telemetry["is_firing"] is False
    assert telemetry["trigger_count"] == 0
    assert service.check_trigger(now=1004.0) is False

    # At t = 1010.5 (10.5 seconds elapsed -> should trigger)
    assert service.check_trigger(now=1010.5) is True
    assert service.trigger_count == 1
    assert len(pulses) == 1
    assert pulses[0][0] == 1

    # Right after trigger, telemetry should report firing state
    telemetry_fired = service.get_telemetry(now=1011.0)
    assert telemetry_fired["is_firing"] is True
    assert telemetry_fired["countdown"] == 9.5
    assert telemetry_fired["status"] == "pulsing"

    # Test manual pulse
    assert service.manual_pulse(now=1015.0) is True
    assert service.trigger_count == 2
    assert len(pulses) == 2

    # Test updating interval
    service.update_interval(45.0)
    assert service.interval_seconds == 45.0
    telemetry_new = service.get_telemetry(now=1015.0)
    assert telemetry_new["interval_seconds"] == 45.0


def test_timer_trigger_node_in_dag():
    """Verify that TimerTriggerNode can be added to DAG, wired, validated, and serialized in telemetry."""
    mgr = GraphDAGManager()

    nodes = {
        "node_stream": {
            "id": "node_stream",
            "type": "StreamSourceNode",
            "title": "Twitch Source: #shroud",
            "properties": {"channel": "shroud", "platform": "twitch"},
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
                {"id": "sync_in", "name": "Sync / Reset In", "type": "trigger"},
            ],
            "outputs": [
                {"id": "trigger_out", "name": "Timer Pulse Out", "type": "trigger"},
                {"id": "video_out", "name": "Triggered Video Out", "type": "video"},
                {"id": "countdown", "name": "Countdown (s)", "type": "scalar"},
                {"id": "trigger_count", "name": "Pulses Fired", "type": "scalar"},
            ],
        },
        "node_gate": {
            "id": "node_gate",
            "type": "GateEvaluatorNode",
            "title": "Gate Evaluator",
            "inputs": [
                {"id": "trigger_1", "name": "Trigger In 1", "type": "trigger"},
            ],
            "outputs": [
                {"id": "clip_trigger", "name": "Clip Trigger", "type": "trigger"},
            ],
        },
        "node_cv": {
            "id": "node_cv",
            "type": "CVTransformerNode",
            "title": "Vision Transformer",
            "inputs": [
                {"id": "video_in", "name": "Video In", "type": "video"},
            ],
            "outputs": [
                {"id": "spike_trigger", "name": "Vision Trigger", "type": "trigger"},
            ],
        },
    }

    wires = [
        # Stream -> Timer video in
        {"id": "w1", "from": "node_stream:video", "to": "node_timer:video_in", "type": "video"},
        # Timer trigger out -> Gate trigger 1
        {"id": "w2", "from": "node_timer:trigger_out", "to": "node_gate:trigger_1", "type": "trigger"},
        # Timer video out -> CV video in
        {"id": "w3", "from": "node_timer:video_out", "to": "node_cv:video_in", "type": "video"},
    ]

    valid, msg = mgr.validate_dag(nodes, wires)
    assert valid is True, msg

    # Sync graph into manager
    success, sync_msg = mgr.sync_graph({"nodes": list(nodes.values()), "wires": wires})
    assert success is True, sync_msg

    # Test updating interval_seconds parameter via update_node_param
    mgr.update_node_param("node_timer", "interval_seconds", 15.0)
    assert mgr.nodes["node_timer"]["properties"]["interval_seconds"] == 15.0
    assert "15s" in mgr.nodes["node_timer"]["title"]

    # Test telemetry payload serialization
    payload = mgr.get_node_telemetry_payload()
    assert "node_timer" in payload
    timer_payload = payload["node_timer"]
    assert timer_payload["interval_seconds"] == 15.0
    assert "countdown" in timer_payload
    assert "is_firing" in timer_payload
    assert timer_payload["enabled"] is True

    # Test manual pulse via update_node_param
    mgr.update_node_param("node_timer", "pulse", True)
    timer_obj = mgr.node_timers["node_timer"]
    assert timer_obj.trigger_count >= 1
