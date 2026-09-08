"""Dynamic Node-Graph DAG Manager for Autonomous Stream Clipper.

Manages declarative graph topology, typed port validation, dynamic fan-out routing
between stream buffers and heuristic workers, and trigger dispatching to clipping DAGs.
"""

from collections import deque
import copy
import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

logger = logging.getLogger(__name__)

# Strongly-Typed Port Signatures
PORT_TYPES = {
    "video": {"name": "Video Stream", "color": "#f43f5e"},
    "audio": {"name": "Audio Stream", "color": "#38bdf8"},
    "chat": {"name": "Chat Event Stream", "color": "#a855f7"},
    "trigger": {"name": "Discrete Trigger Pulse", "color": "#eab308"},
    "scalar": {"name": "Real Number Value", "color": "#10b981"},
    "text": {"name": "Transcript / Narrative", "color": "#6366f1"},
    "clip": {"name": "Rendered Media Asset", "color": "#f97316"},
}

# Permissible connections between output types and input types
COMPATIBLE_TYPES = {
    "video": {"video"},
    "audio": {"audio"},
    "chat": {"chat"},
    "trigger": {"trigger"},
    "scalar": {"scalar"},
    "text": {"text"},
    "clip": {"clip"},
}


class GraphDAGManager:
    """Manages the visual node graph topology, dynamic stream routing, and parameter mutators."""

    def __init__(self, orchestrator=None):
        self.orchestrator = orchestrator
        self.graph_id = "default_studio_graph"
        self.nodes: Dict[str, dict] = {}
        self.wires: List[dict] = []  # List of {"id": str, "from": str, "to": str, "type": str}
        self.last_sync_time = time.time()

        # Initialize default graph topology
        self.load_default_template()

    def load_default_template(self, channel: str = "marlon", simulate: bool = False):
        """Builds a classic ComfyUI workflow template connecting stream sources to heuristics and clipping."""
        self.nodes = {
            "node_stream": {
                "id": "node_stream",
                "type": "StreamSourceNode",
                "title": f"Twitch Source: #{channel}",
                "category": "stream",
                "position": [60, 160],
                "properties": {
                    "channel": channel,
                    "simulate": simulate,
                },
                "inputs": [],
                "outputs": [
                    {"id": "video", "name": "Video Stream", "type": "video"},
                    {"id": "audio", "name": "Audio Stream", "type": "audio"},
                    {"id": "chat", "name": "Chat Stream", "type": "chat"},
                ],
            },
            "node_audio": {
                "id": "node_audio",
                "type": "AudioMonitorNode",
                "title": "Audio Decibel Monitor",
                "category": "audio",
                "position": [440, 60],
                "properties": {
                    "jump_db_threshold": 12.0,
                    "baseline_adaptation": 0.90,
                },
                "inputs": [
                    {"id": "audio_in", "name": "Audio In", "type": "audio"},
                ],
                "outputs": [
                    {"id": "spike_trigger", "name": "Audio Spike", "type": "trigger"},
                    {"id": "live_db", "name": "Current dB", "type": "scalar"},
                ],
            },
            "node_chat": {
                "id": "node_chat",
                "type": "ChatVelocityNode",
                "title": "Chat Velocity Engine",
                "category": "chat",
                "position": [440, 270],
                "properties": {
                    "spike_ratio_threshold": 3.0,
                    "instant_min_threshold": 10.0,
                },
                "inputs": [
                    {"id": "chat_in", "name": "Chat In", "type": "chat"},
                ],
                "outputs": [
                    {"id": "spike_trigger", "name": "Chat Spike", "type": "trigger"},
                    {"id": "velocity", "name": "Messages/s", "type": "scalar"},
                ],
            },
            "node_cv": {
                "id": "node_cv",
                "type": "CVTransformerNode",
                "title": "Hugging Face Vision",
                "category": "cv",
                "position": [440, 480],
                "properties": {
                    "candidate_labels": "gameplay action, victory celebration, defeat game over, in-game menu, streamer facecam, brb waiting screen",
                    "trigger_labels": "victory celebration, jackpot win, epic moment",
                    "confidence_threshold": 0.70,
                },
                "inputs": [
                    {"id": "video_in", "name": "Video In", "type": "video"},
                ],
                "outputs": [
                    {"id": "spike_trigger", "name": "Vision Trigger", "type": "trigger"},
                    {"id": "confidence", "name": "Top Confidence", "type": "scalar"},
                    {"id": "top_label", "name": "Top Class", "type": "text"},
                ],
            },
            "node_ocr": {
                "id": "node_ocr",
                "type": "OCRVisionNode",
                "title": "OCR / Vision Engine",
                "category": "ocr",
                "position": [440, 780],
                "properties": {
                    "multiplier_threshold": 100.0,
                    "roi": {"x": 0.70, "y": 0.85, "w": 0.28, "h": 0.12},
                },
                "inputs": [
                    {"id": "video_in", "name": "Video In", "type": "video"},
                ],
                "outputs": [
                    {"id": "ocr_trigger", "name": "Win Trigger", "type": "trigger"},
                    {"id": "multiplier", "name": "Multiplier", "type": "scalar"},
                ],
            },
            "node_gate": {
                "id": "node_gate",
                "type": "GateEvaluatorNode",
                "title": "Gate Evaluator & Logic",
                "category": "gate",
                "position": [820, 220],
                "properties": {
                    "mode": "WEIGHTED_SCORE",
                    "min_score": 4,
                    "debounce_seconds": 30.0,
                    "post_event_delay": 10.0,
                },
                "inputs": [
                    {"id": "trigger_1", "name": "Audio Trigger In", "type": "trigger"},
                    {"id": "trigger_2", "name": "Chat Trigger In", "type": "trigger"},
                    {"id": "trigger_3", "name": "OCR Trigger In", "type": "trigger"},
                    {"id": "trigger_4", "name": "Vision Trigger In", "type": "trigger"},
                ],
                "outputs": [
                    {"id": "clip_trigger", "name": "Clip Trigger Out", "type": "trigger"},
                    {"id": "score", "name": "Evaluated Score", "type": "scalar"},
                ],
            },
            "node_slicer": {
                "id": "node_slicer",
                "type": "SegmentSlicerNode",
                "title": "60s Rolling Slicer",
                "category": "slicer",
                "position": [1180, 220],
                "properties": {
                    "window_seconds": 60,
                },
                "inputs": [
                    {"id": "video_in", "name": "Video In", "type": "video"},
                    {"id": "trigger_in", "name": "Trigger In", "type": "trigger"},
                ],
                "outputs": [
                    {"id": "candidate_slice", "name": "Raw Candidate Slice", "type": "video"},
                ],
            },
            "node_render": {
                "id": "node_render",
                "type": "HardwareRenderNode",
                "title": "Hardware Video Renderer",
                "category": "render",
                "position": [1520, 220],
                "properties": {
                    "crop_vertical": False,
                    "enable_subs": False,
                    "encoder": "auto",
                },
                "inputs": [
                    {"id": "candidate_in", "name": "Candidate Video", "type": "video"},
                ],
                "outputs": [
                    {"id": "clip_asset", "name": "Finished MP4 Clip", "type": "clip"},
                ],
            },
        }

        # Wires connecting output ports (node:port) to input ports (node:port)
        self.wires = [
            {"id": "w1", "from": "node_stream:audio", "to": "node_audio:audio_in", "type": "audio"},
            {"id": "w2", "from": "node_stream:chat", "to": "node_chat:chat_in", "type": "chat"},
            {"id": "w3", "from": "node_stream:video", "to": "node_ocr:video_in", "type": "video"},
            {"id": "w4", "from": "node_stream:video", "to": "node_slicer:video_in", "type": "video"},
            {"id": "w5", "from": "node_audio:spike_trigger", "to": "node_gate:trigger_1", "type": "trigger"},
            {"id": "w6", "from": "node_chat:spike_trigger", "to": "node_gate:trigger_2", "type": "trigger"},
            {"id": "w7", "from": "node_ocr:ocr_trigger", "to": "node_gate:trigger_3", "type": "trigger"},
            {"id": "w8", "from": "node_gate:clip_trigger", "to": "node_slicer:trigger_in", "type": "trigger"},
            {"id": "w9", "from": "node_slicer:candidate_slice", "to": "node_render:candidate_in", "type": "video"},
            {"id": "w10", "from": "node_stream:video", "to": "node_cv:video_in", "type": "video"},
            {"id": "w11", "from": "node_cv:spike_trigger", "to": "node_gate:trigger_4", "type": "trigger"},
        ]
        self.last_sync_time = time.time()

    def get_graph(self) -> dict:
        """Returns the full graph JSON schema for frontend rendering."""
        return {
            "graph_id": self.graph_id,
            "nodes": list(self.nodes.values()),
            "wires": self.wires,
            "port_types": PORT_TYPES,
            "updated_at": self.last_sync_time,
        }

    def validate_dag(self, nodes: Dict[str, dict], wires: List[dict]) -> Tuple[bool, str]:
        """Validates that the graph has valid port types and no illegal cycles (Kahn's Algorithm)."""
        # 1. Validate connection types
        node_lookup = {n["id"]: n for n in nodes.values()}
        for wire in wires:
            src_node_id, src_port_id = wire["from"].split(":")
            dst_node_id, dst_port_id = wire["to"].split(":")

            if src_node_id not in node_lookup:
                return False, f"Source node {src_node_id} does not exist"
            if dst_node_id not in node_lookup:
                return False, f"Destination node {dst_node_id} does not exist"

            src_node = node_lookup[src_node_id]
            dst_node = node_lookup[dst_node_id]

            src_port = next((p for p in src_node.get("outputs", []) if p["id"] == src_port_id), None)
            dst_port = next((p for p in dst_node.get("inputs", []) if p["id"] == dst_port_id), None)

            if not src_port:
                return False, f"Output port {src_port_id} on {src_node_id} not found"
            if not dst_port:
                return False, f"Input port {dst_port_id} on {dst_node_id} not found"

            # Type compatibility check
            expected_type = dst_port.get("type")
            actual_type = src_port.get("type")
            allowed = COMPATIBLE_TYPES.get(actual_type, {actual_type})
            if expected_type not in allowed:
                return False, f"Incompatible types: Cannot connect {actual_type} to {expected_type}"

        # 2. Cycle Detection (Topological Sort)
        adj: Dict[str, List[str]] = {nid: [] for nid in node_lookup}
        indegree: Dict[str, int] = {nid: 0 for nid in node_lookup}

        for wire in wires:
            src_id = wire["from"].split(":")[0]
            dst_id = wire["to"].split(":")[0]
            adj[src_id].append(dst_id)
            indegree[dst_id] += 1

        queue = deque([nid for nid, deg in indegree.items() if deg == 0])
        visited_count = 0

        while queue:
            curr = queue.popleft()
            visited_count += 1
            for neighbor in adj[curr]:
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    queue.append(neighbor)

        if visited_count != len(node_lookup):
            return False, "Cycle detected in graph. Workflows must be directed acyclic graphs."

        return True, "Valid DAG"

    def sync_graph(self, payload: dict) -> Tuple[bool, str]:
        """Validates, stores, and applies changes from the visual studio."""
        if "graph" in payload and isinstance(payload["graph"], dict):
            payload = payload["graph"]
        nodes_list = payload.get("nodes", [])
        wires = payload.get("wires", [])

        nodes_dict = {n["id"]: n for n in nodes_list}

        valid, err_msg = self.validate_dag(nodes_dict, wires)
        if not valid:
            logger.warning("[GraphDAG] Graph validation failed: %s", err_msg)
            return False, err_msg

        self.nodes = nodes_dict
        self.wires = wires
        self.last_sync_time = time.time()

        # Apply parameters dynamically to active orchestrator sessions
        self._apply_graph_to_orchestrator()

        logger.info("[GraphDAG] Synced graph topology (%d nodes, %d wires)", len(self.nodes), len(self.wires))
        return True, "Graph synced successfully"

    def update_node_param(self, node_id: str, param: str, value: Any) -> bool:
        """Mutates a specific node parameter and propagates to running worker immediately."""
        node = self.nodes.get(node_id)
        if not node:
            return False
        if "properties" not in node:
            node["properties"] = {}
        node["properties"][param] = value
        if node.get("type") == "StreamSourceNode" and param == "channel":
            node["title"] = f"Twitch Source: #{value}"

        # Hot-reload into orchestrator
        self._apply_graph_to_orchestrator()
        return True

    def _apply_graph_to_orchestrator(self):
        """Propagates node settings (thresholds, ROIs, gates) to orchestrator components."""
        if not self.orchestrator:
            return

        # Find stream channel
        stream_node = next((n for n in self.nodes.values() if n["type"] == "StreamSourceNode"), None)
        if not stream_node:
            return

        channel = stream_node.get("properties", {}).get("channel")
        if not channel:
            return

        session = self.orchestrator.sessions.get(channel)
        if not session:
            return

        # 1. Update Audio Monitor settings
        audio_node = next((n for n in self.nodes.values() if n["type"] == "AudioMonitorNode"), None)
        if audio_node and session.audio_monitor:
            props = audio_node.get("properties", {})
            if "jump_db_threshold" in props:
                session.audio_monitor.jump_db_threshold = float(props["jump_db_threshold"])

        # 2. Update Chat Velocity settings
        chat_node = next((n for n in self.nodes.values() if n["type"] == "ChatVelocityNode"), None)
        if chat_node and session.chat_engine:
            props = chat_node.get("properties", {})
            if "spike_ratio_threshold" in props:
                session.chat_engine.spike_ratio_threshold = float(props["spike_ratio_threshold"])
            if "instant_min_threshold" in props:
                session.chat_engine.instant_min_threshold = float(props["instant_min_threshold"])

        # 3. Update OCR settings
        ocr_node = next((n for n in self.nodes.values() if n["type"] == "OCRVisionNode"), None)
        if ocr_node and session.ocr_engine:
            props = ocr_node.get("properties", {})
            if "multiplier_threshold" in props:
                session.ocr_engine.win_multiplier_threshold = float(props["multiplier_threshold"])
            if "roi" in props and isinstance(props["roi"], dict):
                roi = props["roi"]
                session.ocr_engine.crop_box = (
                    float(roi.get("x", 0.70)),
                    float(roi.get("y", 0.85)),
                    float(roi.get("w", 0.28)),
                    float(roi.get("h", 0.12)),
                )

        # 3b. Update CV Transformer settings
        cv_node = next((n for n in self.nodes.values() if n["type"] == "CVTransformerNode"), None)
        if cv_node and getattr(session, "cv_service", None):
            props = cv_node.get("properties", {})
            if "candidate_labels" in props:
                raw_labels = props["candidate_labels"]
                labels_list = [l.strip() for l in raw_labels.split(",") if l.strip()] if isinstance(raw_labels, str) else raw_labels
                session.cv_service.set_candidate_labels(labels_list)
            if "confidence_threshold" in props:
                session.cv_service.set_confidence_threshold(float(props["confidence_threshold"]))
            if "trigger_labels" in props:
                raw_trigs = props["trigger_labels"]
                trigs_list = [l.strip() for l in raw_trigs.split(",") if l.strip()] if isinstance(raw_trigs, str) else raw_trigs
                session.cv_service.set_trigger_labels(trigs_list)

        # 4. Update Gate Evaluator settings
        gate_node = next((n for n in self.nodes.values() if n["type"] == "GateEvaluatorNode"), None)
        if gate_node and session.gate_evaluator:
            props = gate_node.get("properties", {})
            if "debounce_seconds" in props:
                session.gate_evaluator.debounce_sec = float(props["debounce_seconds"])
            if "post_event_delay" in props:
                session.gate_evaluator.post_event_delay = float(props["post_event_delay"])

    def get_node_telemetry_payload(self) -> Dict[str, dict]:
        """Generates real-time telemetry metrics keyed by node ID for in-node widgets."""
        payload: Dict[str, dict] = {}
        if not self.orchestrator or not self.orchestrator.sessions:
            return payload

        # Locate stream node
        stream_node = next((n for n in self.nodes.values() if n["type"] == "StreamSourceNode"), None)
        if not stream_node:
            return payload

        channel = stream_node.get("properties", {}).get("channel")
        session = self.orchestrator.sessions.get(channel) if channel else list(self.orchestrator.sessions.values())[0]
        if not session:
            return payload

        calc = session.chat_engine.recalculate() if session.chat_engine else {}
        extra = session.extra_telemetry

        # Stream Source Node
        payload[stream_node["id"]] = {
            "channel": session.channel,
            "status": "online" if (session.buffer and not session.buffer.is_standby) else "standby",
            "buffered_segments": session.buffer.get_segment_count() if session.buffer else 0,
            "is_buffering": session.buffer.is_alive() if session.buffer else False,
        }

        # Audio Monitor Node
        for n in self.nodes.values():
            if n["type"] == "AudioMonitorNode":
                payload[n["id"]] = {
                    "current_db": extra.get("audio_rms_db", -90.0),
                    "baseline_db": session.audio_monitor.baseline_db if session.audio_monitor else -30.0,
                    "delta_db": session.audio_monitor.delta_db if session.audio_monitor else 0.0,
                    "is_spiking": bool(extra.get("audio_spike", False)),
                    "waveform": extra.get("audio_waveform", []),
                }
            elif n["type"] == "ChatVelocityNode":
                payload[n["id"]] = {
                    "v_instant": calc.get("v_instant", 0.0),
                    "v_baseline": calc.get("v_baseline", 0.0),
                    "spike_ratio": calc.get("spike_ratio", 1.0),
                    "is_spiking": calc.get("is_spiking", False),
                    "recent_messages": calc.get("recent_messages", [])[-6:],
                }
            elif n["type"] == "OCRVisionNode":
                payload[n["id"]] = {
                    "multiplier": extra.get("ocr_multiplier", "1.0x"),
                    "balance": extra.get("ocr_balance", "$0.00"),
                    "pnl_delta": extra.get("ocr_pnl_delta", 0.0),
                }
            elif n["type"] == "CVTransformerNode":
                payload[n["id"]] = {
                    "top_label": extra.get("cv_top_label", "standby"),
                    "confidence": extra.get("cv_confidence", 0.0),
                    "probabilities": extra.get("cv_probabilities", {}),
                    "detections": extra.get("cv_boxes", []),
                    "latency_ms": extra.get("cv_latency_ms", 0.0),
                    "thumbnail_b64": extra.get("cv_thumbnail_b64", ""),
                    "engine": getattr(session.cv_service.engine, "engine_name", "coreml") if getattr(session, "cv_service", None) else "coreml",
                }
            elif n["type"] == "GateEvaluatorNode":
                debounce_sec = getattr(session.gate_evaluator, "debounce_seconds", 30.0) if session.gate_evaluator else 30.0
                last_trig = getattr(session.gate_evaluator, "last_trigger_time", 0.0) if session.gate_evaluator else 0.0
                is_debouncing = (time.time() - last_trig < debounce_sec) if last_trig > 0 else False
                debounce_remaining = max(0.0, (last_trig + debounce_sec) - time.time()) if is_debouncing else 0.0
                payload[n["id"]] = {
                    "score": getattr(session.gate_evaluator, "current_score", 1),
                    "is_debouncing": is_debouncing,
                    "debounce_remaining": debounce_remaining,
                }

        return payload
