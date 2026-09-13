/**
 * Autonomous Stream Clipper - ComfyUI-Style Node Graph Studio Engine
 * Zero-dependency SVG + CSS Hardware-Accelerated DOM Node Graph Architecture.
 */

(function () {
  class NodeStudioEngine {
    constructor() {
      this.container = document.getElementById("graph-studio-container");
      this.canvas = document.getElementById("graph-canvas");
      this.svgLayer = document.getElementById("graph-svg-layer");
      this.nodesLayer = document.getElementById("graph-nodes-layer");

      // Canvas Transform State
      this.panX = 120;
      this.panY = 100;
      this.scale = 0.95;
      this.isPanning = false;
      this.startPan = { x: 0, y: 0 };

      // Active Channel Binding
      this.selectedChannel = (window.activeTab || "").replace(/^#/, "").toLowerCase();
      this.miniPlayers = new Map();

      // Graph Data
      this.nodes = new Map();
      this.wires = []; // [{ id, from: "node:port", to: "node:port", type }]
      this.portTypes = {};

      // Selection & Interaction State
      this.selectedNodeId = null;
      this.selectedWireId = null;
      this.draggedNode = null;
      this.nodeDragOffset = { x: 0, y: 0 };
      this.activeWireDrag = null; // { fromNodeId, fromPortId, fromType, startX, startY, currentX, currentY }
      this.nodeRoiControllers = new Map();

      // Preset Templates with Faceted Relational Taxonomy
      this.nodeCatalog = [
        {
          type: "StreamSourceNode",
          category: "stream",
          stage: "source",
          title: "Stream Source (Twitch / Kick)",
          icon: "🔴",
          desc: "Live HLS, PCM Audio, & Chat",
          inputs_accepted: [],
          outputs_produced: ["video", "audio", "chat"],
          tags: ["stage:source", "out:video", "out:audio", "out:chat", "stream", "twitch", "kick", "ingest", "hls", "pcm", "chat", "irc"],
        },
        {
          type: "VideoCropNode",
          category: "transform",
          stage: "transform",
          title: "Video ROI Cropper",
          icon: "✂️",
          desc: "Targeted spatial crop (facecam, HUD, chat)",
          inputs_accepted: ["video"],
          outputs_produced: ["video"],
          tags: ["stage:transform", "in:video", "out:video", "crop", "roi", "facecam", "bounding-box", "subset", "hud", "filter", "vision"],
        },
        {
          type: "ImageScaleNode",
          category: "transform",
          stage: "transform",
          title: "Resolution & Scaler",
          icon: "🔬",
          desc: "Lanczos4, Bicubic, AI Super-Resolution (ESPCN) & Detail Filters",
          inputs_accepted: ["video"],
          outputs_produced: ["video"],
          tags: [
            "stage:transform", "in:video", "out:video",
            "scale", "resolution", "resample", "upscale", "downscale",
            "lanczos", "bicubic", "nearest", "bilinear", "area",
            "clahe", "sharpen", "denoise", "unsharp",
            "super-resolution", "neural", "ai", "ocr-preprocessor",
            "filter", "vision", "transform"
          ],
        },
        {
          type: "AudioMonitorNode",
          category: "audio",
          stage: "heuristic",
          title: "Audio Decibel Monitor",
          icon: "🔊",
          desc: "RMS dB jump & volume spikes",
          inputs_accepted: ["audio"],
          outputs_produced: ["trigger", "scalar"],
          tags: ["stage:heuristic", "in:audio", "out:trigger", "out:scalar", "audio", "decibels", "rms", "volume", "scream", "loud", "spike", "jump"],
        },
        {
          type: "ChatVelocityNode",
          category: "chat",
          stage: "heuristic",
          title: "Chat Velocity Engine",
          icon: "💬",
          desc: "Messages/sec & spike ratio",
          inputs_accepted: ["chat"],
          outputs_produced: ["trigger", "scalar"],
          tags: ["stage:heuristic", "in:chat", "out:trigger", "out:scalar", "chat", "velocity", "messages-per-sec", "spam", "pog", "hype", "spike"],
        },
        {
          type: "OCRVisionNode",
          category: "ocr",
          stage: "heuristic",
          title: "OCR Classifier",
          icon: "🔍",
          desc: "Multiplier, balance & text recognition (route cropped video in)",
          inputs_accepted: ["video"],
          outputs_produced: ["trigger", "scalar"],
          tags: ["stage:heuristic", "in:video", "out:trigger", "out:scalar", "ocr", "vision", "multiplier", "balance", "tesseract", "numbers", "text", "classifier"],
        },
        {
          type: "CVTransformerNode",
          category: "cv",
          stage: "heuristic",
          title: "HuggingFace Vision",
          icon: "👁️",
          desc: "Zero-shot classification & detection",
          inputs_accepted: ["video"],
          outputs_produced: ["trigger", "scalar", "text"],
          tags: ["stage:heuristic", "in:video", "out:trigger", "out:scalar", "out:text", "vision", "ai", "clip", "vit", "zero-shot", "gameplay", "victory", "celebration"],
        },
        {
          type: "FacecamEmotionNode",
          category: "cv",
          stage: "heuristic",
          title: "Emotion Classifier",
          icon: "🎭",
          desc: "MobileFaceNet & FERPlus facial expressions, valence, arousal, & tilt/rage spikes (route facecam video in)",
          inputs_accepted: ["video"],
          outputs_produced: ["trigger", "scalar"],
          tags: ["stage:heuristic", "in:video", "out:trigger", "out:scalar", "emotion", "classifier", "tilt", "rage", "euphoria", "valence", "arousal", "ai", "ferplus", "happy", "angry", "sad", "surprise"],
        },
        {
          type: "GamblingLedgerNode",
          category: "analytics",
          stage: "analytics",
          title: "Gambling PnL & Ledger",
          icon: "💰",
          desc: "Net PnL, Winrate, Streaks & Martingale alert",
          inputs_accepted: ["scalar"],
          outputs_produced: ["trigger", "scalar"],
          tags: ["stage:analytics", "in:scalar", "out:trigger", "out:scalar", "pnl", "ledger", "winrate", "rtp", "streak", "martingale", "gambling", "stats"],
        },
        {
          type: "ScreenSummarizerNode",
          category: "summarizer",
          stage: "heuristic",
          title: "AI Screen Summarizer",
          icon: "🤖",
          desc: "Multimodal frame vision + chat",
          inputs_accepted: ["video", "chat"],
          outputs_produced: ["trigger", "text"],
          tags: ["stage:heuristic", "in:video", "in:chat", "out:trigger", "out:text", "multimodal", "gemini", "summary", "ai", "vision", "context", "recap"],
        },
        {
          type: "GateEvaluatorNode",
          category: "gate",
          stage: "gate",
          title: "Gate Evaluator & Logic",
          icon: "⚡",
          desc: "Weighted scoring & debounce",
          inputs_accepted: ["trigger"],
          outputs_produced: ["trigger", "scalar"],
          tags: ["stage:gate", "in:trigger", "out:trigger", "out:scalar", "gate", "logic", "combiner", "debounce", "weighted-score", "boolean", "cooldown"],
        },
        {
          type: "ThresholdGateNode",
          category: "gate",
          stage: "gate",
          title: "Threshold Logic Gate",
          icon: "⚖️",
          desc: "Multi-input scalar gate with customizable threshold rules, operators (> / >= / < / <= / ==), scenarios (ALL / ANY / COUNT), and toggled sliders",
          inputs_accepted: ["scalar"],
          outputs_produced: ["trigger", "scalar"],
          tags: [
            "stage:gate", "in:scalar", "out:trigger", "out:scalar",
            "gate", "threshold", "logic", "value", "slider", "compare",
            "above", "below", "all", "any", "count", "multi-input", "filter"
          ],
        },
        {
          type: "SegmentSlicerNode",
          category: "slicer",
          stage: "slicer",
          title: "Rolling Segment Slicer",
          icon: "✂️",
          desc: "60s zero-copy extraction",
          inputs_accepted: ["video", "trigger"],
          outputs_produced: ["video"],
          tags: ["stage:slicer", "in:video", "in:trigger", "out:video", "slicer", "ram-buffer", "zero-copy", "ts", "window", "slice", "extraction"],
        },
        {
          type: "HardwareRenderNode",
          category: "render",
          stage: "render",
          title: "Hardware Video Renderer",
          icon: "🎬",
          desc: "Uncropped 1080p / 9:16 vertical",
          inputs_accepted: ["video"],
          outputs_produced: ["clip"],
          tags: ["stage:render", "in:video", "out:clip", "render", "hardware", "videotoolbox", "vertical", "9:16", "tiktok", "shorts", "subtitles", "karaoke"],
        },
        {
          type: "ClipFolderNode",
          category: "storage",
          stage: "storage",
          title: "Clip Folder / Collection",
          icon: "📂",
          desc: "Multi-renderer folder repository & date organizer",
          inputs_accepted: ["clip"],
          outputs_produced: [],
          tags: ["stage:storage", "in:clip", "storage", "folder", "collection", "album", "save", "organize", "date", "export", "sink"],
        },
      ];

      this.initEvents();
      this.initToolbar();
      this.initSpawnPalette();
      this.loadGraph();
    }

    /* -------------------------------------------------------------
       Coordinate Space Transforms
       ------------------------------------------------------------- */
    screenToWorld(sx, sy) {
      const rect = this.canvas.getBoundingClientRect();
      const x = sx - rect.left;
      const y = sy - rect.top;
      return {
        x: (x - this.panX) / this.scale,
        y: (y - this.panY) / this.scale,
      };
    }

    worldToScreen(wx, wy) {
      return {
        x: wx * this.scale + this.panX,
        y: wy * this.scale + this.panY,
      };
    }

    updateTransform() {
      this.nodesLayer.style.transform = `translate3d(${this.panX}px, ${this.panY}px, 0) scale(${this.scale})`;
      this.canvas.style.backgroundPosition = `${this.panX}px ${this.panY}px`;
      this.canvas.style.backgroundSize = `${24 * this.scale}px ${24 * this.scale}px`;
      this.renderWires();
    }

    /* -------------------------------------------------------------
       Canvas Pan & Zoom Event Handlers
       ------------------------------------------------------------- */
    initEvents() {
      // Mouse Wheel Zoom centered at cursor
      this.container.addEventListener("wheel", (e) => {
        if (!this.container.classList.contains("active")) return;
        e.preventDefault();

        const rect = this.canvas.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        const zoomFactor = e.deltaY < 0 ? 1.08 : 0.92;
        const newScale = Math.min(2.5, Math.max(0.25, this.scale * zoomFactor));
        const deltaScale = newScale - this.scale;

        this.panX -= (mouseX - this.panX) * (deltaScale / this.scale);
        this.panY -= (mouseY - this.panY) * (deltaScale / this.scale);
        this.scale = newScale;

        this.updateTransform();
      }, { passive: false });

      // Canvas Dragging / Panning
      this.canvas.addEventListener("mousedown", (e) => {
        if (e.target === this.canvas || e.target === this.svgLayer) {
          // Middle click or Left click on background
          if (e.button === 0 || e.button === 1) {
            this.isPanning = true;
            this.startPan = { x: e.clientX - this.panX, y: e.clientY - this.panY };
            this.canvas.classList.add("panning");
            this.deselectAll();
            this.closeSpawnPalette();
          }
        }
      });

      window.addEventListener("mousemove", (e) => {
        if (this.isPanning) {
          this.panX = e.clientX - this.startPan.x;
          this.panY = e.clientY - this.startPan.y;
          this.updateTransform();
        } else if (this.draggedNode) {
          const worldPos = this.screenToWorld(e.clientX, e.clientY);
          this.draggedNode.position = [
            Math.round(worldPos.x - this.nodeDragOffset.x),
            Math.round(worldPos.y - this.nodeDragOffset.y),
          ];
          this.updateNodeDOMPosition(this.draggedNode);
          this.renderWires();
        } else if (this.activeWireDrag) {
          const worldPos = this.screenToWorld(e.clientX, e.clientY);
          this.activeWireDrag.currentX = worldPos.x;
          this.activeWireDrag.currentY = worldPos.y;
          this.renderWires();
          this.checkPortHover(e.clientX, e.clientY);
        }
      });

      window.addEventListener("mouseup", (e) => {
        if (this.isPanning) {
          this.isPanning = false;
          this.canvas.classList.remove("panning");
        }
        if (this.draggedNode) {
          this.draggedNode = null;
          this.syncGraphDebounced();
        }
        if (this.activeWireDrag) {
          this.finalizeWireDrag(e);
        }
      });

      // Keyboard Delete
      window.addEventListener("keydown", (e) => {
        if (!this.container.classList.contains("active")) return;
        if (e.key === "Delete" || e.key === "Backspace") {
          // Avoid deleting when user is typing in an input
          if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
          if (this.selectedWireId) {
            this.deleteWire(this.selectedWireId);
          } else if (this.selectedNodeId) {
            this.deleteNode(this.selectedNodeId);
          }
        }
      });

      // Context Menu on Canvas (Right-Click Spawn Menu)
      this.container.addEventListener("contextmenu", (e) => {
        if (!this.container.classList.contains("active")) return;
        e.preventDefault();
        this.openSpawnPalette(e.clientX, e.clientY);
      });
    }

    /* -------------------------------------------------------------
       Wire Rendering & Bézier Math
       ------------------------------------------------------------- */
    getPortWorldCoords(nodeId, portId, isOutput) {
      const nodeEl = document.getElementById(`node-${nodeId}`);
      if (!nodeEl) return null;

      const portEl = nodeEl.querySelector(`.port-pin[data-port="${portId}"]`);
      if (!portEl) return null;

      const rect = portEl.getBoundingClientRect();
      const centerScreen = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
      return this.screenToWorld(centerScreen.x, centerScreen.y);
    }

    computeBezierPath(x1, y1, x2, y2) {
      const dx = Math.max(45, Math.abs(x2 - x1) * 0.55);
      return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
    }

    renderWires() {
      // Clear wire layer
      this.svgLayer.innerHTML = "";

      // Render confirmed graph wires
      this.wires.forEach((wire) => {
        const [fromNodeId, fromPortId] = wire.from.split(":");
        const [toNodeId, toPortId] = wire.to.split(":");

        const p1 = this.getPortWorldCoords(fromNodeId, fromPortId, true);
        const p2 = this.getPortWorldCoords(toNodeId, toPortId, false);

        if (!p1 || !p2) return;

        // Convert world points to SVG screen space
        const s1 = this.worldToScreen(p1.x, p1.y);
        const s2 = this.worldToScreen(p2.x, p2.y);

        const pathStr = this.computeBezierPath(s1.x, s1.y, s2.x, s2.y);

        // Group container for hitbox, visual wire, and midpoint delete button
        const groupEl = document.createElementNS("http://www.w3.org/2000/svg", "g");
        groupEl.setAttribute("class", `graph-wire-group ${this.selectedWireId === wire.id ? "selected" : ""}`);
        groupEl.setAttribute("data-wire-id", wire.id);

        // 1. Invisible wide hitbox for easy clicking & hovering
        const hitboxEl = document.createElementNS("http://www.w3.org/2000/svg", "path");
        hitboxEl.setAttribute("d", pathStr);
        hitboxEl.setAttribute("class", "graph-wire-hitbox");

        // 2. Visible wire path
        const pathEl = document.createElementNS("http://www.w3.org/2000/svg", "path");
        pathEl.setAttribute("d", pathStr);
        pathEl.setAttribute("id", `wire-${wire.id}`);
        pathEl.setAttribute("class", `graph-wire wire-active ${this.selectedWireId === wire.id ? "selected" : ""}`);
        pathEl.style.stroke = this.getPortColor(wire.type);

        // 3. Floating midpoint delete button badge
        // Symmetric horizontal cubic bezier midpoint P(0.5) is exactly ((s1.x + s2.x)/2, (s1.y + s2.y)/2)
        const midX = (s1.x + s2.x) / 2;
        const midY = (s1.y + s2.y) / 2;

        const btnEl = document.createElementNS("http://www.w3.org/2000/svg", "g");
        btnEl.setAttribute("class", "graph-wire-delete-btn");
        btnEl.setAttribute("transform", `translate(${midX}, ${midY})`);
        btnEl.setAttribute("data-wire-id", wire.id);

        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("r", "10");
        circle.setAttribute("class", "wire-delete-circle");

        const cross = document.createElementNS("http://www.w3.org/2000/svg", "path");
        cross.setAttribute("d", "M -3.5 -3.5 L 3.5 3.5 M 3.5 -3.5 L -3.5 3.5");
        cross.setAttribute("class", "wire-delete-cross");

        btnEl.appendChild(circle);
        btnEl.appendChild(cross);

        // Action handlers
        const handleDeleteWire = (e) => {
          e.preventDefault();
          e.stopPropagation();
          this.deleteWire(wire.id, true);
        };

        const handleContextMenu = (e) => {
          e.preventDefault();
          e.stopPropagation();
          this.openWireContextMenu(wire.id, e.clientX, e.clientY);
        };

        btnEl.addEventListener("click", handleDeleteWire);

        hitboxEl.addEventListener("click", (e) => {
          e.stopPropagation();
          if (e.altKey) {
            handleDeleteWire(e);
          } else {
            this.selectWire(wire.id);
          }
        });
        hitboxEl.addEventListener("dblclick", handleDeleteWire);
        hitboxEl.addEventListener("contextmenu", handleContextMenu);

        pathEl.addEventListener("click", (e) => {
          e.stopPropagation();
          if (e.altKey) {
            handleDeleteWire(e);
          } else {
            this.selectWire(wire.id);
          }
        });
        pathEl.addEventListener("dblclick", handleDeleteWire);
        pathEl.addEventListener("contextmenu", handleContextMenu);

        groupEl.appendChild(hitboxEl);
        groupEl.appendChild(pathEl);
        groupEl.appendChild(btnEl);
        this.svgLayer.appendChild(groupEl);
      });

      // Render temporary dragging wire
      if (this.activeWireDrag) {
        const s1 = this.worldToScreen(this.activeWireDrag.startX, this.activeWireDrag.startY);
        const s2 = this.worldToScreen(this.activeWireDrag.currentX, this.activeWireDrag.currentY);
        const dragPath = this.computeBezierPath(s1.x, s1.y, s2.x, s2.y);

        const dragEl = document.createElementNS("http://www.w3.org/2000/svg", "path");
        dragEl.setAttribute("d", dragPath);
        dragEl.setAttribute("class", "drag-temp-wire");
        dragEl.style.stroke = this.getPortColor(this.activeWireDrag.fromType);
        this.svgLayer.appendChild(dragEl);
      }
    }

    getPortColor(type) {
      const colors = {
        video: "#f43f5e",
        audio: "#38bdf8",
        chat: "#a855f7",
        trigger: "#eab308",
        scalar: "#10b981",
        text: "#6366f1",
        clip: "#f97316",
      };
      return colors[type] || "#38bdf8";
    }

    /* -------------------------------------------------------------
       Port Dragging & Magnetic Snapping
       ------------------------------------------------------------- */
    startWireDrag(nodeId, portId, portType, e) {
      e.stopPropagation();
      const startCoord = this.getPortWorldCoords(nodeId, portId, true);
      if (!startCoord) return;

      this.activeWireDrag = {
        fromNodeId: nodeId,
        fromPortId: portId,
        fromType: portType,
        startX: startCoord.x,
        startY: startCoord.y,
        currentX: startCoord.x,
        currentY: startCoord.y,
      };
      this.renderWires();
    }

    checkPortHover(clientX, clientY) {
      const allPins = document.querySelectorAll(".port-pin.input");
      allPins.forEach((pin) => {
        const rect = pin.getBoundingClientRect();
        const dist = Math.hypot(clientX - (rect.left + rect.width / 2), clientY - (rect.top + rect.height / 2));
        const portType = pin.getAttribute("data-type");

        if (dist < 26 && this.activeWireDrag && portType === this.activeWireDrag.fromType) {
          pin.classList.add("hovered");
        } else {
          pin.classList.remove("hovered");
        }
      });
    }

    finalizeWireDrag(e) {
      const hoveredPin = document.querySelector(".port-pin.input.hovered");
      if (hoveredPin && this.activeWireDrag) {
        const toNodeId = hoveredPin.getAttribute("data-node");
        const toPortId = hoveredPin.getAttribute("data-port");
        const toType = hoveredPin.getAttribute("data-type");

        if (toNodeId !== this.activeWireDrag.fromNodeId && toType === this.activeWireDrag.fromType) {
          this.createWire(
            `${this.activeWireDrag.fromNodeId}:${this.activeWireDrag.fromPortId}`,
            `${toNodeId}:${toPortId}`,
            this.activeWireDrag.fromType
          );
        }
      } else if (!hoveredPin && this.activeWireDrag) {
        // Wire dropped onto empty canvas - open context-sensitive spawn palette
        const startScreen = this.worldToScreen(this.activeWireDrag.startX, this.activeWireDrag.startY);
        const dragDist = Math.hypot(e.clientX - startScreen.x, e.clientY - startScreen.y);
        if (dragDist > 25) {
          const wireInfo = {
            fromNodeId: this.activeWireDrag.fromNodeId,
            fromPortId: this.activeWireDrag.fromPortId,
            fromType: this.activeWireDrag.fromType,
          };
          setTimeout(() => {
            this.openSpawnPalette(e.clientX, e.clientY, `in:${wireInfo.fromType}`, wireInfo);
          }, 10);
        }
      }

      document.querySelectorAll(".port-pin.hovered").forEach((p) => p.classList.remove("hovered"));
      this.activeWireDrag = null;
      this.renderWires();
    }

    createWire(fromStr, toStr, type) {
      // Prevent duplicate wire
      if (this.wires.some((w) => w.from === fromStr && w.to === toStr)) return;

      const newWire = {
        id: `w_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`,
        from: fromStr,
        to: toStr,
        type: type,
      };
      this.wires.push(newWire);

      // Check if destination is ThresholdGateNode
      const [fromNodeId, fromPortId] = fromStr.split(":");
      const [toNodeId, toPortId] = toStr.split(":");
      const dstNode = this.nodes.get(toNodeId);
      const srcNode = this.nodes.get(fromNodeId);

      if (dstNode && dstNode.type === "ThresholdGateNode" && srcNode) {
        const srcPort = (srcNode.outputs || []).find((p) => p.id === fromPortId);
        if (srcPort) {
          if (!dstNode.properties) dstNode.properties = {};
          if (!dstNode.properties.rules) dstNode.properties.rules = {};
          const rule = dstNode.properties.rules[toPortId] || { operator: ">=" };
          rule.label = srcPort.name || toPortId;
          if (srcPort.min !== undefined) rule.min = srcPort.min;
          if (srcPort.max !== undefined) rule.max = srcPort.max;
          if (srcPort.step !== undefined) rule.step = srcPort.step;
          if (srcPort.unit !== undefined) rule.unit = srcPort.unit;

          const minV = rule.min !== undefined ? rule.min : 0.0;
          const maxV = rule.max !== undefined ? rule.max : 1.0;
          if (rule.threshold === undefined || rule.threshold < minV || rule.threshold > maxV) {
            rule.threshold = Number(((minV + maxV) / 2.0).toFixed(2));
          }
          dstNode.properties.rules[toPortId] = rule;

          // Re-render the node DOM to reflect new slider bounds, units, and label
          const oldEl = document.getElementById(`node-${toNodeId}`);
          if (oldEl) oldEl.remove();
          this.renderNodeDOM(dstNode);
        }
      }

      this.renderWires();
      this.syncGraphDebounced();
      if (this.latestTelemetry) {
        this.applyTelemetry(this.latestTelemetry);
      }
    }

    _isRootSourceNode(nodeId) {
      const node = this.nodes.get(nodeId);
      if (!node) return true;
      if (node.type === "StreamSourceNode") return true;
      const inputs = node.inputs || [];
      return inputs.length === 0;
    }

    _cascadePruneCutoffNodes(candidateNodeIds, deletedWireIds = new Set(), cutoffNodeIds = new Set()) {
      const queue = [...candidateNodeIds].filter((nid) => nid && !this._isRootSourceNode(nid));

      while (queue.length > 0) {
        const nodeId = queue.shift();
        if (cutoffNodeIds.has(nodeId)) continue;

        // Check if this node has ANY remaining incoming wires (excluding wires already marked deleted)
        const incomingWires = this.wires.filter(
          (w) => !deletedWireIds.has(w.id) && w.to.split(":")[0] === nodeId
        );

        if (incomingWires.length === 0) {
          // Node is completely cutoff!
          cutoffNodeIds.add(nodeId);

          // Find all outgoing wires from this newly cutoff node
          const outgoingWires = this.wires.filter(
            (w) => !deletedWireIds.has(w.id) && w.from.split(":")[0] === nodeId
          );

          for (const outWire of outgoingWires) {
            deletedWireIds.add(outWire.id);
            const nextDstNodeId = outWire.to.split(":")[0];
            if (nextDstNodeId && !cutoffNodeIds.has(nextDstNodeId) && !this._isRootSourceNode(nextDstNodeId)) {
              queue.push(nextDstNodeId);
            }
          }
        }
      }

      return { deletedWireIds, cutoffNodeIds };
    }

    deleteWire(wireId, cascade = true) {
      const wire = this.wires.find((w) => w.id === wireId);
      if (!wire) return;

      const deletedWireIds = new Set([wireId]);
      const targetNodeId = wire.to.split(":")[0];
      let prunedDownstreamCount = 0;
      let cutoffNodeNames = [];

      if (cascade && targetNodeId) {
        const { deletedWireIds: allDeleted, cutoffNodeIds } = this._cascadePruneCutoffNodes(
          [targetNodeId],
          deletedWireIds
        );
        prunedDownstreamCount = allDeleted.size - 1;

        cutoffNodeIds.forEach((cId) => {
          const cNode = this.nodes.get(cId);
          if (cNode) {
            this.renderUnroutedNodeState(cNode);
            cutoffNodeNames.push(cNode.title || cNode.type || cId);
          }
        });
      }

      this.wires = this.wires.filter((w) => !deletedWireIds.has(w.id));
      this.selectedWireId = null;
      this.closeWireContextMenu();
      this.renderWires();
      this.syncGraphDebounced();
      if (this.latestTelemetry) {
        this.applyTelemetry(this.latestTelemetry);
      }

      if (prunedDownstreamCount > 0) {
        const summary = cutoffNodeNames.length <= 2
          ? cutoffNodeNames.join(", ")
          : `${cutoffNodeNames.slice(0, 2).join(", ")} +${cutoffNodeNames.length - 2} more`;
        this.showToast(`✂️ Severed connection & pruned ${prunedDownstreamCount} cutoff downstream wire(s) (${summary}).`);
      } else {
        this.showToast("✂️ Connection removed.");
      }
    }

    openWireContextMenu(wireId, clientX, clientY) {
      this.closeWireContextMenu();
      const menu = document.createElement("div");
      menu.setAttribute("id", "wire-context-menu");
      menu.setAttribute("class", "wire-context-menu");

      const menuWidth = 260;
      const menuHeight = 140;
      const posX = Math.min(clientX, window.innerWidth - menuWidth - 16);
      const posY = Math.min(clientY, window.innerHeight - menuHeight - 16);
      menu.style.left = `${Math.max(12, posX)}px`;
      menu.style.top = `${Math.max(12, posY)}px`;

      menu.innerHTML = `
        <div class="wire-menu-header">Connection Options</div>
        <div class="wire-menu-item delete-cascade" data-action="delete-cascade">
          <span class="icon">✂️</span>
          <span class="label">Delete Connection & Prune Cutoff</span>
          <span class="badge">Default</span>
        </div>
        <div class="wire-menu-item delete-single" data-action="delete-single">
          <span class="icon">🔗</span>
          <span class="label">Delete Connection Only</span>
        </div>
        <div class="wire-menu-divider"></div>
        <div class="wire-menu-item cancel" data-action="cancel">
          <span class="icon">✖️</span>
          <span class="label">Cancel</span>
        </div>
      `;

      menu.querySelector(".delete-cascade").addEventListener("click", (e) => {
        e.stopPropagation();
        this.closeWireContextMenu();
        this.deleteWire(wireId, true);
      });

      menu.querySelector(".delete-single").addEventListener("click", (e) => {
        e.stopPropagation();
        this.closeWireContextMenu();
        this.deleteWire(wireId, false);
      });

      menu.querySelector(".cancel").addEventListener("click", (e) => {
        e.stopPropagation();
        this.closeWireContextMenu();
      });

      document.body.appendChild(menu);

      const dismissHandler = (e) => {
        if (!menu.contains(e.target)) {
          this.closeWireContextMenu();
          window.removeEventListener("pointerdown", dismissHandler);
        }
      };
      setTimeout(() => window.addEventListener("pointerdown", dismissHandler), 10);
    }

    closeWireContextMenu() {
      const existing = document.getElementById("wire-context-menu");
      if (existing) existing.remove();
    }

    selectWire(wireId) {
      this.selectedWireId = wireId;
      this.selectedNodeId = null;
      this.closeWireContextMenu();
      document.querySelectorAll(".studio-node").forEach((n) => n.classList.remove("selected"));
      this.renderWires();
    }

    deselectAll() {
      this.selectedNodeId = null;
      this.selectedWireId = null;
      this.closeWireContextMenu();
      document.querySelectorAll(".studio-node").forEach((n) => n.classList.remove("selected"));
      this.renderWires();
    }

    /* -------------------------------------------------------------
       Node Lifecycle & DOM Generation
       ------------------------------------------------------------- */
    renderNodeDOM(node) {
      const el = document.createElement("div");
      el.setAttribute("id", `node-${node.id}`);
      el.setAttribute("class", `studio-node ${this.selectedNodeId === node.id ? "selected" : ""}`);
      el.style.transform = `translate3d(${node.position[0]}px, ${node.position[1]}px, 0)`;

      // Header
      const header = document.createElement("div");
      header.setAttribute("class", `node-header header-${node.category || "stream"}`);
      header.innerHTML = `
        <div class="node-title-group">
          <span class="node-icon">${this.getNodeIcon(node.type)}</span>
          <span class="node-title">${node.title || node.type}</span>
        </div>
        <button class="node-close-btn" title="Remove Node">&times;</button>
      `;

      // Header dragging
      header.addEventListener("mousedown", (e) => {
        if (e.target.classList.contains("node-close-btn")) return;
        this.selectedNodeId = node.id;
        this.selectedWireId = null;
        document.querySelectorAll(".studio-node").forEach((n) => n.classList.remove("selected"));
        el.classList.add("selected");

        const worldPos = this.screenToWorld(e.clientX, e.clientY);
        this.draggedNode = node;
        this.nodeDragOffset = {
          x: worldPos.x - node.position[0],
          y: worldPos.y - node.position[1],
        };
      });

      // Close button
      header.querySelector(".node-close-btn").addEventListener("click", () => {
        this.deleteNode(node.id);
      });

      // Node Body
      const body = document.createElement("div");
      body.setAttribute("class", "node-body");

      // Ports row
      const portsRow = document.createElement("div");
      portsRow.setAttribute("class", "node-ports-row");

      // Input ports column
      const inCol = document.createElement("div");
      inCol.setAttribute("class", "ports-column inputs");
      (node.inputs || []).forEach((inp) => {
        const wrap = document.createElement("div");
        wrap.setAttribute("class", "port-wrapper input");
        wrap.innerHTML = `
          <div class="port-pin input port-${inp.type}" data-node="${node.id}" data-port="${inp.id}" data-type="${inp.type}"></div>
          <span>${inp.name}</span>
        `;
        if (node.type === "ThresholdGateNode" && (node.inputs || []).length > 1) {
          const rmBtn = document.createElement("button");
          rmBtn.setAttribute("class", "gate-remove-pin-btn");
          rmBtn.setAttribute("title", `Remove pin ${inp.name}`);
          rmBtn.innerHTML = "&times;";
          rmBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            this.removeGateInput(node.id, inp.id);
          });
          wrap.appendChild(rmBtn);
        }
        inCol.appendChild(wrap);
      });

      if (node.type === "ThresholdGateNode") {
        const addPinBtn = document.createElement("button");
        addPinBtn.setAttribute("class", "gate-add-pin-btn");
        addPinBtn.setAttribute("title", "Add dynamic scalar input pin");
        addPinBtn.innerHTML = "<span>+</span> Add Input";
        addPinBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          this.addGateInput(node.id);
        });
        inCol.appendChild(addPinBtn);
      }

      // Output ports column
      const outCol = document.createElement("div");
      outCol.setAttribute("class", "ports-column outputs");
      (node.outputs || []).forEach((out) => {
        const wrap = document.createElement("div");
        wrap.setAttribute("class", "port-wrapper output");
        wrap.innerHTML = `
          <div class="port-pin output port-${out.type}" data-node="${node.id}" data-port="${out.id}" data-type="${out.type}"></div>
          <span>${out.name}</span>
        `;
        const pin = wrap.querySelector(".port-pin");
        pin.addEventListener("mousedown", (e) => {
          this.startWireDrag(node.id, out.id, out.type, e);
        });
        outCol.appendChild(wrap);
      });

      portsRow.appendChild(inCol);
      portsRow.appendChild(outCol);
      body.appendChild(portsRow);

      // In-Node Custom Interactive Widgets
      this.attachNodeWidgets(node, body);

      el.appendChild(header);
      el.appendChild(body);
      this.nodesLayer.appendChild(el);
    }

    updateNodeDOMPosition(node) {
      const el = document.getElementById(`node-${node.id}`);
      if (el) {
        el.style.transform = `translate3d(${node.position[0]}px, ${node.position[1]}px, 0)`;
      }
    }

    deleteNode(nodeId, cascade = true) {
      const node = this.nodes.get(nodeId);
      if (!node) return;

      // Identify downstream candidate nodes before removing outgoing wires
      const downstreamCandidates = [];
      this.wires.forEach((w) => {
        if (w.from.split(":")[0] === nodeId) {
          downstreamCandidates.push(w.to.split(":")[0]);
        }
      });

      // Remove directly connected input & output wires
      const directWireIds = new Set();
      this.wires.forEach((w) => {
        if (w.from.split(":")[0] === nodeId || w.to.split(":")[0] === nodeId) {
          directWireIds.add(w.id);
        }
      });

      this.wires = this.wires.filter((w) => !directWireIds.has(w.id));
      this.nodes.delete(nodeId);

      const el = document.getElementById(`node-${nodeId}`);
      if (el) el.remove();

      let prunedCount = 0;
      if (cascade && downstreamCandidates.length > 0) {
        const { deletedWireIds, cutoffNodeIds } = this._cascadePruneCutoffNodes(
          downstreamCandidates,
          new Set(),
          new Set([nodeId])
        );

        if (deletedWireIds.size > 0) {
          this.wires = this.wires.filter((w) => !deletedWireIds.has(w.id));
          prunedCount = deletedWireIds.size;
        }

        cutoffNodeIds.forEach((cId) => {
          const cNode = this.nodes.get(cId);
          if (cNode) this.renderUnroutedNodeState(cNode);
        });
      }

      this.selectedNodeId = null;
      this.selectedWireId = null;
      this.closeWireContextMenu();
      this.renderWires();
      this.syncGraphDebounced();
      this.updateEmptyState();

      if (prunedCount > 0) {
        this.showToast(`🗑️ Removed node & pruned ${prunedCount} downstream cutoff wire(s).`);
      }
    }

    addGateInput(nodeId, customLabel = null) {
      const node = this.nodes.get(nodeId);
      if (!node || node.type !== "ThresholdGateNode") return;

      if (!node.inputs) node.inputs = [];
      const existingIds = new Set(node.inputs.map((inp) => inp.id));
      let idx = node.inputs.length + 1;
      while (existingIds.has(`val_${idx}`)) {
        idx++;
      }
      const newId = `val_${idx}`;
      const newName = customLabel || `Value In ${idx}`;

      node.inputs.push({ id: newId, name: newName, type: "scalar" });

      if (!node.properties) node.properties = {};
      if (!node.properties.rules) node.properties.rules = {};
      node.properties.rules[newId] = {
        operator: ">=",
        threshold: 0.5,
        min: 0.0,
        max: 1.0,
        step: 0.01,
        unit: "",
        label: newName,
      };

      const oldEl = document.getElementById(`node-${nodeId}`);
      if (oldEl) oldEl.remove();
      this.renderNodeDOM(node);
      this.renderWires();
      this.syncGraphDebounced();
      if (this.latestTelemetry) {
        this.applyTelemetry(this.latestTelemetry);
      }
      this.showToast(`➕ Added input '${newName}' to Threshold Logic Gate.`);
    }

    removeGateInput(nodeId, portId) {
      const node = this.nodes.get(nodeId);
      if (!node || node.type !== "ThresholdGateNode") return;

      if ((node.inputs || []).length <= 1) {
        this.showToast("⚠️ Cannot remove the last remaining input on a Threshold Gate.");
        return;
      }

      node.inputs = (node.inputs || []).filter((inp) => inp.id !== portId);
      if (node.properties?.rules && node.properties.rules[portId]) {
        delete node.properties.rules[portId];
      }

      const targetWireStr = `${nodeId}:${portId}`;
      const deletedWire = this.wires.find((w) => w.to === targetWireStr);
      if (deletedWire) {
        this.deleteWire(deletedWire.id, false);
      }

      const oldEl = document.getElementById(`node-${nodeId}`);
      if (oldEl) oldEl.remove();
      this.renderNodeDOM(node);
      this.renderWires();
      this.syncGraphDebounced();
      if (this.latestTelemetry) {
        this.applyTelemetry(this.latestTelemetry);
      }
      this.showToast(`🗑️ Removed input pin '${portId}' from Threshold Gate.`);
    }

    getNodeIcon(type) {
      const match = this.nodeCatalog.find((c) => c.type === type);
      return match ? match.icon : "📦";
    }

    mountMiniPlayer(nodeId, channel) {
      if (!this.miniPlayers) this.miniPlayers = new Map();
      const existing = this.miniPlayers.get(nodeId);
      if (existing) {
        try { existing.destroy(); } catch (e) {}
        this.miniPlayers.delete(nodeId);
      }

      const videoEl = document.getElementById(`mini-player-${nodeId}`);
      if (!videoEl) return;

      const cleanCh = (channel || this.selectedChannel || window.activeTab || "").replace(/^#/, "").toLowerCase();
      if (!cleanCh) return;

      const streamUrl = `/api/sessions/${cleanCh}/live.m3u8`;

      if (window.Hls && Hls.isSupported()) {
        const hls = new Hls({
          lowLatencyMode: true,
          enableWorker: true,
          backBufferLength: 30,
        });
        hls.loadSource(streamUrl);
        hls.attachMedia(videoEl);
        videoEl.muted = true;
        videoEl.play().catch(() => {});
        this.miniPlayers.set(nodeId, hls);
      } else if (videoEl.canPlayType("application/vnd.apple.mpegurl")) {
        videoEl.src = streamUrl;
        videoEl.muted = true;
        videoEl.play().catch(() => {});
      }
    }

    populateChannelSelect(selectEl, currentChannel) {
      if (!selectEl) return;
      const channels = new Set();
      if (currentChannel) channels.add(currentChannel.toLowerCase());
      if (window.activeSessions) {
        Object.keys(window.activeSessions).forEach((c) => channels.add(c.toLowerCase()));
      }
      if (this.latestTelemetry && this.latestTelemetry.sessions) {
        Object.keys(this.latestTelemetry.sessions).forEach((c) => channels.add(c.toLowerCase()));
      }
      if (channels.size === 0) {
        selectEl.innerHTML = `<option value="" disabled selected>No Active Streams</option>`;
        return;
      }

      const expectedKeys = Array.from(channels).join(",");
      const currentKeys = Array.from(selectEl.options).map((o) => o.value).join(",");
      if (expectedKeys === currentKeys) {
        if (currentChannel && selectEl.value !== currentChannel.toLowerCase()) {
          selectEl.value = currentChannel.toLowerCase();
        }
        return;
      }

      selectEl.innerHTML = Array.from(channels)
        .map(
          (c) =>
            `<option value="${c}" ${c === (currentChannel || "").toLowerCase() ? "selected" : ""}>#${c.toUpperCase()}</option>`
        )
        .join("");
    }

    populateSourceSelect(selectEl, node) {
      if (!selectEl || !node) return;
      const currentCh = (node.properties?.channel || "auto").toLowerCase();
      const autoCh = this.findUpstreamChannel(node.id, new Set());
      const autoLabel = autoCh ? `⚡ Auto (#${autoCh.toUpperCase()})` : "⚡ Auto (Wire)";

      const channels = new Set();
      if (window.activeSessions) {
        Object.keys(window.activeSessions).forEach((c) => channels.add(c.toLowerCase()));
      }
      if (this.latestTelemetry && this.latestTelemetry.sessions) {
        Object.keys(this.latestTelemetry.sessions).forEach((c) => channels.add(c.toLowerCase()));
      }
      for (const n of this.nodes.values()) {
        if (n.type === "StreamSourceNode" && n.properties?.channel) {
          channels.add(n.properties.channel.toLowerCase());
        }
      }

      const expectedKeys = ["auto", ...Array.from(channels)].join(",");
      const currentKeys = Array.from(selectEl.options).map((o) => o.value).join(",");
      const firstOptText = selectEl.options[0]?.text;

      if (expectedKeys === currentKeys && firstOptText === autoLabel) {
        if (selectEl.value !== currentCh) {
          selectEl.value = currentCh;
        }
        return;
      }

      let html = `<option value="auto" ${currentCh === "auto" ? "selected" : ""}>${autoLabel}</option>`;
      for (const ch of channels) {
        html += `<option value="${ch}" ${currentCh === ch ? "selected" : ""}>#${ch.toUpperCase()}</option>`;
      }
      selectEl.innerHTML = html;
    }

    setupSourceSelect(widget, node) {
      const selectEl = widget.querySelector(`#source-select-${node.id}`);
      if (!selectEl) return;
      this.populateSourceSelect(selectEl, node);
      selectEl.addEventListener("change", (e) => {
        node.properties = node.properties || {};
        node.properties.channel = e.target.value;
        this.syncNodeParamDebounced(node.id, "channel", node.properties.channel);
        if (this.latestTelemetry) {
          this.applyTelemetry(this.latestTelemetry);
        }
      });
    }

    getNodeSourceChannel(node) {
      if (!node) return null;
      if (node.type === "StreamSourceNode") {
        return (node.properties?.channel || "").replace(/^#/, "").toLowerCase() || null;
      }
      const explicit = node.properties?.channel;
      if (explicit && explicit !== "auto") {
        return explicit.replace(/^#/, "").toLowerCase();
      }
      return this.findUpstreamChannel(node.id, new Set());
    }

    findUpstreamChannel(nodeId, visited = new Set()) {
      if (visited.has(nodeId)) return null;
      visited.add(nodeId);

      for (const wire of this.wires) {
        const dstNodeId = wire.to.split(":")[0];
        if (dstNodeId === nodeId) {
          const srcNodeId = wire.from.split(":")[0];
          const srcNode = this.nodes.get(srcNodeId);
          if (!srcNode) continue;
          if (srcNode.type === "StreamSourceNode") {
            const ch = (srcNode.properties?.channel || "").replace(/^#/, "").toLowerCase();
            if (ch) return ch;
          }
          const upstreamCh = this.findUpstreamChannel(srcNodeId, visited);
          if (upstreamCh) return upstreamCh;
        }
      }
      return null;
    }

    getNodeUpstreamCropRoi(node, visited = new Set()) {
      if (!node || visited.has(node.id)) return null;
      visited.add(node.id);
      for (const wire of this.wires) {
        const [dstId, dstPort] = wire.to.split(":");
        if (dstId === node.id && (dstPort === "video_in" || dstPort === "video" || !dstPort)) {
          const [srcId, srcPort] = wire.from.split(":");
          const srcNode = this.nodes.get(srcId);
          if (srcNode) {
            if (srcNode.type === "VideoCropNode") {
              const roi = srcNode.properties?.roi || {
                x: srcNode.properties?.x ?? 0.02,
                y: srcNode.properties?.y ?? 0.05,
                w: srcNode.properties?.w ?? 0.22,
                h: srcNode.properties?.h ?? 0.28,
              };
              return { roi, cropNode: srcNode };
            }
            if (srcNode.type === "ImageScaleNode") {
              const upstream = this.getNodeUpstreamCropRoi(srcNode, visited);
              if (upstream) return upstream;
            }
          }
        }
      }
      return null;
    }

    updateDownstreamCroppedPreviews(cropNodeId, roi) {
      if (!cropNodeId || !roi) return;
      for (const wire of this.wires) {
        const [srcId] = wire.from.split(":");
        if (srcId === cropNodeId) {
          const [dstId] = wire.to.split(":");
          const dstNode = this.nodes.get(dstId);
          if (!dstNode) continue;
          if (dstNode.type === "ImageScaleNode") {
            const scaleImg = document.getElementById(`scale-live-img-${dstId}`);
            if (scaleImg && scaleImg.style.display !== "none") {
              const leftPct = -(roi.x / roi.w) * 100;
              const topPct = -(roi.y / roi.h) * 100;
              const widthPct = (1 / roi.w) * 100;
              const heightPct = (1 / roi.h) * 100;
              scaleImg.style.position = "absolute";
              scaleImg.style.width = `${widthPct}%`;
              scaleImg.style.height = `${heightPct}%`;
              scaleImg.style.left = `${leftPct}%`;
              scaleImg.style.top = `${topPct}%`;
              scaleImg.style.maxWidth = "none";
              scaleImg.style.maxHeight = "none";
              scaleImg.style.objectFit = "fill";
            }
            this.updateDownstreamCroppedPreviews(dstId, roi);
          } else if (dstNode.type === "FacecamEmotionNode") {
            const faceImg = document.getElementById(`face-live-img-${dstId}`);
            if (faceImg && faceImg.style.display !== "none") {
              const leftPct = -(roi.x / roi.w) * 100;
              const topPct = -(roi.y / roi.h) * 100;
              const widthPct = (1 / roi.w) * 100;
              const heightPct = (1 / roi.h) * 100;
              faceImg.style.position = "absolute";
              faceImg.style.width = `${widthPct}%`;
              faceImg.style.height = `${heightPct}%`;
              faceImg.style.left = `${leftPct}%`;
              faceImg.style.top = `${topPct}%`;
              faceImg.style.maxWidth = "none";
              faceImg.style.maxHeight = "none";
              faceImg.style.objectFit = "fill";
            }
          } else if (dstNode.type === "OCRVisionNode") {
            const ocrImg = document.getElementById(`ocr-live-img-${dstId}`);
            if (ocrImg && ocrImg.style.display !== "none") {
              const leftPct = -(roi.x / roi.w) * 100;
              const topPct = -(roi.y / roi.h) * 100;
              const widthPct = (1 / roi.w) * 100;
              const heightPct = (1 / roi.h) * 100;
              ocrImg.style.position = "absolute";
              ocrImg.style.width = `${widthPct}%`;
              ocrImg.style.height = `${heightPct}%`;
              ocrImg.style.left = `${leftPct}%`;
              ocrImg.style.top = `${topPct}%`;
              ocrImg.style.maxWidth = "none";
              ocrImg.style.maxHeight = "none";
              ocrImg.style.objectFit = "fill";
            }
          }
        }
      }
    }

    renderUnroutedNodeState(node) {
      if (!node || node.type === "StreamSourceNode" || node.type === "ClipFolderNode") return;
      const nodeId = node.id;
      const el = document.getElementById(`node-${nodeId}`);
      if (el) el.classList.remove("spiking");

      if (node.type === "CVTransformerNode") {
        const topValEl = document.getElementById(`cv-top-val-${nodeId}`);
        const latencyTag = document.getElementById(`cv-latency-tag-${nodeId}`);
        const thumbImg = document.getElementById(`cv-thumb-${nodeId}`);
        const thumbPlaceholder = document.getElementById(`cv-thumb-placeholder-${nodeId}`);
        const barsBox = document.getElementById(`cv-bars-${nodeId}`);

        if (topValEl) {
          topValEl.textContent = "UNROUTED";
          topValEl.style.color = "#64748b";
        }
        if (latencyTag) latencyTag.textContent = "-- ms";
        if (thumbImg) {
          thumbImg.style.display = "none";
          thumbImg.removeAttribute("src");
        }
        if (thumbPlaceholder) {
          thumbPlaceholder.style.display = "flex";
          thumbPlaceholder.textContent = "Unrouted (Connect Video In or Assign Stream)";
        }
        if (barsBox) {
          barsBox.innerHTML = '<div style="color:#475569; font-size:10px; text-align:center; padding:8px 0;">No active stream routed</div>';
        }
      } else if (node.type === "OCRVisionNode") {
        const valEl = document.getElementById(`ocr-val-${nodeId}`);
        const statusEl = document.getElementById(`ocr-status-${nodeId}`);
        const ocrImg = document.getElementById(`ocr-live-img-${nodeId}`);
        const ocrPlaceholder = document.getElementById(`ocr-placeholder-${nodeId}`);
        const listEl = document.getElementById(`ocr-node-list-${nodeId}`);

        if (valEl) {
          valEl.textContent = "— (Unrouted)";
          valEl.style.color = "#64748b";
        }
        if (statusEl) {
          statusEl.textContent = "UNROUTED";
          statusEl.style.color = "#64748b";
        }
        if (ocrImg) {
          ocrImg.style.display = "none";
          ocrImg.removeAttribute("src");
        }
        if (ocrPlaceholder) {
          ocrPlaceholder.style.display = "block";
          ocrPlaceholder.textContent = "Unrouted (Connect Video In or Assign Stream)";
        }
        if (listEl) {
          listEl.innerHTML = '<div style="color:#475569; font-size:10px; text-align:center; padding:6px 0;">No stream data</div>';
        }
      } else if (node.type === "VideoCropNode") {
        const cropImg = document.getElementById(`crop-live-img-${nodeId}`);
        const cropPlaceholder = document.getElementById(`crop-placeholder-${nodeId}`);
        if (cropImg) {
          cropImg.style.display = "none";
          cropImg.removeAttribute("src");
        }
        if (cropPlaceholder) {
          cropPlaceholder.style.display = "block";
          cropPlaceholder.textContent = "Unrouted (Connect Video In or Assign Stream)";
        }
      } else if (node.type === "ImageScaleNode") {
        const scaleImg = document.getElementById(`scale-live-img-${nodeId}`);
        const scalePlaceholder = document.getElementById(`scale-placeholder-${nodeId}`);
        const scaleBadge = document.getElementById(`scale-dim-badge-${nodeId}`);
        const latencyTag = document.getElementById(`scale-latency-tag-${nodeId}`);
        const cropBadge = document.getElementById(`scale-crop-badge-${nodeId}`);
        if (scaleImg) {
          scaleImg.style.display = "none";
          scaleImg.removeAttribute("src");
        }
        if (scalePlaceholder) {
          scalePlaceholder.style.display = "block";
          scalePlaceholder.textContent = "Unrouted (Connect Video In or Crop Node)";
        }
        if (cropBadge) cropBadge.style.display = "none";
        if (scaleBadge) scaleBadge.textContent = "--x-- ➔ --x-- (2.0x)";
        if (latencyTag) latencyTag.textContent = "-- ms";
      } else if (node.type === "FacecamEmotionNode") {
        const faceImg = document.getElementById(`face-live-img-${nodeId}`);
        const facePlaceholder = document.getElementById(`face-placeholder-${nodeId}`);
        const cropBadge = document.getElementById(`face-crop-badge-${nodeId}`);
        const tiltNum = document.getElementById(`face-tilt-num-${nodeId}`);
        const tiltPill = document.getElementById(`face-tilt-pill-${nodeId}`);
        const topVal = document.getElementById(`face-top-val-${nodeId}`);
        const euphoriaVal = document.getElementById(`face-euphoria-val-${nodeId}`);
        const valenceVal = document.getElementById(`face-valence-val-${nodeId}`);
        const barsBox = document.getElementById(`face-bars-${nodeId}`);
        const latencyTag = document.getElementById(`face-latency-tag-${nodeId}`);

        if (cropBadge) {
          cropBadge.style.display = "none";
        }
        if (faceImg) {
          faceImg.style.display = "none";
          faceImg.removeAttribute("src");
        }
        if (facePlaceholder) {
          facePlaceholder.style.display = "block";
          facePlaceholder.textContent = "Unrouted (Connect Video In or Assign Stream)";
        }
        if (tiltNum) {
          tiltNum.textContent = "--";
          tiltNum.style.color = "#64748b";
        }
        if (tiltPill) {
          tiltPill.textContent = "UNROUTED";
          tiltPill.style.color = "#64748b";
          tiltPill.style.background = "rgba(100,116,139,0.15)";
        }
        if (topVal) {
          topVal.textContent = "STANDBY";
          topVal.style.color = "#64748b";
        }
        if (euphoriaVal) euphoriaVal.textContent = "--%";
        if (valenceVal) valenceVal.textContent = "--";
        if (latencyTag) latencyTag.textContent = "-- ms";
        if (barsBox) {
          barsBox.innerHTML = '<div style="color:#475569; font-size:10px; text-align:center; padding:8px 0;">No stream data</div>';
        }
      } else if (node.type === "AudioMonitorNode") {
        const valEl = document.getElementById(`audio-val-${nodeId}`);
        const spikeTag = document.getElementById(`audio-spike-tag-${nodeId}`);
        const canvas = document.getElementById(`wave-canvas-${nodeId}`);

        if (valEl) valEl.textContent = "-- dB";
        if (spikeTag) {
          spikeTag.textContent = "UNROUTED";
          spikeTag.style.color = "#64748b";
        }
        if (canvas) {
          const ctx = canvas.getContext("2d");
          if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
      } else if (node.type === "ChatVelocityNode") {
        const valEl = document.getElementById(`chat-val-${nodeId}`);
        const spikeTag = document.getElementById(`chat-spike-tag-${nodeId}`);
        const ticker = document.getElementById(`chat-ticker-${nodeId}`);

        if (valEl) valEl.textContent = "0.0 msgs/s";
        if (spikeTag) {
          spikeTag.textContent = "UNROUTED";
          spikeTag.style.color = "#64748b";
        }
        if (ticker) {
          ticker.innerHTML = '<div style="color:#475569; font-size:10px; text-align:center; padding:12px 0;">Connect Chat In to stream</div>';
        }
      } else if (node.type === "GamblingLedgerNode") {
        const pnlEl = document.getElementById(`ledger-pnl-${nodeId}`);
        const chaseBadge = document.getElementById(`ledger-chase-badge-${nodeId}`);
        const winrateEl = document.getElementById(`ledger-winrate-${nodeId}`);
        const streakEl = document.getElementById(`ledger-streak-${nodeId}`);
        const rtpEl = document.getElementById(`ledger-rtp-${nodeId}`);
        const drawdownEl = document.getElementById(`ledger-drawdown-${nodeId}`);
        const canvas = document.getElementById(`ledger-canvas-${nodeId}`);

        if (pnlEl) {
          pnlEl.textContent = "$0.00";
          pnlEl.className = "ledger-pnl-val";
        }
        if (chaseBadge) chaseBadge.style.display = "none";
        if (winrateEl) winrateEl.textContent = "0.0%";
        if (streakEl) {
          streakEl.textContent = "0";
          streakEl.style.color = "#64748b";
        }
        if (rtpEl) rtpEl.textContent = "100.0%";
        if (drawdownEl) drawdownEl.textContent = "$0.00";
        if (canvas) {
          const ctx = canvas.getContext("2d");
          if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
      } else if (node.type === "GateEvaluatorNode") {
        const scoreEl = document.getElementById(`gate-score-${nodeId}`);
        const statusEl = document.getElementById(`gate-status-${nodeId}`);
        if (scoreEl) scoreEl.textContent = "0";
        if (statusEl) {
          statusEl.textContent = "UNROUTED";
          statusEl.style.color = "#64748b";
          statusEl.classList.remove("active");
        }
      }
    }

    setSelectedChannel(channel) {
      if (!channel) return;
      const cleanCh = channel.replace(/^#/, "").toLowerCase();
      this.selectedChannel = cleanCh;

      const streamSourceNodes = Array.from(this.nodes.values()).filter(
        (n) => n.type === "StreamSourceNode"
      );

      // Only update StreamSourceNode if there's exactly 1 stream source node.
      // If multiple stream source nodes exist, each keeps its own channel!
      if (streamSourceNodes.length === 1) {
        const node = streamSourceNodes[0];
        node.properties = node.properties || {};
        node.properties.channel = cleanCh;
        const plat = (node.properties.platform || "twitch").toLowerCase();
        const platLabel = plat === "kick" ? "Kick" : "Twitch";
        node.title = `${platLabel} Source: #${cleanCh}`;

        // Update header title in DOM
        const nodeEl = document.getElementById(`node-${node.id}`);
        if (nodeEl) {
          const titleEl = nodeEl.querySelector(".node-title");
          if (titleEl) {
            titleEl.textContent = `${platLabel} Source: #${cleanCh}`;
          }
          const selectEl = nodeEl.querySelector(`#channel-select-${node.id}`);
          if (selectEl) {
            this.populateChannelSelect(selectEl, cleanCh);
          }
        }

        // Remount mini player video to the selected channel
        this.mountMiniPlayer(node.id, cleanCh);

        // Sync parameter to backend DAG so telemetry focuses on this channel
        this.syncNodeParamDebounced(node.id, "channel", cleanCh);
      }

      if (this.latestTelemetry) {
        this.applyTelemetry(this.latestTelemetry);
      }
    }

    /* -------------------------------------------------------------
       Interactive Draggable & Resizable ROI Bounding Box Engine
       ------------------------------------------------------------- */
    setupDraggableRoiBox(containerEl, initialRoi, color, label, onChange) {
      const box = document.createElement("div");
      box.className = "roi-draggable-box";
      box.style.borderColor = color;
      box.style.backgroundColor = color.startsWith("#") ? `${color}22` : "rgba(56, 189, 248, 0.15)";
      box.style.color = color;

      let currentRoi = {
        x: initialRoi?.x ?? 0.1,
        y: initialRoi?.y ?? 0.1,
        w: initialRoi?.w ?? 0.2,
        h: initialRoi?.h ?? 0.2,
      };

      const badge = document.createElement("div");
      badge.className = "roi-label-badge";
      badge.style.background = color;
      box.appendChild(badge);

      const handle = document.createElement("div");
      handle.className = "roi-resize-handle";
      handle.style.background = color;
      box.appendChild(handle);

      const updateDomStyle = () => {
        box.style.left = `${(currentRoi.x * 100).toFixed(1)}%`;
        box.style.top = `${(currentRoi.y * 100).toFixed(1)}%`;
        box.style.width = `${(currentRoi.w * 100).toFixed(1)}%`;
        box.style.height = `${(currentRoi.h * 100).toFixed(1)}%`;
        badge.textContent = `${label} (${Math.round(currentRoi.x * 100)}%, ${Math.round(currentRoi.y * 100)}% - ${Math.round(currentRoi.w * 100)}x${Math.round(currentRoi.h * 100)}%)`;
      };

      updateDomStyle();
      containerEl.appendChild(box);

      // Dragging entire box
      box.addEventListener("mousedown", (e) => {
        if (e.target === handle) return;
        e.stopPropagation();
        e.preventDefault();

        box.classList.add("active");
        const cRect = containerEl.getBoundingClientRect();
        const startMouseX = e.clientX;
        const startMouseY = e.clientY;
        const startX = currentRoi.x;
        const startY = currentRoi.y;

        const onMouseMove = (ev) => {
          const dx = (ev.clientX - startMouseX) / (cRect.width || 1);
          const dy = (ev.clientY - startMouseY) / (cRect.height || 1);
          currentRoi.x = Math.max(0, Math.min(1 - currentRoi.w, startX + dx));
          currentRoi.y = Math.max(0, Math.min(1 - currentRoi.h, startY + dy));
          updateDomStyle();
          if (typeof onChange === "function") onChange({ ...currentRoi }, false);
        };

        const onMouseUp = () => {
          box.classList.remove("active");
          window.removeEventListener("mousemove", onMouseMove);
          window.removeEventListener("mouseup", onMouseUp);
          if (typeof onChange === "function") onChange({ ...currentRoi }, true);
        };

        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
      });

      // Resizing handle
      handle.addEventListener("mousedown", (e) => {
        e.stopPropagation();
        e.preventDefault();

        box.classList.add("active");
        const cRect = containerEl.getBoundingClientRect();
        const startMouseX = e.clientX;
        const startMouseY = e.clientY;
        const startW = currentRoi.w;
        const startH = currentRoi.h;

        const onResizeMove = (ev) => {
          const dw = (ev.clientX - startMouseX) / (cRect.width || 1);
          const dh = (ev.clientY - startMouseY) / (cRect.height || 1);
          currentRoi.w = Math.max(0.04, Math.min(1 - currentRoi.x, startW + dw));
          currentRoi.h = Math.max(0.04, Math.min(1 - currentRoi.y, startH + dh));
          updateDomStyle();
          if (typeof onChange === "function") onChange({ ...currentRoi }, false);
        };

        const onResizeUp = () => {
          box.classList.remove("active");
          window.removeEventListener("mousemove", onResizeMove);
          window.removeEventListener("mouseup", onResizeUp);
          if (typeof onChange === "function") onChange({ ...currentRoi }, true);
        };

        window.addEventListener("mousemove", onResizeMove);
        window.addEventListener("mouseup", onResizeUp);
      });

      return {
        box,
        update: (newRoi) => {
          currentRoi = { ...newRoi };
          updateDomStyle();
        },
        getRoi: () => ({ ...currentRoi }),
        setVisible: (v) => { box.style.display = v ? "block" : "none"; },
        setActive: (v) => {
          if (v) box.classList.add("active");
          else box.classList.remove("active");
        },
      };
    }

    /* -------------------------------------------------------------
       In-Node Interactive Widgets
       ------------------------------------------------------------- */
    attachNodeWidgets(node, bodyEl) {
      const props = node.properties || {};

      if (node.type === "StreamSourceNode") {
        const currentChannel = (node.properties?.channel || this.selectedChannel || window.activeTab || "").replace(/^#/, "").toLowerCase();
        const currentPlatform = (node.properties?.platform || (currentChannel.includes("kick") ? "kick" : "twitch")).toLowerCase();
        node.properties = node.properties || {};
        node.properties.channel = currentChannel;
        node.properties.platform = currentPlatform;
        const platLabel = currentPlatform === "kick" ? "Kick" : "Twitch";
        node.title = currentChannel ? `${platLabel} Source: #${currentChannel}` : `${platLabel} Source`;

        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        widget.innerHTML = `
          <div class="widget-label">
            <span id="platform-label-${node.id}">${currentPlatform === "kick" ? "🟢 Kick Live Stream" : "🟣 Twitch Live Stream"}</span>
            <span class="widget-val" id="stream-status-${node.id}">CONNECTING</span>
          </div>
          <div class="node-channel-row" style="margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between; gap: 8px;">
            <span style="font-size: 11px; color: #94a3b8; white-space: nowrap;">Platform:</span>
            <select class="node-platform-select" id="platform-select-${node.id}" style="background: rgba(0,0,0,0.5); border: 1px solid rgba(56, 189, 248, 0.3); color: #38bdf8; font-weight: 800; font-size: 11px; padding: 2px 6px; border-radius: 6px; cursor: pointer;">
              <option value="twitch" ${currentPlatform === "twitch" ? "selected" : ""}>🟣 Twitch</option>
              <option value="kick" ${currentPlatform === "kick" ? "selected" : ""}>🟢 Kick</option>
            </select>
          </div>
          <div class="node-channel-row" style="margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between; gap: 8px;">
            <span style="font-size: 11px; color: #94a3b8; white-space: nowrap;">Selected Stream:</span>
            <select class="node-channel-select" id="channel-select-${node.id}" style="flex: 1; background: rgba(0,0,0,0.5); border: 1px solid rgba(56, 189, 248, 0.3); color: #38bdf8; font-weight: 800; font-size: 11px; padding: 3px 6px; border-radius: 6px; cursor: pointer;">
              <option value="${currentChannel}">#${currentChannel.toUpperCase()}</option>
            </select>
          </div>
          <div class="node-video-preview">
            <video id="mini-player-${node.id}" autoplay muted playsinline></video>
            <div class="preview-badge" id="preview-badge-${node.id}">🟢 Live HLS</div>
          </div>
          <button class="roi-tab-btn" style="margin-top: 8px; width: 100%; text-align: center; background: rgba(56, 189, 248, 0.15); border-color: #38bdf8; color: #38bdf8; padding: 5px;" id="btn-open-calibrator-${node.id}">🎯 Calibrate ROIs Over Full Stream</button>
        `;
        bodyEl.appendChild(widget);

        // Hook up platform dropdown
        const platSelectEl = widget.querySelector(`#platform-select-${node.id}`);
        if (platSelectEl) {
          platSelectEl.addEventListener("change", (e) => {
            const newPlat = e.target.value;
            node.properties.platform = newPlat;
            const newTitle = `${newPlat === "kick" ? "Kick" : "Twitch"} Source: #${node.properties.channel}`;
            node.title = newTitle;
            const titleEl = document.getElementById(`node-${node.id}`)?.querySelector(".node-title");
            if (titleEl) titleEl.textContent = newTitle;
            const platLabelEl = widget.querySelector(`#platform-label-${node.id}`);
            if (platLabelEl) platLabelEl.textContent = newPlat === "kick" ? "🟢 Kick Live Stream" : "🟣 Twitch Live Stream";
            this.syncNodeParamDebounced(node.id, "platform", newPlat);
          });
        }

        // Populate and hook up select dropdown for this specific stream node
        const selectEl = widget.querySelector(`#channel-select-${node.id}`);
        if (selectEl) {
          this.populateChannelSelect(selectEl, currentChannel);
          selectEl.addEventListener("change", (e) => {
            const newCh = e.target.value.replace(/^#/, "").toLowerCase();
            node.properties = node.properties || {};
            node.properties.channel = newCh;
            const plat = (node.properties.platform || (newCh.includes("kick") ? "kick" : "twitch")).toLowerCase();
            node.properties.platform = plat;
            const platLabel = plat === "kick" ? "Kick" : "Twitch";
            node.title = `${platLabel} Source: #${newCh}`;
            const titleEl = document.getElementById(`node-${node.id}`)?.querySelector(".node-title");
            if (titleEl) titleEl.textContent = `${platLabel} Source: #${newCh}`;
            this.mountMiniPlayer(node.id, newCh);
            this.syncNodeParamDebounced(node.id, "channel", newCh);
            if (this.latestTelemetry) {
              this.applyTelemetry(this.latestTelemetry);
            }
          });
        }

        // Calibrate button click
        widget.querySelector(`#btn-open-calibrator-${node.id}`)?.addEventListener("click", () => {
          this.openStreamCalibrator();
        });

        // Mount HLS stream on mini player
        setTimeout(() => {
          this.mountMiniPlayer(node.id, currentChannel);
        }, 100);
      } else if (node.type === "AudioMonitorNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        widget.innerHTML = `
          <div class="node-source-row" style="margin-bottom:6px; display:flex; align-items:center; justify-content:space-between; gap:6px; background:rgba(0,0,0,0.25); padding:3px 6px; border-radius:4px;">
            <span style="font-size:10px; color:#94a3b8; white-space:nowrap;">Stream Source:</span>
            <select class="node-source-select" id="source-select-${node.id}" style="flex:1; max-width:140px; background:rgba(0,0,0,0.5); border:1px solid rgba(56,189,248,0.3); color:#38bdf8; font-size:10px; border-radius:4px; padding:2px 4px; cursor:pointer;">
              <option value="auto">⚡ Auto (Wire)</option>
            </select>
          </div>
          <div class="widget-label">
            <span>Live RMS Decibel Level</span>
            <span class="widget-val" id="audio-val-${node.id}">-- dB</span>
          </div>
          <canvas class="node-wave-canvas" id="wave-canvas-${node.id}" width="280" height="52"></canvas>
          <div style="display:flex; justify-content:space-between; font-size:9px; color:#94a3b8;">
            <span>Spike Threshold: +${props.jump_db_threshold || 12} dB</span>
            <span id="audio-spike-tag-${node.id}" style="color:#64748b;">UNROUTED</span>
          </div>
          <input type="range" class="node-slider" min="6" max="24" step="1" value="${props.jump_db_threshold || 12}" />
        `;
        const slider = widget.querySelector(".node-slider");
        slider.addEventListener("input", (e) => {
          props.jump_db_threshold = parseFloat(e.target.value);
          widget.querySelector("span:nth-child(1)").textContent = `Spike Threshold: +${props.jump_db_threshold} dB`;
          this.syncNodeParamDebounced(node.id, "jump_db_threshold", props.jump_db_threshold);
        });
        this.setupSourceSelect(widget, node);
        bodyEl.appendChild(widget);
      } else if (node.type === "ChatVelocityNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        widget.innerHTML = `
          <div class="node-source-row" style="margin-bottom:6px; display:flex; align-items:center; justify-content:space-between; gap:6px; background:rgba(0,0,0,0.25); padding:3px 6px; border-radius:4px;">
            <span style="font-size:10px; color:#94a3b8; white-space:nowrap;">Stream Source:</span>
            <select class="node-source-select" id="source-select-${node.id}" style="flex:1; max-width:140px; background:rgba(0,0,0,0.5); border:1px solid rgba(56,189,248,0.3); color:#38bdf8; font-size:10px; border-radius:4px; padding:2px 4px; cursor:pointer;">
              <option value="auto">⚡ Auto (Wire)</option>
            </select>
          </div>
          <div class="widget-label">
            <span>Chat Density Velocity</span>
            <span class="widget-val" id="chat-val-${node.id}">0.0 msgs/s</span>
          </div>
          <div class="node-chat-ticker" id="chat-ticker-${node.id}">
            <div style="color:#475569; font-size:10px; text-align:center; padding:12px 0;">Connect Chat In to stream</div>
          </div>
          <div style="display:flex; justify-content:space-between; font-size:9px; color:#94a3b8; margin-top:4px;">
            <span>Spike Ratio: ${props.spike_ratio_threshold || 3.0}x</span>
            <span id="chat-spike-tag-${node.id}" style="color:#64748b;">UNROUTED</span>
          </div>
        `;
        this.setupSourceSelect(widget, node);
        bodyEl.appendChild(widget);
      } else if (node.type === "OCRVisionNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        widget.innerHTML = `
          <div class="node-source-row" style="margin-bottom:6px; display:flex; align-items:center; justify-content:space-between; gap:6px; background:rgba(0,0,0,0.25); padding:3px 6px; border-radius:4px;">
            <span style="font-size:10px; color:#94a3b8; white-space:nowrap;">Stream Source:</span>
            <select class="node-source-select" id="source-select-${node.id}" style="flex:1; max-width:140px; background:rgba(0,0,0,0.5); border:1px solid rgba(56,189,248,0.3); color:#38bdf8; font-size:10px; border-radius:4px; padding:2px 4px; cursor:pointer;">
              <option value="auto">⚡ Auto (Wire)</option>
            </select>
          </div>
          <div class="widget-label">
            <span>OCR Stream Classifier</span>
            <span class="widget-val" id="ocr-val-${node.id}">— (Unrouted)</span>
          </div>
          <div class="node-roi-container roi-container-${node.id}">
            <img class="roi-live-img" id="ocr-live-img-${node.id}" style="display:none;" />
            <div class="roi-placeholder-text" id="ocr-placeholder-${node.id}">Unrouted (Connect Video In or Crop Node)</div>
          </div>
          <div style="display:flex; justify-content:space-between; font-size:9px; color:#94a3b8; margin-top:4px;">
            <span>Win Threshold: ≥ ${props.multiplier_threshold || 100}x</span>
            <span id="ocr-status-${node.id}" style="color:#64748b;">UNROUTED</span>
          </div>
          <input type="range" class="node-slider" min="10" max="500" step="10" value="${props.multiplier_threshold || 100}" />
          <div class="ocr-node-list" id="ocr-node-list-${node.id}" style="margin-top:6px; display:flex; flex-direction:column; gap:4px; max-height:140px; overflow-y:auto;"></div>
        `;
        const slider = widget.querySelector(".node-slider");
        slider.addEventListener("input", (e) => {
          props.multiplier_threshold = parseFloat(e.target.value);
          widget.querySelector("span:nth-child(1)").textContent = `Win Threshold: ≥ ${props.multiplier_threshold}x`;
          this.syncNodeParamDebounced(node.id, "multiplier_threshold", props.multiplier_threshold);
        });

        this.setupSourceSelect(widget, node);
        bodyEl.appendChild(widget);
      } else if (node.type === "VideoCropNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget cropper-widget");
        const currentPreset = props.preset || "facecam_tl";
        const initialRoi = props.roi || {
          x: props.x ?? 0.02,
          y: props.y ?? 0.05,
          w: props.w ?? 0.22,
          h: props.h ?? 0.28,
        };
        props.roi = initialRoi;

        widget.innerHTML = `
          <div class="node-source-row" style="margin-bottom:6px; display:flex; align-items:center; justify-content:space-between; gap:6px; background:rgba(0,0,0,0.25); padding:3px 6px; border-radius:4px;">
            <span style="font-size:10px; color:#94a3b8; white-space:nowrap;">Stream Source:</span>
            <select class="node-source-select" id="source-select-${node.id}" style="flex:1; max-width:140px; background:rgba(0,0,0,0.5); border:1px solid rgba(56,189,248,0.3); color:#38bdf8; font-size:10px; border-radius:4px; padding:2px 4px; cursor:pointer;">
              <option value="auto">⚡ Auto (Wire)</option>
            </select>
          </div>
          <div class="widget-label" style="display:flex; align-items:center; justify-content:space-between; gap:4px;">
            <span>Target ROI Crop</span>
            <select class="roi-preset-select" id="crop-preset-${node.id}" style="background:rgba(0,0,0,0.5); border:1px solid rgba(244,63,94,0.4); color:#fb7185; font-size:9.5px; border-radius:4px; padding:1px 4px; cursor:pointer;">
              <option value="custom" ${currentPreset === "custom" ? "selected" : ""}>✏️ Custom ROI</option>
              <option value="facecam_tl" ${currentPreset === "facecam_tl" ? "selected" : ""}>📷 Facecam (Top-Left)</option>
              <option value="facecam_tr" ${currentPreset === "facecam_tr" ? "selected" : ""}>📷 Facecam (Top-Right)</option>
              <option value="facecam_bl" ${currentPreset === "facecam_bl" ? "selected" : ""}>📷 Facecam (Bottom-Left)</option>
              <option value="facecam_br" ${currentPreset === "facecam_br" ? "selected" : ""}>📷 Facecam (Bottom-Right)</option>
              <option value="hud_bottom" ${currentPreset === "hud_bottom" ? "selected" : ""}>📊 Bottom HUD / Balance</option>
              <option value="gameplay_center" ${currentPreset === "gameplay_center" ? "selected" : ""}>🎯 Center Gameplay</option>
            </select>
          </div>
          <div class="node-roi-container roi-container-${node.id}">
            <img class="roi-live-img" id="crop-live-img-${node.id}" style="display:none;" />
            <div class="roi-placeholder-text" id="crop-placeholder-${node.id}">Unrouted (Connect Video In or Assign Stream)</div>
          </div>
          <div class="crop-coords-bar" id="crop-coords-${node.id}" style="display:flex; justify-content:space-between; font-size:9px; color:#94a3b8; margin-top:4px; padding:2px 4px; background:rgba(0,0,0,0.2); border-radius:4px;">
            <span>X: ${Math.round(initialRoi.x * 100)}% Y: ${Math.round(initialRoi.y * 100)}%</span>
            <span>Size: ${Math.round(initialRoi.w * 100)}% × ${Math.round(initialRoi.h * 100)}%</span>
          </div>
        `;

        this.setupSourceSelect(widget, node);
        bodyEl.appendChild(widget);

        // Mount interactive draggable crop box
        setTimeout(() => {
          const container = widget.querySelector(`.roi-container-${node.id}`);
          if (container) {
            const ctrl = this.setupDraggableRoiBox(container, initialRoi, "#f43f5e", "Crop", (roi, isFinal) => {
              props.roi = roi;
              props.x = roi.x;
              props.y = roi.y;
              props.w = roi.w;
              props.h = roi.h;
              const coordsEl = widget.querySelector(`#crop-coords-${node.id}`);
              if (coordsEl) {
                coordsEl.innerHTML = `<span>X: ${Math.round(roi.x * 100)}% Y: ${Math.round(roi.y * 100)}%</span><span>Size: ${Math.round(roi.w * 100)}% × ${Math.round(roi.h * 100)}%</span>`;
              }
              if (isFinal) {
                this.syncNodeParamDebounced(node.id, "roi", roi);
                this.showToast("Video Crop ROI calibrated");
              }
              this.updateDownstreamCroppedPreviews(node.id, roi);
            });
            this.nodeRoiControllers.set(`${node.id}:crop`, ctrl);

            // Handle preset changes
            const presetSelect = widget.querySelector(`#crop-preset-${node.id}`);
            presetSelect?.addEventListener("change", (e) => {
              const pVal = e.target.value;
              props.preset = pVal;
              let targetRoi = null;
              if (pVal === "facecam_tl") targetRoi = { x: 0.02, y: 0.05, w: 0.22, h: 0.28 };
              else if (pVal === "facecam_tr") targetRoi = { x: 0.76, y: 0.05, w: 0.22, h: 0.28 };
              else if (pVal === "facecam_bl") targetRoi = { x: 0.02, y: 0.67, w: 0.22, h: 0.28 };
              else if (pVal === "facecam_br") targetRoi = { x: 0.76, y: 0.67, w: 0.22, h: 0.28 };
              else if (pVal === "hud_bottom") targetRoi = { x: 0.25, y: 0.85, w: 0.50, h: 0.13 };
              else if (pVal === "gameplay_center") targetRoi = { x: 0.15, y: 0.15, w: 0.70, h: 0.70 };

              if (targetRoi && ctrl) {
                ctrl.update(targetRoi);
                props.roi = targetRoi;
                props.x = targetRoi.x;
                props.y = targetRoi.y;
                props.w = targetRoi.w;
                props.h = targetRoi.h;
                const coordsEl = widget.querySelector(`#crop-coords-${node.id}`);
                if (coordsEl) {
                  coordsEl.innerHTML = `<span>X: ${Math.round(targetRoi.x * 100)}% Y: ${Math.round(targetRoi.y * 100)}%</span><span>Size: ${Math.round(targetRoi.w * 100)}% × ${Math.round(targetRoi.h * 100)}%</span>`;
                }
                this.syncNodeParamDebounced(node.id, "roi", targetRoi);
                this.syncNodeParamDebounced(node.id, "preset", pVal);
                this.showToast(`Applied preset: ${pVal}`);
                this.updateDownstreamCroppedPreviews(node.id, targetRoi);
              }
            });
          }
        }, 50);
      } else if (node.type === "ImageScaleNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget scaler-widget");
        const curFactor = props.scale_factor !== undefined ? props.scale_factor : 2.0;
        const curAlgo = props.algorithm || "bicubic";
        const curSharpen = props.sharpen_strength !== undefined ? props.sharpen_strength : 0.5;

        widget.innerHTML = `
          <div class="node-source-row" style="margin-bottom:6px; display:flex; align-items:center; justify-content:space-between; gap:6px; background:rgba(0,0,0,0.25); padding:3px 6px; border-radius:4px;">
            <span style="font-size:10px; color:#94a3b8; white-space:nowrap;">Stream Source:</span>
            <select class="node-source-select" id="source-select-${node.id}" style="flex:1; max-width:140px; background:rgba(0,0,0,0.5); border:1px solid rgba(56,189,248,0.3); color:#38bdf8; font-size:10px; border-radius:4px; padding:2px 4px; cursor:pointer;">
              <option value="auto">⚡ Auto (Wire)</option>
            </select>
          </div>
          <div class="node-algo-row" style="margin-bottom:6px; display:flex; align-items:center; justify-content:space-between; gap:6px; background:rgba(0,0,0,0.25); padding:3px 6px; border-radius:4px;">
            <span style="font-size:10px; color:#94a3b8; white-space:nowrap;">Algorithm:</span>
            <select class="scaler-algo-select" id="algo-select-${node.id}" style="flex:1; max-width:150px; background:rgba(0,0,0,0.5); border:1px solid rgba(14,165,233,0.4); color:#38bdf8; font-size:9.5px; border-radius:4px; padding:2px 4px; cursor:pointer;">
              <optgroup label="⚡ Classical Resamplers">
                <option value="lanczos4" ${curAlgo === "lanczos4" ? "selected" : ""}>Lanczos-4 (High Quality)</option>
                <option value="bicubic" ${curAlgo === "bicubic" ? "selected" : ""}>Bicubic (Sharp)</option>
                <option value="bilinear" ${curAlgo === "bilinear" ? "selected" : ""}>Bilinear (Fast Smooth)</option>
                <option value="area" ${curAlgo === "area" ? "selected" : ""}>Area (Downsample Clean)</option>
                <option value="nearest" ${curAlgo === "nearest" ? "selected" : ""}>Nearest (Pixel Art / Fast)</option>
              </optgroup>
              <optgroup label="✨ Detail & Contrast">
                <option value="unsharp_mask" ${curAlgo === "unsharp_mask" ? "selected" : ""}>Unsharp Mask (Crisp Edges)</option>
                <option value="clahe" ${curAlgo === "clahe" ? "selected" : ""}>CLAHE (Local Contrast)</option>
                <option value="bilateral" ${curAlgo === "bilateral" ? "selected" : ""}>Bilateral (Denoise & Edge)</option>
              </optgroup>
              <optgroup label="🧠 Neural AI Super-Res">
                <option value="neural_subpixel" ${curAlgo === "neural_subpixel" ? "selected" : ""}>ESPCN Sub-Pixel (ONNX AI)</option>
              </optgroup>
            </select>
          </div>
          <div class="widget-label" style="display:flex; align-items:center; justify-content:space-between; gap:4px; margin-bottom:4px;">
            <span>Scale Multiplier</span>
            <div class="scale-pills" id="scale-pills-${node.id}" style="display:inline-flex; gap:3px;">
              <button type="button" class="scale-pill-btn" data-scale="0.5" style="border:none; background:${Math.abs(curFactor - 0.5) < 0.05 ? 'rgba(56,189,248,0.3)' : 'rgba(255,255,255,0.08)'}; color:${Math.abs(curFactor - 0.5) < 0.05 ? '#38bdf8' : '#94a3b8'}; font-size:9px; font-weight:700; padding:1px 5px; border-radius:3px; cursor:pointer;">0.5x</button>
              <button type="button" class="scale-pill-btn" data-scale="1.0" style="border:none; background:${Math.abs(curFactor - 1.0) < 0.05 ? 'rgba(56,189,248,0.3)' : 'rgba(255,255,255,0.08)'}; color:${Math.abs(curFactor - 1.0) < 0.05 ? '#38bdf8' : '#94a3b8'}; font-size:9px; font-weight:700; padding:1px 5px; border-radius:3px; cursor:pointer;">1.0x</button>
              <button type="button" class="scale-pill-btn" data-scale="2.0" style="border:none; background:${Math.abs(curFactor - 2.0) < 0.05 ? 'rgba(56,189,248,0.3)' : 'rgba(255,255,255,0.08)'}; color:${Math.abs(curFactor - 2.0) < 0.05 ? '#38bdf8' : '#94a3b8'}; font-size:9px; font-weight:700; padding:1px 5px; border-radius:3px; cursor:pointer;">2.0x</button>
              <button type="button" class="scale-pill-btn" data-scale="4.0" style="border:none; background:${Math.abs(curFactor - 4.0) < 0.05 ? 'rgba(56,189,248,0.3)' : 'rgba(255,255,255,0.08)'}; color:${Math.abs(curFactor - 4.0) < 0.05 ? '#38bdf8' : '#94a3b8'}; font-size:9px; font-weight:700; padding:1px 5px; border-radius:3px; cursor:pointer;">4.0x</button>
            </div>
          </div>
          <div class="node-roi-container roi-container-${node.id}">
            <img class="roi-live-img" id="scale-live-img-${node.id}" style="display:none;" />
            <div class="roi-placeholder-text" id="scale-placeholder-${node.id}">Unrouted (Connect Video In or Crop Node)</div>
            <div class="crop-source-badge" id="scale-crop-badge-${node.id}" style="display:none; position:absolute; top:4px; right:4px; font-size:9px; background:rgba(14,165,233,0.85); color:#fff; padding:1px 5px; border-radius:3px; font-weight:600; pointer-events:none; z-index:2; backdrop-filter:blur(4px);">🔬 SCALED</div>
          </div>
          <div class="scale-status-bar" style="display:flex; justify-content:space-between; align-items:center; font-size:9px; color:#94a3b8; margin-top:5px; padding:3px 6px; background:rgba(0,0,0,0.35); border-radius:4px; border:1px solid rgba(255,255,255,0.05); font-family:monospace;">
            <span id="scale-dim-badge-${node.id}" style="color:#38bdf8; font-weight:700;">--x-- ➔ --x-- (${curFactor}x)</span>
            <span id="scale-latency-tag-${node.id}" style="color:#06b6d4;">-- ms</span>
          </div>
          <div style="display:flex; justify-content:space-between; font-size:9px; color:#94a3b8; margin-top:6px;">
            <span id="scale-factor-label-${node.id}">Multiplier: ${curFactor}x</span>
            <span id="scale-sharpen-label-${node.id}">Sharpen: ${curSharpen}</span>
          </div>
          <div style="display:flex; gap:8px; margin-top:2px;">
            <input type="range" class="node-slider scale-factor-slider" id="scale-factor-slider-${node.id}" min="0.25" max="4.0" step="0.25" value="${curFactor}" style="flex:1;" />
            <input type="range" class="node-slider scale-sharpen-slider" id="scale-sharpen-slider-${node.id}" min="0.0" max="2.0" step="0.1" value="${curSharpen}" style="flex:1;" />
          </div>
        `;

        const factorSlider = widget.querySelector(`#scale-factor-slider-${node.id}`);
        const sharpenSlider = widget.querySelector(`#scale-sharpen-slider-${node.id}`);
        const factorLabel = widget.querySelector(`#scale-factor-label-${node.id}`);
        const sharpenLabel = widget.querySelector(`#scale-sharpen-label-${node.id}`);
        const pillsBox = widget.querySelector(`#scale-pills-${node.id}`);

        const updatePillStyles = (val) => {
          if (pillsBox) {
            pillsBox.querySelectorAll(".scale-pill-btn").forEach(btn => {
              const bVal = parseFloat(btn.dataset.scale);
              const isActive = Math.abs(bVal - val) < 0.05;
              btn.style.background = isActive ? "rgba(56,189,248,0.3)" : "rgba(255,255,255,0.08)";
              btn.style.color = isActive ? "#38bdf8" : "#94a3b8";
            });
          }
        };

        factorSlider?.addEventListener("input", (e) => {
          const val = parseFloat(e.target.value);
          props.scale_factor = val;
          if (factorLabel) factorLabel.textContent = `Multiplier: ${val}x`;
          updatePillStyles(val);
          this.syncNodeParamDebounced(node.id, "scale_factor", val);
        });

        sharpenSlider?.addEventListener("input", (e) => {
          const val = parseFloat(e.target.value);
          props.sharpen_strength = val;
          if (sharpenLabel) sharpenLabel.textContent = `Sharpen: ${val}`;
          this.syncNodeParamDebounced(node.id, "sharpen_strength", val);
        });

        pillsBox?.querySelectorAll(".scale-pill-btn").forEach(btn => {
          btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const val = parseFloat(btn.dataset.scale);
            props.scale_factor = val;
            if (factorSlider) factorSlider.value = val;
            if (factorLabel) factorLabel.textContent = `Multiplier: ${val}x`;
            updatePillStyles(val);
            this.syncNodeParamDebounced(node.id, "scale_factor", val);
            this.showToast(`Scale factor set to ${val}x`);
          });
        });

        const algoSelect = widget.querySelector(`#algo-select-${node.id}`);
        algoSelect?.addEventListener("change", (e) => {
          const val = e.target.value;
          props.algorithm = val;
          this.syncNodeParamDebounced(node.id, "algorithm", val);
          this.showToast(`Switched algorithm to ${val}`);
        });

        this.setupSourceSelect(widget, node);
        bodyEl.appendChild(widget);
      } else if (node.type === "FacecamEmotionNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        const tiltThresh = props.tilt_threshold !== undefined ? props.tilt_threshold : 65.0;
        const curModel = props.model || "ferplus";
        widget.innerHTML = `
          <div class="node-source-row" style="margin-bottom:6px; display:flex; align-items:center; justify-content:space-between; gap:6px; background:rgba(0,0,0,0.25); padding:3px 6px; border-radius:4px;">
            <span style="font-size:10px; color:#94a3b8; white-space:nowrap;">Stream Source:</span>
            <select class="node-source-select" id="source-select-${node.id}" style="flex:1; max-width:140px; background:rgba(0,0,0,0.5); border:1px solid rgba(56,189,248,0.3); color:#38bdf8; font-size:10px; border-radius:4px; padding:2px 4px; cursor:pointer;">
              <option value="auto">⚡ Auto (Wire)</option>
            </select>
          </div>
          <div class="node-model-row" style="margin-bottom:6px; display:flex; align-items:center; justify-content:space-between; gap:6px; background:rgba(0,0,0,0.25); padding:3px 6px; border-radius:4px;">
            <span style="font-size:10px; color:#94a3b8; white-space:nowrap;">Model Engine:</span>
            <select class="node-model-select" id="model-select-${node.id}" style="flex:1; max-width:140px; background:rgba(0,0,0,0.5); border:1px solid rgba(168,85,247,0.4); color:#c084fc; font-size:10px; border-radius:4px; padding:2px 4px; cursor:pointer;">
              <option value="ferplus" ${curModel === "ferplus" ? "selected" : ""}>🧠 FERPlus (8-Class ONNX)</option>
              <option value="mobilefacenet" ${curModel === "mobilefacenet" ? "selected" : ""}>⚡ MobileFaceNet (7-Class)</option>
            </select>
          </div>
          <div class="widget-label">
            <span>Emotional Dynamics & Tilt</span>
            <span class="widget-val" id="face-top-val-${node.id}">STANDBY</span>
          </div>
          <div class="node-roi-container roi-container-${node.id}">
            <img class="roi-live-img" id="face-live-img-${node.id}" style="display:none;" />
            <div class="roi-placeholder-text" id="face-placeholder-${node.id}">Unrouted (Connect Video In or Crop Node)</div>
            <div class="crop-source-badge" id="face-crop-badge-${node.id}" style="display:none; position:absolute; top:4px; right:4px; font-size:9px; background:rgba(244,63,94,0.85); color:#fff; padding:1px 5px; border-radius:3px; font-weight:600; pointer-events:none; z-index:2; backdrop-filter:blur(4px);">✂️ CROPPED</div>
          </div>
          <div class="tilt-card">
            <div class="tilt-meter-box">
              <span style="font-size: 9px; color: #94a3b8; font-weight: 700;">TILT INDEX</span>
              <span class="tilt-num" id="face-tilt-num-${node.id}" style="color: #64748b;">--</span>
            </div>
            <div style="text-align: right;">
              <span class="tilt-state-pill" id="face-tilt-pill-${node.id}" style="background: rgba(100, 116, 139, 0.15); color: #64748b;">UNROUTED</span>
              <div style="font-size: 9px; color: #94a3b8; margin-top: 4px;">Euphoria: <strong id="face-euphoria-val-${node.id}" style="color: #64748b;">--%</strong></div>
            </div>
          </div>
          <div style="margin-top: 6px;">
            <div style="display: flex; justify-content: space-between; font-size: 9px; color: #94a3b8;">
              <span>Valence (Frustrated ⟵ ⟶ Happy)</span>
              <span id="face-valence-val-${node.id}">--</span>
            </div>
            <div class="valence-track">
              <div class="valence-indicator" id="face-valence-ind-${node.id}" style="left: 50%;"></div>
            </div>
          </div>
          <div class="face-mode-toggle-row" style="margin-top:8px; margin-bottom:4px; display:flex; justify-content:space-between; align-items:center;">
            <span style="font-size:9px; color:#94a3b8; font-weight:700; text-transform:uppercase; letter-spacing:0.5px;">Output Metrics</span>
            <div class="face-mode-switch" id="face-mode-switch-${node.id}" style="display:inline-flex; background:rgba(0,0,0,0.4); border:1px solid rgba(255,255,255,0.08); border-radius:4px; padding:2px; gap:2px;">
              <button type="button" class="mode-btn mode-btn-probs" data-mode="probs" style="border:none; background:${props.display_mode !== 'logits' ? 'rgba(56,189,248,0.25)' : 'transparent'}; color:${props.display_mode !== 'logits' ? '#38bdf8' : '#94a3b8'}; font-size:9px; font-weight:600; padding:2px 7px; border-radius:3px; cursor:pointer; transition:all 0.15s ease;">% Probs</button>
              <button type="button" class="mode-btn mode-btn-logits" data-mode="logits" style="border:none; background:${props.display_mode === 'logits' ? 'rgba(168,85,247,0.25)' : 'transparent'}; color:${props.display_mode === 'logits' ? '#c084fc' : '#94a3b8'}; font-size:9px; font-weight:600; padding:2px 7px; border-radius:3px; cursor:pointer; transition:all 0.15s ease;">Raw Logits</button>
            </div>
          </div>
          <div class="cv-bars-box" id="face-bars-${node.id}">
            <div style="color:#475569; font-size:10px; text-align:center; padding:8px 0;">No active stream routed</div>
          </div>
          <div style="display:flex; justify-content:space-between; font-size:9px; color:#94a3b8; margin-top:4px;">
            <span id="tilt-thresh-label-${node.id}">Tilt Trigger Threshold: ≥ ${tiltThresh}</span>
            <span id="face-latency-tag-${node.id}" style="color:#06b6d4;">-- ms</span>
          </div>
          <input type="range" class="node-slider" min="40" max="95" step="5" value="${tiltThresh}" />
        `;
        const slider = widget.querySelector(".node-slider");
        slider.addEventListener("input", (e) => {
          props.tilt_threshold = parseFloat(e.target.value);
          widget.querySelector(`#tilt-thresh-label-${node.id}`).textContent = `Tilt Trigger Threshold: ≥ ${props.tilt_threshold}`;
          this.syncNodeParamDebounced(node.id, "tilt_threshold", props.tilt_threshold);
        });
        const modelSelect = widget.querySelector(`#model-select-${node.id}`);
        if (modelSelect) {
          modelSelect.addEventListener("change", (e) => {
            props.model = e.target.value;
            this.syncNodeParamDebounced(node.id, "model", props.model);
            this.showToast(`Switched emotion model to ${props.model === "ferplus" ? "FERPlus (8-Class ONNX)" : "MobileFaceNet"}`);
          });
        }
        const modeSwitch = widget.querySelector(`#face-mode-switch-${node.id}`);
        if (modeSwitch) {
          modeSwitch.querySelectorAll(".mode-btn").forEach(btn => {
            btn.addEventListener("click", (e) => {
              e.stopPropagation();
              const targetMode = btn.dataset.mode;
              props.display_mode = targetMode;
              modeSwitch.querySelectorAll(".mode-btn").forEach(b => {
                const isActive = b.dataset.mode === targetMode;
                b.style.background = isActive ? (targetMode === "logits" ? "rgba(168,85,247,0.25)" : "rgba(56,189,248,0.25)") : "transparent";
                b.style.color = isActive ? (targetMode === "logits" ? "#c084fc" : "#38bdf8") : "#94a3b8";
              });
              if (this.latestTelemetry) {
                this.applyTelemetry(this.latestTelemetry);
              }
            });
          });
        }
        this.setupSourceSelect(widget, node);
        bodyEl.appendChild(widget);
      } else if (node.type === "GamblingLedgerNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        widget.innerHTML = `
          <div class="node-source-row" style="margin-bottom:6px; display:flex; align-items:center; justify-content:space-between; gap:6px; background:rgba(0,0,0,0.25); padding:3px 6px; border-radius:4px;">
            <span style="font-size:10px; color:#94a3b8; white-space:nowrap;">Stream Source:</span>
            <select class="node-source-select" id="source-select-${node.id}" style="flex:1; max-width:140px; background:rgba(0,0,0,0.5); border:1px solid rgba(56,189,248,0.3); color:#38bdf8; font-size:10px; border-radius:4px; padding:2px 4px; cursor:pointer;">
              <option value="auto">⚡ Auto (Wire)</option>
            </select>
          </div>
          <div class="ledger-hero-card">
            <div style="font-size: 9px; color: #94a3b8; font-weight: 700; text-transform: uppercase;">Session Net Profit / Loss</div>
            <div class="ledger-pnl-val pnl-positive" id="ledger-pnl-${node.id}">+$0.00</div>
          </div>
          <div class="chasing-warning-badge" id="ledger-chase-badge-${node.id}">
            ⚠️ LOSS CHASING DETECTED (MARTINGALE BET ESCALATION)
          </div>
          <div class="gambling-hud-grid">
            <div class="hud-stat-cell">
              <div class="hud-stat-lbl">Winrate (Hit %)</div>
              <div class="hud-stat-val" id="ledger-winrate-${node.id}">0.0%</div>
            </div>
            <div class="hud-stat-cell">
              <div class="hud-stat-lbl">Current Streak</div>
              <div class="hud-stat-val" id="ledger-streak-${node.id}">0</div>
            </div>
            <div class="hud-stat-cell">
              <div class="hud-stat-lbl">Experienced RTP</div>
              <div class="hud-stat-val" id="ledger-rtp-${node.id}">100.0%</div>
            </div>
            <div class="hud-stat-cell">
              <div class="hud-stat-lbl">Max Drawdown</div>
              <div class="hud-stat-val" id="ledger-drawdown-${node.id}">$0.00</div>
            </div>
          </div>
          <div style="margin-top: 8px;">
            <div style="font-size: 9px; color: #94a3b8; font-weight: 600; margin-bottom: 2px;">Rolling PnL Curve (Spins History):</div>
            <canvas class="node-wave-canvas" id="ledger-canvas-${node.id}" width="280" height="48" style="background: rgba(0,0,0,0.5); border-radius: 4px;"></canvas>
          </div>
        `;
        this.setupSourceSelect(widget, node);
        bodyEl.appendChild(widget);
      } else if (node.type === "CVTransformerNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        const currentLabels = props.candidate_labels || "gameplay action, victory celebration, defeat game over, in-game menu, streamer facecam, brb waiting screen";
        const thresh = props.confidence_threshold !== undefined ? props.confidence_threshold : 0.70;
        widget.innerHTML = `
          <div class="node-source-row" style="margin-bottom:6px; display:flex; align-items:center; justify-content:space-between; gap:6px; background:rgba(0,0,0,0.25); padding:3px 6px; border-radius:4px;">
            <span style="font-size:10px; color:#94a3b8; white-space:nowrap;">Stream Source:</span>
            <select class="node-source-select" id="source-select-${node.id}" style="flex:1; max-width:140px; background:rgba(0,0,0,0.5); border:1px solid rgba(56,189,248,0.3); color:#38bdf8; font-size:10px; border-radius:4px; padding:2px 4px; cursor:pointer;">
              <option value="auto">⚡ Auto (Wire)</option>
            </select>
          </div>
          <div class="widget-label">
            <span id="cv-engine-badge-${node.id}">⚡ CoreML / ANE</span>
            <span class="widget-val" id="cv-top-val-${node.id}">UNROUTED</span>
          </div>
          <div class="cv-preview-frame">
            <img id="cv-thumb-${node.id}" class="cv-thumb-img" alt="CV Frame Preview" style="display:none;" />
            <div id="cv-thumb-placeholder-${node.id}" class="cv-thumb-placeholder">Unrouted (Connect Video In or Assign Stream)</div>
          </div>
          <div class="cv-bars-box" id="cv-bars-${node.id}">
            <div style="color:#475569; font-size:10px; text-align:center; padding:8px 0;">No active stream routed</div>
          </div>
          <div style="display:flex; justify-content:space-between; font-size:9px; color:#94a3b8; margin-top:4px;">
            <span id="cv-thresh-label-${node.id}">Trigger Cutoff: ≥ ${(thresh * 100).toFixed(0)}%</span>
            <span id="cv-latency-tag-${node.id}" style="color:#38bdf8;">-- ms</span>
          </div>
          <input type="range" class="node-slider" min="0.30" max="0.95" step="0.05" value="${thresh}" />
          <div style="margin-top:6px;">
            <div style="font-size:9px; color:#94a3b8; margin-bottom:2px;">Prompt Classes (comma-separated):</div>
            <input type="text" class="node-input-text cv-labels-input" value="${currentLabels}" style="width: 100%; box-sizing: border-box; background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.15); border-radius: 4px; color: #f8fafc; font-size: 10px; padding: 4px 6px;" />
          </div>
        `;
        const slider = widget.querySelector(".node-slider");
        slider.addEventListener("input", (e) => {
          props.confidence_threshold = parseFloat(e.target.value);
          widget.querySelector(`#cv-thresh-label-${node.id}`).textContent = `Trigger Cutoff: ≥ ${(props.confidence_threshold * 100).toFixed(0)}%`;
          this.syncNodeParamDebounced(node.id, "confidence_threshold", props.confidence_threshold);
        });
        const labelsInput = widget.querySelector(".cv-labels-input");
        labelsInput.addEventListener("change", (e) => {
          props.candidate_labels = e.target.value;
          this.syncNodeParamDebounced(node.id, "candidate_labels", props.candidate_labels);
        });
        this.setupSourceSelect(widget, node);
        bodyEl.appendChild(widget);
      } else if (node.type === "GateEvaluatorNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        widget.innerHTML = `
          <div class="node-source-row" style="margin-bottom:6px; display:flex; align-items:center; justify-content:space-between; gap:6px; background:rgba(0,0,0,0.25); padding:3px 6px; border-radius:4px;">
            <span style="font-size:10px; color:#94a3b8; white-space:nowrap;">Stream Source:</span>
            <select class="node-source-select" id="source-select-${node.id}" style="flex:1; max-width:140px; background:rgba(0,0,0,0.5); border:1px solid rgba(56,189,248,0.3); color:#38bdf8; font-size:10px; border-radius:4px; padding:2px 4px; cursor:pointer;">
              <option value="auto">⚡ Auto (Wire)</option>
            </select>
          </div>
          <div class="widget-label">
            <span>Fused Multi-Modal Score</span>
            <span class="widget-val">Threshold: ≥ ${props.min_score || 4}/10</span>
          </div>
          <div class="score-gauge-box">
            <div class="score-dial" id="gate-score-${node.id}">0</div>
            <div class="score-status-pill" id="gate-status-${node.id}">UNROUTED</div>
          </div>
        `;
        this.setupSourceSelect(widget, node);
        bodyEl.appendChild(widget);
      } else if (node.type === "ThresholdGateNode") {
        this.renderThresholdGateWidget(node, bodyEl);
      } else if (node.type === "HardwareRenderNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        widget.innerHTML = `
          <div class="widget-label">
            <span>Render Pipeline Status</span>
            <span class="widget-val" id="render-status-${node.id}">IDLE</span>
          </div>
          <div style="font-size:10px; color:#94a3b8;">
            Encoder: <strong>Apple Silicon VideoToolbox</strong> | Full 1080p
          </div>
        `;
        bodyEl.appendChild(widget);
      } else if (node.type === "ClipFolderNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget clip-folder-widget");
        const folderName = props.folder_name || "Highlight Reels";
        const folderDate = props.date || new Date().toISOString().split("T")[0];

        widget.innerHTML = `
          <div class="widget-label">
            <span style="display: flex; align-items: center; gap: 4px;">📂 Folder Storage</span>
            <span class="widget-val" id="folder-status-${node.id}">READY</span>
          </div>

          <div style="margin-bottom: 6px;">
            <div style="font-size: 9px; color: #94a3b8; margin-bottom: 2px; text-transform: uppercase;">Folder Name:</div>
            <input type="text" class="node-input-text folder-name-input" id="folder-name-${node.id}" value="${folderName}" placeholder="e.g. Crazy Slots & Wins" style="width: 100%; box-sizing: border-box; background: rgba(0,0,0,0.5); border: 1px solid rgba(249, 115, 22, 0.5); border-radius: 4px; color: #fed7aa; font-weight: 700; font-size: 11px; padding: 4px 6px;" />
          </div>

          <div style="margin-bottom: 8px;">
            <div style="font-size: 9px; color: #94a3b8; margin-bottom: 2px; text-transform: uppercase;">Folder Date:</div>
            <input type="date" class="node-input-date folder-date-input" id="folder-date-${node.id}" value="${folderDate}" style="width: 100%; box-sizing: border-box; background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.15); border-radius: 4px; color: #f8fafc; font-size: 11px; padding: 4px 6px;" />
          </div>

          <div class="folder-stats-grid" style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 8px;">
            <div style="background: rgba(0,0,0,0.35); padding: 6px 8px; border-radius: 4px; border: 1px solid rgba(249,115,22,0.2);">
              <div style="font-size: 8px; color: #94a3b8; text-transform: uppercase;">Saved Clips</div>
              <div style="font-size: 14px; font-weight: 800; color: #f97316;" id="folder-count-${node.id}">0</div>
            </div>
            <div style="background: rgba(0,0,0,0.35); padding: 6px 8px; border-radius: 4px; border: 1px solid rgba(56,189,248,0.2);">
              <div style="font-size: 8px; color: #94a3b8; text-transform: uppercase;">Total Time</div>
              <div style="font-size: 14px; font-weight: 800; color: #38bdf8;" id="folder-duration-${node.id}">0s</div>
            </div>
          </div>

          <div style="font-size: 9px; color: #64748b; margin-bottom: 8px; line-height: 1.3;" id="folder-renderers-${node.id}">
            🔌 <em>Connect a Hardware Video Renderer to route clips here</em>
          </div>

          <div class="folder-mini-preview" id="folder-mini-preview-${node.id}" style="display: flex; gap: 4px; overflow-x: auto; margin-bottom: 8px; min-height: 24px; padding: 2px 0;">
            <div style="font-size: 10px; color: #475569; font-style: italic;">No clips recorded to folder yet</div>
          </div>

          <button class="folder-view-btn" id="btn-open-folder-${node.id}" style="width: 100%; display: flex; align-items: center; justify-content: center; gap: 6px; background: linear-gradient(135deg, rgba(249, 115, 22, 0.25), rgba(234, 88, 12, 0.4)); border: 1px solid #f97316; color: #fed7aa; padding: 7px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; cursor: pointer; transition: all 0.2s ease;">
            📂 Open Folder View of Clips
          </button>
        `;

        const nameInput = widget.querySelector(`#folder-name-${node.id}`);
        nameInput?.addEventListener("change", (e) => {
          const val = e.target.value.trim() || "Clips";
          node.properties = node.properties || {};
          node.properties.folder_name = val;
          node.title = `Clip Folder: ${val}`;
          const titleEl = document.getElementById(`node-${node.id}`)?.querySelector(".node-title");
          if (titleEl) titleEl.textContent = `Clip Folder: ${val}`;
          this.syncNodeParamDebounced(node.id, "folder_name", val);
        });

        const dateInput = widget.querySelector(`#folder-date-${node.id}`);
        dateInput?.addEventListener("change", (e) => {
          const val = e.target.value;
          node.properties = node.properties || {};
          node.properties.date = val;
          this.syncNodeParamDebounced(node.id, "date", val);
        });

        const viewBtn = widget.querySelector(`#btn-open-folder-${node.id}`);
        viewBtn?.addEventListener("click", () => {
          this.openFolderViewModal(node.id);
        });

        bodyEl.appendChild(widget);
      }
    }

    renderThresholdGateWidget(node, bodyEl) {
      const props = node.properties || {};
      const rules = props.rules || {};
      const logicMode = props.logic_mode || "ALL";
      const minCount = props.min_count !== undefined ? props.min_count : 1;
      const debounceSec = props.debounce_seconds !== undefined ? props.debounce_seconds : 10.0;
      const showSliders = props.show_sliders !== undefined ? Boolean(props.show_sliders) : true;

      const widget = document.createElement("div");
      widget.setAttribute("class", `node-widget threshold-gate-widget ${showSliders ? "" : "sliders-hidden"}`);
      widget.setAttribute("id", `threshold-gate-widget-${node.id}`);

      // Top control bar
      const topBarHtml = `
        <div class="gate-header-controls">
          <div class="gate-control-group">
            <label class="gate-control-label">Scenario:</label>
            <select class="gate-select gate-logic-mode-select" id="gate-logic-${node.id}">
              <option value="ALL" ${logicMode === "ALL" ? "selected" : ""}>ALL (AND)</option>
              <option value="ANY" ${logicMode === "ANY" ? "selected" : ""}>ANY (OR)</option>
              <option value="COUNT" ${logicMode === "COUNT" ? "selected" : ""}>COUNT (≥ N)</option>
            </select>
          </div>
          <div class="gate-control-group count-group" id="gate-count-group-${node.id}" style="${logicMode === 'COUNT' ? '' : 'display:none;'}">
            <label class="gate-control-label">Min:</label>
            <input type="number" class="gate-input-number gate-min-count-input" id="gate-min-count-${node.id}" value="${minCount}" min="1" max="20" style="width: 36px;" />
          </div>
          <div class="gate-control-group">
            <label class="gate-control-label">Cooldown:</label>
            <input type="number" class="gate-input-number gate-debounce-input" id="gate-debounce-${node.id}" value="${debounceSec}" min="1" max="120" step="1" style="width: 40px;" />
            <span class="gate-unit-text">s</span>
          </div>
          <button type="button" class="gate-slider-toggle-btn ${showSliders ? 'active' : ''}" id="gate-slider-toggle-${node.id}" title="Toggle Sliders Display">
            ${showSliders ? '🎚️ Sliders: On' : '🎚️ Sliders: Off'}
          </button>
        </div>

        <div class="gate-status-bar">
          <span class="gate-count-badge" id="gate-count-badge-${node.id}">0/0 Passed</span>
          <span class="gate-status-pill standby" id="gate-status-${node.id}">STANDBY</span>
        </div>

        <div class="gate-rules-list" id="gate-rules-list-${node.id}"></div>
      `;

      widget.innerHTML = topBarHtml;
      const rulesListEl = widget.querySelector(`#gate-rules-list-${node.id}`);

      // Render rule rows for each input
      (node.inputs || []).forEach((inp) => {
        const portId = inp.id;
        const rule = rules[portId] || {
          operator: ">=",
          threshold: 0.5,
          min: 0.0,
          max: 1.0,
          step: 0.01,
          unit: "",
          label: inp.name || portId,
        };

        const ruleRow = document.createElement("div");
        ruleRow.setAttribute("class", "gate-rule-item");
        ruleRow.setAttribute("id", `gate-rule-${node.id}-${portId}`);

        const minVal = rule.min !== undefined ? rule.min : 0.0;
        const maxVal = rule.max !== undefined ? rule.max : 1.0;
        const stepVal = rule.step !== undefined ? rule.step : 0.01;
        const currentThresh = rule.threshold !== undefined ? rule.threshold : 0.5;
        const op = rule.operator || ">=";
        const label = rule.label || inp.name || portId;
        const unit = rule.unit || "";

        ruleRow.innerHTML = `
          <div class="gate-rule-header">
            <div class="gate-rule-name-wrap">
              <span class="gate-pass-icon unconnected" id="gate-pass-${node.id}-${portId}" title="Unconnected">⚪</span>
              <span class="gate-rule-label" title="${label}">${label}</span>
            </div>
            <div class="gate-rule-op-wrap">
              <select class="gate-select gate-op-select" data-port="${portId}">
                <option value=">=" ${op === ">=" ? "selected" : ""}>&ge; (At least)</option>
                <option value=">" ${op === ">" ? "selected" : ""}>&gt; (Above)</option>
                <option value="<=" ${op === "<=" ? "selected" : ""}>&le; (At most)</option>
                <option value="<" ${op === "<" ? "selected" : ""}>&lt; (Below)</option>
                <option value="==" ${op === "==" ? "selected" : ""}>= (Equal)</option>
              </select>
              <input type="number" class="gate-input-number gate-thresh-input" data-port="${portId}" value="${currentThresh}" min="${minVal}" max="${maxVal}" step="${stepVal}" />
              <span class="gate-unit-text">${unit}</span>
              <div class="gate-val-badge" id="gate-val-${node.id}-${portId}">--</div>
            </div>
          </div>
          <div class="gate-slider-row">
            <span class="gate-range-bound min">${minVal}${unit}</span>
            <input type="range" class="gate-slider" data-port="${portId}" min="${minVal}" max="${maxVal}" step="${stepVal}" value="${currentThresh}" />
            <span class="gate-range-bound max">${maxVal}${unit}</span>
          </div>
        `;

        // Event listeners for rule controls
        const opSelect = ruleRow.querySelector(".gate-op-select");
        const threshInput = ruleRow.querySelector(".gate-thresh-input");
        const sliderInput = ruleRow.querySelector(".gate-slider");

        opSelect.addEventListener("change", (e) => {
          rule.operator = e.target.value;
          if (!node.properties) node.properties = {};
          if (!node.properties.rules) node.properties.rules = {};
          node.properties.rules[portId] = rule;
          this.syncNodeParamDebounced(node.id, "rules", node.properties.rules);
          if (this.latestTelemetry) this.applyTelemetry(this.latestTelemetry);
        });

        const updateThresh = (val) => {
          const numVal = parseFloat(val);
          if (isNaN(numVal)) return;
          rule.threshold = numVal;
          threshInput.value = numVal;
          sliderInput.value = numVal;
          if (!node.properties) node.properties = {};
          if (!node.properties.rules) node.properties.rules = {};
          node.properties.rules[portId] = rule;
          this.syncNodeParamDebounced(node.id, "rules", node.properties.rules);
          if (this.latestTelemetry) this.applyTelemetry(this.latestTelemetry);
        };

        threshInput.addEventListener("input", (e) => updateThresh(e.target.value));
        sliderInput.addEventListener("input", (e) => updateThresh(e.target.value));

        rulesListEl.appendChild(ruleRow);
      });

      // Top control listeners
      const logicSelect = widget.querySelector(`#gate-logic-${node.id}`);
      const countGroup = widget.querySelector(`#gate-count-group-${node.id}`);
      const minCountInput = widget.querySelector(`#gate-min-count-${node.id}`);
      const debounceInput = widget.querySelector(`#gate-debounce-${node.id}`);
      const sliderToggleBtn = widget.querySelector(`#gate-slider-toggle-${node.id}`);

      logicSelect.addEventListener("change", (e) => {
        const val = e.target.value;
        node.properties.logic_mode = val;
        countGroup.style.display = val === "COUNT" ? "" : "none";
        this.syncNodeParamDebounced(node.id, "logic_mode", val);
        if (this.latestTelemetry) this.applyTelemetry(this.latestTelemetry);
      });

      minCountInput.addEventListener("input", (e) => {
        const val = parseInt(e.target.value, 10) || 1;
        node.properties.min_count = val;
        this.syncNodeParamDebounced(node.id, "min_count", val);
        if (this.latestTelemetry) this.applyTelemetry(this.latestTelemetry);
      });

      debounceInput.addEventListener("input", (e) => {
        const val = parseFloat(e.target.value) || 10.0;
        node.properties.debounce_seconds = val;
        this.syncNodeParamDebounced(node.id, "debounce_seconds", val);
      });

      sliderToggleBtn.addEventListener("click", () => {
        const newShow = !widget.classList.contains("sliders-hidden") ? false : true;
        node.properties.show_sliders = newShow;
        if (newShow) {
          widget.classList.remove("sliders-hidden");
          sliderToggleBtn.classList.add("active");
          sliderToggleBtn.textContent = "🎚️ Sliders: On";
        } else {
          widget.classList.add("sliders-hidden");
          sliderToggleBtn.classList.remove("active");
          sliderToggleBtn.textContent = "🎚️ Sliders: Off";
        }
        this.syncNodeParamDebounced(node.id, "show_sliders", newShow);
      });

      bodyEl.appendChild(widget);
    }

    /* -------------------------------------------------------------
       Real-Time Telemetry & Visual Pulses
       ------------------------------------------------------------- */
    applyTelemetry(telemetry) {
      if (!telemetry) return;
      this.latestTelemetry = telemetry;
      if (!this.container || !this.container.classList.contains("active")) return;

      const sessions = telemetry.sessions || {};

      // Update each node according to its routed stream source
      this.nodes.forEach((node) => {
        if (node.type === "StreamSourceNode") {
          const nodeCh = (node.properties?.channel || "").replace(/^#/, "").toLowerCase();
          const session = sessions[nodeCh];
          const statusEl = document.getElementById(`stream-status-${node.id}`);
          if (statusEl) {
            const isOnline = session && (session.status === "online" || session.is_buffering);
            statusEl.textContent = isOnline ? "ONLINE" : "STANDBY";
            statusEl.style.color = isOnline ? "#34d399" : "#94a3b8";
          }
          const selectEl = document.getElementById(`channel-select-${node.id}`);
          if (selectEl) {
            this.populateChannelSelect(selectEl, nodeCh);
          }
          return;
        }

        if (node.type === "ClipFolderNode") {
          const nodesData = telemetry.nodes || {};
          const fData = nodesData[node.id];
          const countEl = document.getElementById(`folder-count-${node.id}`);
          const durEl = document.getElementById(`folder-duration-${node.id}`);
          const rendEl = document.getElementById(`folder-renderers-${node.id}`);
          const previewEl = document.getElementById(`folder-mini-preview-${node.id}`);
          const statusEl = document.getElementById(`folder-status-${node.id}`);

          if (fData) {
            if (countEl) countEl.textContent = fData.clip_count;
            if (durEl) durEl.textContent = `${fData.total_duration}s`;
            if (statusEl) {
              statusEl.textContent = fData.clip_count > 0 ? `${fData.clip_count} SAVED` : "READY";
              statusEl.style.color = fData.clip_count > 0 ? "#f97316" : "#94a3b8";
            }
            if (rendEl) {
              if (fData.wired_renderers && fData.wired_renderers.length > 0) {
                rendEl.innerHTML = `🔌 <strong>Inbound:</strong> <span style="color:#38bdf8; font-weight:700;">${fData.wired_renderers.length} Renderer${fData.wired_renderers.length > 1 ? "s" : ""}</span> (${fData.wired_renderers.join(", ")})`;
                rendEl.style.color = "#94a3b8";
              } else {
                rendEl.innerHTML = `🔌 <em>No renderers wired. Connect a Hardware Video Renderer to store clips here.</em>`;
                rendEl.style.color = "#64748b";
              }
            }
            if (previewEl && fData.recent_clips) {
              if (fData.recent_clips.length === 0) {
                previewEl.innerHTML = `<div style="font-size:10px; color:#475569; font-style:italic; padding:4px 0;">No clips recorded to folder yet</div>`;
              } else {
                previewEl.innerHTML = fData.recent_clips.slice(0, 5).map(c => `
                  <div class="folder-mini-card" data-clip-id="${c.id}" style="position:relative; width:48px; height:32px; border-radius:3px; overflow:hidden; border:1px solid rgba(249,115,22,0.4); flex-shrink:0; cursor:pointer;" title="${c.title} (${c.duration}s)">
                    <img src="${c.thumbnail_url || c.video_url}" style="width:100%; height:100%; object-fit:cover;" onerror="this.style.display='none'" />
                    <span style="position:absolute; bottom:1px; right:2px; font-size:7px; background:rgba(0,0,0,0.8); color:#fed7aa; padding:0 2px; border-radius:2px;">${Math.round(c.duration)}s</span>
                  </div>
                `).join("");
                previewEl.querySelectorAll(".folder-mini-card").forEach(el => {
                  el.addEventListener("click", () => {
                    this.openFolderViewModal(node.id);
                  });
                });
              }
            }
          }
          return;
        }

        if (node.type === "ThresholdGateNode") {
          const nodesData = telemetry.nodes || {};
          const gateData = nodesData[node.id] || {};
          const statusEl = document.getElementById(`gate-status-${node.id}`);
          const countBadgeEl = document.getElementById(`gate-count-badge-${node.id}`);

          const passedCount = gateData.passed_count ?? 0;
          const totalConnected = gateData.total_connected ?? 0;
          const gateFired = Boolean(gateData.gate_fired);
          const isDebouncing = Boolean(gateData.is_debouncing);
          const debounceRemaining = gateData.debounce_remaining ?? 0;
          const isTrigger = Boolean(gateData.is_trigger);

          if (countBadgeEl) {
            countBadgeEl.textContent = `${passedCount}/${totalConnected} Passed`;
          }

          if (statusEl) {
            if (isTrigger || gateFired) {
              statusEl.textContent = isDebouncing ? `COOLDOWN (${debounceRemaining}s)` : "TRIGGER FIRED ⚡";
              statusEl.className = "gate-status-pill " + (isDebouncing ? "cooldown" : "fired");
              if (isTrigger) {
                this.pulseWiresFromNode(node.id);
              }
            } else if (totalConnected === 0) {
              statusEl.textContent = "STANDBY";
              statusEl.className = "gate-status-pill standby";
            } else {
              statusEl.textContent = isDebouncing ? `COOLDOWN (${debounceRemaining}s)` : "MONITORING";
              statusEl.className = "gate-status-pill " + (isDebouncing ? "cooldown" : "monitoring");
            }
          }

          // Update per-input live readouts and status checkmarks
          const inputsData = gateData.inputs || {};
          (node.inputs || []).forEach((inp) => {
            const pinData = inputsData[inp.id];
            const liveValEl = document.getElementById(`gate-val-${node.id}-${inp.id}`);
            const passIconEl = document.getElementById(`gate-pass-${node.id}-${inp.id}`);
            if (liveValEl && pinData) {
              if (pinData.value !== null && pinData.value !== undefined) {
                const formatted = typeof pinData.value === "number"
                  ? (Math.abs(pinData.value) < 1 && pinData.value !== 0 ? pinData.value.toFixed(2) : Math.round(pinData.value * 10) / 10)
                  : pinData.value;
                liveValEl.textContent = `${formatted}${pinData.unit || ""}`;
              } else {
                liveValEl.textContent = "--";
              }
            }
            if (passIconEl && pinData) {
              if (!pinData.connected) {
                passIconEl.textContent = "⚪";
                passIconEl.title = "Not connected";
                passIconEl.className = "gate-pass-icon unconnected";
              } else if (pinData.passed) {
                passIconEl.textContent = "✅";
                passIconEl.title = "Condition met";
                passIconEl.className = "gate-pass-icon passed";
              } else {
                passIconEl.textContent = "❌";
                passIconEl.title = "Condition not met";
                passIconEl.className = "gate-pass-icon failed";
              }
            }
          });
          return;
        }

        // For all worker nodes: determine routed session via wires or explicit assignment
        const sourceChannel = this.getNodeSourceChannel(node);
        const sourceSelectEl = document.getElementById(`source-select-${node.id}`);
        if (sourceSelectEl) {
          this.populateSourceSelect(sourceSelectEl, node);
        }

        const nodeSession = sourceChannel ? sessions[sourceChannel] : null;

        if (!nodeSession) {
          this.renderUnroutedNodeState(node);
          return;
        }

        // Route-specific telemetry updates
        if (node.type === "AudioMonitorNode") {
          const valEl = document.getElementById(`audio-val-${node.id}`);
          const spikeTag = document.getElementById(`audio-spike-tag-${node.id}`);
          const canvas = document.getElementById(`wave-canvas-${node.id}`);

          if (valEl && nodeSession.audio_rms_db !== undefined) {
            valEl.textContent = `${nodeSession.audio_rms_db.toFixed(1)} dB`;
          }

          if (nodeSession.audio_spike) {
            document.getElementById(`node-${node.id}`)?.classList.add("spiking");
            if (spikeTag) {
              spikeTag.textContent = "🔥 SPIKE DETECTED";
              spikeTag.style.color = "#f59e0b";
            }
            this.pulseWiresFromNode(node.id);
          } else {
            document.getElementById(`node-${node.id}`)?.classList.remove("spiking");
            if (spikeTag) {
              spikeTag.textContent = "QUIET";
              spikeTag.style.color = "#64748b";
            }
          }

          if (canvas && nodeSession.audio_waveform) {
            this.drawNeonWaveform(canvas, nodeSession.audio_waveform);
          }
        } else if (node.type === "ChatVelocityNode") {
          const valEl = document.getElementById(`chat-val-${node.id}`);
          const spikeTag = document.getElementById(`chat-spike-tag-${node.id}`);
          const ticker = document.getElementById(`chat-ticker-${node.id}`);

          if (valEl) {
            valEl.textContent = `${(nodeSession.v_instant || 0).toFixed(1)} msgs/s (${(nodeSession.spike_ratio || 1.0).toFixed(1)}x)`;
          }

          if (nodeSession.is_spiking) {
            document.getElementById(`node-${node.id}`)?.classList.add("spiking");
            if (spikeTag) {
              spikeTag.textContent = "⚡ HYPE SURGE";
              spikeTag.style.color = "#a855f7";
            }
            this.pulseWiresFromNode(node.id);
          } else {
            document.getElementById(`node-${node.id}`)?.classList.remove("spiking");
            if (spikeTag) {
              spikeTag.textContent = "NORMAL";
              spikeTag.style.color = "#64748b";
            }
          }

          if (ticker && nodeSession.recent_messages && nodeSession.recent_messages.length) {
            ticker.innerHTML = nodeSession.recent_messages
              .slice(-4)
              .map(
                (m) => `<div class="node-chat-msg"><span class="chat-user">${m.user}:</span><span class="chat-text">${m.text}</span></div>`
              )
              .join("");
            ticker.scrollTop = ticker.scrollHeight;
          }
        } else if (node.type === "OCRVisionNode") {
          const valEl = document.getElementById(`ocr-val-${node.id}`);
          const statusEl = document.getElementById(`ocr-status-${node.id}`);
          const slotMetrics = nodeSession.slot_metrics || {};
          if (valEl) {
            const mult = slotMetrics.multiplier || (nodeSession.ocr_multiplier ? parseFloat(nodeSession.ocr_multiplier) : 1.0);
            const tier = slotMetrics.win_tier || "BASE";
            const pnl = slotMetrics.net_pnl !== undefined
              ? (slotMetrics.net_pnl >= 0 ? `+$${slotMetrics.net_pnl.toFixed(2)}` : `-$${Math.abs(slotMetrics.net_pnl).toFixed(2)}`)
              : (nodeSession.ocr_balance || "$0.00");
            valEl.textContent = `${typeof mult === 'number' ? mult.toFixed(1) : mult}x (${pnl})`;
            valEl.style.color = "#38bdf8";
            if (statusEl) {
              statusEl.textContent = tier !== "BASE" ? tier.replace("_", " ") : "MONITORING";
              statusEl.style.color = slotMetrics.is_big_win ? "#fbbf24" : "#10b981";
            }
          }
          const ocrImg = document.getElementById(`ocr-live-img-${node.id}`);
          const ocrPlaceholder = document.getElementById(`ocr-placeholder-${node.id}`);
          const frameB64 = nodeSession.stream_frame_b64 || nodeSession.cv_thumbnail_b64;
          if (ocrImg && frameB64) {
            const upstreamCrop = this.getNodeUpstreamCropRoi(node);
            if (upstreamCrop) {
              const roi = upstreamCrop.roi;
              const leftPct = -(roi.x / roi.w) * 100;
              const topPct = -(roi.y / roi.h) * 100;
              const widthPct = (1 / roi.w) * 100;
              const heightPct = (1 / roi.h) * 100;
              ocrImg.src = frameB64;
              ocrImg.style.position = "absolute";
              ocrImg.style.width = `${widthPct}%`;
              ocrImg.style.height = `${heightPct}%`;
              ocrImg.style.left = `${leftPct}%`;
              ocrImg.style.top = `${topPct}%`;
              ocrImg.style.maxWidth = "none";
              ocrImg.style.maxHeight = "none";
              ocrImg.style.objectFit = "fill";
            } else {
              ocrImg.src = frameB64;
              ocrImg.style.position = "absolute";
              ocrImg.style.width = "100%";
              ocrImg.style.height = "100%";
              ocrImg.style.left = "0px";
              ocrImg.style.top = "0px";
              ocrImg.style.maxWidth = "100%";
              ocrImg.style.maxHeight = "100%";
              ocrImg.style.objectFit = "fill";
            }
            ocrImg.style.display = "block";
            if (ocrPlaceholder) ocrPlaceholder.style.display = "none";
          }
          const listEl = document.getElementById(`ocr-node-list-${node.id}`);
          const extracted = nodeSession.ocr_extracted_areas || nodeSession.dynamic_ocr_areas || [];
          if (listEl && extracted.length > 0) {
            listEl.innerHTML = extracted.map(a => `
              <div style="display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.04); border-left:3px solid ${a.color || '#38bdf8'}; border-radius:4px; padding:3px 6px; font-size:10px;">
                <span style="color:#cbd5e1; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:90px;">${a.label || 'Area'}</span>
                <span style="color:${a.color || '#38bdf8'}; font-family:monospace; font-weight:700; max-width:110px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${a.text || '—'}</span>
              </div>
            `).join("");
          }
        } else if (node.type === "VideoCropNode") {
          const cropImg = document.getElementById(`crop-live-img-${node.id}`);
          const cropPlaceholder = document.getElementById(`crop-placeholder-${node.id}`);
          const frameB64 = nodeSession.stream_frame_b64 || nodeSession.cv_thumbnail_b64;
          if (cropImg && frameB64) {
            cropImg.src = frameB64;
            cropImg.style.display = "block";
            if (cropPlaceholder) cropPlaceholder.style.display = "none";
          }
        } else if (node.type === "ImageScaleNode") {
          const scaleImg = document.getElementById(`scale-live-img-${node.id}`);
          const scalePlaceholder = document.getElementById(`scale-placeholder-${node.id}`);
          const scaleBadge = document.getElementById(`scale-dim-badge-${node.id}`);
          const latencyTag = document.getElementById(`scale-latency-tag-${node.id}`);
          const cropBadge = document.getElementById(`scale-crop-badge-${node.id}`);

          const scalerThumb = nodeSession.scaler_thumbnail_b64;
          const frameB64 = scalerThumb || nodeSession.stream_frame_b64 || nodeSession.cv_thumbnail_b64;

          if (scaleImg && frameB64) {
            const upstreamCrop = this.getNodeUpstreamCropRoi(node);
            if (scalerThumb) {
              scaleImg.src = scalerThumb;
              scaleImg.style.position = "absolute";
              scaleImg.style.width = "100%";
              scaleImg.style.height = "100%";
              scaleImg.style.left = "0px";
              scaleImg.style.top = "0px";
              scaleImg.style.maxWidth = "100%";
              scaleImg.style.maxHeight = "100%";
              scaleImg.style.objectFit = "contain";
              if (cropBadge) cropBadge.style.display = upstreamCrop ? "block" : "none";
            } else if (upstreamCrop) {
              const roi = upstreamCrop.roi;
              const leftPct = -(roi.x / roi.w) * 100;
              const topPct = -(roi.y / roi.h) * 100;
              const widthPct = (1 / roi.w) * 100;
              const heightPct = (1 / roi.h) * 100;
              scaleImg.src = frameB64;
              scaleImg.style.position = "absolute";
              scaleImg.style.width = `${widthPct}%`;
              scaleImg.style.height = `${heightPct}%`;
              scaleImg.style.left = `${leftPct}%`;
              scaleImg.style.top = `${topPct}%`;
              scaleImg.style.maxWidth = "none";
              scaleImg.style.maxHeight = "none";
              scaleImg.style.objectFit = "fill";
              if (cropBadge) cropBadge.style.display = "block";
            } else {
              scaleImg.src = frameB64;
              scaleImg.style.position = "absolute";
              scaleImg.style.width = "100%";
              scaleImg.style.height = "100%";
              scaleImg.style.left = "0px";
              scaleImg.style.top = "0px";
              scaleImg.style.maxWidth = "100%";
              scaleImg.style.maxHeight = "100%";
              scaleImg.style.objectFit = "cover";
              if (cropBadge) cropBadge.style.display = "none";
            }
            scaleImg.style.display = "block";
            if (scalePlaceholder) scalePlaceholder.style.display = "none";
          }

          if (scaleBadge) {
            const inRes = nodeSession.scaler_input_res || "—";
            const outRes = nodeSession.scaler_output_res || "—";
            const curFactor = node.properties?.scale_factor || 2.0;
            scaleBadge.textContent = `${inRes} ➔ ${outRes} (${curFactor}x)`;
          }
          if (latencyTag && nodeSession.scaler_latency_ms !== undefined) {
            latencyTag.textContent = `${nodeSession.scaler_latency_ms.toFixed(1)} ms`;
          }
        } else if (node.type === "FacecamEmotionNode") {
          const faceImg = document.getElementById(`face-live-img-${node.id}`);
          const facePlaceholder = document.getElementById(`face-placeholder-${node.id}`);
          const cropBadge = document.getElementById(`face-crop-badge-${node.id}`);
          const tiltNum = document.getElementById(`face-tilt-num-${node.id}`);
          const tiltPill = document.getElementById(`face-tilt-pill-${node.id}`);
          const topVal = document.getElementById(`face-top-val-${node.id}`);
          const euphoriaVal = document.getElementById(`face-euphoria-val-${node.id}`);
          const valenceVal = document.getElementById(`face-valence-val-${node.id}`);
          const valenceInd = document.getElementById(`face-valence-ind-${node.id}`);
          const barsBox = document.getElementById(`face-bars-${node.id}`);

          const emoThumb = nodeSession.emotion_thumbnail_b64;
          const frameB64 = emoThumb || nodeSession.stream_frame_b64 || nodeSession.cv_thumbnail_b64;
          if (faceImg && frameB64) {
            const upstreamCrop = this.getNodeUpstreamCropRoi(node);
            if (emoThumb) {
              // Backend already cropped this frame
              faceImg.src = emoThumb;
              faceImg.style.position = "absolute";
              faceImg.style.width = "100%";
              faceImg.style.height = "100%";
              faceImg.style.left = "0px";
              faceImg.style.top = "0px";
              faceImg.style.maxWidth = "100%";
              faceImg.style.maxHeight = "100%";
              faceImg.style.objectFit = "cover";
              if (cropBadge) cropBadge.style.display = upstreamCrop ? "block" : "none";
            } else if (upstreamCrop) {
              // Crop stream frame using upstream VideoCropNode ROI
              const roi = upstreamCrop.roi;
              const leftPct = -(roi.x / roi.w) * 100;
              const topPct = -(roi.y / roi.h) * 100;
              const widthPct = (1 / roi.w) * 100;
              const heightPct = (1 / roi.h) * 100;

              faceImg.src = frameB64;
              faceImg.style.position = "absolute";
              faceImg.style.width = `${widthPct}%`;
              faceImg.style.height = `${heightPct}%`;
              faceImg.style.left = `${leftPct}%`;
              faceImg.style.top = `${topPct}%`;
              faceImg.style.maxWidth = "none";
              faceImg.style.maxHeight = "none";
              faceImg.style.objectFit = "fill";
              if (cropBadge) cropBadge.style.display = "block";
            } else {
              // Full frame fallback
              faceImg.src = frameB64;
              faceImg.style.position = "absolute";
              faceImg.style.width = "100%";
              faceImg.style.height = "100%";
              faceImg.style.left = "0px";
              faceImg.style.top = "0px";
              faceImg.style.maxWidth = "100%";
              faceImg.style.maxHeight = "100%";
              faceImg.style.objectFit = "cover";
              if (cropBadge) cropBadge.style.display = "none";
            }
            faceImg.style.display = "block";
            if (facePlaceholder) facePlaceholder.style.display = "none";
          }

          if (nodeSession.emotion_tilt !== undefined) {
            const tilt = nodeSession.emotion_tilt;
            if (tiltNum) {
              tiltNum.textContent = tilt.toFixed(1);
            }
            if (topVal) topVal.textContent = (nodeSession.emotion_top || "neutral").toUpperCase();
            if (euphoriaVal && nodeSession.emotion_euphoria !== undefined) {
              euphoriaVal.textContent = `${nodeSession.emotion_euphoria.toFixed(0)}%`;
            }

            let tiltColor = "#34d399";
            let tiltText = "CALM";
            if (tilt >= 80) { tiltColor = "#ef4444"; tiltText = "🔥 FULL TILT"; }
            else if (tilt >= 60) { tiltColor = "#f59e0b"; tiltText = "HEATING UP"; }
            else if (tilt >= 40) { tiltColor = "#38bdf8"; tiltText = "CAUTION"; }

            if (tiltNum) tiltNum.style.color = tiltColor;
            if (tiltPill) {
              tiltPill.textContent = tiltText;
              tiltPill.style.color = tiltColor;
              tiltPill.style.background = `${tiltColor}22`;
            }

            if (nodeSession.is_tilting) {
              document.getElementById(`node-${node.id}`)?.classList.add("spiking");
              this.pulseWiresFromNode(node.id);
            } else {
              document.getElementById(`node-${node.id}`)?.classList.remove("spiking");
            }
          }

          if (nodeSession.emotion_valence !== undefined) {
            if (valenceVal) valenceVal.textContent = (nodeSession.emotion_valence > 0 ? "+" : "") + nodeSession.emotion_valence.toFixed(2);
            if (valenceInd) {
              const pct = Math.max(5, Math.min(95, ((nodeSession.emotion_valence + 1.0) / 2.0) * 100));
              valenceInd.style.left = `${pct}%`;
              valenceInd.style.background = nodeSession.emotion_valence >= 0 ? "#34d399" : "#ef4444";
            }
          }

          const modelSelect = document.getElementById(`model-select-${node.id}`);
          if (modelSelect && nodeSession.model && modelSelect.value !== nodeSession.model) {
            modelSelect.value = nodeSession.model;
          }

          const latencyTag = document.getElementById(`face-latency-tag-${node.id}`);
          const latency = nodeSession.latency_ms !== undefined ? nodeSession.latency_ms : nodeSession.emotion_latency_ms;
          if (latencyTag && latency !== undefined && latency > 0) {
            latencyTag.textContent = `${latency.toFixed(1)} ms`;
          }

          if (barsBox) {
            const barColors = {
              happiness: "#10b981",
              joy: "#10b981",
              surprise: "#38bdf8",
              shock: "#38bdf8",
              neutral: "#64748b",
              contempt: "#f59e0b",
              anger: "#ef4444",
              rage: "#ef4444",
              fear: "#a855f7",
              disgust: "#84cc16",
              sadness: "#6366f1",
              despair: "#6366f1",
            };

            const isLogitsMode = (node.properties?.display_mode === "logits");
            if (isLogitsMode && nodeSession.raw_logits && Object.keys(nodeSession.raw_logits).length > 0) {
              const logitsObj = nodeSession.raw_logits;
              const values = Object.values(logitsObj).map(v => Number(v) || 0.0);
              const maxAbs = Math.max(1.0, ...values.map(Math.abs));

              barsBox.innerHTML = Object.entries(logitsObj).map(([emo, rawVal]) => {
                const val = Number(rawVal) || 0.0;
                const isPos = val >= 0;
                const pct = Math.min(50, Math.round((Math.abs(val) / maxAbs) * 50));
                const leftPos = isPos ? 50 : (50 - pct);
                const color = barColors[emo] || '#38bdf8';
                const sign = val > 0 ? "+" : "";
                return `
                  <div class="cv-prob-row" style="margin:2px 0;">
                    <span class="cv-prob-label" style="font-size:10px;">${emo}</span>
                    <div class="cv-prob-track" style="position:relative; background:rgba(255,255,255,0.08); height:6px; border-radius:3px; overflow:hidden;">
                      <div style="position:absolute; left:50%; top:0; bottom:0; width:1px; background:rgba(255,255,255,0.35); z-index:2;"></div>
                      <div class="cv-prob-fill" style="position:absolute; left:${leftPos}%; width:${pct}%; height:100%; background:${color}; border-radius:2px; transition:all 0.2s ease;"></div>
                    </div>
                    <span class="cv-prob-pct" style="color:${color}; font-family:monospace; width:48px; font-size:10px; font-weight:700;">${sign}${val.toFixed(2)}</span>
                  </div>
                `;
              }).join("");
            } else if (nodeSession.emotion_distribution) {
              const dist = nodeSession.emotion_distribution;
              barsBox.innerHTML = Object.entries(dist).map(([emo, val]) => `
                <div class="cv-prob-row">
                  <span class="cv-prob-label">${emo}</span>
                  <div class="cv-prob-track"><div class="cv-prob-fill" style="width: ${Math.round(val * 100)}%; background: ${barColors[emo] || '#38bdf8'};"></div></div>
                  <span class="cv-prob-pct" style="color: ${barColors[emo] || '#38bdf8'};">${Math.round(val * 100)}%</span>
                </div>
              `).join("");
            }
          }
        } else if (node.type === "GamblingLedgerNode") {
          const ledger = nodeSession.gambling_ledger || {};
          const pnlEl = document.getElementById(`ledger-pnl-${node.id}`);
          const chaseBadge = document.getElementById(`ledger-chase-badge-${node.id}`);
          const winrateEl = document.getElementById(`ledger-winrate-${node.id}`);
          const streakEl = document.getElementById(`ledger-streak-${node.id}`);
          const rtpEl = document.getElementById(`ledger-rtp-${node.id}`);
          const drawdownEl = document.getElementById(`ledger-drawdown-${node.id}`);
          const canvas = document.getElementById(`ledger-canvas-${node.id}`);

          const netPnl = ledger.net_pnl !== undefined ? ledger.net_pnl : 0.0;
          if (pnlEl) {
            pnlEl.textContent = (netPnl >= 0 ? "+$" : "-$") + Math.abs(netPnl).toLocaleString('en-US', { minimumFractionDigits: 2 });
            pnlEl.className = `ledger-pnl-val ${netPnl >= 0 ? 'pnl-positive' : 'pnl-negative'}`;
          }

          if (chaseBadge) {
            if (ledger.is_chasing_losses) {
              chaseBadge.style.display = "block";
              this.pulseWiresFromNode(node.id);
            } else {
              chaseBadge.style.display = "none";
            }
          }

          if (winrateEl) winrateEl.textContent = `${(ledger.winrate_pct || 0).toFixed(1)}%`;
          if (streakEl) {
            const streak = ledger.current_streak || 0;
            streakEl.textContent = streak > 0 ? `🔥 +${streak} Wins` : (streak < 0 ? `💀 ${Math.abs(streak)} Losses` : "0");
            streakEl.style.color = streak > 0 ? "#34d399" : (streak < 0 ? "#f43f5e" : "#f8fafc");
          }
          if (rtpEl) rtpEl.textContent = `${(ledger.experienced_rtp || 100).toFixed(1)}%`;
          if (drawdownEl) {
            drawdownEl.textContent = `-$${(ledger.drawdown_dollars || 0).toFixed(2)} (${(ledger.drawdown_pct || 0).toFixed(1)}%)`;
          }

          if (canvas && ledger.pnl_history) {
            this.drawPnlSparkline(canvas, ledger.pnl_history);
          }
        } else if (node.type === "CVTransformerNode") {
          const topValEl = document.getElementById(`cv-top-val-${node.id}`);
          const latencyTag = document.getElementById(`cv-latency-tag-${node.id}`);
          const thumbImg = document.getElementById(`cv-thumb-${node.id}`);
          const thumbPlaceholder = document.getElementById(`cv-thumb-placeholder-${node.id}`);
          const barsBox = document.getElementById(`cv-bars-${node.id}`);

          const frameB64 = nodeSession.cv_thumbnail_b64 || nodeSession.stream_frame_b64;
          if (thumbImg && frameB64) {
            thumbImg.src = frameB64;
            thumbImg.style.display = "block";
            if (thumbPlaceholder) thumbPlaceholder.style.display = "none";
          }

          if (nodeSession.cv_top_label) {
            if (topValEl) {
              topValEl.textContent = `${nodeSession.cv_top_label.toUpperCase()} (${(nodeSession.cv_confidence * 100).toFixed(0)}%)`;
              topValEl.style.color = nodeSession.cv_confidence >= 0.70 ? "#34d399" : "#38bdf8";
            }
          } else if (frameB64) {
            if (topValEl) {
              topValEl.textContent = "PROCESSING...";
              topValEl.style.color = "#38bdf8";
            }
          }

          if (latencyTag && nodeSession.cv_latency_ms) {
            latencyTag.textContent = `⚡ ${nodeSession.cv_latency_ms.toFixed(1)} ms`;
          }

          if (barsBox && nodeSession.cv_probabilities && Object.keys(nodeSession.cv_probabilities).length > 0) {
            const sorted = Object.entries(nodeSession.cv_probabilities).sort((a, b) => b[1] - a[1]).slice(0, 3);
            barsBox.innerHTML = sorted.map(([label, prob]) => `
              <div class="cv-prob-row">
                <span class="cv-prob-label">${label}</span>
                <div class="cv-prob-track"><div class="cv-prob-fill" style="width: ${Math.round(prob * 100)}%;"></div></div>
                <span class="cv-prob-pct">${Math.round(prob * 100)}%</span>
              </div>
            `).join("");
          }

          if (nodeSession.cv_confidence >= 0.75) {
            this.pulseWiresFromNode(node.id);
          }
        } else if (node.type === "GateEvaluatorNode") {
          const scoreEl = document.getElementById(`gate-score-${node.id}`);
          const statusEl = document.getElementById(`gate-status-${node.id}`);
          const score = nodeSession.spike_ratio > 3.0 || nodeSession.audio_spike ? 8 : 1;

          if (scoreEl) scoreEl.textContent = score;
          if (statusEl) {
            if (score >= 4) {
              statusEl.textContent = "TRIGGER READY";
              statusEl.classList.add("active");
              this.pulseWiresFromNode(node.id);
            } else {
              statusEl.textContent = "MONITORING";
              statusEl.classList.remove("active");
            }
          }
        }
      });
    }

    pulseWiresFromNode(nodeId) {
      this.wires.forEach((w) => {
        if (w.from.startsWith(`${nodeId}:`)) {
          const pathEl = document.getElementById(`wire-${w.id}`);
          if (pathEl) {
            pathEl.classList.add("wire-pulse");
            setTimeout(() => pathEl.classList.remove("wire-pulse"), 700);
          }
        }
      });
    }

    drawNeonWaveform(canvas, waveform) {
      const ctx = canvas.getContext("2d");
      const w = canvas.width;
      const h = canvas.height;

      ctx.clearRect(0, 0, w, h);

      ctx.beginPath();
      ctx.strokeStyle = "#38bdf8";
      ctx.lineWidth = 2;
      ctx.shadowBlur = 8;
      ctx.shadowColor = "#38bdf8";

      const sliceWidth = w / waveform.length;
      let x = 0;

      for (let i = 0; i < waveform.length; i++) {
        const v = waveform[i]; // in [-1.0, 1.0]
        const y = (h / 2) + (v * (h / 2.2));

        if (i === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
        x += sliceWidth;
      }

      ctx.stroke();
      ctx.shadowBlur = 0;
    }

    drawPnlSparkline(canvas, history) {
      const ctx = canvas.getContext("2d");
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);

      // Draw dashed baseline zero
      ctx.strokeStyle = "rgba(255, 255, 255, 0.15)";
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(0, h / 2);
      ctx.lineTo(w, h / 2);
      ctx.stroke();
      ctx.setLineDash([]);

      if (!history || history.length < 2) return;

      const pnlVals = history.map(d => typeof d === "object" ? d.pnl : d);
      const maxPnl = Math.max(...pnlVals, 100);
      const minPnl = Math.min(...pnlVals, -100);
      const range = Math.max(1, maxPnl - minPnl);

      const latestPnl = pnlVals[pnlVals.length - 1];
      const strokeColor = latestPnl >= 0 ? "#10b981" : "#f43f5e";

      ctx.beginPath();
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 2;
      ctx.shadowBlur = 6;
      ctx.shadowColor = strokeColor;

      const step = w / (pnlVals.length - 1);
      pnlVals.forEach((p, idx) => {
        const x = idx * step;
        const norm = (p - minPnl) / range;
        const y = h - (norm * (h - 8) + 4);
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
      ctx.shadowBlur = 0;
    }

    openStreamCalibrator() {
      let modal = document.getElementById("stream-roi-calibrator-modal");
      if (!modal) {
        modal = document.createElement("div");
        modal.id = "stream-roi-calibrator-modal";
        modal.innerHTML = `
          <div class="calibrator-window">
            <div class="calibrator-header">
              <div style="font-weight: 800; font-size: 13px; color: #38bdf8; display: flex; align-items: center; gap: 8px;">
                <span>🎯 Live Stream Content ROI Calibrator</span>
                <span style="font-size: 10px; color: #94a3b8; font-weight: 400;">(Drag & resize boxes over stream to emphasize content)</span>
              </div>
              <button class="studio-btn" id="calibrator-close-btn" style="padding: 4px 10px; font-size: 11px;">✕ Close</button>
            </div>
            <div class="calibrator-body">
              <div class="calibrator-canvas-wrap" id="calibrator-canvas-container">
                <img id="calibrator-stream-frame" class="roi-live-img" alt="Stream Frame" />
                <div class="roi-placeholder-text" id="calibrator-placeholder">Waiting for stream frame...</div>
              </div>
              <div class="calibrator-sidebar">
                <div style="font-size: 11px; font-weight: 700; color: #e2e8f0; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 4px;">
                  Active Content Regions
                </div>
                <div id="calibrator-box-list" style="display: flex; flex-direction: column; gap: 8px;"></div>
                <div style="margin-top: auto; display: flex; gap: 8px;">
                  <button class="studio-btn primary" id="calibrator-apply-btn" style="flex: 1; text-align: center;">💾 Apply to DAG</button>
                </div>
              </div>
            </div>
          </div>
        `;
        document.body.appendChild(modal);

        modal.querySelector("#calibrator-close-btn")?.addEventListener("click", () => {
          modal.classList.remove("active");
        });
        modal.querySelector("#calibrator-apply-btn")?.addEventListener("click", () => {
          this.syncGraph();
          this.showToast("All stream content ROIs saved and synced to pipeline!");
          modal.classList.remove("active");
        });
      }

      modal.classList.add("active");

      // Update frame preview from latest stream telemetry
      const targetCh = (this.selectedChannel || window.activeTab || "").toLowerCase();
      const frameEl = modal.querySelector("#calibrator-stream-frame");
      const placeEl = modal.querySelector("#calibrator-placeholder");
      const primarySession = window.latestTelemetry?.sessions?.[targetCh] || Object.values(window.latestTelemetry?.sessions || {})[0];
      const frameB64 = primarySession?.stream_frame_b64 || primarySession?.cv_thumbnail_b64;
      if (frameB64 && frameEl) {
        frameEl.src = frameB64;
        if (placeEl) placeEl.style.display = "none";
      }

      // Populate boxes
      const canvasContainer = modal.querySelector("#calibrator-canvas-container");
      canvasContainer.querySelectorAll(".roi-draggable-box").forEach(b => b.remove());

      const listEl = modal.querySelector("#calibrator-box-list");
      listEl.innerHTML = "";

      const registeredRois = [];

      this.nodes.forEach(n => {
        if (n.type === "VideoCropNode") {
          registeredRois.push({
            nodeId: n.id,
            paramKey: "roi",
            label: n.title || "Video Cropper",
            color: "#f43f5e",
            roi: n.properties?.roi || { x: 0.02, y: 0.05, w: 0.22, h: 0.28 },
          });
        }
      });

      registeredRois.forEach(item => {
        this.setupDraggableRoiBox(canvasContainer, item.roi, item.color, item.label, (newRoi, isFinal) => {
          item.roi = newRoi;
          const node = this.nodes.get(item.nodeId);
          if (node) {
            if (item.subKey) {
              node.properties.rois = node.properties.rois || {};
              node.properties.rois[item.subKey] = newRoi;
            } else {
              node.properties[item.paramKey] = newRoi;
            }
          }
          if (isFinal) {
            this.syncNodeParamDebounced(item.nodeId, item.paramKey, newRoi);
            const inNodeCtrl = this.nodeRoiControllers.get(`${item.nodeId}:${item.subKey || (item.paramKey.replace('_roi', ''))}`);
            if (inNodeCtrl) inNodeCtrl.update(newRoi);
          }
        });

        const row = document.createElement("div");
        row.className = "calibrator-box-toggle";
        row.innerHTML = `
          <div style="display: flex; align-items: center; gap: 8px;">
            <div style="width: 10px; height: 10px; border-radius: 2px; background: ${item.color};"></div>
            <span style="color: #f1f5f9; font-weight: 700;">${item.label}</span>
          </div>
          <span style="font-family: monospace; font-size: 10px; color: #94a3b8;">${Math.round(item.roi.w * 100)}x${Math.round(item.roi.h * 100)}%</span>
        `;
        listEl.appendChild(row);
      });
    }

    /* -------------------------------------------------------------
       Folder View of Clips Modal
       ------------------------------------------------------------- */
    async openFolderViewModal(nodeId) {
      const node = this.nodes.get(nodeId);
      const folderName = node?.properties?.folder_name || "Highlight Reels";
      const folderDate = node?.properties?.date || new Date().toISOString().split("T")[0];

      let modal = document.getElementById("clip-folder-modal");
      if (!modal) {
        modal = document.createElement("div");
        modal.id = "clip-folder-modal";
        modal.className = "folder-view-modal";
        modal.innerHTML = `
          <div class="folder-view-window">
            <div class="folder-view-header">
              <div class="folder-view-title-group">
                <span style="font-size: 24px;">📂</span>
                <div>
                  <div class="folder-view-title" id="fview-title">${folderName}</div>
                  <div class="folder-view-meta">
                    <span class="fview-pill fview-date" id="fview-date-tag">📅 ${folderDate}</span>
                    <span class="fview-pill fview-count" id="fview-stats-tag">0 clips</span>
                    <span class="fview-pill fview-renderers" id="fview-renderers-tag" style="display: none;"></span>
                  </div>
                </div>
              </div>
              <div class="folder-view-controls">
                <input type="text" id="fview-search-input" class="fview-search" placeholder="🔍 Filter clips..." />
                <button class="studio-btn" id="fview-refresh-btn" title="Refresh clips">🔄 Refresh</button>
                <button class="studio-btn" id="fview-close-btn" style="padding: 6px 12px; font-weight: 800;">✕</button>
              </div>
            </div>

            <!-- Inline Clip Player Area (hidden until a clip is played) -->
            <div class="folder-active-player" id="fview-active-player" style="display: none;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-size: 13px; font-weight: 700; color: #fed7aa;" id="fview-player-title">Now Playing</span>
                <button class="studio-btn" id="fview-player-close" style="font-size: 10px; padding: 2px 8px;">✕ Close Player</button>
              </div>
              <video id="fview-video" controls autoplay playsinline style="width: 100%; max-height: 420px; border-radius: 8px; background: #000; outline: none; box-shadow: 0 8px 24px rgba(0,0,0,0.7);"></video>
            </div>

            <div class="folder-view-body" id="fview-clips-grid">
              <div class="fview-loading">Loading folder clips...</div>
            </div>
          </div>
        `;
        document.body.appendChild(modal);

        modal.querySelector("#fview-close-btn")?.addEventListener("click", () => {
          modal.classList.remove("active");
          const v = modal.querySelector("#fview-video");
          if (v) { v.pause(); v.src = ""; }
        });

        modal.querySelector("#fview-player-close")?.addEventListener("click", () => {
          const p = modal.querySelector("#fview-active-player");
          const v = modal.querySelector("#fview-video");
          if (p) p.style.display = "none";
          if (v) { v.pause(); v.src = ""; }
        });

        modal.addEventListener("click", (e) => {
          if (e.target === modal) {
            modal.classList.remove("active");
            const v = modal.querySelector("#fview-video");
            if (v) { v.pause(); v.src = ""; }
          }
        });
      }

      // Update header details for this specific folder node
      modal.querySelector("#fview-title").textContent = folderName;
      modal.querySelector("#fview-date-tag").textContent = `📅 ${folderDate}`;

      // Check wired renderers
      const wiredRenderers = [];
      this.wires.forEach(w => {
        if (w.to.split(":")[0] === nodeId) {
          const srcId = w.from.split(":")[0];
          const srcNode = this.nodes.get(srcId);
          if (srcNode && srcNode.type === "HardwareRenderNode") {
            wiredRenderers.push(srcNode.title || srcId);
          }
        }
      });
      const rendTag = modal.querySelector("#fview-renderers-tag");
      if (rendTag) {
        if (wiredRenderers.length > 0) {
          rendTag.textContent = `🔌 ${wiredRenderers.length} Renderers (${wiredRenderers.join(", ")})`;
          rendTag.style.display = "inline-flex";
        } else {
          rendTag.style.display = "none";
        }
      }

      modal.classList.add("active");

      // Load clips from backend API
      const loadClips = async () => {
        const grid = modal.querySelector("#fview-clips-grid");
        if (!grid) return;
        grid.innerHTML = '<div class="fview-loading">Loading folder clips...</div>';

        try {
          const res = await fetch(`/api/folders/${encodeURIComponent(nodeId)}/clips`);
          let clips = [];
          if (res.ok) {
            clips = await res.json();
          } else {
            // Fallback: fetch all and filter client side
            const allRes = await fetch("/api/clips?limit=100");
            if (allRes.ok) {
              const allClips = await allRes.json();
              clips = allClips.filter(c => c.folder_id === nodeId);
            }
          }

          modal.querySelector("#fview-stats-tag").textContent = `${clips.length} clip${clips.length !== 1 ? "s" : ""}`;

          const renderGrid = (filterTerm = "") => {
            const term = filterTerm.trim().toLowerCase();
            const filtered = clips.filter(c => {
              if (!term) return true;
              return (
                (c.suggested_title && c.suggested_title.toLowerCase().includes(term)) ||
                (c.channel_name && c.channel_name.toLowerCase().includes(term)) ||
                (c.id && c.id.toLowerCase().includes(term))
              );
            });

            if (filtered.length === 0) {
              grid.innerHTML = `
                <div class="fview-empty">
                  <div style="font-size: 42px; margin-bottom: 8px;">📂</div>
                  <div style="font-weight: 700; font-size: 14px; color: #cbd5e1; margin-bottom: 4px;">
                    ${clips.length === 0 ? "No Clips In This Folder Yet" : "No Clips Matching Filter"}
                  </div>
                  <div style="font-size: 11px; color: #64748b; max-width: 380px; text-align: center; line-height: 1.5;">
                    ${clips.length === 0 ? "Route the finished output of any Hardware Video Renderer into this Clip Folder node. Triggered highlight clips will automatically be stored here." : "Try clearing your search query to see all clips."}
                  </div>
                </div>
              `;
              return;
            }

            grid.innerHTML = filtered.map(c => {
              const duration = c.duration_seconds ? `${Number(c.duration_seconds).toFixed(1)}s` : "--";
              const score = c.heuristic_score || 0;
              const dateStr = c.created_at ? new Date(c.created_at).toLocaleString() : "";
              const thumb = c.thumbnail_url || c.video_url;
              return `
                <div class="fview-clip-card" data-id="${c.id}">
                  <div class="fview-card-thumb">
                    <img src="${thumb}" alt="${c.suggested_title || 'Clip'}" onerror="this.src='/static/icons/video_placeholder.png'" />
                    <div class="fview-play-badge" data-video="${c.video_url}" data-title="${c.suggested_title || 'Stream Clip'}">▶ Play</div>
                    <span class="fview-dur-pill">${duration}</span>
                    <span class="fview-score-pill">★ ${score}</span>
                  </div>
                  <div class="fview-card-body">
                    <div class="fview-clip-title" title="${c.suggested_title || 'Stream Clip'}">${c.suggested_title || 'Stream Highlight Clip'}</div>
                    <div class="fview-clip-meta">
                      <span class="fview-ch-badge">#${c.channel_name || 'stream'}</span>
                      <span class="fview-date">${dateStr}</span>
                    </div>
                    <div class="fview-card-actions">
                      <button class="fview-action-btn play-btn" data-video="${c.video_url}" data-title="${c.suggested_title || 'Stream Clip'}">▶ Watch</button>
                      <a href="${c.video_url}" download class="fview-action-btn download-btn">⬇ MP4</a>
                      <button class="fview-action-btn delete-btn" data-id="${c.id}" title="Delete clip">🗑</button>
                    </div>
                  </div>
                </div>
              `;
            }).join("");

            // Play button handlers
            grid.querySelectorAll(".play-btn, .fview-play-badge").forEach(btn => {
              btn.addEventListener("click", () => {
                const videoUrl = btn.getAttribute("data-video");
                const clipTitle = btn.getAttribute("data-title");
                const player = modal.querySelector("#fview-active-player");
                const videoEl = modal.querySelector("#fview-video");
                const titleEl = modal.querySelector("#fview-player-title");
                if (player && videoEl && videoUrl) {
                  titleEl.textContent = `▶ ${clipTitle}`;
                  videoEl.src = videoUrl;
                  player.style.display = "block";
                  videoEl.play().catch(() => {});
                  player.scrollIntoView({ behavior: "smooth" });
                }
              });
            });

            // Delete clip handlers
            grid.querySelectorAll(".delete-btn").forEach(btn => {
              btn.addEventListener("click", async (e) => {
                e.stopPropagation();
                const cid = btn.getAttribute("data-id");
                if (!cid) return;
                if (!confirm("Are you sure you want to delete this clip from the folder and disk?")) return;
                try {
                  const delRes = await fetch(`/api/clips/${encodeURIComponent(cid)}`, { method: "DELETE" });
                  if (delRes.ok) {
                    this.showToast("Clip deleted successfully");
                    await loadClips();
                  } else {
                    alert("Failed to delete clip");
                  }
                } catch (err) {
                  console.error("Delete clip error:", err);
                }
              });
            });
          };

          renderGrid();

          // Hook up search filter input
          const searchInput = modal.querySelector("#fview-search-input");
          if (searchInput) {
            searchInput.value = "";
            searchInput.oninput = (e) => {
              renderGrid(e.target.value);
            };
          }
        } catch (e) {
          console.error("Error loading folder clips:", e);
          grid.innerHTML = `<div class="fview-empty" style="color: #ef4444;">Failed to load clips: ${e.message}</div>`;
        }
      };

      // Refresh button
      const refreshBtn = modal.querySelector("#fview-refresh-btn");
      if (refreshBtn) {
        refreshBtn.onclick = () => {
          loadClips();
        };
      }

      loadClips();
    }

    /* -------------------------------------------------------------
       Floating Toolbar & Spawn Palette
       ------------------------------------------------------------- */
    initToolbar() {
      const tb = document.getElementById("studio-toolbar");
      if (!tb) return;

      document.getElementById("btn-add-node")?.addEventListener("click", () => {
        this.openSpawnPalette(window.innerWidth / 2 - 130, 160);
      });

      document.getElementById("btn-calibrate-rois")?.addEventListener("click", () => {
        this.openStreamCalibrator();
      });

      document.getElementById("btn-sync-graph")?.addEventListener("click", () => {
        this.syncGraph();
      });

      document.getElementById("btn-auto-layout")?.addEventListener("click", () => {
        this.autoLayout();
      });

      document.getElementById("btn-reset-view")?.addEventListener("click", () => {
        this.panX = 120;
        this.panY = 100;
        this.scale = 0.95;
        this.updateTransform();
      });
    }

    initSpawnPalette() {
      const palette = document.getElementById("node-spawn-palette");
      const list = palette?.querySelector(".spawn-list");
      const search = palette?.querySelector(".spawn-search");
      const clearBtn = palette?.querySelector(".spawn-clear-btn");
      const pills = palette?.querySelectorAll(".spawn-pill");
      if (!palette || !list) return;

      this.currentPaletteFilterTag = "all";
      this.pendingWireAutoConnect = null;

      // Handle Filter Pills
      pills?.forEach((pill) => {
        pill.addEventListener("click", () => {
          pills.forEach((p) => p.classList.remove("active"));
          pill.classList.add("active");
          this.currentPaletteFilterTag = pill.getAttribute("data-filter") || "all";
          this.renderSpawnItems(search ? search.value : "");
        });
      });

      // Clear search button
      clearBtn?.addEventListener("click", () => {
        if (search) search.value = "";
        this.currentPaletteFilterTag = "all";
        pills?.forEach((p) => p.classList.toggle("active", p.getAttribute("data-filter") === "all"));
        this.renderSpawnItems("");
        search?.focus();
      });

      this.renderSpawnItems = (filterText = "") => {
        list.innerHTML = "";
        const lower = filterText.toLowerCase().trim();
        const activeTag = this.currentPaletteFilterTag || "all";

        this.nodeCatalog.forEach((item) => {
          // 1. Tag / Category Pill Filter
          if (activeTag !== "all") {
            if (activeTag.startsWith("in:")) {
              const reqIn = activeTag.slice(3);
              if (!item.inputs_accepted || !item.inputs_accepted.includes(reqIn)) return;
            } else if (activeTag.startsWith("out:")) {
              const reqOut = activeTag.slice(4);
              if (!item.outputs_produced || !item.outputs_produced.includes(reqOut)) return;
            } else if (activeTag.includes("stage:")) {
              const stages = activeTag.split(",").map((s) => s.replace("stage:", "").trim());
              if (!stages.includes(item.stage)) return;
            }
          }

          // 2. Search Text Filter (supports keywords, tags, in:*, out:*, stage:*)
          if (lower) {
            if (lower.startsWith("in:")) {
              const reqIn = lower.slice(3);
              if (!item.inputs_accepted || !item.inputs_accepted.includes(reqIn)) return;
            } else if (lower.startsWith("out:")) {
              const reqOut = lower.slice(4);
              if (!item.outputs_produced || !item.outputs_produced.includes(reqOut)) return;
            } else if (lower.startsWith("stage:")) {
              const reqStage = lower.slice(6);
              if (item.stage !== reqStage) return;
            } else {
              const matchTitle = item.title.toLowerCase().includes(lower);
              const matchDesc = item.desc.toLowerCase().includes(lower);
              const matchType = item.type.toLowerCase().includes(lower);
              const matchTags = (item.tags || []).some((t) => t.toLowerCase().includes(lower));
              if (!matchTitle && !matchDesc && !matchType && !matchTags) return;
            }
          }

          const getPortColor = (type) => {
            if (this.portTypes && this.portTypes[type]?.color) {
              return this.portTypes[type].color;
            }
            const fallbackColors = {
              video: "#f43f5e",
              audio: "#38bdf8",
              chat: "#a855f7",
              trigger: "#eab308",
              scalar: "#10b981",
              text: "#6366f1",
              clip: "#f97316"
            };
            return fallbackColors[type] || "#94a3b8";
          };

          // Format I/O Dot Matrix Badges with explicit INS / OUTS sections
          const inDots = (item.inputs_accepted && item.inputs_accepted.length > 0)
            ? item.inputs_accepted.map((t) => {
                const col = getPortColor(t);
                const isMatch = lower && (lower.includes(t) || lower === `in:${t}`);
                const matchCls = isMatch ? " io-match" : "";
                return `<span class="io-group${matchCls}" title="Input: ${t}"><span class="io-dot" style="background:${col}; box-shadow:0 0 5px ${col}99;"></span><span class="io-label">${t}</span></span>`;
              }).join(" ")
            : `<span class="io-none">none</span>`;

          const outDots = (item.outputs_produced && item.outputs_produced.length > 0)
            ? item.outputs_produced.map((t) => {
                const col = getPortColor(t);
                const isMatch = lower && (lower.includes(t) || lower === `out:${t}`);
                const matchCls = isMatch ? " io-match" : "";
                return `<span class="io-group${matchCls}" title="Output: ${t}"><span class="io-dot" style="background:${col}; box-shadow:0 0 5px ${col}99;"></span><span class="io-label">${t}</span></span>`;
              }).join(" ")
            : `<span class="io-none">none</span>`;

          const row = document.createElement("div");
          row.setAttribute("class", "spawn-item");
          row.innerHTML = `
            <div class="spawn-item-header">
              <span style="font-size: 14px;">${item.icon}</span>
              <span class="spawn-item-title">${item.title}</span>
              <span class="spawn-item-stage">${item.stage}</span>
            </div>
            <div class="spawn-item-desc">${item.desc}</div>
            <div class="spawn-item-io">
              <div class="io-block io-block-in">
                <span class="io-section-label">INS:</span>
                <div class="io-port-chips">${inDots}</div>
              </div>
              <span class="io-arrow">➔</span>
              <div class="io-block io-block-out">
                <span class="io-section-label">OUTS:</span>
                <div class="io-port-chips">${outDots}</div>
              </div>
            </div>
          `;

          row.addEventListener("click", () => {
            const worldPos = this.screenToWorld(
              parseInt(palette.style.left) + 330,
              parseInt(palette.style.top) + 40
            );
            const newNode = this.addNode(item.type, Math.round(worldPos.x), Math.round(worldPos.y));

            // Context-sensitive wire auto-connect
            if (this.pendingWireAutoConnect && newNode) {
              const { fromNodeId, fromPortId, fromType } = this.pendingWireAutoConnect;
              const compatibleInput = (newNode.inputs || []).find((p) => p.type === fromType);
              if (compatibleInput) {
                this.createWire(`${fromNodeId}:${fromPortId}`, `${newNode.id}:${compatibleInput.id}`, fromType);
              }
              this.pendingWireAutoConnect = null;
            }

            this.closeSpawnPalette();
          });
          list.appendChild(row);
        });

        if (list.children.length === 0) {
          const emptyRow = document.createElement("div");
          emptyRow.style.padding = "20px 10px";
          emptyRow.style.textAlign = "center";
          emptyRow.style.color = "#64748b";
          emptyRow.style.fontSize = "11px";
          emptyRow.innerHTML = `No matching nodes found for "<strong>${filterText || activeTag}</strong>"`;
          list.appendChild(emptyRow);
        }
      };

      this.renderSpawnItems();

      search?.addEventListener("input", (e) => {
        this.renderSpawnItems(e.target.value);
      });
    }

    openSpawnPalette(clientX, clientY, filterTag = "all", autoConnect = null) {
      const p = document.getElementById("node-spawn-palette");
      if (!p) return;

      this.pendingWireAutoConnect = autoConnect;
      this.currentPaletteFilterTag = filterTag || "all";

      // Sync active filter pill UI
      const pills = p.querySelectorAll(".spawn-pill");
      pills.forEach((pill) => {
        const pFilter = pill.getAttribute("data-filter");
        pill.classList.toggle("active", pFilter === this.currentPaletteFilterTag);
      });

      // Keep within window bounds
      const menuWidth = 330;
      const menuHeight = 420;
      const clampedX = Math.min(clientX, window.innerWidth - menuWidth - 20);
      const clampedY = Math.min(clientY, window.innerHeight - menuHeight - 20);

      p.style.left = `${Math.max(10, clampedX)}px`;
      p.style.top = `${Math.max(10, clampedY)}px`;
      p.classList.add("active");

      const search = p.querySelector(".spawn-search");
      if (search) {
        search.value = "";
        search.focus();
      }
      if (typeof this.renderSpawnItems === "function") {
        this.renderSpawnItems("");
      }
    }

    closeSpawnPalette() {
      this.pendingWireAutoConnect = null;
      document.getElementById("node-spawn-palette")?.classList.remove("active");
    }

    addNode(type, x = 200, y = 200) {
      const catalogItem = this.nodeCatalog.find((c) => c.type === type);
      const newId = `node_${type.toLowerCase().replace("node", "")}_${Date.now().toString(36)}`;

      let inputs = [];
      let outputs = [];

      if (type === "StreamSourceNode") {
        outputs = [
          { id: "video", name: "Video Stream", type: "video" },
          { id: "audio", name: "Audio Stream", type: "audio" },
          { id: "chat", name: "Chat Stream", type: "chat" },
        ];
      } else if (type === "VideoCropNode") {
        inputs = [{ id: "video_in", name: "Full Video In", type: "video" }];
        outputs = [{ id: "video_out", name: "Cropped Video", type: "video" }];
      } else if (type === "ImageScaleNode" || type === "ResolutionModifierNode") {
        type = "ImageScaleNode";
        inputs = [{ id: "video_in", name: "Video In", type: "video" }];
        outputs = [{ id: "video_out", name: "Scaled Video", type: "video" }];
      } else if (type === "AudioMonitorNode") {
        inputs = [{ id: "audio_in", name: "Audio In", type: "audio" }];
        outputs = [
          { id: "spike_trigger", name: "Audio Spike", type: "trigger" },
          { id: "live_db", name: "Current dB", type: "scalar" },
        ];
      } else if (type === "ChatVelocityNode") {
        inputs = [{ id: "chat_in", name: "Chat In", type: "chat" }];
        outputs = [
          { id: "spike_trigger", name: "Chat Spike", type: "trigger" },
          { id: "velocity", name: "Messages/s", type: "scalar" },
        ];
      } else if (type === "OCRVisionNode") {
        inputs = [{ id: "video_in", name: "Video In", type: "video" }];
        outputs = [
          { id: "ocr_trigger", name: "Win Trigger", type: "trigger" },
          { id: "multiplier", name: "Multiplier", type: "scalar" },
        ];
      } else if (type === "CVTransformerNode") {
        inputs = [{ id: "video_in", name: "Video In", type: "video" }];
        outputs = [
          { id: "spike_trigger", name: "Vision Trigger", type: "trigger" },
          { id: "confidence", name: "Top Confidence", type: "scalar" },
          { id: "top_label", name: "Top Class", type: "text" },
        ];
      } else if (type === "FacecamEmotionNode" || type === "EmotionFERPlusNode") {
        inputs = [{ id: "video_in", name: "Video In", type: "video" }];
        outputs = [
          { id: "tilt_trigger", name: "Tilt Trigger", type: "trigger" },
          { id: "euphoria_trigger", name: "Euphoria Trigger", type: "trigger" },
          { id: "tilt_score", name: "Tilt Index", type: "scalar", min: 0.0, max: 100.0, step: 1.0, unit: "pts" },
          { id: "euphoria_score", name: "Euphoria Index", type: "scalar", min: 0.0, max: 100.0, step: 1.0, unit: "pts" },
          { id: "valence", name: "Valence", type: "scalar", min: -1.0, max: 1.0, step: 0.05, unit: "" },
          { id: "arousal", name: "Arousal", type: "scalar", min: 0.0, max: 1.0, step: 0.05, unit: "" },
          { id: "happy", name: "Happy Metric", type: "scalar", min: 0.0, max: 1.0, step: 0.01, unit: "%" },
          { id: "angry", name: "Angry / Rage Metric", type: "scalar", min: 0.0, max: 1.0, step: 0.01, unit: "%" },
          { id: "surprise", name: "Surprise Metric", type: "scalar", min: 0.0, max: 1.0, step: 0.01, unit: "%" },
          { id: "sad", name: "Sadness Metric", type: "scalar", min: 0.0, max: 1.0, step: 0.01, unit: "%" },
          { id: "fear", name: "Fear Metric", type: "scalar", min: 0.0, max: 1.0, step: 0.01, unit: "%" },
          { id: "disgust", name: "Disgust Metric", type: "scalar", min: 0.0, max: 1.0, step: 0.01, unit: "%" },
          { id: "neutral", name: "Neutral Metric", type: "scalar", min: 0.0, max: 1.0, step: 0.01, unit: "%" },
          { id: "contempt", name: "Contempt Metric", type: "scalar", min: 0.0, max: 1.0, step: 0.01, unit: "%" },
        ];
      } else if (type === "ThresholdGateNode" || type === "BasicGateNode" || type === "ValueGateNode") {
        type = "ThresholdGateNode";
        inputs = [
          { id: "val_1", name: "Value In 1", type: "scalar" },
        ];
        outputs = [
          { id: "trigger_out", name: "Gate Trigger Out", type: "trigger" },
          { id: "passed_count", name: "Passed Inputs", type: "scalar", min: 0.0, max: 10.0, step: 1.0, unit: "" },
          { id: "active", name: "Gate Active (0/1)", type: "scalar", min: 0.0, max: 1.0, step: 1.0, unit: "" },
        ];
      } else if (type === "GamblingLedgerNode") {
        inputs = [{ id: "ocr_in", name: "OCR Data In", type: "scalar" }];
        outputs = [
          { id: "big_win_trigger", name: "Big Win Trigger", type: "trigger" },
          { id: "tilt_bet_trigger", name: "Martingale Tilt Trigger", type: "trigger" },
          { id: "net_pnl", name: "Net PnL ($)", type: "scalar" },
          { id: "winrate", name: "Winrate %", type: "scalar" },
          { id: "rtp", name: "Experienced RTP %", type: "scalar" },
        ];
      } else if (type === "GateEvaluatorNode") {
        inputs = [
          { id: "trigger_1", name: "Trigger In 1", type: "trigger" },
          { id: "trigger_2", name: "Trigger In 2", type: "trigger" },
          { id: "trigger_3", name: "Trigger In 3", type: "trigger" },
          { id: "trigger_4", name: "Trigger In 4", type: "trigger" },
        ];
        outputs = [
          { id: "clip_trigger", name: "Clip Trigger Out", type: "trigger" },
          { id: "score", name: "Evaluated Score", type: "scalar" },
        ];
      } else if (type === "SegmentSlicerNode") {
        inputs = [
          { id: "video_in", name: "Video In", type: "video" },
          { id: "trigger_in", name: "Trigger In", type: "trigger" },
        ];
        outputs = [{ id: "candidate_slice", name: "Candidate Slice", type: "video" }];
      } else if (type === "HardwareRenderNode") {
        inputs = [{ id: "candidate_in", name: "Candidate In", type: "video" }];
        outputs = [{ id: "clip_asset", name: "Finished Clip", type: "clip" }];
      } else if (type === "ClipFolderNode") {
        inputs = [{ id: "clip_in", name: "Clip In", type: "clip" }];
        outputs = [];
      }

      const newNode = {
        id: newId,
        type: type,
        title: catalogItem ? catalogItem.title : type,
        category: catalogItem ? catalogItem.category : "stream",
        stage: catalogItem ? catalogItem.stage : "heuristic",
        inputs_accepted: catalogItem ? catalogItem.inputs_accepted : [],
        outputs_produced: catalogItem ? catalogItem.outputs_produced : [],
        tags: catalogItem ? catalogItem.tags : [],
        position: [x, y],
        properties: {
          channel: type === "StreamSourceNode" ? (this.selectedChannel || window.activeTab || "stream") : "auto",
        },
        inputs: inputs,
        outputs: outputs,
      };

      if (type === "ClipFolderNode") {
        newNode.title = "Clip Folder: Highlight Reels";
        newNode.properties = {
          folder_name: "Highlight Reels",
          date: new Date().toISOString().split("T")[0],
        };
      } else if (type === "VideoCropNode") {
        newNode.properties.roi = { x: 0.02, y: 0.05, w: 0.22, h: 0.28 };
        newNode.properties.preset = "facecam_tl";
      } else if (type === "ImageScaleNode") {
        newNode.properties.scale_factor = 2.0;
        newNode.properties.algorithm = "bicubic";
        newNode.properties.sharpen_strength = 0.5;
        newNode.properties.clahe_clip_limit = 2.0;
        newNode.properties.denoise_strength = 0.0;
        newNode.properties.target_w = 0;
        newNode.properties.target_h = 0;
      } else if (type === "FacecamEmotionNode" || type === "EmotionFERPlusNode") {
        newNode.type = "FacecamEmotionNode";
        newNode.properties.model = "ferplus";
        newNode.properties.tilt_threshold = 65.0;
        newNode.properties.euphoria_threshold = 75.0;
      } else if (type === "ThresholdGateNode") {
        newNode.properties.logic_mode = "ALL";
        newNode.properties.min_count = 1;
        newNode.properties.debounce_seconds = 10.0;
        newNode.properties.show_sliders = true;
        newNode.properties.rules = {
          val_1: {
            operator: ">=",
            threshold: 0.5,
            min: 0.0,
            max: 1.0,
            step: 0.01,
            unit: "",
            label: "Value In 1",
          },
        };
      }

      this.nodes.set(newId, newNode);
      this.renderNodeDOM(newNode);
      if (type !== "StreamSourceNode" && type !== "ClipFolderNode") {
        this.renderUnroutedNodeState(newNode);
      }
      this.renderWires();
      this.syncGraphDebounced();
      this.updateEmptyState();
      if (this.latestTelemetry) {
        this.applyTelemetry(this.latestTelemetry);
      }
      return newNode;
    }

    autoLayout() {
      // Clean left-to-right columnar alignment
      let streamX = 60, col2X = 460, col3X = 860, col4X = 1240, col5X = 1600, col6X = 1960;
      let yCounters = { col1: 140, col2: 60, col3: 160, col4: 160, col5: 160, col6: 160 };

      this.nodes.forEach((node) => {
        if (node.type === "StreamSourceNode") {
          node.position = [streamX, yCounters.col1];
          yCounters.col1 += 260;
        } else if (["VideoCropNode", "ImageScaleNode", "AudioMonitorNode", "ChatVelocityNode", "CVTransformerNode", "OCRVisionNode", "FacecamEmotionNode", "ScreenSummarizerNode"].includes(node.type)) {
          node.position = [col2X, yCounters.col2];
          yCounters.col2 += (node.type === "CVTransformerNode" || node.type === "FacecamEmotionNode" || node.type === "VideoCropNode" || node.type === "ImageScaleNode" ? 340 : 220);
        } else if (node.type === "GamblingLedgerNode" || node.type === "GateEvaluatorNode" || node.type === "ThresholdGateNode") {
          node.position = [col3X, yCounters.col3];
          yCounters.col3 += 260;
        } else if (node.type === "SegmentSlicerNode") {
          node.position = [col4X, yCounters.col4];
          yCounters.col4 += 200;
        } else if (node.type === "HardwareRenderNode") {
          node.position = [col5X, yCounters.col5];
          yCounters.col5 += 200;
        } else if (node.type === "ClipFolderNode") {
          node.position = [col6X, yCounters.col6];
          yCounters.col6 += 260;
        } else {
          node.position = [col5X, yCounters.col5];
          yCounters.col5 += 200;
        }
        this.updateNodeDOMPosition(node);
      });
      this.renderWires();
      this.syncGraphDebounced();
    }

    /* -------------------------------------------------------------
       Backend REST Graph Sync
       ------------------------------------------------------------- */
    async loadGraph() {
      try {
        const res = await fetch("/api/graph");
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();

        this.nodesLayer.innerHTML = "";
        this.nodes.clear();
        this.wires = data.wires || [];
        this.portTypes = data.port_types || {};

        (data.nodes || []).forEach((n) => {
          if (n.type === "StreamSourceNode") {
            const ch = (n.properties?.channel || this.selectedChannel || window.activeTab || "").replace(/^#/, "").toLowerCase();
            const plat = (n.properties?.platform || (ch.includes("kick") ? "kick" : "twitch")).toLowerCase();
            const platLabel = plat === "kick" ? "Kick" : "Twitch";
            n.properties = n.properties || {};
            n.properties.channel = ch;
            n.properties.platform = plat;
            n.title = ch ? `${platLabel} Source: #${ch}` : `${platLabel} Source`;
          }
          this.nodes.set(n.id, n);
          this.renderNodeDOM(n);
        });

        // Initialize state for each node (unrouted if no session)
        if (window.latestTelemetry) {
          this.applyTelemetry(window.latestTelemetry);
        } else {
          this.nodes.forEach((n) => {
            if (n.type !== "StreamSourceNode") {
              this.renderUnroutedNodeState(n);
            }
          });
        }

        this.updateTransform();
        this.updateEmptyState();
      } catch (err) {
        console.warn("[NodeStudio] Failed to load graph from backend:", err);
      }
    }

    updateEmptyState() {
      if (!this.canvas) return;
      let emptyEl = this.canvas.querySelector(".canvas-empty-state");
      if (this.nodes.size === 0) {
        if (!emptyEl) {
          emptyEl = document.createElement("div");
          emptyEl.className = "canvas-empty-state";
          emptyEl.innerHTML = `
            <div class="empty-state-card">
              <div class="empty-state-icon">🕸️</div>
              <h3 class="empty-state-title">Node Studio Canvas is Empty</h3>
              <p class="empty-state-desc">No active heuristic pipeline. Add a live stream above, create nodes manually, or ask AI Copilot to build an autonomous pipeline.</p>
              <div class="empty-state-actions">
                <button class="empty-action-btn" id="btn-empty-add-node">➕ Add Node</button>
                <button class="empty-action-btn primary" id="btn-empty-ai-copilot">🤖 Ask AI Copilot</button>
              </div>
            </div>
          `;
          this.canvas.appendChild(emptyEl);
          emptyEl.querySelector("#btn-empty-add-node")?.addEventListener("click", () => {
            this.openSpawnPalette(window.innerWidth / 2 - 130, 160);
          });
          emptyEl.querySelector("#btn-empty-ai-copilot")?.addEventListener("click", () => {
            if (window.AIChat && typeof window.AIChat.openDrawer === "function") {
              window.AIChat.openDrawer();
            } else {
              document.getElementById("btn-ai-chat-toggle")?.click();
            }
          });
        }
        emptyEl.style.display = "flex";
      } else {
        if (emptyEl) {
          emptyEl.style.display = "none";
        }
      }
    }

    async handleStreamAdded(channel, platform = "twitch", autoSequence = true) {
      this.selectedChannel = (channel || "").replace(/^#/, "").toLowerCase();
      await this.loadGraph();
      if (autoSequence) {
        this.showToast(`⚡ Auto-generated clipping DAG for #${this.selectedChannel}`);
      } else {
        this.showToast(`🔧 Added #${this.selectedChannel} stream source (manual wiring ready)`);
      }
    }

    async syncGraph() {
      const payload = {
        nodes: Array.from(this.nodes.values()),
        wires: this.wires,
      };

      try {
        const res = await fetch("/api/graph/sync", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.success) {
          this.showToast("Graph synced to backend DAG");
        } else {
          this.showToast(data.error || "DAG validation error", true);
        }
      } catch (err) {
        console.error("[NodeStudio] Sync failed:", err);
      }
    }

    syncGraphDebounced() {
      clearTimeout(this._syncTimer);
      this._syncTimer = setTimeout(() => this.syncGraph(), 800);
    }

    syncNodeParamDebounced(nodeId, param, val) {
      clearTimeout(this._paramTimer);
      this._paramTimer = setTimeout(async () => {
        try {
          await fetch(`/api/graph/nodes/${nodeId}/param`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ param, value: val }),
          });
        } catch (e) {}
      }, 300);
    }

    showToast(msg, isError = false) {
      const toast = document.createElement("div");
      toast.style.position = "fixed";
      toast.style.bottom = "24px";
      toast.style.right = "24px";
      toast.style.background = isError ? "#e11d48" : "#0284c7";
      toast.style.color = "#ffffff";
      toast.style.padding = "8px 16px";
      toast.style.borderRadius = "8px";
      toast.style.fontSize = "12px";
      toast.style.fontWeight = "700";
      toast.style.zIndex = "999";
      toast.style.boxShadow = "0 8px 24px rgba(0,0,0,0.5)";
      toast.textContent = msg;
      document.body.appendChild(toast);
      setTimeout(() => toast.remove(), 2500);
    }
  }

  // Initialize global NodeStudio singleton
  window.NodeStudio = new NodeStudioEngine();
})();
