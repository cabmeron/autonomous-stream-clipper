import os
import time
import pytest
from PIL import Image

from services.heuristics.cv_transformer import (
    CVTransformerService,
    FrameExtractor,
    HeuristicVisionEngine,
    ONNXCoreMLVisionEngine,
)
from services.heuristics.gate_evaluator import GateEvaluator
from services.orchestrator_dag import GraphDAGManager


@pytest.fixture
def sample_image():
    """Creates a temporary RGB image for testing."""
    img = Image.new("RGB", (640, 360), color=(180, 140, 50))
    return img


def test_heuristic_vision_engine_classify(sample_image):
    engine = HeuristicVisionEngine()
    labels = ["gameplay action", "victory celebration", "defeat game over", "in-game menu"]
    probs = engine.classify(sample_image, labels)

    assert isinstance(probs, dict)
    assert len(probs) == len(labels)
    # Probabilities should sum to approximately 1.0
    total = sum(probs.values())
    assert abs(total - 1.0) < 0.05
    for l in labels:
        assert 0.0 <= probs[l] <= 1.0


def test_heuristic_vision_engine_detect(sample_image):
    engine = HeuristicVisionEngine()
    query_labels = ["streamer facecam", "hud status"]
    detections = engine.detect(sample_image, query_labels)

    assert isinstance(detections, list)
    assert len(detections) >= 2
    for det in detections:
        assert "label" in det
        assert "box" in det
        assert "score" in det
        assert len(det["box"]) == 4
        # Normalized bounding boxes [x, y, w, h] between 0 and 1
        for coord in det["box"]:
            assert 0.0 <= coord <= 1.0


def test_onnx_coreml_engine_initialization():
    engine = ONNXCoreMLVisionEngine()
    assert "coreml" in engine.engine_name.lower() or "onnx" in engine.engine_name.lower()


def test_cv_transformer_service_workflow(tmp_path, sample_image):
    # Save test image as png
    test_img_path = str(tmp_path / "test_frame.png")
    sample_image.save(test_img_path)

    triggered = []

    def on_trigger(res):
        triggered.append(res)

    service = CVTransformerService(
        candidate_labels=["gameplay action", "victory celebration", "menu"],
        trigger_labels=["victory celebration"],
        confidence_threshold=0.20,  # Low threshold to ensure trigger fires
        engine_type="heuristic",
        on_trigger_callback=on_trigger,
    )

    # Mock extract_frame to return sample_image directly
    service.extractor.extract_frame = lambda path: sample_image

    result = service.process_segment(test_img_path)
    assert result is not None
    assert "top_label" in result
    assert "confidence" in result
    assert "probabilities" in result
    assert "detections" in result
    assert "latency_ms" in result
    assert "thumbnail_b64" in result
    assert result["thumbnail_b64"].startswith("data:image/jpeg;base64,")

    # Dynamic hot-reloading
    service.set_candidate_labels(["action", "win", "loss"])
    assert service.candidate_labels == ["action", "win", "loss"]

    service.set_confidence_threshold(0.85)
    assert service.confidence_threshold == 0.85


def test_gate_evaluator_cv_integration():
    dispatched = []

    def on_dispatch(ctx):
        dispatched.append(ctx)

    gate = GateEvaluator(
        on_trigger_dispatch=on_dispatch,
        debounce_seconds=0.0,  # disable debounce for test
        post_event_delay_seconds=0.0,
    )

    # 1. Base signals below threshold (score < 4)
    score_low = gate.calculate_score(
        chat_instant=2.0,
        chat_ratio=1.0,
        win_multiplier=1.0,
        pnl_delta=0.0,
        audio_delta=2.0,
        cv_score=0.10,
        cv_label="in-game menu",
    )
    assert score_low < 4

    # 2. Victory celebration CV signal should boost score >= 4
    score_high = gate.calculate_score(
        chat_instant=2.0,
        chat_ratio=1.0,
        win_multiplier=1.0,
        pnl_delta=0.0,
        audio_delta=2.0,
        cv_score=0.88,
        cv_label="victory celebration",
    )
    assert score_high >= 5


def test_orchestrator_dag_cv_node():
    dag = GraphDAGManager()
    
    # Add a CVTransformerNode
    cv_node = {
        "id": "node_cv_test",
        "type": "CVTransformerNode",
        "title": "Hugging Face Vision",
        "category": "cv",
        "position": [440, 680],
        "properties": {
            "candidate_labels": "gameplay, victory, menu",
            "confidence_threshold": 0.75,
        },
        "inputs": [{"id": "video_in", "name": "Video In", "type": "video"}],
        "outputs": [
            {"id": "spike_trigger", "name": "Vision Trigger", "type": "trigger"},
            {"id": "confidence", "name": "Top Confidence", "type": "scalar"},
            {"id": "top_label", "name": "Top Class", "type": "text"},
        ],
    }
    dag.nodes["node_cv_test"] = cv_node

    # Wire video stream -> CV node -> gate
    dag.wires.append({"id": "w_cv_in", "from": "node_stream:video", "to": "node_cv_test:video_in", "type": "video"})
    dag.wires.append({"id": "w_cv_out", "from": "node_cv_test:spike_trigger", "to": "node_gate:trigger_1", "type": "trigger"})

    is_valid, msg = dag.validate_dag(dag.nodes, dag.wires)
    assert is_valid, f"DAG validation failed: {msg}"
