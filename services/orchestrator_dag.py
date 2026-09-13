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

    def __init__(self, orchestrator=None, load_template: bool = False):
        self.orchestrator = orchestrator
        self.graph_id = "default_studio_graph"
        self.nodes: Dict[str, dict] = {}
        self.wires: List[dict] = []  # List of {"id": str, "from": str, "to": str, "type": str}
        self.last_sync_time = time.time()

        # Initialize graph topology: empty by default, or populated if requested
        if load_template:
            self.load_default_template()

    def load_default_template(self, channel: str = "stream", simulate: bool = False):
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
                    "platform": "twitch",
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
            "node_folder": {
                "id": "node_folder",
                "type": "ClipFolderNode",
                "title": "Clip Folder: Highlight Reels",
                "category": "storage",
                "position": [1880, 220],
                "properties": {
                    "folder_name": "Highlight Reels",
                    "date": time.strftime("%Y-%m-%d"),
                },
                "inputs": [
                    {"id": "clip_in", "name": "Clip In", "type": "clip"},
                ],
                "outputs": [],
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
            {"id": "w12", "from": "node_render:clip_asset", "to": "node_folder:clip_in", "type": "clip"},
        ]
        self.last_sync_time = time.time()

    def add_stream_pipeline(
        self,
        channel: str,
        platform: str = "twitch",
        auto_sequence: bool = True,
        simulate: bool = False,
    ) -> dict:
        """Dynamically adds a stream source node or generates a full clipping sequence for a new stream."""
        from services.ingest.stream_buffer import clean_channel_name
        clean_ch = clean_channel_name(channel)
        plat = str(platform or "twitch").lower()

        # Check if a StreamSourceNode already exists for this channel
        existing_stream_node = None
        for nid, n in self.nodes.items():
            if n.get("type") == "StreamSourceNode" and clean_channel_name(n.get("properties", {}).get("channel", "")) == clean_ch:
                existing_stream_node = n
                break

        if not auto_sequence:
            # Mode: Stream only -> User builds nodes manually
            if not self.nodes or len(self.nodes) == 0:
                # First node in empty graph: single isolated StreamSourceNode
                self.nodes = {
                    "node_stream": {
                        "id": "node_stream",
                        "type": "StreamSourceNode",
                        "title": f"{plat.capitalize()} Source: #{clean_ch}",
                        "category": "stream",
                        "position": [60, 160],
                        "properties": {
                            "channel": clean_ch,
                            "platform": plat,
                            "simulate": simulate,
                        },
                        "inputs": [],
                        "outputs": [
                            {"id": "video", "name": "Video Stream", "type": "video"},
                            {"id": "audio", "name": "Audio Stream", "type": "audio"},
                            {"id": "chat", "name": "Chat Stream", "type": "chat"},
                        ],
                    }
                }
                self.wires = []
            elif not existing_stream_node:
                # Append a new isolated StreamSourceNode with no wires
                new_id = f"node_stream_{clean_ch}"
                max_y = max([n.get("position", [0, 160])[1] for n in self.nodes.values()] or [0])
                self.nodes[new_id] = {
                    "id": new_id,
                    "type": "StreamSourceNode",
                    "title": f"{plat.capitalize()} Source: #{clean_ch}",
                    "category": "stream",
                    "position": [60, max_y + 260],
                    "properties": {
                        "channel": clean_ch,
                        "platform": plat,
                        "simulate": simulate,
                    },
                    "inputs": [],
                    "outputs": [
                        {"id": "video", "name": "Video Stream", "type": "video"},
                        {"id": "audio", "name": "Audio Stream", "type": "audio"},
                        {"id": "chat", "name": "Chat Stream", "type": "chat"},
                    ],
                }
            self.last_sync_time = time.time()
            self._apply_graph_to_orchestrator()
            return self.get_graph()

        # Mode: auto_sequence is True -> Generate complete clipping pipeline
        if not self.nodes or len(self.nodes) == 0:
            # Configure default pipeline template for this stream
            self.load_default_template(channel=clean_ch, simulate=simulate)
            if "node_stream" in self.nodes:
                self.nodes["node_stream"]["properties"]["platform"] = plat
                self.nodes["node_stream"]["title"] = f"{plat.capitalize()} Source: #{clean_ch}"
            self._apply_graph_to_orchestrator()
            return self.get_graph()

        # If a stream node for this channel already exists, return current graph
        if existing_stream_node:
            return self.get_graph()

        # Generate a complete parallel clipping sequence for this new stream
        suffix = clean_ch
        base_y = max([n.get("position", [0, 160])[1] for n in self.nodes.values()] or [0]) + 340

        stream_nid = f"node_stream_{suffix}"
        audio_nid = f"node_audio_{suffix}"
        chat_nid = f"node_chat_{suffix}"
        cv_nid = f"node_cv_{suffix}"
        ocr_nid = f"node_ocr_{suffix}"
        gate_nid = f"node_gate_{suffix}"
        slicer_nid = f"node_slicer_{suffix}"
        render_nid = f"node_render_{suffix}"

        # Wire into existing ClipFolderNode or create one
        folder_node = next((n for n in self.nodes.values() if n.get("type") == "ClipFolderNode"), None)
        folder_nid = folder_node["id"] if folder_node else f"node_folder_{suffix}"

        self.nodes[stream_nid] = {
            "id": stream_nid,
            "type": "StreamSourceNode",
            "title": f"{plat.capitalize()} Source: #{clean_ch}",
            "category": "stream",
            "position": [60, base_y + 100],
            "properties": {"channel": clean_ch, "platform": plat, "simulate": simulate},
            "inputs": [],
            "outputs": [
                {"id": "video", "name": "Video Stream", "type": "video"},
                {"id": "audio", "name": "Audio Stream", "type": "audio"},
                {"id": "chat", "name": "Chat Stream", "type": "chat"},
            ],
        }
        self.nodes[audio_nid] = {
            "id": audio_nid,
            "type": "AudioMonitorNode",
            "title": f"Audio Monitor (#{clean_ch})",
            "category": "audio",
            "position": [440, base_y],
            "properties": {"jump_db_threshold": 12.0, "baseline_adaptation": 0.90},
            "inputs": [{"id": "audio_in", "name": "Audio In", "type": "audio"}],
            "outputs": [
                {"id": "spike_trigger", "name": "Audio Spike", "type": "trigger"},
                {"id": "live_db", "name": "Current dB", "type": "scalar"},
            ],
        }
        self.nodes[chat_nid] = {
            "id": chat_nid,
            "type": "ChatVelocityNode",
            "title": f"Chat Velocity (#{clean_ch})",
            "category": "chat",
            "position": [440, base_y + 210],
            "properties": {"spike_ratio_threshold": 3.0, "instant_min_threshold": 10.0},
            "inputs": [{"id": "chat_in", "name": "Chat In", "type": "chat"}],
            "outputs": [
                {"id": "spike_trigger", "name": "Chat Spike", "type": "trigger"},
                {"id": "velocity", "name": "Messages/s", "type": "scalar"},
            ],
        }
        self.nodes[cv_nid] = {
            "id": cv_nid,
            "type": "CVTransformerNode",
            "title": f"Hugging Face Vision (#{clean_ch})",
            "category": "cv",
            "position": [440, base_y + 420],
            "properties": {
                "candidate_labels": "gameplay action, victory celebration, defeat game over, in-game menu, streamer facecam, brb waiting screen",
                "trigger_labels": "victory celebration, jackpot win, epic moment",
                "confidence_threshold": 0.70,
            },
            "inputs": [{"id": "video_in", "name": "Video In", "type": "video"}],
            "outputs": [
                {"id": "spike_trigger", "name": "Vision Trigger", "type": "trigger"},
                {"id": "confidence", "name": "Top Confidence", "type": "scalar"},
                {"id": "top_label", "name": "Top Class", "type": "text"},
            ],
        }
        self.nodes[ocr_nid] = {
            "id": ocr_nid,
            "type": "OCRVisionNode",
            "title": f"OCR Engine (#{clean_ch})",
            "category": "ocr",
            "position": [440, base_y + 720],
            "properties": {
                "multiplier_threshold": 100.0,
                "roi": {"x": 0.70, "y": 0.85, "w": 0.28, "h": 0.12},
            },
            "inputs": [{"id": "video_in", "name": "Video In", "type": "video"}],
            "outputs": [
                {"id": "ocr_trigger", "name": "Win Trigger", "type": "trigger"},
                {"id": "multiplier", "name": "Multiplier", "type": "scalar"},
            ],
        }
        self.nodes[gate_nid] = {
            "id": gate_nid,
            "type": "GateEvaluatorNode",
            "title": f"Gate Evaluator (#{clean_ch})",
            "category": "gate",
            "position": [820, base_y + 160],
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
        }
        self.nodes[slicer_nid] = {
            "id": slicer_nid,
            "type": "SegmentSlicerNode",
            "title": f"Rolling Slicer (#{clean_ch})",
            "category": "slicer",
            "position": [1180, base_y + 160],
            "properties": {"window_seconds": 60},
            "inputs": [
                {"id": "video_in", "name": "Video In", "type": "video"},
                {"id": "trigger_in", "name": "Trigger In", "type": "trigger"},
            ],
            "outputs": [
                {"id": "candidate_slice", "name": "Raw Candidate Slice", "type": "video"},
            ],
        }
        self.nodes[render_nid] = {
            "id": render_nid,
            "type": "HardwareRenderNode",
            "title": f"Hardware Renderer (#{clean_ch})",
            "category": "render",
            "position": [1520, base_y + 160],
            "properties": {"crop_vertical": False, "enable_subs": False, "encoder": "auto"},
            "inputs": [{"id": "candidate_in", "name": "Candidate Video", "type": "video"}],
            "outputs": [{"id": "clip_asset", "name": "Finished MP4 Clip", "type": "clip"}],
        }
        if not folder_node:
            self.nodes[folder_nid] = {
                "id": folder_nid,
                "type": "ClipFolderNode",
                "title": f"Clip Folder: Highlight Reels",
                "category": "storage",
                "position": [1880, base_y + 160],
                "properties": {
                    "folder_name": "Highlight Reels",
                    "date": time.strftime("%Y-%m-%d"),
                },
                "inputs": [{"id": "clip_in", "name": "Clip In", "type": "clip"}],
                "outputs": [],
            }

        # Generate wires for this new sequence
        new_wires = [
            {"id": f"w_{suffix}_1", "from": f"{stream_nid}:audio", "to": f"{audio_nid}:audio_in", "type": "audio"},
            {"id": f"w_{suffix}_2", "from": f"{stream_nid}:chat", "to": f"{chat_nid}:chat_in", "type": "chat"},
            {"id": f"w_{suffix}_3", "from": f"{stream_nid}:video", "to": f"{ocr_nid}:video_in", "type": "video"},
            {"id": f"w_{suffix}_4", "from": f"{stream_nid}:video", "to": f"{slicer_nid}:video_in", "type": "video"},
            {"id": f"w_{suffix}_5", "from": f"{audio_nid}:spike_trigger", "to": f"{gate_nid}:trigger_1", "type": "trigger"},
            {"id": f"w_{suffix}_6", "from": f"{chat_nid}:spike_trigger", "to": f"{gate_nid}:trigger_2", "type": "trigger"},
            {"id": f"w_{suffix}_7", "from": f"{ocr_nid}:ocr_trigger", "to": f"{gate_nid}:trigger_3", "type": "trigger"},
            {"id": f"w_{suffix}_8", "from": f"{gate_nid}:clip_trigger", "to": f"{slicer_nid}:trigger_in", "type": "trigger"},
            {"id": f"w_{suffix}_9", "from": f"{slicer_nid}:candidate_slice", "to": f"{render_nid}:candidate_in", "type": "video"},
            {"id": f"w_{suffix}_10", "from": f"{stream_nid}:video", "to": f"{cv_nid}:video_in", "type": "video"},
            {"id": f"w_{suffix}_11", "from": f"{cv_nid}:spike_trigger", "to": f"{gate_nid}:trigger_4", "type": "trigger"},
            {"id": f"w_{suffix}_12", "from": f"{render_nid}:clip_asset", "to": f"{folder_nid}:clip_in", "type": "clip"},
        ]
        self.wires.extend(new_wires)

        self.last_sync_time = time.time()
        self._apply_graph_to_orchestrator()
        return self.get_graph()

    def remove_stream_pipeline(self, channel: str) -> dict:
        """Removes a stream node and attached wires when a session is closed."""
        from services.ingest.stream_buffer import clean_channel_name
        clean_ch = clean_channel_name(channel)

        nodes_to_remove = []
        for nid, n in list(self.nodes.items()):
            if n.get("type") == "StreamSourceNode" and clean_channel_name(n.get("properties", {}).get("channel", "")) == clean_ch:
                nodes_to_remove.append(nid)
            elif f"_{clean_ch}" in nid:
                nodes_to_remove.append(nid)

        for nid in nodes_to_remove:
            self.nodes.pop(nid, None)

        self.wires = [
            w for w in self.wires
            if w["from"].split(":")[0] not in nodes_to_remove and w["to"].split(":")[0] not in nodes_to_remove
        ]

        # If all stream nodes were removed, clear graph cleanly
        stream_nodes = [n for n in self.nodes.values() if n.get("type") == "StreamSourceNode"]
        if not stream_nodes:
            self.nodes = {}
            self.wires = []

        self.last_sync_time = time.time()
        self._apply_graph_to_orchestrator()
        return self.get_graph()

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
        if node.get("type") == "StreamSourceNode":
            if param in ("channel", "platform"):
                ch = node["properties"].get("channel", "stream")
                plat = str(node["properties"].get("platform", "twitch")).capitalize()
                node["title"] = f"{plat} Source: #{ch}"
        if node.get("type") == "ClipFolderNode" and param == "folder_name":
            node["title"] = f"Clip Folder: {value}"

        # Hot-reload into orchestrator
        self._apply_graph_to_orchestrator()
        return True

    def get_node_source_session(self, node_id: str) -> Optional[Any]:
        """Resolves the active StreamSession routed to a specific node via wires or explicit channel assignment."""
        if not self.orchestrator or not self.orchestrator.sessions:
            return None

        node = self.nodes.get(node_id)
        if not node:
            return None

        from services.ingest.stream_buffer import clean_channel_name

        # 1. If it's a StreamSourceNode itself
        if node.get("type") == "StreamSourceNode":
            ch = node.get("properties", {}).get("channel")
            if ch:
                clean_ch = clean_channel_name(str(ch))
                if clean_ch in self.orchestrator.sessions:
                    return self.orchestrator.sessions[clean_ch]
            return None

        # 2. If node has explicit channel assignment (manual override)
        explicit_ch = node.get("properties", {}).get("channel")
        if explicit_ch and explicit_ch != "auto":
            clean_ch = clean_channel_name(str(explicit_ch))
            if clean_ch in self.orchestrator.sessions:
                return self.orchestrator.sessions[clean_ch]

        # 3. Trace upstream along incoming wires to find source StreamSourceNode
        return self._find_upstream_session(node_id, set())

    def _find_upstream_session(self, node_id: str, visited: Set[str]) -> Optional[Any]:
        if node_id in visited:
            return None
        visited.add(node_id)

        from services.ingest.stream_buffer import clean_channel_name

        for wire in self.wires:
            dst_node_id = wire.get("to", "").split(":")[0]
            if dst_node_id == node_id:
                src_node_id = wire.get("from", "").split(":")[0]
                src_node = self.nodes.get(src_node_id)
                if not src_node:
                    continue

                if src_node.get("type") == "StreamSourceNode":
                    ch = src_node.get("properties", {}).get("channel")
                    if ch:
                        clean_ch = clean_channel_name(str(ch))
                        if clean_ch in self.orchestrator.sessions:
                            return self.orchestrator.sessions[clean_ch]

                # Recurse upstream through intermediate processing nodes
                upstream_sess = self._find_upstream_session(src_node_id, visited)
                if upstream_sess:
                    return upstream_sess

        return None

    def get_downstream_folder_for_session(self, channel: str) -> Optional[Dict[str, Any]]:
        """Finds the downstream ClipFolderNode connected to the HardwareRenderNode for a given session."""
        from services.ingest.stream_buffer import clean_channel_name
        target_ch = clean_channel_name(channel)

        # 1. First, search for HardwareRenderNode(s) routed from target_ch
        render_node_ids = []
        for nid, n in self.nodes.items():
            if n.get("type") == "HardwareRenderNode":
                sess = self.get_node_source_session(nid)
                if sess and clean_channel_name(sess.channel) == target_ch:
                    render_node_ids.append(nid)

        # If no specific render node matched the session, fall back to any HardwareRenderNode
        if not render_node_ids:
            render_node_ids = [nid for nid, n in self.nodes.items() if n.get("type") == "HardwareRenderNode"]

        # 2. Check outgoing wires from these render nodes to any ClipFolderNode
        for r_id in render_node_ids:
            for wire in self.wires:
                src_node_id, src_port_id = wire.get("from", "").split(":")
                dst_node_id, dst_port_id = wire.get("to", "").split(":")
                if src_node_id == r_id:
                    dst_node = self.nodes.get(dst_node_id)
                    if dst_node and dst_node.get("type") == "ClipFolderNode":
                        props = dst_node.get("properties", {})
                        return {
                            "folder_id": dst_node["id"],
                            "folder_name": props.get("folder_name", "Highlight Reels"),
                            "folder_date": props.get("date", time.strftime("%Y-%m-%d")),
                        }

        # 3. Fallback: if there is any wire with type "clip" leading to a ClipFolderNode
        for wire in self.wires:
            dst_node_id = wire.get("to", "").split(":")[0]
            dst_node = self.nodes.get(dst_node_id)
            if dst_node and dst_node.get("type") == "ClipFolderNode":
                props = dst_node.get("properties", {})
                return {
                    "folder_id": dst_node["id"],
                    "folder_name": props.get("folder_name", "Highlight Reels"),
                    "folder_date": props.get("date", time.strftime("%Y-%m-%d")),
                }

        return None

    def _apply_graph_to_orchestrator(self):
        """Propagates node settings (thresholds, ROIs, gates) to orchestrator components per routed session."""
        if not self.orchestrator:
            return

        for node_id, node in self.nodes.items():
            ntype = node.get("type")
            props = node.get("properties", {})

            if ntype == "ThresholdGateNode":
                if "rules" not in props:
                    props["rules"] = {}
                for inp in node.get("inputs", []):
                    port_id = inp["id"]
                    if port_id not in props["rules"]:
                        props["rules"][port_id] = {
                            "operator": ">=",
                            "threshold": 0.5,
                            "min": 0.0,
                            "max": 1.0,
                            "step": 0.01,
                            "unit": "",
                            "label": inp.get("name", port_id),
                        }
                    # Inherit range metadata from incoming wire if available
                    for wire in self.wires:
                        if wire.get("to") == f"{node_id}:{port_id}":
                            src_id, src_port_id = wire.get("from", "").split(":")
                            src_node = self.nodes.get(src_id)
                            if src_node:
                                src_port = next((p for p in src_node.get("outputs", []) if p["id"] == src_port_id), None)
                                if src_port:
                                    rule = props["rules"][port_id]
                                    rule["label"] = src_port.get("name", port_id)
                                    if "min" in src_port:
                                        rule["min"] = src_port["min"]
                                    if "max" in src_port:
                                        rule["max"] = src_port["max"]
                                    if "step" in src_port:
                                        rule["step"] = src_port["step"]
                                    if "unit" in src_port:
                                        rule["unit"] = src_port["unit"]
                continue

            session = self.get_node_source_session(node_id)
            if not session:
                continue

            if ntype == "AudioMonitorNode" and session.audio_monitor:
                if "jump_db_threshold" in props:
                    session.audio_monitor.jump_db_threshold = float(props["jump_db_threshold"])

            elif ntype == "ChatVelocityNode" and session.chat_engine:
                if "spike_ratio_threshold" in props:
                    session.chat_engine.spike_ratio_threshold = float(props["spike_ratio_threshold"])
                if "instant_min_threshold" in props:
                    session.chat_engine.instant_min_threshold = float(props["instant_min_threshold"])

            elif ntype == "OCRVisionNode":
                if session.ocr_engine:
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
                if getattr(session, "dynamic_ocr", None):
                    if "dynamic_areas" in props and isinstance(props["dynamic_areas"], (list, dict)):
                        session.dynamic_ocr.set_areas(props["dynamic_areas"])

            elif ntype == "CVTransformerNode" and getattr(session, "cv_service", None):
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

            elif ntype == "VideoCropNode":
                crop_roi = props.get("roi") or {
                    "x": float(props.get("x", 0.02)),
                    "y": float(props.get("y", 0.05)),
                    "w": float(props.get("w", 0.22)),
                    "h": float(props.get("h", 0.28)),
                }
                # Propagate cropped ROI to downstream nodes wired to this VideoCropNode
                downstream_targets = [
                    w["to"].split(":")[0] for w in self.wires
                    if w.get("from", "").startswith(f"{node_id}:")
                ]
                for target_id in downstream_targets:
                    target_node = self.nodes.get(target_id)
                    if target_node:
                        t_type = target_node.get("type")
                        if t_type == "ImageScaleNode" and getattr(session, "image_scaler", None):
                            session.image_scaler.crop_roi = crop_roi
                            # Propagate further to nodes downstream of ImageScaleNode
                            further_targets = [
                                w2["to"].split(":")[0] for w2 in self.wires
                                if w2.get("from", "").startswith(f"{target_id}:")
                            ]
                            for f_id in further_targets:
                                f_node = self.nodes.get(f_id)
                                if f_node and f_node.get("type") == "FacecamEmotionNode" and getattr(session, "streamer_emotion", None):
                                    session.streamer_emotion_uses_scaler = True
                                    session.streamer_emotion.update_roi(0.0, 0.0, 1.0, 1.0)
                                elif f_node and f_node.get("type") == "OCRVisionNode" and getattr(session, "dynamic_ocr", None):
                                    session.dynamic_ocr.set_areas([{"id": "cropped_ocr", **crop_roi}])
                        elif t_type == "FacecamEmotionNode" and getattr(session, "streamer_emotion", None):
                            session.streamer_emotion_uses_scaler = False
                            session.streamer_emotion.update_roi(
                                crop_roi.get("x", 0.02), crop_roi.get("y", 0.05),
                                crop_roi.get("w", 0.22), crop_roi.get("h", 0.28)
                            )
                        elif t_type == "OCRVisionNode" and getattr(session, "dynamic_ocr", None):
                            session.dynamic_ocr.set_areas([{"id": "cropped_ocr", **crop_roi}])

            elif ntype == "ImageScaleNode" and getattr(session, "image_scaler", None):
                scale_factor = props.get("scale_factor", 2.0)
                algorithm = props.get("algorithm", "bicubic")
                sharpen_strength = props.get("sharpen_strength", 0.5)
                clahe_clip_limit = props.get("clahe_clip_limit", 2.0)
                denoise_strength = props.get("denoise_strength", 0.0)
                target_w = props.get("target_w", 0)
                target_h = props.get("target_h", 0)
                session.image_scaler.set_parameters(
                    scale_factor=scale_factor,
                    algorithm=algorithm,
                    sharpen_strength=sharpen_strength,
                    clahe_clip_limit=clahe_clip_limit,
                    denoise_strength=denoise_strength,
                    target_w=target_w,
                    target_h=target_h,
                )
                # Check if there is an upstream VideoCropNode wired to this ImageScaleNode
                upstream_crop = next((
                    self.nodes.get(w["from"].split(":")[0])
                    for w in self.wires
                    if w.get("to", "").startswith(f"{node_id}:")
                    and self.nodes.get(w["from"].split(":")[0], {}).get("type") == "VideoCropNode"
                ), None)
                if upstream_crop:
                    c_props = upstream_crop.get("properties", {})
                    c_roi = c_props.get("roi") or {
                        "x": float(c_props.get("x", 0.02)),
                        "y": float(c_props.get("y", 0.05)),
                        "w": float(c_props.get("w", 0.22)),
                        "h": float(c_props.get("h", 0.28)),
                    }
                    session.image_scaler.crop_roi = c_roi
                else:
                    session.image_scaler.crop_roi = None

            elif ntype == "FacecamEmotionNode" and getattr(session, "streamer_emotion", None):
                if "model" in props:
                    session.streamer_emotion.set_model(props["model"])
                if "tilt_threshold" in props:
                    session.streamer_emotion.tilt_threshold = float(props["tilt_threshold"])
                if "euphoria_threshold" in props:
                    session.streamer_emotion.euphoria_threshold = float(props["euphoria_threshold"])

                # Check upstream nodes for either ImageScaleNode or VideoCropNode
                upstream_wire = next((
                    w for w in self.wires
                    if w.get("to", "").startswith(f"{node_id}:")
                ), None)
                if upstream_wire:
                    up_src_id = upstream_wire["from"].split(":")[0]
                    up_node = self.nodes.get(up_src_id)
                    if up_node and up_node.get("type") == "ImageScaleNode":
                        session.streamer_emotion_uses_scaler = True
                        session.streamer_emotion.update_roi(0.0, 0.0, 1.0, 1.0)
                    elif up_node and up_node.get("type") == "VideoCropNode":
                        session.streamer_emotion_uses_scaler = False
                        c_props = up_node.get("properties", {})
                        c_roi = c_props.get("roi") or {
                            "x": float(c_props.get("x", 0.02)),
                            "y": float(c_props.get("y", 0.05)),
                            "w": float(c_props.get("w", 0.22)),
                            "h": float(c_props.get("h", 0.28)),
                        }
                        session.streamer_emotion.update_roi(
                            c_roi.get("x", 0.02), c_roi.get("y", 0.05),
                            c_roi.get("w", 0.22), c_roi.get("h", 0.28)
                        )
                    else:
                        session.streamer_emotion_uses_scaler = False

            elif ntype == "GamblingLedgerNode" and getattr(session, "gambling_ledger", None):
                if "starting_balance" in props and props["starting_balance"] is not None:
                    session.gambling_ledger.set_starting_balance(float(props["starting_balance"]))
                if "big_win_multiplier" in props:
                    session.gambling_ledger.big_win_multiplier = float(props["big_win_multiplier"])
                if "big_win_dollars" in props:
                    session.gambling_ledger.big_win_dollars = float(props["big_win_dollars"])

            elif ntype == "GateEvaluatorNode" and session.gate_evaluator:
                if "debounce_seconds" in props:
                    session.gate_evaluator.debounce_sec = float(props["debounce_seconds"])
                if "post_event_delay" in props:
                    session.gate_evaluator.post_event_delay = float(props["post_event_delay"])

    def get_node_telemetry_payload(self) -> Dict[str, dict]:
        """Generates real-time telemetry metrics keyed by node ID for in-node widgets."""
        payload: Dict[str, dict] = {}
        if not self.orchestrator:
            return payload

        for n in self.nodes.values():
            node_id = n["id"]
            node_type = n["type"]

            # Stream Source Node
            if node_type == "StreamSourceNode":
                ch = n.get("properties", {}).get("channel")
                session = self.get_node_source_session(node_id)
                if session:
                    payload[node_id] = {
                        "channel": session.channel,
                        "platform": getattr(session, "platform", "twitch"),
                        "status": "online" if (session.buffer and not session.buffer.is_standby) else "standby",
                        "buffered_segments": session.buffer.get_segment_count() if session.buffer else 0,
                        "is_buffering": session.buffer.is_alive() if session.buffer else False,
                    }
                else:
                    payload[node_id] = {
                        "channel": ch or "unassigned",
                        "platform": n.get("properties", {}).get("platform", "twitch"),
                        "status": "standby",
                        "buffered_segments": 0,
                        "is_buffering": False,
                    }
                continue

            # Clip Folder Repository Node
            if node_type == "ClipFolderNode":
                props = n.get("properties", {})
                folder_name = props.get("folder_name", "Highlight Reels")
                folder_date = props.get("date", time.strftime("%Y-%m-%d"))

                # Query SQLite database for clips stored in this folder
                db = getattr(self.orchestrator, "db", None)
                folder_clips = db.get_clips_by_folder(node_id, limit=20) if db else []
                total_duration = sum(float(c.get("duration_seconds") or 0.0) for c in folder_clips)

                # Trace all upstream renderers wired into this folder node
                wired_renderers = []
                for wire in self.wires:
                    dst = wire.get("to", "").split(":")[0]
                    if dst == node_id:
                        src_id = wire.get("from", "").split(":")[0]
                        src_node = self.nodes.get(src_id)
                        if src_node and src_node.get("type") == "HardwareRenderNode":
                            wired_renderers.append(src_node.get("title", src_id))

                payload[node_id] = {
                    "folder_id": node_id,
                    "folder_name": folder_name,
                    "folder_date": folder_date,
                    "clip_count": len(folder_clips),
                    "total_duration": round(total_duration, 1),
                    "wired_renderers": wired_renderers,
                    "recent_clips": [
                        {
                            "id": c.get("id"),
                            "title": c.get("suggested_title", "Stream Highlight"),
                            "thumbnail_url": c.get("thumbnail_url", ""),
                            "video_url": c.get("video_url", ""),
                            "duration": float(c.get("duration_seconds") or 0.0),
                            "created_at": c.get("created_at", ""),
                        }
                        for c in folder_clips[:6]
                    ],
                }
                continue

            # ThresholdGateNode will be evaluated in second pass after all upstream payloads are computed
            if node_type == "ThresholdGateNode":
                continue

            # For worker nodes: resolve routed session via wires or explicit channel
            session = self.get_node_source_session(node_id)
            if not session:
                payload[node_id] = {
                    "unrouted": True,
                    "status": "unrouted",
                }
                continue

            calc = session.chat_engine.recalculate() if getattr(session, "chat_engine", None) else {}
            extra = getattr(session, "extra_telemetry", {})
            props = n.get("properties", {})

            if node_type == "AudioMonitorNode":
                payload[node_id] = {
                    "current_db": extra.get("audio_rms_db", -90.0),
                    "baseline_db": session.audio_monitor.baseline_db if session.audio_monitor else -30.0,
                    "delta_db": session.audio_monitor.delta_db if session.audio_monitor else 0.0,
                    "is_spiking": bool(extra.get("audio_spike", False)),
                    "waveform": extra.get("audio_waveform", []),
                    "source_channel": session.channel,
                }
            elif node_type == "ChatVelocityNode":
                payload[node_id] = {
                    "v_instant": calc.get("v_instant", 0.0),
                    "v_baseline": calc.get("v_baseline", 0.0),
                    "spike_ratio": calc.get("spike_ratio", 1.0),
                    "is_spiking": calc.get("is_spiking", False),
                    "recent_messages": calc.get("recent_messages", [])[-6:],
                    "source_channel": session.channel,
                }
            elif node_type == "OCRVisionNode":
                payload[node_id] = {
                    "multiplier": extra.get("ocr_multiplier", "1.0x"),
                    "balance": extra.get("ocr_balance", "$0.00"),
                    "pnl_delta": extra.get("ocr_pnl_delta", 0.0),
                    "roi": getattr(session.ocr_engine, "roi", None),
                    "stream_frame_b64": extra.get("stream_frame_b64", ""),
                    "ocr_extracted_areas": extra.get("ocr_extracted_areas", []),
                    "dynamic_ocr_areas": session.dynamic_ocr.get_areas() if getattr(session, "dynamic_ocr", None) else [],
                    "slot_metrics": extra.get("slot_metrics") or (session.dynamic_ocr.compute_slot_metrics() if getattr(session, "dynamic_ocr", None) else {}),
                    "source_channel": session.channel,
                }
            elif node_type == "VideoCropNode":
                payload[node_id] = {
                    "roi": props.get("roi") or {
                        "x": float(props.get("x", 0.02)),
                        "y": float(props.get("y", 0.05)),
                        "w": float(props.get("w", 0.22)),
                        "h": float(props.get("h", 0.28)),
                    },
                    "preset": props.get("preset", "facecam_tl"),
                    "stream_frame_b64": extra.get("stream_frame_b64", ""),
                    "source_channel": session.channel,
                }
            elif node_type == "ImageScaleNode":
                scaler = getattr(session, "image_scaler", None)
                payload[node_id] = {
                    "scale_factor": props.get("scale_factor", getattr(scaler, "scale_factor", 2.0)),
                    "algorithm": props.get("algorithm", getattr(scaler, "algorithm", "bicubic")),
                    "sharpen_strength": props.get("sharpen_strength", getattr(scaler, "sharpen_strength", 0.5)),
                    "clahe_clip_limit": props.get("clahe_clip_limit", getattr(scaler, "clahe_clip_limit", 2.0)),
                    "denoise_strength": props.get("denoise_strength", getattr(scaler, "denoise_strength", 0.0)),
                    "target_w": props.get("target_w", getattr(scaler, "target_w", 0)),
                    "target_h": props.get("target_h", getattr(scaler, "target_h", 0)),
                    "input_res": extra.get("scaler_input_res", "—"),
                    "output_res": extra.get("scaler_output_res", "—"),
                    "latency_ms": extra.get("scaler_latency_ms", 0.0),
                    "scaled_thumbnail_b64": extra.get("scaler_thumbnail_b64", ""),
                    "stream_frame_b64": extra.get("scaler_thumbnail_b64") or extra.get("stream_frame_b64", ""),
                    "source_channel": session.channel,
                }
            elif node_type == "CVTransformerNode":
                payload[node_id] = {
                    "top_label": extra.get("cv_top_label", "standby"),
                    "confidence": extra.get("cv_confidence", 0.0),
                    "probabilities": extra.get("cv_probabilities", {}),
                    "detections": extra.get("cv_boxes", []),
                    "latency_ms": extra.get("cv_latency_ms", 0.0),
                    "thumbnail_b64": extra.get("cv_thumbnail_b64", ""),
                    "stream_frame_b64": extra.get("stream_frame_b64", ""),
                    "engine": getattr(session.cv_service.engine, "engine_name", "coreml") if getattr(session, "cv_service", None) else "coreml",
                    "source_channel": session.channel,
                }
            elif node_type == "FacecamEmotionNode":
                face_b64 = extra.get("emotion_thumbnail_b64") or extra.get("stream_frame_b64", "")
                emotions = extra.get("emotion_distribution", {})
                if getattr(session, "streamer_emotion", None):
                    get_met = session.streamer_emotion.get_metric_value
                else:
                    get_met = lambda k: float(emotions.get(k, 0.0))
                payload[node_id] = {
                    "top_emotion": extra.get("emotion_top", "neutral"),
                    "confidence": extra.get("emotion_confidence", 0.0),
                    "emotions": emotions,
                    "raw_logits": extra.get("emotion_raw_logits", {}),
                    "valence": extra.get("emotion_valence", 0.0),
                    "arousal": extra.get("emotion_arousal", 0.0),
                    "tilt_score": extra.get("emotion_tilt", 0.0),
                    "euphoria_score": extra.get("emotion_euphoria", 0.0),
                    "is_tilting": extra.get("is_tilting", False),
                    "happy": get_met("happy"),
                    "angry": get_met("angry"),
                    "surprise": get_met("surprise"),
                    "sad": get_met("sad"),
                    "fear": get_met("fear"),
                    "disgust": get_met("disgust"),
                    "neutral": get_met("neutral"),
                    "contempt": get_met("contempt"),
                    "model": extra.get("emotion_model", getattr(session.streamer_emotion, "model_name", "ferplus")) if getattr(session, "streamer_emotion", None) else "ferplus",
                    "latency_ms": extra.get("emotion_latency_ms", 0.0),
                    "stream_frame_b64": face_b64,
                    "face_thumbnail_b64": extra.get("emotion_thumbnail_b64", ""),
                    "source_channel": session.channel,
                }
            elif node_type == "GamblingLedgerNode":
                ledger_summary = session.gambling_ledger.get_summary() if getattr(session, "gambling_ledger", None) else {}
                payload[node_id] = {
                    "starting_balance": ledger_summary.get("starting_balance", 0.0),
                    "current_balance": ledger_summary.get("current_balance", 0.0),
                    "net_pnl": ledger_summary.get("net_pnl", 0.0),
                    "winrate": ledger_summary.get("winrate_pct", 0.0),
                    "winrate_pct": ledger_summary.get("winrate_pct", 0.0),
                    "current_streak": ledger_summary.get("current_streak", 0),
                    "total_spins": ledger_summary.get("total_spins", 0),
                    "total_wagered": ledger_summary.get("total_wagered", 0.0),
                    "total_payout": ledger_summary.get("total_payout", 0.0),
                    "rtp": ledger_summary.get("experienced_rtp", 100.0),
                    "experienced_rtp": ledger_summary.get("experienced_rtp", 100.0),
                    "is_chasing_losses": ledger_summary.get("is_chasing_losses", False),
                    "drawdown_dollars": ledger_summary.get("drawdown_dollars", 0.0),
                    "drawdown_pct": ledger_summary.get("drawdown_pct", 0.0),
                    "pnl_history": ledger_summary.get("pnl_history", [])[-20:],
                    "source_channel": session.channel,
                }
            elif node_type == "GateEvaluatorNode":
                debounce_sec = getattr(session.gate_evaluator, "debounce_seconds", 30.0) if session.gate_evaluator else 30.0
                last_trig = getattr(session.gate_evaluator, "last_trigger_time", 0.0) if session.gate_evaluator else 0.0
                is_debouncing = (time.time() - last_trig < debounce_sec) if last_trig > 0 else False
                debounce_remaining = max(0.0, (last_trig + debounce_sec) - time.time()) if is_debouncing else 0.0
                payload[node_id] = {
                    "score": getattr(session.gate_evaluator, "current_score", 1),
                    "is_debouncing": is_debouncing,
                    "debounce_remaining": debounce_remaining,
                    "source_channel": session.channel,
                }

        # Second Pass: Evaluate ThresholdGateNode instances using populated upstream payloads
        for n in self.nodes.values():
            if n.get("type") != "ThresholdGateNode":
                continue
            node_id = n["id"]
            props = n.get("properties", {})
            rules = props.get("rules", {})
            logic_mode = str(props.get("logic_mode", "ALL")).upper()
            min_count = int(props.get("min_count", 1))
            debounce_sec = float(props.get("debounce_seconds", 10.0))
            show_sliders = bool(props.get("show_sliders", True))

            input_evaluations = {}
            passed_count = 0
            total_connected = 0

            for inp in n.get("inputs", []):
                port_id = inp["id"]
                incoming_wire = next((w for w in self.wires if w.get("to") == f"{node_id}:{port_id}"), None)
                current_val = None
                passed = False
                rule = rules.get(port_id, {
                    "operator": ">=",
                    "threshold": 0.5,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "unit": "",
                    "label": inp.get("name", port_id)
                })
                op = rule.get("operator", ">=")
                thresh = float(rule.get("threshold", 0.5))

                if incoming_wire:
                    total_connected += 1
                    up_id, up_port = incoming_wire["from"].split(":")
                    up_payload = payload.get(up_id, {})

                    if up_port in up_payload and isinstance(up_payload[up_port], (int, float)):
                        current_val = float(up_payload[up_port])
                    elif up_port == "delta_db" and "delta_db" in up_payload:
                        current_val = float(up_payload["delta_db"])
                    elif up_port in ("live_db", "current_db") and "current_db" in up_payload:
                        current_val = float(up_payload["current_db"])
                    elif up_port in ("velocity", "v_instant") and "v_instant" in up_payload:
                        current_val = float(up_payload["v_instant"])
                    elif up_port == "spike_ratio" and "spike_ratio" in up_payload:
                        current_val = float(up_payload["spike_ratio"])
                    elif up_port == "multiplier":
                        try:
                            current_val = float(str(up_payload.get("multiplier", "1.0")).replace("x", ""))
                        except Exception:
                            current_val = 1.0
                    elif up_port == "balance":
                        try:
                            current_val = float(str(up_payload.get("balance", "0")).replace("$", "").replace(",", ""))
                        except Exception:
                            current_val = 0.0
                    elif up_port in ("net_pnl", "winrate", "rtp"):
                        current_val = float(up_payload.get(up_port, 0.0))
                    elif up_port in ("valence", "arousal", "tilt_score", "euphoria_score", "happy", "angry", "surprise", "sad", "fear", "disgust", "neutral", "contempt", "confidence"):
                        current_val = float(up_payload.get(up_port, 0.0))
                    elif up_payload.get("emotions") and up_port in up_payload["emotions"]:
                        current_val = float(up_payload["emotions"][up_port])
                    else:
                        try:
                            raw_val = up_payload.get(up_port)
                            if raw_val is not None:
                                current_val = float(raw_val)
                        except (ValueError, TypeError):
                            current_val = None

                    if current_val is not None:
                        if op == ">" and current_val > thresh:
                            passed = True
                        elif op == ">=" and current_val >= thresh:
                            passed = True
                        elif op == "<" and current_val < thresh:
                            passed = True
                        elif op == "<=" and current_val <= thresh:
                            passed = True
                        elif op == "==" and abs(current_val - thresh) < 1e-4:
                            passed = True
                        elif op == "!=" and abs(current_val - thresh) >= 1e-4:
                            passed = True

                        if passed:
                            passed_count += 1

                input_evaluations[port_id] = {
                    "value": current_val,
                    "passed": passed,
                    "connected": incoming_wire is not None,
                    "label": rule.get("label", inp.get("name", port_id)),
                    "threshold": thresh,
                    "operator": op,
                    "min": rule.get("min", 0.0),
                    "max": rule.get("max", 1.0),
                    "step": rule.get("step", 0.01),
                    "unit": rule.get("unit", ""),
                }

            gate_fired = False
            if total_connected > 0:
                if logic_mode == "ALL":
                    gate_fired = (passed_count == total_connected)
                elif logic_mode == "ANY":
                    gate_fired = (passed_count > 0)
                elif logic_mode == "COUNT":
                    gate_fired = (passed_count >= min_count)

            now = time.time()
            if not hasattr(self, "_threshold_gate_last_triggers"):
                self._threshold_gate_last_triggers = {}
            last_trig = self._threshold_gate_last_triggers.get(node_id, 0.0)
            is_debouncing = (now - last_trig < debounce_sec) if last_trig > 0 else False
            debounce_remaining = max(0.0, (last_trig + debounce_sec) - now) if is_debouncing else 0.0

            is_trigger = False
            if gate_fired and not is_debouncing:
                self._threshold_gate_last_triggers[node_id] = now
                is_trigger = True
                is_debouncing = True
                debounce_remaining = debounce_sec

            session = self.get_node_source_session(node_id)

            payload[node_id] = {
                "logic_mode": logic_mode,
                "min_count": min_count,
                "debounce_seconds": debounce_sec,
                "show_sliders": show_sliders,
                "total_connected": total_connected,
                "passed_count": passed_count,
                "gate_fired": gate_fired,
                "is_trigger": is_trigger,
                "is_debouncing": is_debouncing,
                "debounce_remaining": round(debounce_remaining, 1),
                "inputs": input_evaluations,
                "rules": rules,
                "source_channel": session.channel if session else "unassigned",
            }

        return payload
