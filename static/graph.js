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
      this.selectedChannel = (window.activeTab || "marlon").replace(/^#/, "").toLowerCase();
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

      // Preset Templates
      this.nodeCatalog = [
        { type: "StreamSourceNode", category: "stream", title: "Stream Source (Twitch / Kick)", icon: "🔴", desc: "Live HLS, PCM Audio, & Chat" },
        { type: "AudioMonitorNode", category: "audio", title: "Audio Decibel Monitor", icon: "🔊", desc: "RMS dB jump & volume spikes" },
        { type: "ChatVelocityNode", category: "chat", title: "Chat Velocity Engine", icon: "💬", desc: "Messages/sec & spike ratio" },
        { type: "OCRVisionNode", category: "ocr", title: "OCR / Vision Engine", icon: "🔍", desc: "Multiplier & slot balance detection" },
        { type: "CVTransformerNode", category: "cv", title: "HuggingFace Vision", icon: "👁️", desc: "Zero-shot classification & detection" },
        { type: "FacecamEmotionNode", category: "cv", title: "Facecam Emotion & Tilt", icon: "😡", desc: "Tilt Index, Valence, Arousal & Spikes" },
        { type: "GamblingOCRNode", category: "ocr", title: "Gambling Multi-OCR", icon: "🎰", desc: "Balance, Bet, Win & Reel motion HUD" },
        { type: "GamblingLedgerNode", category: "analytics", title: "Gambling PnL & Ledger", icon: "💰", desc: "Net PnL, Winrate, Streaks & Martingale alert" },
        { type: "ScreenSummarizerNode", category: "summarizer", title: "AI Screen Summarizer", icon: "🤖", desc: "Multimodal frame vision + chat" },
        { type: "GateEvaluatorNode", category: "gate", title: "Gate Evaluator & Logic", icon: "⚡", desc: "Weighted scoring & debounce" },
        { type: "SegmentSlicerNode", category: "slicer", title: "Rolling Segment Slicer", icon: "✂️", desc: "60s zero-copy extraction" },
        { type: "HardwareRenderNode", category: "render", title: "Hardware Video Renderer", icon: "🎬", desc: "Uncropped 1080p / 9:16 vertical" },
        { type: "ClipFolderNode", category: "storage", title: "Clip Folder / Collection", icon: "📂", desc: "Multi-renderer folder repository & date organizer" },
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

        const pathEl = document.createElementNS("http://www.w3.org/2000/svg", "path");
        pathEl.setAttribute("d", pathStr);
        pathEl.setAttribute("id", `wire-${wire.id}`);
        pathEl.setAttribute("class", `graph-wire wire-active ${this.selectedWireId === wire.id ? "selected" : ""}`);
        pathEl.style.stroke = this.getPortColor(wire.type);

        // Click to select wire
        pathEl.addEventListener("click", (e) => {
          e.stopPropagation();
          this.selectWire(wire.id);
        });

        this.svgLayer.appendChild(pathEl);
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
      this.renderWires();
      this.syncGraphDebounced();
      if (this.latestTelemetry) {
        this.applyTelemetry(this.latestTelemetry);
      }
    }

    deleteWire(wireId) {
      this.wires = this.wires.filter((w) => w.id !== wireId);
      this.selectedWireId = null;
      this.renderWires();
      this.syncGraphDebounced();
      if (this.latestTelemetry) {
        this.applyTelemetry(this.latestTelemetry);
      }
    }

    selectWire(wireId) {
      this.selectedWireId = wireId;
      this.selectedNodeId = null;
      document.querySelectorAll(".studio-node").forEach((n) => n.classList.remove("selected"));
      this.renderWires();
    }

    deselectAll() {
      this.selectedNodeId = null;
      this.selectedWireId = null;
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
        inCol.appendChild(wrap);
      });

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

    deleteNode(nodeId) {
      // Remove all connected wires
      this.wires = this.wires.filter(
        (w) => !w.from.startsWith(`${nodeId}:`) && !w.to.startsWith(`${nodeId}:`)
      );
      this.nodes.delete(nodeId);

      const el = document.getElementById(`node-${nodeId}`);
      if (el) el.remove();

      this.renderWires();
      this.syncGraphDebounced();
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

      const cleanCh = (channel || "marlon").replace(/^#/, "").toLowerCase();
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
        channels.add("marlon");
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
      } else if (node.type === "FacecamEmotionNode") {
        const faceImg = document.getElementById(`face-live-img-${nodeId}`);
        const facePlaceholder = document.getElementById(`face-placeholder-${nodeId}`);
        const tiltNum = document.getElementById(`face-tilt-num-${nodeId}`);
        const tiltPill = document.getElementById(`face-tilt-pill-${nodeId}`);
        const topVal = document.getElementById(`face-top-val-${nodeId}`);
        const euphoriaVal = document.getElementById(`face-euphoria-val-${nodeId}`);
        const valenceVal = document.getElementById(`face-valence-val-${nodeId}`);
        const barsBox = document.getElementById(`face-bars-${nodeId}`);
        const latencyTag = document.getElementById(`face-latency-tag-${nodeId}`);

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
      } else if (node.type === "GamblingOCRNode") {
        const gImg = document.getElementById(`g-live-img-${nodeId}`);
        const gPlaceholder = document.getElementById(`g-placeholder-${nodeId}`);
        const spinBadge = document.getElementById(`g-spin-state-${nodeId}`);
        const balVal = document.getElementById(`g-bal-val-${nodeId}`);
        const betVal = document.getElementById(`g-bet-val-${nodeId}`);
        const winVal = document.getElementById(`g-win-val-${nodeId}`);
        const multVal = document.getElementById(`g-mult-val-${nodeId}`);

        if (gImg) {
          gImg.style.display = "none";
          gImg.removeAttribute("src");
        }
        if (gPlaceholder) {
          gPlaceholder.style.display = "block";
          gPlaceholder.textContent = "Unrouted (Connect Video In or Assign Stream)";
        }
        if (spinBadge) {
          spinBadge.textContent = "UNROUTED";
          spinBadge.style.color = "#64748b";
        }
        if (balVal) balVal.textContent = "$--";
        if (betVal) betVal.textContent = "$--";
        if (winVal) winVal.textContent = "$--";
        if (multVal) multVal.textContent = "--x";
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
        const currentChannel = (node.properties?.channel || this.selectedChannel || window.activeTab || "marlon").replace(/^#/, "").toLowerCase();
        const currentPlatform = (node.properties?.platform || (currentChannel.includes("kick") ? "kick" : "twitch")).toLowerCase();
        node.properties = node.properties || {};
        node.properties.channel = currentChannel;
        node.properties.platform = currentPlatform;
        const platLabel = currentPlatform === "kick" ? "Kick" : "Twitch";
        node.title = `${platLabel} Source: #${currentChannel}`;

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
            <span>Interactive ROI Crop Box</span>
            <span class="widget-val" id="ocr-val-${node.id}">— (Unrouted)</span>
          </div>
          <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:6px; margin-top:2px;">
            <span style="font-size:9px; color:#94a3b8; font-weight:700;">PRESET:</span>
            <div style="display:flex; gap:3px;">
              <button class="slot-preset-btn-mini" data-preset="pragmatic_play" style="font-size:9px; padding:2px 5px; border-radius:4px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.05); color:#cbd5e1; cursor:pointer;">Pragmatic</button>
              <button class="slot-preset-btn-mini" data-preset="hacksaw_gaming" style="font-size:9px; padding:2px 5px; border-radius:4px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.05); color:#cbd5e1; cursor:pointer;">Hacksaw</button>
              <button class="slot-preset-btn-mini" data-preset="nolimit_city" style="font-size:9px; padding:2px 5px; border-radius:4px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.05); color:#cbd5e1; cursor:pointer;">Nolimit</button>
              <button class="slot-preset-btn-mini" data-preset="default_slots" style="font-size:9px; padding:2px 5px; border-radius:4px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.05); color:#cbd5e1; cursor:pointer;">Stake</button>
            </div>
          </div>
          <div class="node-roi-container roi-container-${node.id}">
            <img class="roi-live-img" id="ocr-live-img-${node.id}" style="display:none;" />
            <div class="roi-placeholder-text" id="ocr-placeholder-${node.id}">Unrouted (Connect Video In or Assign Stream)</div>
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

        widget.querySelectorAll(".slot-preset-btn-mini").forEach(btn => {
          btn.addEventListener("click", (e) => {
            const preset = btn.getAttribute("data-preset");
            props.slot_preset = preset;
            this.syncNodeParamDebounced(node.id, "slot_preset", preset);
            if (window.applySlotPreset) {
              window.applySlotPreset(preset);
            }
            widget.querySelectorAll(".slot-preset-btn-mini").forEach(b => {
              b.style.background = "rgba(255,255,255,0.05)";
              b.style.color = "#cbd5e1";
              b.style.borderColor = "rgba(255,255,255,0.1)";
            });
            btn.style.background = "#53fc18";
            btn.style.color = "#000";
            btn.style.borderColor = "#53fc18";
            this.showToast(`Applied ${preset} layout`);
          });
        });

        this.setupSourceSelect(widget, node);
        bodyEl.appendChild(widget);

        // Mount interactive draggable ROI box
        setTimeout(() => {
          const container = widget.querySelector(`.roi-container-${node.id}`);
          if (container) {
            const initialRoi = props.roi || { x: 0.70, y: 0.85, w: 0.28, h: 0.12 };
            props.roi = initialRoi;
            const ctrl = this.setupDraggableRoiBox(container, initialRoi, "#10b981", "OCR ROI", (roi, isFinal) => {
              props.roi = roi;
              if (isFinal) {
                this.syncNodeParamDebounced(node.id, "roi", roi);
                this.showToast("OCR ROI calibrated");
              }
            });
            this.nodeRoiControllers.set(`${node.id}:ocr`, ctrl);
          }
        }, 50);
      } else if (node.type === "FacecamEmotionNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        const tiltThresh = props.tilt_threshold !== undefined ? props.tilt_threshold : 65.0;
        widget.innerHTML = `
          <div class="node-source-row" style="margin-bottom:6px; display:flex; align-items:center; justify-content:space-between; gap:6px; background:rgba(0,0,0,0.25); padding:3px 6px; border-radius:4px;">
            <span style="font-size:10px; color:#94a3b8; white-space:nowrap;">Stream Source:</span>
            <select class="node-source-select" id="source-select-${node.id}" style="flex:1; max-width:140px; background:rgba(0,0,0,0.5); border:1px solid rgba(56,189,248,0.3); color:#38bdf8; font-size:10px; border-radius:4px; padding:2px 4px; cursor:pointer;">
              <option value="auto">⚡ Auto (Wire)</option>
            </select>
          </div>
          <div class="widget-label">
            <span>Facecam ROI & Emotional Dynamics</span>
            <span class="widget-val" id="face-top-val-${node.id}">STANDBY</span>
          </div>
          <div class="node-roi-container roi-container-${node.id}">
            <img class="roi-live-img" id="face-live-img-${node.id}" style="display:none;" />
            <div class="roi-placeholder-text" id="face-placeholder-${node.id}">Unrouted (Connect Video In or Assign Stream)</div>
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
        this.setupSourceSelect(widget, node);
        bodyEl.appendChild(widget);

        // Mount interactive draggable facecam ROI box
        setTimeout(() => {
          const container = widget.querySelector(`.roi-container-${node.id}`);
          if (container) {
            const initialRoi = props.face_roi || { x: 0.02, y: 0.05, w: 0.22, h: 0.28 };
            props.face_roi = initialRoi;
            const ctrl = this.setupDraggableRoiBox(container, initialRoi, "#06b6d4", "Facecam", (roi, isFinal) => {
              props.face_roi = roi;
              if (isFinal) {
                this.syncNodeParamDebounced(node.id, "face_roi", roi);
                this.showToast("Streamer Facecam ROI calibrated");
              }
            });
            this.nodeRoiControllers.set(`${node.id}:face`, ctrl);
          }
        }, 50);
      } else if (node.type === "GamblingOCRNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        const currentPreset = props.preset || "pragmatic_standard";
        widget.innerHTML = `
          <div class="node-source-row" style="margin-bottom:6px; display:flex; align-items:center; justify-content:space-between; gap:6px; background:rgba(0,0,0,0.25); padding:3px 6px; border-radius:4px;">
            <span style="font-size:10px; color:#94a3b8; white-space:nowrap;">Stream Source:</span>
            <select class="node-source-select" id="source-select-${node.id}" style="flex:1; max-width:140px; background:rgba(0,0,0,0.5); border:1px solid rgba(56,189,248,0.3); color:#38bdf8; font-size:10px; border-radius:4px; padding:2px 4px; cursor:pointer;">
              <option value="auto">⚡ Auto (Wire)</option>
            </select>
          </div>
          <div class="widget-label">
            <span>Casino Slot Multi-Region HUD</span>
            <span class="widget-val" id="g-spin-state-${node.id}" style="color: #64748b;">UNROUTED</span>
          </div>
          <div class="roi-tab-bar" id="g-tabs-${node.id}">
            <button class="roi-tab-btn active" data-target="all">👁️ All ROIs</button>
            <button class="roi-tab-btn" data-target="balance" style="color:#10b981;">🟩 Balance</button>
            <button class="roi-tab-btn" data-target="bet" style="color:#38bdf8;">🟦 Bet Size</button>
            <button class="roi-tab-btn" data-target="win" style="color:#f59e0b;">🟨 Win Payout</button>
            <button class="roi-tab-btn" data-target="reels" style="color:#a855f7;">🟪 Reels Area</button>
          </div>
          <div class="node-roi-container roi-container-${node.id}">
            <img class="roi-live-img" id="g-live-img-${node.id}" style="display:none;" />
            <div class="roi-placeholder-text" id="g-placeholder-${node.id}">Unrouted (Connect Video In or Assign Stream)</div>
          </div>
          <div class="gambling-hud-grid">
            <div class="hud-stat-cell">
              <div class="hud-stat-lbl">Parsed Balance</div>
              <div class="hud-stat-val" id="g-bal-val-${node.id}">$--</div>
            </div>
            <div class="hud-stat-cell">
              <div class="hud-stat-lbl">Active Bet Size</div>
              <div class="hud-stat-val" id="g-bet-val-${node.id}">$--</div>
            </div>
            <div class="hud-stat-cell">
              <div class="hud-stat-lbl">Recent Win</div>
              <div class="hud-stat-val" id="g-win-val-${node.id}">$--</div>
            </div>
            <div class="hud-stat-cell">
              <div class="hud-stat-lbl">Multiplier</div>
              <div class="hud-stat-val" id="g-mult-val-${node.id}">--x</div>
            </div>
          </div>
          <div style="margin-top: 6px; display: flex; align-items: center; justify-content: space-between; gap: 6px;">
            <span style="font-size: 9px; color: #94a3b8;">Coordinate Preset:</span>
            <select class="node-channel-select g-preset-select" style="flex: 1; font-size: 10px; background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.15); border-radius: 4px; color: #f8fafc; padding: 2px 4px;">
              <option value="pragmatic_standard" ${currentPreset === "pragmatic_standard" ? "selected" : ""}>Pragmatic Play Standard</option>
              <option value="hacksaw_standard" ${currentPreset === "hacksaw_standard" ? "selected" : ""}>Hacksaw Gaming Standard</option>
              <option value="stake_originals" ${currentPreset === "stake_originals" ? "selected" : ""}>Stake Originals HUD</option>
              <option value="custom" ${currentPreset === "custom" ? "selected" : ""}>Custom ROI Layout</option>
            </select>
          </div>
        `;
        const presetSel = widget.querySelector(".g-preset-select");
        presetSel.addEventListener("change", (e) => {
          props.preset = e.target.value;
          this.syncNodeParamDebounced(node.id, "preset", props.preset);
          this.showToast(`Switched HUD preset to ${e.target.value}`);
        });
        this.setupSourceSelect(widget, node);
        bodyEl.appendChild(widget);

        // Mount interactive draggable boxes for balance, bet, win, reels
        setTimeout(() => {
          const container = widget.querySelector(`.roi-container-${node.id}`);
          if (container) {
            props.rois = props.rois || {
              balance: { x: 0.05, y: 0.92, w: 0.18, h: 0.06 },
              bet: { x: 0.42, y: 0.92, w: 0.16, h: 0.06 },
              win: { x: 0.35, y: 0.50, w: 0.30, h: 0.14 },
              reels: { x: 0.20, y: 0.15, w: 0.60, h: 0.70 },
            };
            const colors = { balance: "#10b981", bet: "#38bdf8", win: "#f59e0b", reels: "#a855f7" };
            const ctrls = {};
            for (const [key, rval] of Object.entries(props.rois)) {
              ctrls[key] = this.setupDraggableRoiBox(container, rval, colors[key] || "#10b981", key.toUpperCase(), (roi, isFinal) => {
                props.rois[key] = roi;
                if (isFinal) {
                  this.syncNodeParamDebounced(node.id, `roi_${key}`, roi);
                  this.syncNodeParamDebounced(node.id, "rois", props.rois);
                  this.showToast(`Updated ${key.toUpperCase()} ROI`);
                }
              });
            }
            this.nodeRoiControllers.set(`${node.id}:gambling`, ctrls);

            // Tab bar switcher
            const tabs = widget.querySelectorAll(".roi-tab-btn");
            tabs.forEach((tab) => {
              tab.addEventListener("click", () => {
                tabs.forEach((t) => t.classList.remove("active"));
                tab.classList.add("active");
                const target = tab.getAttribute("data-target");
                if (target === "all") {
                  Object.values(ctrls).forEach((c) => { c.setVisible(true); c.setActive(false); });
                } else {
                  Object.entries(ctrls).forEach(([k, c]) => {
                    c.setVisible(true);
                    c.setActive(k === target);
                  });
                }
              });
            });
          }
        }, 50);
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
            ocrImg.src = frameB64;
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
        } else if (node.type === "FacecamEmotionNode") {
          const faceImg = document.getElementById(`face-live-img-${node.id}`);
          const facePlaceholder = document.getElementById(`face-placeholder-${node.id}`);
          const tiltNum = document.getElementById(`face-tilt-num-${node.id}`);
          const tiltPill = document.getElementById(`face-tilt-pill-${node.id}`);
          const topVal = document.getElementById(`face-top-val-${node.id}`);
          const euphoriaVal = document.getElementById(`face-euphoria-val-${node.id}`);
          const valenceVal = document.getElementById(`face-valence-val-${node.id}`);
          const valenceInd = document.getElementById(`face-valence-ind-${node.id}`);
          const barsBox = document.getElementById(`face-bars-${node.id}`);

          const frameB64 = nodeSession.stream_frame_b64 || nodeSession.cv_thumbnail_b64;
          if (faceImg && frameB64) {
            faceImg.src = frameB64;
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

          if (barsBox && nodeSession.emotion_distribution) {
            const dist = nodeSession.emotion_distribution;
            const barColors = { joy: "#34d399", rage: "#ef4444", shock: "#f59e0b", despair: "#a855f7", neutral: "#64748b" };
            barsBox.innerHTML = Object.entries(dist).map(([emo, val]) => `
              <div class="cv-prob-row">
                <span class="cv-prob-label">${emo}</span>
                <div class="cv-prob-track"><div class="cv-prob-fill" style="width: ${Math.round(val * 100)}%; background: ${barColors[emo] || '#38bdf8'};"></div></div>
                <span class="cv-prob-pct" style="color: ${barColors[emo] || '#38bdf8'};">${Math.round(val * 100)}%</span>
              </div>
            `).join("");
          }
        } else if (node.type === "GamblingOCRNode") {
          const gImg = document.getElementById(`g-live-img-${node.id}`);
          const gPlaceholder = document.getElementById(`g-placeholder-${node.id}`);
          const spinBadge = document.getElementById(`g-spin-state-${node.id}`);
          const balVal = document.getElementById(`g-bal-val-${node.id}`);
          const betVal = document.getElementById(`g-bet-val-${node.id}`);
          const winVal = document.getElementById(`g-win-val-${node.id}`);
          const multVal = document.getElementById(`g-mult-val-${node.id}`);

          const frameB64 = nodeSession.stream_frame_b64 || nodeSession.cv_thumbnail_b64;
          if (gImg && frameB64) {
            gImg.src = frameB64;
            gImg.style.display = "block";
            if (gPlaceholder) gPlaceholder.style.display = "none";
          }

          if (balVal && nodeSession.gambling_balance !== undefined) {
            balVal.textContent = `$${Number(nodeSession.gambling_balance).toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
          }
          if (betVal && nodeSession.gambling_bet !== undefined) {
            betVal.textContent = `$${Number(nodeSession.gambling_bet).toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
          }
          if (winVal && nodeSession.gambling_win !== undefined) {
            winVal.textContent = `$${Number(nodeSession.gambling_win).toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
          }
          if (multVal && nodeSession.gambling_multiplier !== undefined) {
            multVal.textContent = nodeSession.gambling_multiplier ? `${nodeSession.gambling_multiplier.toFixed(1)}x` : "1.0x";
          }
          if (spinBadge && nodeSession.gambling_spin_state) {
            spinBadge.textContent = nodeSession.gambling_spin_state;
            if (nodeSession.gambling_spin_state === "WIN_CELEBRATION") {
              spinBadge.style.color = "#f59e0b";
              this.pulseWiresFromNode(node.id);
            } else if (nodeSession.gambling_spin_state === "SPINNING") {
              spinBadge.style.color = "#38bdf8";
            } else {
              spinBadge.style.color = "#94a3b8";
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
      const targetCh = (this.selectedChannel || "marlon").toLowerCase();
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
        if (n.type === "FacecamEmotionNode") {
          registeredRois.push({
            nodeId: n.id,
            paramKey: "face_roi",
            label: "Streamer Facecam",
            color: "#06b6d4",
            roi: n.properties?.face_roi || { x: 0.02, y: 0.05, w: 0.22, h: 0.28 },
          });
        } else if (n.type === "GamblingOCRNode") {
          const rois = n.properties?.rois || {
            balance: { x: 0.05, y: 0.92, w: 0.18, h: 0.06 },
            bet: { x: 0.42, y: 0.92, w: 0.16, h: 0.06 },
            win: { x: 0.35, y: 0.50, w: 0.30, h: 0.14 },
            reels: { x: 0.20, y: 0.15, w: 0.60, h: 0.70 },
          };
          const gColors = { balance: "#10b981", bet: "#38bdf8", win: "#f59e0b", reels: "#a855f7" };
          Object.entries(rois).forEach(([k, r]) => {
            registeredRois.push({
              nodeId: n.id,
              subKey: k,
              paramKey: `roi_${k}`,
              label: `Casino ${k.toUpperCase()}`,
              color: gColors[k] || "#10b981",
              roi: r,
            });
          });
        } else if (n.type === "OCRVisionNode") {
          registeredRois.push({
            nodeId: n.id,
            paramKey: "roi",
            label: "Generic OCR",
            color: "#10b981",
            roi: n.properties?.roi || { x: 0.70, y: 0.85, w: 0.28, h: 0.12 },
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
      if (!palette || !list) return;

      this.renderSpawnItems = (filterText = "") => {
        list.innerHTML = "";
        const lower = filterText.toLowerCase();

        this.nodeCatalog.forEach((item) => {
          if (lower && !item.title.toLowerCase().includes(lower) && !item.desc.toLowerCase().includes(lower)) return;

          const row = document.createElement("div");
          row.setAttribute("class", "spawn-item");
          row.innerHTML = `<span>${item.icon}</span> <span>${item.title}</span>`;
          row.addEventListener("click", () => {
            const worldPos = this.screenToWorld(
              parseInt(palette.style.left) + 280,
              parseInt(palette.style.top) + 40
            );
            this.addNode(item.type, Math.round(worldPos.x), Math.round(worldPos.y));
            this.closeSpawnPalette();
          });
          list.appendChild(row);
        });
      };

      this.renderSpawnItems();

      search?.addEventListener("input", (e) => {
        this.renderSpawnItems(e.target.value);
      });
    }

    openSpawnPalette(clientX, clientY) {
      const p = document.getElementById("node-spawn-palette");
      if (!p) return;
      p.style.left = `${clientX}px`;
      p.style.top = `${clientY}px`;
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
      } else if (type === "FacecamEmotionNode") {
        inputs = [{ id: "video_in", name: "Video In", type: "video" }];
        outputs = [
          { id: "tilt_trigger", name: "Tilt Trigger", type: "trigger" },
          { id: "euphoria_trigger", name: "Euphoria Trigger", type: "trigger" },
          { id: "tilt_score", name: "Tilt Index", type: "scalar" },
          { id: "valence", name: "Valence", type: "scalar" },
        ];
      } else if (type === "GamblingOCRNode") {
        inputs = [{ id: "video_in", name: "Video In", type: "video" }];
        outputs = [
          { id: "balance", name: "Balance", type: "scalar" },
          { id: "bet", name: "Bet Size", type: "scalar" },
          { id: "win", name: "Win Payout", type: "scalar" },
          { id: "multiplier", name: "Multiplier", type: "scalar" },
          { id: "ocr_data", name: "OCR Metrics", type: "scalar" },
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
        ];
        outputs = [
          { id: "clip_trigger", name: "Clip Trigger Out", type: "trigger" },
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
        position: [x, y],
        properties: {
          channel: type === "StreamSourceNode" ? (this.selectedChannel || window.activeTab || "marlon") : "auto",
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
      }

      this.nodes.set(newId, newNode);
      this.renderNodeDOM(newNode);
      if (type !== "StreamSourceNode" && type !== "ClipFolderNode") {
        this.renderUnroutedNodeState(newNode);
      }
      this.renderWires();
      this.syncGraphDebounced();
      if (this.latestTelemetry) {
        this.applyTelemetry(this.latestTelemetry);
      }
    }

    autoLayout() {
      // Clean left-to-right columnar alignment
      let streamX = 60, col2X = 460, col3X = 860, col4X = 1240, col5X = 1600, col6X = 1960;
      let yCounters = { col1: 140, col2: 60, col3: 160, col4: 160, col5: 160, col6: 160 };

      this.nodes.forEach((node) => {
        if (node.type === "StreamSourceNode") {
          node.position = [streamX, yCounters.col1];
          yCounters.col1 += 260;
        } else if (["AudioMonitorNode", "ChatVelocityNode", "CVTransformerNode", "OCRVisionNode", "FacecamEmotionNode", "GamblingOCRNode", "ScreenSummarizerNode"].includes(node.type)) {
          node.position = [col2X, yCounters.col2];
          yCounters.col2 += (node.type === "CVTransformerNode" || node.type === "FacecamEmotionNode" || node.type === "GamblingOCRNode" ? 340 : 220);
        } else if (node.type === "GamblingLedgerNode" || node.type === "GateEvaluatorNode") {
          node.position = [col3X, yCounters.col3];
          yCounters.col3 += 240;
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
            const ch = (n.properties?.channel || this.selectedChannel || window.activeTab || "marlon").replace(/^#/, "").toLowerCase();
            const plat = (n.properties?.platform || (ch.includes("kick") ? "kick" : "twitch")).toLowerCase();
            const platLabel = plat === "kick" ? "Kick" : "Twitch";
            n.properties = n.properties || {};
            n.properties.channel = ch;
            n.properties.platform = plat;
            n.title = `${platLabel} Source: #${ch}`;
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
      } catch (err) {
        console.warn("[NodeStudio] Failed to load graph from backend:", err);
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
