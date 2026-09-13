"""Unit tests for ImageScalerService and ImageScaleNode DAG orchestration."""

import os
import numpy as np
from PIL import Image
import pytest

from services.vision.image_scaler import ImageScalerService, SUPPORTED_ALGORITHMS
from services.orchestrator_dag import GraphDAGManager


class DummySession:
    def __init__(self, channel="test_stream"):
        self.channel = channel
        self.buffer = None
        self.image_scaler = ImageScalerService()
        self.streamer_emotion = None
        self.dynamic_ocr = None
        self.extra_telemetry = {}


class DummyOrchestrator:
    def __init__(self):
        self.sessions = {"test_stream": DummySession("test_stream")}


class TestImageScalerService:
    def setup_method(self):
        self.scaler = ImageScalerService(scale_factor=2.0, algorithm="bicubic")
        # Generate synthetic 100x60 RGB image with gradient details
        arr = np.zeros((60, 100, 3), dtype=np.uint8)
        arr[:30, :50] = [255, 0, 0]
        arr[:30, 50:] = [0, 255, 0]
        arr[30:, :50] = [0, 0, 255]
        arr[30:, 50:] = [255, 255, 255]
        self.test_img = Image.fromarray(arr)

    def test_init_and_defaults(self):
        assert self.scaler.scale_factor == 2.0
        assert self.scaler.algorithm == "bicubic"
        assert self.scaler.sharpen_strength == 0.5
        assert self.scaler.clahe_clip_limit == 2.0
        assert self.scaler.denoise_strength == 0.0

    def test_compute_target_dimensions_multipliers(self):
        # 2.0x of 100x60 -> 200x120
        assert self.scaler.compute_target_dimensions(100, 60) == (200, 120)

        # 0.5x of 100x60 -> 50x30
        self.scaler.set_parameters(scale_factor=0.5)
        assert self.scaler.compute_target_dimensions(100, 60) == (50, 30)

        # 4.0x of 100x60 -> 400x240
        self.scaler.set_parameters(scale_factor=4.0)
        assert self.scaler.compute_target_dimensions(100, 60) == (400, 240)

    def test_compute_target_dimensions_explicit(self):
        # Explicit width and height
        self.scaler.set_parameters(target_w=320, target_h=240)
        assert self.scaler.compute_target_dimensions(100, 60) == (320, 240)

        # Explicit width only (preserves 100x60 aspect ratio = 0.6)
        self.scaler.set_parameters(target_w=300, target_h=0)
        assert self.scaler.compute_target_dimensions(100, 60) == (300, 180)

        # Explicit height only
        self.scaler.set_parameters(target_w=0, target_h=120)
        assert self.scaler.compute_target_dimensions(100, 60) == (200, 120)

    @pytest.mark.parametrize("algo", ["lanczos4", "bicubic", "bilinear", "area", "nearest"])
    def test_classical_resamplers_upscaling(self, algo):
        self.scaler.set_parameters(scale_factor=2.0, algorithm=algo, target_w=0, target_h=0)
        res = self.scaler.process_frame(self.test_img)
        assert res["input_res"] == "100x60"
        assert res["output_res"] == "200x120"
        assert res["scale_factor"] == 2.0
        assert res["frame"].size == (200, 120)
        assert res["algorithm"] == algo
        assert res["latency_ms"] >= 0.0
        assert res["scaled_thumbnail_b64"].startswith("data:image/jpeg;base64,")

    @pytest.mark.parametrize("algo", ["lanczos4", "bicubic", "bilinear", "area", "nearest"])
    def test_classical_resamplers_downscaling(self, algo):
        self.scaler.set_parameters(scale_factor=0.5, algorithm=algo, target_w=0, target_h=0)
        res = self.scaler.process_frame(self.test_img)
        assert res["input_res"] == "100x60"
        assert res["output_res"] == "50x30"
        assert res["scale_factor"] == 0.5
        assert res["frame"].size == (50, 30)

    @pytest.mark.parametrize("algo", ["unsharp_mask", "clahe", "bilateral"])
    def test_detail_and_contrast_enhancement_filters(self, algo):
        self.scaler.set_parameters(
            scale_factor=1.5,
            algorithm=algo,
            sharpen_strength=1.0,
            clahe_clip_limit=3.0,
            target_w=0,
            target_h=0,
        )
        res = self.scaler.process_frame(self.test_img)
        assert res["input_res"] == "100x60"
        assert res["output_res"] == "150x90"
        assert res["frame"].size == (150, 90)
        assert res["algorithm"] == algo
        assert len(res["scaled_thumbnail_b64"]) > 50

    def test_neural_super_resolution_model(self):
        self.scaler.set_parameters(scale_factor=2.0, algorithm="neural_subpixel", target_w=0, target_h=0)
        res = self.scaler.process_frame(self.test_img)
        assert res["input_res"] == "100x60"
        assert res["output_res"] == "200x120"
        assert res["frame"].size == (200, 120)
        assert res["algorithm"] == "neural_subpixel"
        assert res["latency_ms"] > 0.0

    def test_hot_reload_parameters(self):
        self.scaler.set_parameters(
            scale_factor=3.5,
            algorithm="lanczos4",
            sharpen_strength=1.2,
            clahe_clip_limit=4.0,
            denoise_strength=0.5,
            target_w=640,
            target_h=480,
        )
        assert self.scaler.scale_factor == 3.5
        assert self.scaler.algorithm == "lanczos4"
        assert self.scaler.sharpen_strength == 1.2
        assert self.scaler.clahe_clip_limit == 4.0
        assert self.scaler.denoise_strength == 0.5
        assert self.scaler.target_w == 640
        assert self.scaler.target_h == 480


class TestImageScaleNodeDAG:
    def setup_method(self):
        self.orch = DummyOrchestrator()
        self.dag = GraphDAGManager(orchestrator=self.orch)

    def test_dag_hot_reload_and_telemetry(self):
        # 1. Add StreamSourceNode and ImageScaleNode wired together
        ok, msg = self.dag.sync_graph({
            "nodes": [
                {
                    "id": "src_1",
                    "type": "StreamSourceNode",
                    "properties": {"channel": "test_stream"},
                    "inputs": [],
                    "outputs": [{"id": "video", "name": "Video Stream", "type": "video"}],
                },
                {
                    "id": "scaler_1",
                    "type": "ImageScaleNode",
                    "properties": {
                        "scale_factor": 3.0,
                        "algorithm": "lanczos4",
                        "sharpen_strength": 0.8,
                    },
                    "inputs": [{"id": "video_in", "name": "Video In", "type": "video"}],
                    "outputs": [{"id": "video_out", "name": "Video Out", "type": "video"}],
                },
            ],
            "wires": [
                {"id": "w1", "from": "src_1:video", "to": "scaler_1:video_in", "type": "video"}
            ],
        })
        assert ok is True

        # 2. Apply graph to orchestrator session
        self.dag._apply_graph_to_orchestrator()
        session = self.orch.sessions["test_stream"]
        assert session.image_scaler.scale_factor == 3.0
        assert session.image_scaler.algorithm == "lanczos4"
        assert session.image_scaler.sharpen_strength == 0.8

        # 3. Check telemetry payload
        session.extra_telemetry["scaler_input_res"] = "640x360"
        session.extra_telemetry["scaler_output_res"] = "1920x1080"
        session.extra_telemetry["scaler_latency_ms"] = 4.2
        session.extra_telemetry["scaler_thumbnail_b64"] = "data:image/jpeg;base64,TEST_THUMB"

        telemetry = self.dag.get_node_telemetry_payload()
        assert "scaler_1" in telemetry
        t_data = telemetry["scaler_1"]
        assert t_data["scale_factor"] == 3.0
        assert t_data["algorithm"] == "lanczos4"
        assert t_data["input_res"] == "640x360"
        assert t_data["output_res"] == "1920x1080"
        assert t_data["latency_ms"] == 4.2
        assert t_data["scaled_thumbnail_b64"] == "data:image/jpeg;base64,TEST_THUMB"

    def test_upstream_crop_propagation_through_scaler(self):
        # src -> crop -> scaler
        ok, msg = self.dag.sync_graph({
            "nodes": [
                {
                    "id": "src_1",
                    "type": "StreamSourceNode",
                    "properties": {"channel": "test_stream"},
                    "inputs": [],
                    "outputs": [{"id": "video", "name": "Video Stream", "type": "video"}],
                },
                {
                    "id": "crop_1",
                    "type": "VideoCropNode",
                    "properties": {"roi": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}},
                    "inputs": [{"id": "video_in", "name": "Video In", "type": "video"}],
                    "outputs": [{"id": "video_out", "name": "Video Out", "type": "video"}],
                },
                {
                    "id": "scaler_1",
                    "type": "ImageScaleNode",
                    "inputs": [{"id": "video_in", "name": "Video In", "type": "video"}],
                    "outputs": [{"id": "video_out", "name": "Video Out", "type": "video"}],
                },
            ],
            "wires": [
                {"id": "w1", "from": "src_1:video", "to": "crop_1:video_in", "type": "video"},
                {"id": "w2", "from": "crop_1:video_out", "to": "scaler_1:video_in", "type": "video"},
            ],
        })
        assert ok is True

        self.dag._apply_graph_to_orchestrator()
        session = self.orch.sessions["test_stream"]
        assert session.image_scaler.crop_roi == {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
