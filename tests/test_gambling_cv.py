"""Unit test suite for gambling intelligence, streamer emotion, and OCR heuristics."""

import pytest
from PIL import Image
import numpy as np

from services.heuristics.streamer_emotion import StreamerEmotionService, EMOTION_CLASSES
from services.heuristics.gambling_ocr import GamblingOCREngine, CASINO_PRESETS
from services.heuristics.gambling_ledger import GamblingLedger
from services.orchestrator_dag import GraphDAGManager


# ==========================================
# 1. Streamer Emotion & Tilt Engine Tests
# ==========================================

def test_streamer_emotion_basic_analysis():
    from services.heuristics.streamer_emotion import FERPLUS_CLASSES

    svc = StreamerEmotionService()
    
    # Create test image 640x360
    img = Image.new("RGB", (640, 360), color=(180, 140, 130))
    metrics = svc.process_frame(img)

    assert "top_emotion" in metrics
    assert metrics["top_emotion"] in FERPLUS_CLASSES or metrics["top_emotion"] in EMOTION_CLASSES
    assert -1.0 <= metrics["valence"] <= 1.0
    assert 0.0 <= metrics["arousal"] <= 1.0
    assert 0.0 <= metrics["tilt_score"] <= 100.0
    assert 0.0 <= metrics["euphoria_score"] <= 100.0
    assert "emotions" in metrics
    assert len(metrics["emotions"]) in (len(FERPLUS_CLASSES), len(EMOTION_CLASSES))


def test_streamer_emotion_roi_clamping_and_crop():
    svc = StreamerEmotionService()
    svc.update_roi(x=-0.5, y=1.5, w=0.01, h=2.0)
    
    # Check clamping
    assert svc.face_roi["x"] == 0.0
    assert svc.face_roi["y"] == 1.0
    assert svc.face_roi["w"] == 0.05
    assert svc.face_roi["h"] == 1.0

    svc.update_roi(x=0.1, y=0.1, w=0.3, h=0.4)
    frame = Image.new("RGB", (1000, 1000), color="blue")
    cropped = svc.crop_face(frame)
    assert cropped.size == (300, 400)


def test_tilt_score_loss_streak_and_bet_escalation():
    svc = StreamerEmotionService()
    
    # Neutral emotion probabilities
    probs = {"joy": 0.05, "shock": 0.05, "rage": 0.50, "despair": 0.30, "neutral": 0.10, "arousal": 0.8}
    
    # Baseline tilt
    tilt_baseline = svc.compute_tilt_score(probs)
    
    # Add context: 6-loss streak + 2.5x bet escalation (chasing)
    svc.update_gambling_context(loss_streak=6, bet_escalation=2.5)
    tilt_escalated = svc.compute_tilt_score(probs)

    assert tilt_escalated > tilt_baseline
    assert tilt_escalated <= 100.0


def test_emotion_spike_callbacks():
    tilt_spikes = []
    euphoria_spikes = []

    svc = StreamerEmotionService(
        tilt_threshold=50.0,
        euphoria_threshold=50.0,
        on_tilt_spike=lambda m: tilt_spikes.append(m),
        on_euphoria_spike=lambda m: euphoria_spikes.append(m),
    )

    # Force rage/despair with high loss streak
    svc.update_gambling_context(loss_streak=10, bet_escalation=3.0)
    # Bright red image triggering rage
    red_img = Image.new("RGB", (320, 240), color=(255, 30, 30))
    res = svc.process_frame(red_img)
    
    # Either rage or tilt triggered callback if threshold passed
    if res["is_tilt_spike"]:
        assert len(tilt_spikes) >= 1


# ==========================================
# 2. Gambling OCR Engine Tests
# ==========================================

def test_gambling_ocr_currency_parsing():
    ocr = GamblingOCREngine()

    # Standard formats
    assert ocr.parse_currency("$1,500.50") == 1500.50
    assert ocr.parse_currency("€250.00") == 250.00
    assert ocr.parse_currency("£99.99") == 99.99
    assert ocr.parse_currency("500") == 500.0

    # Multiplier / K suffix
    assert ocr.parse_currency("25.5k") == 25500.0
    assert ocr.parse_currency("1.2M") == 1200000.0
    assert ocr.parse_currency("10k") == 10000.0

    # European notation comma/dot normalization
    assert ocr.parse_currency("1.250,50") == 1250.50

    # Invalid input
    assert ocr.parse_currency("") is None
    assert ocr.parse_currency("BALANCE ONLY") is None


def test_gambling_ocr_multiplier_parsing():
    ocr = GamblingOCREngine()

    assert ocr.parse_multiplier("150x") == 150.0
    assert ocr.parse_multiplier("x50") == 50.0
    assert ocr.parse_multiplier("MEGA WIN 250.5X") == 250.5
    assert ocr.parse_multiplier("X 1000") == 1000.0
    assert ocr.parse_multiplier("NO MULT") is None


def test_gambling_ocr_presets_and_rois():
    ocr = GamblingOCREngine(preset="pragmatic_standard")
    assert "balance" in ocr.rois
    assert "bet" in ocr.rois
    assert "win" in ocr.rois
    assert "reels" in ocr.rois

    # Switch to hacksaw
    ocr.set_preset("hacksaw_standard")
    assert ocr.rois["bet"]["x"] == CASINO_PRESETS["hacksaw_standard"]["bet"]["x"]

    # Update single ROI
    ocr.update_roi("balance", 0.1, 0.2, 0.3, 0.4)
    assert ocr.rois["balance"] == {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}

    # Region cropping
    frame = Image.new("RGB", (1000, 1000), color="green")
    cropped = ocr.crop_region(frame, "balance")
    assert cropped.size == (300, 400)


def test_gambling_ocr_spin_motion():
    ocr = GamblingOCREngine()

    # Initial frame -> IDLE
    frame1 = Image.new("RGB", (200, 200), color=(50, 50, 50))
    s1 = ocr.detect_spin_state(frame1)
    assert s1 == "IDLE"

    # Similar frame -> IDLE
    frame2 = Image.new("RGB", (200, 200), color=(52, 52, 52))
    s2 = ocr.detect_spin_state(frame2)
    assert s2 == "IDLE"

    # Drastically different frame -> SPINNING
    frame3 = Image.new("RGB", (200, 200), color=(250, 250, 250))
    s3 = ocr.detect_spin_state(frame3)
    assert s3 in ("SPINNING", "WIN_CELEBRATION")


# ==========================================
# 3. Gambling Ledger & Tilt Chasing Tests
# ==========================================

def test_gambling_ledger_session_analytics():
    ledger = GamblingLedger(initial_balance=1000.0, baseline_bet=20.0)

    assert ledger.get_net_pnl() == 0.0
    assert ledger.get_winrate_pct() == 0.0
    assert ledger.get_experienced_rtp() == 100.0

    # Spin 1: $20 bet, $0 win (loss)
    ledger.record_spin_outcome(bet_amount=20.0, win_amount=0.0)
    assert ledger.total_spins == 1
    assert ledger.losing_spins == 1
    assert ledger.current_streak == -1
    assert ledger.multiplier_distribution["<2x"] == 1

    # Spin 2: $20 bet, $100 win (5x)
    ledger.record_spin_outcome(bet_amount=20.0, win_amount=100.0)
    assert ledger.total_spins == 2
    assert ledger.winning_spins == 1
    assert ledger.current_streak == 1
    assert ledger.multiplier_distribution["2x-10x"] == 1
    assert ledger.get_winrate_pct() == 50.0
    assert ledger.get_experienced_rtp() == 250.0  # $100 payout / $40 wagered = 250%


def test_gambling_ledger_martingale_loss_chasing():
    tilt_alerts = []
    ledger = GamblingLedger(
        initial_balance=500.0,
        baseline_bet=10.0,
        on_tilt_bet=lambda a: tilt_alerts.append(a),
    )

    # 3 consecutive losses at base bet
    ledger.record_spin_outcome(10.0, 0.0)
    ledger.record_spin_outcome(10.0, 0.0)
    ledger.record_spin_outcome(10.0, 0.0)
    assert ledger.current_streak == -3
    assert ledger.is_chasing_losses is False

    # 4th spin: Martingale double-up ($25 bet > 1.95x baseline of $10)
    ledger.record_spin_outcome(25.0, 0.0)
    assert ledger.current_streak == -4
    assert ledger.is_chasing_losses is True
    assert len(tilt_alerts) == 1
    assert tilt_alerts[0]["escalation_ratio"] == 2.5
    assert tilt_alerts[0]["loss_streak"] == 4


def test_gambling_ledger_big_win_callback():
    big_wins = []
    ledger = GamblingLedger(
        initial_balance=2000.0,
        big_win_multiplier=50.0,
        on_big_win=lambda w: big_wins.append(w),
    )

    # Spin with 75x multiplier
    ledger.record_spin_outcome(bet_amount=20.0, win_amount=1500.0, multiplier=75.0)
    assert len(big_wins) == 1
    assert big_wins[0]["multiplier"] == 75.0
    assert ledger.multiplier_distribution["50x-100x"] == 1


def test_gambling_ledger_drawdown():
    ledger = GamblingLedger()
    ledger.set_starting_balance(1000.0)
    
    # Balance moves up to 1500 (new peak)
    ledger.update_from_ocr({"balance": 1500.0, "spin_state": "IDLE"})
    dd_dlrs, dd_pct = ledger.get_drawdown()
    assert dd_dlrs == 0.0
    assert dd_pct == 0.0

    # Balance drops to 1200
    ledger.update_from_ocr({"balance": 1200.0, "spin_state": "IDLE"})
    dd_dlrs, dd_pct = ledger.get_drawdown()
    assert dd_dlrs == 300.0
    assert dd_pct == 20.0


# ==========================================
# 4. DAG Integration & Parameter Hot-Reload
# ==========================================

def test_dag_gambling_nodes_hot_reload():
    mgr = GraphDAGManager()
    
    # Add FacecamEmotionNode to graph
    mgr.nodes["node_face"] = {
        "id": "node_face",
        "type": "FacecamEmotionNode",
        "title": "Facecam Emotion & Tilt",
        "properties": {
            "tilt_threshold": 65.0,
            "euphoria_threshold": 75.0,
        },
        "inputs": [{"id": "video_in", "name": "Video Frame", "type": "video"}],
        "outputs": [
            {"id": "tilt_trigger", "name": "Tilt Spike Trigger", "type": "trigger"},
            {"id": "tilt_score", "name": "Tilt Index (0-100)", "type": "score"},
        ],
    }

    # Add VideoCropNode to graph
    mgr.nodes["node_crop"] = {
        "id": "node_crop",
        "type": "VideoCropNode",
        "title": "Slot HUD Crop",
        "properties": {
            "preset": "slot_hud",
            "roi": {"x": 0.05, "y": 0.92, "w": 0.18, "h": 0.06},
        },
        "inputs": [{"id": "video_in", "name": "Video Frame", "type": "video"}],
        "outputs": [
            {"id": "video_out", "name": "Cropped Video", "type": "video"},
        ],
    }

    # Test parameter hot-reload
    assert mgr.update_node_param("node_face", "tilt_threshold", 75.0) is True
    assert mgr.nodes["node_face"]["properties"]["tilt_threshold"] == 75.0

    # Test ROI parameter update on VideoCropNode
    new_bal_roi = {"x": 0.10, "y": 0.88, "w": 0.20, "h": 0.08}
    assert mgr.update_node_param("node_crop", "roi", new_bal_roi) is True
    assert mgr.nodes["node_crop"]["properties"]["roi"] == new_bal_roi


def test_video_crop_to_emotion_classifier_roi_propagation():
    """Verifies VideoCropNode wiring to FacecamEmotionNode propagates ROI and generates cropped face thumbnail."""
    svc = StreamerEmotionService()
    img = Image.new("RGB", (640, 360), color=(120, 80, 70))
    metrics = svc.process_frame(img)
    assert "face_thumbnail_b64" in metrics
    assert metrics["face_thumbnail_b64"].startswith("data:image/jpeg;base64,")

    # Set up mock session and orchestrator
    class MockSession:
        def __init__(self):
            self.channel = "tarik"
            self.buffer = None
            self.streamer_emotion = StreamerEmotionService()
            self.extra_telemetry = {
                "stream_frame_b64": "data:image/jpeg;base64,full_frame",
                "emotion_thumbnail_b64": "data:image/jpeg;base64,cropped_face",
            }

    class MockOrchestrator:
        def __init__(self):
            self.sessions = {"tarik": MockSession()}

    mgr = GraphDAGManager(orchestrator=MockOrchestrator())
    # Add StreamSourceNode
    mgr.nodes["src"] = {
        "id": "src",
        "type": "StreamSourceNode",
        "properties": {"channel": "tarik"},
        "outputs": [{"id": "video", "type": "video"}],
    }
    # Add VideoCropNode
    crop_roi = {"x": 0.76, "y": 0.05, "w": 0.22, "h": 0.28}
    mgr.nodes["crop"] = {
        "id": "crop",
        "type": "VideoCropNode",
        "properties": {"roi": crop_roi},
        "inputs": [{"id": "video_in", "type": "video"}],
        "outputs": [{"id": "video_out", "type": "video"}],
    }
    # Add FacecamEmotionNode
    mgr.nodes["face"] = {
        "id": "face",
        "type": "FacecamEmotionNode",
        "properties": {},
        "inputs": [{"id": "video_in", "type": "video"}],
        "outputs": [{"id": "tilt_score", "type": "score"}],
    }
    # Connect src -> crop -> face
    mgr.wires = [
        {"id": "w1", "from": "src:video", "to": "crop:video_in", "type": "video"},
        {"id": "w2", "from": "crop:video_out", "to": "face:video_in", "type": "video"},
    ]

    # Apply to orchestrator
    mgr._apply_graph_to_orchestrator()

    session = mgr.orchestrator.sessions["tarik"]
    assert session.streamer_emotion.face_roi["x"] == 0.76
    assert session.streamer_emotion.face_roi["y"] == 0.05
    assert session.streamer_emotion.face_roi["w"] == 0.22
    assert session.streamer_emotion.face_roi["h"] == 0.28

    # Verify telemetry payload prefers cropped thumbnail
    payload = mgr.get_node_telemetry_payload()
    assert "face" in payload
    assert payload["face"]["stream_frame_b64"] == "data:image/jpeg;base64,cropped_face"
    assert payload["face"]["face_thumbnail_b64"] == "data:image/jpeg;base64,cropped_face"


def test_ferplus_onnx_model_loading_and_8_classes():
    """Verifies Microsoft FERPlus 8-class ONNX inference, tensor shape, and metric computation."""
    from services.heuristics.streamer_emotion import StreamerEmotionService, FERPLUS_CLASSES

    svc = StreamerEmotionService(model_name="ferplus")
    assert svc.model_name == "ferplus"
    assert svc.ferplus_net is not None or svc.ort_ferplus_session is not None

    test_frame = Image.new("RGB", (320, 240), color=(120, 110, 100))
    metrics = svc.process_frame(test_frame)

    assert "emotions" in metrics
    for cls_name in FERPLUS_CLASSES:
        assert cls_name in metrics["emotions"]
        assert 0.0 <= metrics["emotions"][cls_name] <= 1.0

    assert len(metrics["emotions"]) == 8
    prob_sum = sum(metrics["emotions"].values())
    assert 0.98 <= prob_sum <= 1.02

    assert "raw_logits" in metrics
    assert len(metrics["raw_logits"]) == 8
    for cls_name in FERPLUS_CLASSES:
        assert cls_name in metrics["raw_logits"]
        assert isinstance(metrics["raw_logits"][cls_name], float)

    assert -1.0 <= metrics["valence"] <= 1.0
    assert 0.0 <= metrics["arousal"] <= 1.0
    assert 0.0 <= metrics["tilt_score"] <= 100.0
    assert 0.0 <= metrics["euphoria_score"] <= 100.0
    assert metrics["latency_ms"] >= 0.0
    assert metrics["model"] == "ferplus"


def test_ferplus_tilt_and_contempt_metric():
    """Verifies that contempt and anger directly elevate the calculated tilt index."""
    from services.heuristics.streamer_emotion import StreamerEmotionService

    svc = StreamerEmotionService(model_name="ferplus")

    # Calm / happy baseline
    calm_probs = {"happiness": 0.85, "neutral": 0.10, "arousal": 0.4}
    tilt_calm = svc.compute_tilt_score(calm_probs)

    # Frustrated with contempt & anger
    tilt_probs = {"anger": 0.60, "contempt": 0.30, "disgust": 0.05, "sadness": 0.05, "arousal": 0.8}
    tilt_spiked = svc.compute_tilt_score(tilt_probs)

    assert tilt_spiked > tilt_calm
    assert tilt_spiked >= 35.0  # Significant tilt pressure


def test_dag_emotion_model_hot_reload():
    """Verifies that switching model from 'ferplus' to 'mobilefacenet' dynamically updates DAG session."""
    class MockSession:
        def __init__(self):
            self.channel = "shroud"
            self.streamer_emotion = StreamerEmotionService(model_name="ferplus")
            self.extra_telemetry = {}

    class MockOrchestrator:
        def __init__(self):
            self.sessions = {"shroud": MockSession()}

    mgr = GraphDAGManager(orchestrator=MockOrchestrator())
    mgr.nodes["face_node"] = {
        "id": "face_node",
        "type": "FacecamEmotionNode",
        "properties": {"model": "ferplus"},
        "inputs": [{"id": "video_in", "type": "video"}],
        "outputs": [{"id": "tilt_score", "type": "score"}],
    }
    mgr.nodes["src"] = {
        "id": "src",
        "type": "StreamSourceNode",
        "properties": {"channel": "shroud"},
        "outputs": [{"id": "video", "type": "video"}],
    }
    mgr.wires = [{"id": "w1", "from": "src:video", "to": "face_node:video_in", "type": "video"}]

    mgr._apply_graph_to_orchestrator()
    session = mgr.orchestrator.sessions["shroud"]
    assert session.streamer_emotion.model_name == "ferplus"

    # Hot reload model to mobilefacenet
    assert mgr.update_node_param("face_node", "model", "mobilefacenet") is True
    mgr._apply_graph_to_orchestrator()
    assert session.streamer_emotion.model_name == "mobilefacenet"

