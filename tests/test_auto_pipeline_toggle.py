import pytest
from services.orchestrator_dag import GraphDAGManager
from orchestrator import StreamClipperOrchestrator


def test_add_stream_pipeline_manual_mode_initial():
    """Verify that when auto_sequence is False, initial placeholder is replaced with a single isolated StreamSourceNode."""
    mgr = GraphDAGManager()
    graph = mgr.add_stream_pipeline("xqc", platform="kick", auto_sequence=False)

    # Exactly 1 node: the isolated StreamSourceNode
    assert len(graph["nodes"]) == 1
    stream_node = graph["nodes"][0]
    assert stream_node["type"] == "StreamSourceNode"
    assert stream_node["properties"]["channel"] == "xqc"
    assert stream_node["properties"]["platform"] == "kick"
    assert stream_node["title"] == "Kick Source: #xqc"

    # 0 wires: user must build and route nodes manually
    assert len(graph["wires"]) == 0

    # Valid DAG according to Kahn's algorithm
    valid, msg = mgr.validate_dag(mgr.nodes, mgr.wires)
    assert valid is True
    assert msg == "Valid DAG"


def test_add_stream_pipeline_manual_mode_secondary():
    """Verify that adding a secondary stream with auto_sequence=False appends an isolated StreamSourceNode with 0 wires."""
    mgr = GraphDAGManager()
    # First stream added with auto_sequence=True (full DAG)
    mgr.add_stream_pipeline("zarbex", platform="twitch", auto_sequence=True)
    initial_node_count = len(mgr.nodes)
    initial_wire_count = len(mgr.wires)

    # Second stream added with auto_sequence=False (manual mode)
    graph = mgr.add_stream_pipeline("trainwreckstv", platform="kick", auto_sequence=False)

    # Exactly 1 new node added
    assert len(graph["nodes"]) == initial_node_count + 1
    new_node = next((n for n in graph["nodes"] if n["id"] == "node_stream_trainwreckstv"), None)
    assert new_node is not None
    assert new_node["type"] == "StreamSourceNode"
    assert new_node["properties"]["channel"] == "trainwreckstv"
    assert new_node["properties"]["platform"] == "kick"

    # Wires count remains unchanged: no auto-wired downstream nodes for trainwreckstv
    assert len(graph["wires"]) == initial_wire_count
    for w in graph["wires"]:
        assert "trainwreckstv" not in w["from"]
        assert "trainwreckstv" not in w["to"]

    # Graph remains a valid DAG
    valid, msg = mgr.validate_dag(mgr.nodes, mgr.wires)
    assert valid is True


def test_add_stream_pipeline_auto_sequence_initial():
    """Verify that when auto_sequence is True, default template is configured with full clipping DAG."""
    mgr = GraphDAGManager()
    graph = mgr.add_stream_pipeline("tarik", platform="twitch", auto_sequence=True)

    node_types = [n["type"] for n in graph["nodes"]]
    assert "StreamSourceNode" in node_types
    assert "AudioMonitorNode" in node_types
    assert "ChatVelocityNode" in node_types
    assert "CVTransformerNode" in node_types
    assert "OCRVisionNode" in node_types
    assert "GateEvaluatorNode" in node_types
    assert "SegmentSlicerNode" in node_types
    assert "HardwareRenderNode" in node_types
    assert "ClipFolderNode" in node_types

    assert len(graph["wires"]) >= 12
    valid, msg = mgr.validate_dag(mgr.nodes, mgr.wires)
    assert valid is True


def test_add_stream_pipeline_auto_sequence_secondary():
    """Verify that adding a secondary stream with auto_sequence=True generates parallel workers and wires."""
    mgr = GraphDAGManager()
    mgr.add_stream_pipeline("streamer1", platform="twitch", auto_sequence=True)

    graph = mgr.add_stream_pipeline("streamer2", platform="kick", auto_sequence=True)
    s2_nodes = [n for n in graph["nodes"] if "streamer2" in n["id"]]
    assert len(s2_nodes) >= 7

    s2_wires = [w for w in graph["wires"] if "streamer2" in w["id"]]
    assert len(s2_wires) == 12

    valid, msg = mgr.validate_dag(mgr.nodes, mgr.wires)
    assert valid is True


@pytest.mark.asyncio
async def test_orchestrator_add_session_manual_toggle():
    """Verify orchestrator add_session propagates auto_sequence=False to GraphDAGManager."""
    orch = StreamClipperOrchestrator()
    orch.running = False

    status = await orch.add_session("slot_king", platform="kick", simulate=True, auto_sequence=False)
    assert status["channel"] == "slot_king"
    assert status["platform"] == "kick"

    graph = orch.graph_manager.get_graph()
    # Placeholder template should be replaced by single isolated stream node
    assert len(graph["nodes"]) == 1
    assert graph["nodes"][0]["properties"]["channel"] == "slot_king"
    assert len(graph["wires"]) == 0