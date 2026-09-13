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

# Per-category node blueprint: type, display title, default properties, and ports.
# Presets and custom templates are just an ordered list of these category keys -
# this is the single source of truth for what each worker node looks like.
CATEGORY_DEFS: Dict[str, dict] = {
    "audio": {
        "type": "AudioMonitorNode",
        "title": "Audio Monitor",
        "properties": {"jump_db_threshold": 12.0, "baseline_adaptation": 0.90},
        "inputs": [{"id": "audio_in", "name": "Audio In", "type": "audio"}],
        "outputs": [
            {"id": "spike_trigger", "name": "Audio Spike", "type": "trigger"},
            {"id": "live_db", "name": "Current dB", "type": "scalar"},
        ],
    },
    "chat": {
        "type": "ChatVelocityNode",
        "title": "Chat Velocity Engine",
        "properties": {"spike_ratio_threshold": 3.0, "instant_min_threshold": 10.0},
        "inputs": [{"id": "chat_in", "name": "Chat In", "type": "chat"}],
        "outputs": [
            {"id": "spike_trigger", "name": "Chat Spike", "type": "trigger"},
            {"id": "velocity", "name": "Messages/s", "type": "scalar"},
        ],
    },
    "cv": {
        "type": "CVTransformerNode",
        "title": "Hugging Face Vision",
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
    },
    "ocr": {
        "type": "OCRVisionNode",
        "title": "OCR / Vision Engine",
        "properties": {
            "multiplier_threshold": 100.0,
            "roi": {"x": 0.70, "y": 0.85, "w": 0.28, "h": 0.12},
        },
        "inputs": [{"id": "video_in", "name": "Video In", "type": "video"}],
        "outputs": [
            {"id": "ocr_trigger", "name": "Win Trigger", "type": "trigger"},
            {"id": "multiplier", "name": "Multiplier", "type": "scalar"},
        ],
    },
    "gate": {
        "type": "GateEvaluatorNode",
        "title": "Gate Evaluator & Logic",
        "properties": {
            "mode": "WEIGHTED_SCORE",
            "min_score": 4,
            "debounce_seconds": 30.0,
            "post_event_delay": 10.0,
        },
        # Populated dynamically per-instantiation from GATE_TRIGGER_SOURCES.
        "inputs": [],
        "outputs": [
            {"id": "clip_trigger", "name": "Clip Trigger Out", "type": "trigger"},
            {"id": "score", "name": "Evaluated Score", "type": "scalar"},
        ],
    },
    "slicer": {
        "type": "SegmentSlicerNode",
        "title": "60s Rolling Slicer",
        "properties": {"window_seconds": 60},
        "inputs": [
            {"id": "video_in", "name": "Video In", "type": "video"},
            {"id": "trigger_in", "name": "Trigger In", "type": "trigger"},
        ],
        "outputs": [{"id": "candidate_slice", "name": "Raw Candidate Slice", "type": "video"}],
    },
    "render": {
        "type": "HardwareRenderNode",
        "title": "Hardware Video Renderer",
        "properties": {"crop_vertical": False, "enable_subs": False, "encoder": "auto"},
        "inputs": [{"id": "candidate_in", "name": "Candidate Video", "type": "video"}],
        "outputs": [{"id": "clip_asset", "name": "Finished MP4 Clip", "type": "clip"}],
    },
    "folder": {
        "type": "ClipFolderNode",
        "title": "Clip Folder: Highlight Reels",
        "properties": {"folder_name": "Highlight Reels"},
        "inputs": [{"id": "clip_in", "name": "Clip In", "type": "clip"}],
        "outputs": [],
    },
}

# Categories that produce a trigger consumed by the gate, in preferred port order.
# (category, output_port_id, input_port_label)
GATE_TRIGGER_SOURCES: List[Tuple[str, str, str]] = [
    ("audio", "spike_trigger", "Audio Trigger In"),
    ("chat", "spike_trigger", "Chat Trigger In"),
    ("ocr", "ocr_trigger", "OCR Trigger In"),
    ("cv", "spike_trigger", "Vision Trigger In"),
]

# Fixed wiring shape (excluding the dynamically-numbered trigger->gate wires above).
# Entries are silently skipped if either category isn't present in a given pipeline.
BASE_WIRE_DEFS: List[Tuple[str, str, str, str]] = [
    ("stream", "audio", "audio", "audio_in"),
    ("stream", "chat", "chat", "chat_in"),
    ("stream", "video", "ocr", "video_in"),
    ("stream", "video", "cv", "video_in"),
    ("stream", "video", "slicer", "video_in"),
    ("gate", "clip_trigger", "slicer", "trigger_in"),
    ("slicer", "candidate_slice", "render", "candidate_in"),
    ("render", "clip_asset", "folder", "clip_in"),
]

# Node layout: x column per category, y offset from the stream source node's row.
CATEGORY_LAYOUT: Dict[str, Tuple[int, int]] = {
    "audio": (440, -160),
    "chat": (440, 50),
    "cv": (440, 260),
    "ocr": (440, 560),
    "gate": (820, 60),
    "slicer": (1180, 60),
    "render": (1520, 60),
    "folder": (1880, 60),
}

# Built-in starter presets. Users can also save their own via save_custom_template().
BUILTIN_PRESETS: Dict[str, dict] = {
    "gambling_slots": {
        "id": "gambling_slots",
        "name": "Gambling / Slots Streamer",
        "description": (
            "Full heuristics stack tuned for slot-stream big-win detection: chat velocity, "
            "audio spikes, computer vision, and OCR win-multiplier reading, all feeding a "
            "gate evaluator into the render pipeline."
        ),
        "built_in": True,
        "categories": ["audio", "chat", "cv", "ocr", "gate", "slicer", "render", "folder"],
    },
    "general_highlights": {
        "id": "general_highlights",
        "name": "General Highlights",
        "description": (
            "Chat velocity, audio spikes, and computer vision feeding a gate evaluator - no "
            "OCR or gambling-specific engines. A good fit for non-gambling streams."
        ),
        "built_in": True,
        "categories": ["audio", "chat", "cv", "gate", "slicer", "render", "folder"],
    },
    "minimal": {
        "id": "minimal",
        "name": "Minimal (Chat + Audio Only)",
        "description": (
            "Just chat velocity and audio spikes feeding the gate evaluator - the lightest "
            "starting point to build on."
        ),
        "built_in": True,
        "categories": ["audio", "chat", "gate", "slicer", "render", "folder"],
    },
}
DEFAULT_PRESET_ID = "gambling_slots"


class GraphDAGManager:
    """Manages the visual node graph topology, dynamic stream routing, and parameter mutators."""

    def __init__(self, orchestrator=None):
        self.orchestrator = orchestrator
        self.graph_id = "default_studio_graph"
        # Starts empty: no placeholder pipeline is built (and therefore nothing can ever
        # trigger a clip) until a user actually adds a stream or picks a preset/template.
        self.nodes: Dict[str, dict] = {}
        self.wires: List[dict] = []  # List of {"id": str, "from": str, "to": str, "type": str}
        self.last_sync_time = time.time()

    def _reachable_from(self, seed_ids: Set[str]) -> Set[str]:
        """Follows wires forward (from -> to) to collect every node downstream of the seeds."""
        seen = set(seed_ids)
        queue = deque(seed_ids)
        while queue:
            cur = queue.popleft()
            for wire in self.wires:
                src = wire.get("from", "").split(":")[0]
                dst = wire.get("to", "").split(":")[0]
                if src == cur and dst not in seen:
                    seen.add(dst)
                    queue.append(dst)
        return seen

    def get_preset_definition(self, preset_id: str) -> Optional[dict]:
        """Resolves a preset id to its definition - checks built-ins first, then saved custom templates."""
        if not preset_id:
            return None
        if preset_id in BUILTIN_PRESETS:
            return BUILTIN_PRESETS[preset_id]
        if self.orchestrator and getattr(self.orchestrator, "db", None):
            try:
                return self.orchestrator.db.get_template(preset_id)
            except Exception as e:
                logger.warning("[GraphDAG] Failed to load custom template '%s': %s", preset_id, e)
        return None

    def list_presets(self) -> List[dict]:
        """Returns built-in presets plus any custom templates saved by the user."""
        presets = [
            {"id": p["id"], "name": p["name"], "description": p["description"], "built_in": True}
            for p in BUILTIN_PRESETS.values()
        ]
        if self.orchestrator and getattr(self.orchestrator, "db", None):
            try:
                for t in self.orchestrator.db.list_templates():
                    presets.append({
                        "id": t["id"],
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "built_in": False,
                    })
            except Exception as e:
                logger.warning("[GraphDAG] Failed to list custom templates: %s", e)
        return presets

    def save_custom_template(self, name: str, channel: str) -> Optional[dict]:
        """Snapshots an active stream's pipeline (which categories + tuned properties) as a
        reusable named template. Captures the heuristic mix and its threshold tuning, not
        arbitrary custom wiring - templates always use the standard wiring shape for whatever
        categories they include.
        """
        from services.ingest.stream_buffer import clean_channel_name
        clean_ch = clean_channel_name(channel)

        stream_node = next(
            (
                n for n in self.nodes.values()
                if n.get("type") == "StreamSourceNode"
                and clean_channel_name(n.get("properties", {}).get("channel", "")) == clean_ch
            ),
            None,
        )
        if not stream_node:
            return None

        type_to_category = {v["type"]: k for k, v in CATEGORY_DEFS.items()}
        reachable = self._reachable_from({stream_node["id"]})

        categories: List[str] = []
        property_overrides: Dict[str, dict] = {}
        for nid in reachable:
            if nid == stream_node["id"]:
                continue
            node = self.nodes.get(nid)
            if not node:
                continue
            cat = type_to_category.get(node.get("type"))
            if not cat or cat == "folder":
                continue
            categories.append(cat)
            property_overrides[cat] = dict(node.get("properties", {}))

        if any(self.nodes.get(nid, {}).get("type") == "ClipFolderNode" for nid in reachable):
            categories.append("folder")

        if not categories:
            return None

        template_id = f"custom_{uuid.uuid4().hex[:12]}"
        definition = {
            "id": template_id,
            "name": name,
            "description": f"Custom template saved from #{clean_ch}",
            "built_in": False,
            "categories": categories,
            "property_overrides": property_overrides,
        }

        if self.orchestrator and getattr(self.orchestrator, "db", None):
            self.orchestrator.db.save_template(template_id, name, definition)

        return definition

    def delete_custom_template(self, template_id: str) -> bool:
        """Removes a saved custom template. Built-in presets can't be deleted."""
        if template_id in BUILTIN_PRESETS:
            return False
        if self.orchestrator and getattr(self.orchestrator, "db", None):
            try:
                return self.orchestrator.db.delete_template(template_id)
            except Exception as e:
                logger.warning("[GraphDAG] Failed to delete custom template '%s': %s", template_id, e)
        return False

    @staticmethod
    def _port_type(node: dict, port_id: str, io: str) -> str:
        for p in node.get(io, []):
            if p["id"] == port_id:
                return p["type"]
        return "trigger"

    def _instantiate_pipeline(
        self,
        categories: List[str],
        channel: str,
        plat: str,
        simulate: bool,
        base_y: float,
        property_overrides: Optional[Dict[str, dict]] = None,
    ) -> Tuple[Dict[str, dict], List[dict]]:
        """Builds a fresh, channel-suffixed node/wire set for the given preset categories."""
        suffix = channel
        property_overrides = property_overrides or {}
        node_ids: Dict[str, str] = {"stream": f"node_stream_{suffix}"}
        new_nodes: Dict[str, dict] = {}

        new_nodes[node_ids["stream"]] = {
            "id": node_ids["stream"],
            "type": "StreamSourceNode",
            "title": f"{plat.capitalize()} Source: #{channel}",
            "category": "stream",
            "position": [60, base_y],
            "properties": {"channel": channel, "platform": plat, "simulate": simulate},
            "inputs": [],
            "outputs": [
                {"id": "video", "name": "Video Stream", "type": "video"},
                {"id": "audio", "name": "Audio Stream", "type": "audio"},
                {"id": "chat", "name": "Chat Stream", "type": "chat"},
            ],
        }

        present = [c for c in categories if c != "folder" and c in CATEGORY_DEFS]
        folder_requested = "folder" in categories

        for cat in present:
            cat_def = CATEGORY_DEFS[cat]
            nid = f"node_{cat}_{suffix}"
            node_ids[cat] = nid
            x_off, y_off = CATEGORY_LAYOUT[cat]
            props = dict(cat_def["properties"])
            props.update(property_overrides.get(cat, {}))

            if cat == "gate":
                inputs = []
                for idx, (src_cat, _out_port, label) in enumerate(GATE_TRIGGER_SOURCES, start=1):
                    if src_cat in present:
                        inputs.append({"id": f"trigger_{idx}", "name": label, "type": "trigger"})
            else:
                inputs = copy.deepcopy(cat_def["inputs"])

            new_nodes[nid] = {
                "id": nid,
                "type": cat_def["type"],
                "title": f"{cat_def['title']} (#{channel})",
                "category": cat,
                "position": [x_off, base_y + y_off],
                "properties": props,
                "inputs": inputs,
                "outputs": copy.deepcopy(cat_def["outputs"]),
            }

        folder_nid = None
        if folder_requested:
            existing_folder = next((n for n in self.nodes.values() if n.get("type") == "ClipFolderNode"), None)
            if existing_folder:
                folder_nid = existing_folder["id"]
            else:
                folder_nid = f"node_folder_{suffix}"
                fdef = CATEGORY_DEFS["folder"]
                x_off, y_off = CATEGORY_LAYOUT["folder"]
                new_nodes[folder_nid] = {
                    "id": folder_nid,
                    "type": fdef["type"],
                    "title": fdef["title"],
                    "category": "folder",
                    "position": [x_off, base_y + y_off],
                    "properties": {"folder_name": "Highlight Reels", "date": time.strftime("%Y-%m-%d")},
                    "inputs": copy.deepcopy(fdef["inputs"]),
                    "outputs": [],
                }
            node_ids["folder"] = folder_nid

        new_wires: List[dict] = []
        wire_i = 0
        for src_cat, src_port, dst_cat, dst_port in BASE_WIRE_DEFS:
            if src_cat not in node_ids or dst_cat not in node_ids:
                continue
            wire_i += 1
            new_wires.append({
                "id": f"w_{suffix}_{wire_i}",
                "from": f"{node_ids[src_cat]}:{src_port}",
                "to": f"{node_ids[dst_cat]}:{dst_port}",
                "type": self._port_type(new_nodes[node_ids[src_cat]], src_port, "outputs"),
            })

        if "gate" in node_ids:
            gate_nid = node_ids["gate"]
            trig_idx = 0
            for src_cat, src_port, _label in GATE_TRIGGER_SOURCES:
                if src_cat not in node_ids:
                    continue
                trig_idx += 1
                new_wires.append({
                    "id": f"w_{suffix}_gate_{trig_idx}",
                    "from": f"{node_ids[src_cat]}:{src_port}",
                    "to": f"{gate_nid}:trigger_{trig_idx}",
                    "type": "trigger",
                })

        return new_nodes, new_wires

    def add_stream_pipeline(
        self,
        channel: str,
        platform: str = "twitch",
        auto_sequence: bool = True,
        simulate: bool = False,
        preset: Optional[str] = None,
    ) -> dict:
        """Adds a stream: a bare source node in manual mode, or a full preset-driven pipeline."""
        from services.ingest.stream_buffer import clean_channel_name
        clean_ch = clean_channel_name(channel)
        plat = str(platform or "twitch").lower()

        existing_stream_node = None
        for nid, n in self.nodes.items():
            if n.get("type") == "StreamSourceNode" and clean_channel_name(n.get("properties", {}).get("channel", "")) == clean_ch:
                existing_stream_node = n
                break
        if existing_stream_node:
            return self.get_graph()

        base_y = 160 if not self.nodes else max(n.get("position", [0, 0])[1] for n in self.nodes.values()) + 340

        if not auto_sequence:
            # Manual mode: just drop in a bare StreamSourceNode with no wires.
            new_id = f"node_stream_{clean_ch}"
            self.nodes[new_id] = {
                "id": new_id,
                "type": "StreamSourceNode",
                "title": f"{plat.capitalize()} Source: #{clean_ch}",
                "category": "stream",
                "position": [60, base_y],
                "properties": {"channel": clean_ch, "platform": plat, "simulate": simulate},
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

        preset_def = self.get_preset_definition(preset) or BUILTIN_PRESETS[DEFAULT_PRESET_ID]
        new_nodes, new_wires = self._instantiate_pipeline(
            categories=preset_def["categories"],
            channel=clean_ch,
            plat=plat,
            simulate=simulate,
            base_y=base_y,
            property_overrides=preset_def.get("property_overrides"),
        )
        self.nodes.update(new_nodes)
        self.wires.extend(new_wires)
        self.last_sync_time = time.time()
        self._apply_graph_to_orchestrator()
        return self.get_graph()

    def remove_stream_pipeline(self, channel: str) -> dict:
        """Removes a stream node and every worker node exclusively wired to it.

        Traces the DAG by following wires rather than assuming any node-ID naming
        convention, so it works regardless of which preset built the pipeline.
        """
        from services.ingest.stream_buffer import clean_channel_name
        clean_ch = clean_channel_name(channel)

        target_stream_ids = {
            nid for nid, n in self.nodes.items()
            if n.get("type") == "StreamSourceNode"
            and clean_channel_name(n.get("properties", {}).get("channel", "")) == clean_ch
        }
        if not target_stream_ids:
            return self.get_graph()

        other_stream_ids = {
            nid for nid, n in self.nodes.items()
            if n.get("type") == "StreamSourceNode" and nid not in target_stream_ids
        }

        reachable_from_target = self._reachable_from(target_stream_ids)
        reachable_from_others = self._reachable_from(other_stream_ids) if other_stream_ids else set()

        # Never remove a node still reachable from another active stream
        # (e.g. a shared ClipFolderNode wired from multiple renderers).
        nodes_to_remove = reachable_from_target - reachable_from_others

        for nid in nodes_to_remove:
            self.nodes.pop(nid, None)

        self.wires = [
            w for w in self.wires
            if w["from"].split(":")[0] not in nodes_to_remove and w["to"].split(":")[0] not in nodes_to_remove
        ]

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

        # Reject renaming a StreamSourceNode onto a channel another StreamSourceNode
        # already owns - each active stream must keep its own dedicated pipeline,
        # never two pipelines silently pointing at the same channel.
        if node.get("type") == "StreamSourceNode" and param == "channel":
            from services.ingest.stream_buffer import clean_channel_name
            new_ch = clean_channel_name(str(value))
            collision = any(
                nid != node_id
                and n.get("type") == "StreamSourceNode"
                and clean_channel_name(n.get("properties", {}).get("channel", "")) == new_ch
                for nid, n in self.nodes.items()
            )
            if new_ch and collision:
                logger.warning(
                    "[GraphDAG] Refused to rename node %s to channel '%s': already owned by another StreamSourceNode",
                    node_id, new_ch,
                )
                return False

        if "properties" not in node:
            node["properties"] = {}
        node["properties"][param] = value
        if node.get("type") == "StreamSourceNode":
            if param in ("channel", "platform"):
                ch = node["properties"].get("channel", "marlon")
                plat = str(node["properties"].get("platform", "twitch")).capitalize()
                node["title"] = f"{plat} Source: #{ch}"
        if node.get("type") == "GamblingOCRNode" and param.startswith("roi_"):
            rkey = param.replace("roi_", "")
            if "rois" not in node["properties"] or not isinstance(node["properties"]["rois"], dict):
                node["properties"]["rois"] = {}
            node["properties"]["rois"][rkey] = value
        if node.get("type") == "OCRVisionNode" and param == "slot_preset":
            channel = self.nodes.get("node_stream", {}).get("properties", {}).get("channel")
            session = self.orchestrator.sessions.get(channel) if (self.orchestrator and channel) else None
            if session and getattr(session, "dynamic_ocr", None):
                session.dynamic_ocr.apply_slot_preset(str(value))
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

            elif ntype == "FacecamEmotionNode" and getattr(session, "streamer_emotion", None):
                if "tilt_threshold" in props:
                    session.streamer_emotion.tilt_threshold = float(props["tilt_threshold"])
                if "euphoria_threshold" in props:
                    session.streamer_emotion.euphoria_threshold = float(props["euphoria_threshold"])
                if "face_roi" in props and isinstance(props["face_roi"], dict):
                    r = props["face_roi"]
                    session.streamer_emotion.update_roi(r.get("x", 0.02), r.get("y", 0.05), r.get("w", 0.22), r.get("h", 0.28))

            elif ntype == "GamblingOCRNode" and getattr(session, "gambling_ocr", None):
                if "preset" in props:
                    session.gambling_ocr.set_preset(props["preset"])
                if "rois" in props and isinstance(props["rois"], dict):
                    for rkey, rval in props["rois"].items():
                        if isinstance(rval, dict):
                            session.gambling_ocr.update_roi(rkey, rval.get("x", 0), rval.get("y", 0), rval.get("w", 0.1), rval.get("h", 0.1))
                for rk in ("balance", "bet", "win", "reels"):
                    if f"roi_{rk}" in props and isinstance(props[f"roi_{rk}"], dict):
                        rv = props[f"roi_{rk}"]
                        session.gambling_ocr.update_roi(rk, rv.get("x", 0), rv.get("y", 0), rv.get("w", 0.1), rv.get("h", 0.1))

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

            # For worker nodes: resolve routed session via wires or explicit channel
            session = self.get_node_source_session(node_id)
            if not session:
                payload[node_id] = {
                    "unrouted": True,
                    "status": "unrouted",
                }
                continue

            calc = session.chat_engine.recalculate() if session.chat_engine else {}
            extra = session.extra_telemetry

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
                payload[node_id] = {
                    "top_emotion": extra.get("emotion_top", "neutral"),
                    "confidence": extra.get("emotion_confidence", 0.0),
                    "emotions": extra.get("emotion_distribution", {}),
                    "valence": extra.get("emotion_valence", 0.0),
                    "arousal": extra.get("emotion_arousal", 0.0),
                    "tilt_score": extra.get("emotion_tilt", 0.0),
                    "euphoria_score": extra.get("emotion_euphoria", 0.0),
                    "is_tilting": extra.get("is_tilting", False),
                    "face_roi": getattr(session.streamer_emotion, "face_roi", {}) if getattr(session, "streamer_emotion", None) else {},
                    "stream_frame_b64": extra.get("stream_frame_b64", ""),
                    "source_channel": session.channel,
                }
            elif node_type == "GamblingOCRNode":
                payload[node_id] = {
                    "balance": extra.get("gambling_balance", 0.0),
                    "bet": extra.get("gambling_bet", 0.0),
                    "win": extra.get("gambling_win", 0.0),
                    "multiplier": extra.get("gambling_multiplier", 0.0),
                    "spin_state": extra.get("gambling_spin_state", "IDLE"),
                    "rois": getattr(session.gambling_ocr, "rois", {}) if getattr(session, "gambling_ocr", None) else {},
                    "stream_frame_b64": extra.get("stream_frame_b64", ""),
                    "source_channel": session.channel,
                }
            elif node_type == "GamblingLedgerNode":
                ledger_summary = session.gambling_ledger.get_summary() if getattr(session, "gambling_ledger", None) else {}
                payload[node_id] = {
                    "starting_balance": ledger_summary.get("starting_balance", 0.0),
                    "current_balance": ledger_summary.get("current_balance", 0.0),
                    "net_pnl": ledger_summary.get("net_pnl", 0.0),
                    "winrate_pct": ledger_summary.get("winrate_pct", 0.0),
                    "current_streak": ledger_summary.get("current_streak", 0),
                    "total_spins": ledger_summary.get("total_spins", 0),
                    "total_wagered": ledger_summary.get("total_wagered", 0.0),
                    "total_payout": ledger_summary.get("total_payout", 0.0),
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
                arm_status = session.gate_evaluator.get_arm_status() if session.gate_evaluator else {"is_arming": False, "arm_remaining_seconds": 0.0}
                payload[node_id] = {
                    "score": getattr(session.gate_evaluator, "current_score", 1),
                    "is_debouncing": is_debouncing,
                    "debounce_remaining": debounce_remaining,
                    "is_arming": arm_status["is_arming"],
                    "arm_remaining_seconds": arm_status["arm_remaining_seconds"],
                    "source_channel": session.channel,
                }

        return payload
