import pytest
from services.orchestrator_dag import GraphDAGManager, COMPATIBLE_TYPES, PORT_TYPES


def test_default_template_structure():
    """Verify that default graph template contains expected node catalog and wires."""
    mgr = GraphDAGManager()
    graph = mgr.get_graph()

    assert "nodes" in graph
    assert "wires" in graph
    assert len(graph["nodes"]) >= 5
    assert len(graph["wires"]) >= 5

    # Check StreamSourceNode
    stream_node = next((n for n in graph["nodes"] if n["type"] == "StreamSourceNode"), None)
    assert stream_node is not None
    output_types = [p["type"] for p in stream_node["outputs"]]
    assert "video" in output_types
    assert "audio" in output_types
    assert "chat" in output_types

    # Check AudioMonitorNode
    audio_node = next((n for n in graph["nodes"] if n["type"] == "AudioMonitorNode"), None)
    assert audio_node is not None
    assert audio_node["inputs"][0]["type"] == "audio"
    assert any(p["type"] == "trigger" for p in audio_node["outputs"])


def test_type_compatibility_validation():
    """Verify that type compatibility prevents illegal wire connections."""
    mgr = GraphDAGManager()
    nodes = {n["id"]: n for n in mgr.nodes.values()}

    # Valid wire: video -> video
    valid_wires = [
        {"id": "w_test", "from": "node_stream:video", "to": "node_ocr:video_in", "type": "video"}
    ]
    valid, msg = mgr.validate_dag(nodes, valid_wires)
    assert valid is True

    # Invalid wire: audio -> video_in
    invalid_wires = [
        {"id": "w_bad", "from": "node_stream:audio", "to": "node_ocr:video_in", "type": "audio"}
    ]
    valid, msg = mgr.validate_dag(nodes, invalid_wires)
    assert valid is False
    assert "Incompatible types" in msg


def test_cycle_detection_kahns_algorithm():
    """Verify that cycles are rejected to maintain a strict DAG."""
    mgr = GraphDAGManager()

    # Create cyclic nodes: A -> B -> C -> A
    cyclic_nodes = {
        "node_a": {
            "id": "node_a", "type": "TestNode",
            "inputs": [{"id": "in", "type": "trigger"}],
            "outputs": [{"id": "out", "type": "trigger"}]
        },
        "node_b": {
            "id": "node_b", "type": "TestNode",
            "inputs": [{"id": "in", "type": "trigger"}],
            "outputs": [{"id": "out", "type": "trigger"}]
        },
        "node_c": {
            "id": "node_c", "type": "TestNode",
            "inputs": [{"id": "in", "type": "trigger"}],
            "outputs": [{"id": "out", "type": "trigger"}]
        },
    }
    cyclic_wires = [
        {"id": "w1", "from": "node_a:out", "to": "node_b:in", "type": "trigger"},
        {"id": "w2", "from": "node_b:out", "to": "node_c:in", "type": "trigger"},
        {"id": "w3", "from": "node_c:out", "to": "node_a:in", "type": "trigger"},
    ]

    valid, msg = mgr.validate_dag(cyclic_nodes, cyclic_wires)
    assert valid is False
    assert "Cycle detected" in msg


def test_node_param_hot_reload():
    """Verify that update_node_param updates properties immediately."""
    mgr = GraphDAGManager()
    ok = mgr.update_node_param("node_audio", "jump_db_threshold", 16.5)
    assert ok is True
    assert mgr.nodes["node_audio"]["properties"]["jump_db_threshold"] == 16.5


def test_sync_graph_payload():
    """Verify that sync_graph applies new layout."""
    mgr = GraphDAGManager()
    payload = {
        "nodes": list(mgr.nodes.values()),
        "wires": mgr.wires,
    }
    ok, msg = mgr.sync_graph(payload)
    assert ok is True
    assert "synced" in msg.lower()


def test_stream_node_channel_switch():
    """Verify that switching channel on StreamSourceNode updates title and properties."""
    mgr = GraphDAGManager()
    ok = mgr.update_node_param("node_stream", "channel", "zarbex")
    assert ok is True
    assert mgr.nodes["node_stream"]["properties"]["channel"] == "zarbex"
    assert mgr.nodes["node_stream"]["title"] == "Twitch Source: #zarbex"


def test_multi_stream_routing_and_isolation():
    """Verify that worker nodes resolve exactly to the stream they are wired to (Twitch vs Kick)."""
    class MockSession:
        def __init__(self, channel, platform="twitch"):
            self.channel = channel
            self.platform = platform
            self.buffer = None
            self.chat_engine = None
            self.audio_monitor = None
            self.ocr_engine = None
            self.cv_service = None
            self.extra_telemetry = {
                "cv_top_label": f"{channel}_label",
                "cv_confidence": 0.88,
                "cv_probabilities": {f"{channel}_label": 0.88},
                "stream_frame_b64": f"data:image/jpeg;base64,{channel}_frame",
            }

    class MockOrchestrator:
        def __init__(self):
            self.sessions = {
                "twitch_stream": MockSession("twitch_stream", "twitch"),
                "kick_stream": MockSession("kick_stream", "kick"),
            }

    mgr = GraphDAGManager(orchestrator=MockOrchestrator())

    # Build a graph with 2 StreamSourceNodes (1 Twitch, 1 Kick) and 1 CVTransformerNode
    nodes = {
        "src_twitch": {
            "id": "src_twitch",
            "type": "StreamSourceNode",
            "properties": {"channel": "twitch_stream", "platform": "twitch"},
            "outputs": [{"id": "video", "type": "video"}],
        },
        "src_kick": {
            "id": "src_kick",
            "type": "StreamSourceNode",
            "properties": {"channel": "kick_stream", "platform": "kick"},
            "outputs": [{"id": "video", "type": "video"}],
        },
        "cv_node": {
            "id": "cv_node",
            "type": "CVTransformerNode",
            "properties": {"channel": "auto"},
            "inputs": [{"id": "video_in", "type": "video"}],
            "outputs": [{"id": "spike_trigger", "type": "trigger"}],
        },
    }

    # Case 1: Wire Kick stream to CVTransformerNode
    wires_kick = [
        {"id": "w1", "from": "src_kick:video", "to": "cv_node:video_in", "type": "video"}
    ]
    mgr.sync_graph({"nodes": list(nodes.values()), "wires": wires_kick})

    resolved_session = mgr.get_node_source_session("cv_node")
    assert resolved_session is not None
    assert resolved_session.channel == "kick_stream"
    assert resolved_session.platform == "kick"

    telemetry = mgr.get_node_telemetry_payload()
    assert telemetry["cv_node"]["source_channel"] == "kick_stream"
    assert telemetry["cv_node"]["top_label"] == "kick_stream_label"
    assert "twitch_stream" not in telemetry["cv_node"]["top_label"]

    # Case 2: Switch wire to Twitch stream
    wires_twitch = [
        {"id": "w2", "from": "src_twitch:video", "to": "cv_node:video_in", "type": "video"}
    ]
    mgr.sync_graph({"nodes": list(nodes.values()), "wires": wires_twitch})

    resolved_session = mgr.get_node_source_session("cv_node")
    assert resolved_session is not None
    assert resolved_session.channel == "twitch_stream"
    assert resolved_session.platform == "twitch"

    telemetry = mgr.get_node_telemetry_payload()
    assert telemetry["cv_node"]["source_channel"] == "twitch_stream"
    assert telemetry["cv_node"]["top_label"] == "twitch_stream_label"


def test_unrouted_node_telemetry_isolation():
    """Verify that newly spawned or unwired nodes return unrouted status and empty telemetry."""
    class MockSession:
        def __init__(self, channel):
            self.channel = channel
            self.buffer = None
            self.chat_engine = None
            self.extra_telemetry = {"cv_top_label": "action", "cv_confidence": 0.9}

    class MockOrchestrator:
        def __init__(self):
            self.sessions = {"twitch_stream": MockSession("twitch_stream")}

    mgr = GraphDAGManager(orchestrator=MockOrchestrator())

    # Add unwired CVTransformerNode
    nodes = {
        "src_twitch": {
            "id": "src_twitch",
            "type": "StreamSourceNode",
            "properties": {"channel": "twitch_stream"},
            "outputs": [{"id": "video", "type": "video"}],
        },
        "new_cv_node": {
            "id": "new_cv_node",
            "type": "CVTransformerNode",
            "properties": {"channel": "auto"},
            "inputs": [{"id": "video_in", "type": "video"}],
            "outputs": [{"id": "spike_trigger", "type": "trigger"}],
        },
    }
    # No wires to new_cv_node
    mgr.sync_graph({"nodes": list(nodes.values()), "wires": []})

    assert mgr.get_node_source_session("new_cv_node") is None

    telemetry = mgr.get_node_telemetry_payload()
    assert telemetry["new_cv_node"]["unrouted"] is True
    assert telemetry["new_cv_node"]["status"] == "unrouted"
    assert "top_label" not in telemetry["new_cv_node"]


def test_explicit_node_channel_override():
    """Verify that manually assigning a channel on a node overrides incoming wires."""
    class MockSession:
        def __init__(self, channel):
            self.channel = channel
            self.buffer = None
            self.chat_engine = None
            self.extra_telemetry = {"cv_top_label": f"{channel}_metric"}

    class MockOrchestrator:
        def __init__(self):
            self.sessions = {
                "twitch_stream": MockSession("twitch_stream"),
                "kick_stream": MockSession("kick_stream"),
            }

    mgr = GraphDAGManager(orchestrator=MockOrchestrator())

    nodes = {
        "src_twitch": {
            "id": "src_twitch",
            "type": "StreamSourceNode",
            "properties": {"channel": "twitch_stream"},
            "outputs": [{"id": "video", "type": "video"}],
        },
        "cv_node": {
            "id": "cv_node",
            "type": "CVTransformerNode",
            "properties": {"channel": "kick_stream"},  # Explicit override
            "inputs": [{"id": "video_in", "type": "video"}],
            "outputs": [{"id": "spike_trigger", "type": "trigger"}],
        },
    }
    # Wire from Twitch, but node is explicitly assigned to Kick
    wires = [{"id": "w1", "from": "src_twitch:video", "to": "cv_node:video_in", "type": "video"}]
    mgr.sync_graph({"nodes": list(nodes.values()), "wires": wires})

    resolved = mgr.get_node_source_session("cv_node")
    assert resolved is not None
    assert resolved.channel == "kick_stream"


