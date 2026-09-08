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

