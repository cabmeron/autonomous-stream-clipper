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
        { type: "StreamSourceNode", category: "stream", title: "Twitch Stream Source", icon: "🔴", desc: "Live HLS, PCM Audio, & IRC Chat" },
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
    }

    deleteWire(wireId) {
      this.wires = this.wires.filter((w) => w.id !== wireId);
      this.selectedWireId = null;
      this.renderWires();
      this.syncGraphDebounced();
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
      if (channels.size === 0) {
        channels.add("marlon");
      }

      selectEl.innerHTML = Array.from(channels)
        .map(
          (c) =>
            `<option value="${c}" ${c === currentChannel.toLowerCase() ? "selected" : ""}>#${c.toUpperCase()}</option>`
        )
        .join("");
    }

    setSelectedChannel(channel) {
      if (!channel) return;
      const cleanCh = channel.replace(/^#/, "").toLowerCase();
      this.selectedChannel = cleanCh;

      for (const node of this.nodes.values()) {
        if (node.type === "StreamSourceNode") {
          node.properties = node.properties || {};
          node.properties.channel = cleanCh;
          node.title = `Twitch Source: #${cleanCh}`;

          // Update header title in DOM
          const nodeEl = document.getElementById(`node-${node.id}`);
          if (nodeEl) {
            const titleEl = nodeEl.querySelector(".node-title");
            if (titleEl) {
              titleEl.textContent = `Twitch Source: #${cleanCh}`;
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
        const currentChannel = (this.selectedChannel || node.properties?.channel || window.activeTab || "marlon").replace(/^#/, "").toLowerCase();
        node.properties = node.properties || {};
        node.properties.channel = currentChannel;
        node.title = `Twitch Source: #${currentChannel}`;

        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        widget.innerHTML = `
          <div class="widget-label">
            <span>Twitch Live Stream</span>
            <span class="widget-val" id="stream-status-${node.id}">CONNECTING</span>
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

        // Populate and hook up select dropdown
        const selectEl = widget.querySelector(`#channel-select-${node.id}`);
        if (selectEl) {
          this.populateChannelSelect(selectEl, currentChannel);
          selectEl.addEventListener("change", (e) => {
            const newCh = e.target.value;
            this.setSelectedChannel(newCh);
            if (typeof window.selectTab === "function") {
              window.selectTab(newCh);
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
          <div class="widget-label">
            <span>Live RMS Decibel Level</span>
            <span class="widget-val" id="audio-val-${node.id}">-32.0 dB</span>
          </div>
          <canvas class="node-wave-canvas" id="wave-canvas-${node.id}" width="280" height="52"></canvas>
          <div style="display:flex; justify-content:space-between; font-size:9px; color:#94a3b8;">
            <span>Spike Threshold: +${props.jump_db_threshold || 12} dB</span>
            <span id="audio-spike-tag-${node.id}" style="color:#64748b;">QUIET</span>
          </div>
          <input type="range" class="node-slider" min="6" max="24" step="1" value="${props.jump_db_threshold || 12}" />
        `;
        const slider = widget.querySelector(".node-slider");
        slider.addEventListener("input", (e) => {
          props.jump_db_threshold = parseFloat(e.target.value);
          widget.querySelector("span:nth-child(1)").textContent = `Spike Threshold: +${props.jump_db_threshold} dB`;
          this.syncNodeParamDebounced(node.id, "jump_db_threshold", props.jump_db_threshold);
        });
        bodyEl.appendChild(widget);
      } else if (node.type === "ChatVelocityNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        widget.innerHTML = `
          <div class="widget-label">
            <span>Chat Density Velocity</span>
            <span class="widget-val" id="chat-val-${node.id}">0.0 msgs/s</span>
          </div>
          <div class="node-chat-ticker" id="chat-ticker-${node.id}">
            <div class="node-chat-msg"><span class="chat-user">system</span><span class="chat-text">Listening to IRC stream...</span></div>
          </div>
          <div style="display:flex; justify-content:space-between; font-size:9px; color:#94a3b8; margin-top:4px;">
            <span>Spike Ratio: ${props.spike_ratio_threshold || 3.0}x</span>
            <span id="chat-spike-tag-${node.id}" style="color:#64748b;">NORMAL</span>
          </div>
        `;
        bodyEl.appendChild(widget);
      } else if (node.type === "OCRVisionNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        widget.innerHTML = `
          <div class="widget-label">
            <span>Interactive ROI Crop Box</span>
            <span class="widget-val" id="ocr-val-${node.id}">1.0x Multiplier</span>
          </div>
          <div class="node-roi-container roi-container-${node.id}">
            <img class="roi-live-img" id="ocr-live-img-${node.id}" style="display:none;" />
            <div class="roi-placeholder-text" id="ocr-placeholder-${node.id}">Live Screen Frame (Drag Box to Select Area)</div>
          </div>
          <div style="display:flex; justify-content:space-between; font-size:9px; color:#94a3b8; margin-top:4px;">
            <span>Win Threshold: ≥ ${props.multiplier_threshold || 100}x</span>
            <span id="ocr-status-${node.id}" style="color:#10b981;">MONITORING</span>
          </div>
          <input type="range" class="node-slider" min="10" max="500" step="10" value="${props.multiplier_threshold || 100}" />
        `;
        const slider = widget.querySelector(".node-slider");
        slider.addEventListener("input", (e) => {
          props.multiplier_threshold = parseFloat(e.target.value);
          widget.querySelector("span:nth-child(1)").textContent = `Win Threshold: ≥ ${props.multiplier_threshold}x`;
          this.syncNodeParamDebounced(node.id, "multiplier_threshold", props.multiplier_threshold);
        });
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
          <div class="widget-label">
            <span>Facecam ROI & Emotional Dynamics</span>
            <span class="widget-val" id="face-top-val-${node.id}">CALM</span>
          </div>
          <div class="node-roi-container roi-container-${node.id}">
            <img class="roi-live-img" id="face-live-img-${node.id}" style="display:none;" />
            <div class="roi-placeholder-text" id="face-placeholder-${node.id}">Stream Frame (Drag Box Over Facecam)</div>
          </div>
          <div class="tilt-card">
            <div class="tilt-meter-box">
              <span style="font-size: 9px; color: #94a3b8; font-weight: 700;">TILT INDEX</span>
              <span class="tilt-num" id="face-tilt-num-${node.id}" style="color: #34d399;">0.0</span>
            </div>
            <div style="text-align: right;">
              <span class="tilt-state-pill" id="face-tilt-pill-${node.id}" style="background: rgba(52, 211, 153, 0.15); color: #34d399;">CALM</span>
              <div style="font-size: 9px; color: #94a3b8; margin-top: 4px;">Euphoria: <strong id="face-euphoria-val-${node.id}" style="color: #fbbf24;">0%</strong></div>
            </div>
          </div>
          <div style="margin-top: 6px;">
            <div style="display: flex; justify-content: space-between; font-size: 9px; color: #94a3b8;">
              <span>Valence (Frustrated ⟵ ⟶ Happy)</span>
              <span id="face-valence-val-${node.id}">0.0</span>
            </div>
            <div class="valence-track">
              <div class="valence-indicator" id="face-valence-ind-${node.id}" style="left: 50%;"></div>
            </div>
          </div>
          <div class="cv-bars-box" id="face-bars-${node.id}">
            <div class="cv-prob-row"><span class="cv-prob-label">joy</span><div class="cv-prob-track"><div class="cv-prob-fill" style="width: 10%; background: #34d399;"></div></div><span class="cv-prob-pct">10%</span></div>
            <div class="cv-prob-row"><span class="cv-prob-label">rage</span><div class="cv-prob-track"><div class="cv-prob-fill" style="width: 5%; background: #ef4444;"></div></div><span class="cv-prob-pct">5%</span></div>
            <div class="cv-prob-row"><span class="cv-prob-label">shock</span><div class="cv-prob-track"><div class="cv-prob-fill" style="width: 5%; background: #f59e0b;"></div></div><span class="cv-prob-pct">5%</span></div>
            <div class="cv-prob-row"><span class="cv-prob-label">despair</span><div class="cv-prob-track"><div class="cv-prob-fill" style="width: 5%; background: #a855f7;"></div></div><span class="cv-prob-pct">5%</span></div>
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
          <div class="widget-label">
            <span>Casino Slot Multi-Region HUD</span>
            <span class="widget-val" id="g-spin-state-${node.id}" style="color: #94a3b8;">IDLE</span>
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
            <div class="roi-placeholder-text" id="g-placeholder-${node.id}">Live Casino Stream (Drag Boxes to Calibrate)</div>
          </div>
          <div class="gambling-hud-grid">
            <div class="hud-stat-cell">
              <div class="hud-stat-lbl">Parsed Balance</div>
              <div class="hud-stat-val" id="g-bal-val-${node.id}">$0.00</div>
            </div>
            <div class="hud-stat-cell">
              <div class="hud-stat-lbl">Active Bet Size</div>
              <div class="hud-stat-val" id="g-bet-val-${node.id}">$0.00</div>
            </div>
            <div class="hud-stat-cell">
              <div class="hud-stat-lbl">Recent Win</div>
              <div class="hud-stat-val" id="g-win-val-${node.id}">$0.00</div>
            </div>
            <div class="hud-stat-cell">
              <div class="hud-stat-lbl">Multiplier</div>
              <div class="hud-stat-val" id="g-mult-val-${node.id}">1.0x</div>
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
        bodyEl.appendChild(widget);
      } else if (node.type === "CVTransformerNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        const currentLabels = props.candidate_labels || "gameplay action, victory celebration, defeat game over, in-game menu, streamer facecam, brb waiting screen";
        const thresh = props.confidence_threshold !== undefined ? props.confidence_threshold : 0.70;
        widget.innerHTML = `
          <div class="widget-label">
            <span id="cv-engine-badge-${node.id}">⚡ CoreML / ANE</span>
            <span class="widget-val" id="cv-top-val-${node.id}">STANDBY</span>
          </div>
          <div class="cv-preview-frame">
            <img id="cv-thumb-${node.id}" class="cv-thumb-img" alt="CV Frame Preview" style="display:none;" />
            <div id="cv-thumb-placeholder-${node.id}" class="cv-thumb-placeholder">Live Screen Frame & Bounding Boxes</div>
          </div>
          <div class="cv-bars-box" id="cv-bars-${node.id}">
            <div class="cv-prob-row"><span class="cv-prob-label">gameplay action</span><div class="cv-prob-track"><div class="cv-prob-fill" style="width: 65%;"></div></div><span class="cv-prob-pct">65%</span></div>
            <div class="cv-prob-row"><span class="cv-prob-label">victory celebration</span><div class="cv-prob-track"><div class="cv-prob-fill" style="width: 25%;"></div></div><span class="cv-prob-pct">25%</span></div>
            <div class="cv-prob-row"><span class="cv-prob-label">streamer facecam</span><div class="cv-prob-track"><div class="cv-prob-fill" style="width: 5%;"></div></div><span class="cv-prob-pct">5%</span></div>
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
        bodyEl.appendChild(widget);
      } else if (node.type === "GateEvaluatorNode") {
        const widget = document.createElement("div");
        widget.setAttribute("class", "node-widget");
        widget.innerHTML = `
          <div class="widget-label">
            <span>Fused Multi-Modal Score</span>
            <span class="widget-val">Threshold: ≥ ${props.min_score || 4}/10</span>
          </div>
          <div class="score-gauge-box">
            <div class="score-dial" id="gate-score-${node.id}">1</div>
            <div class="score-status-pill" id="gate-status-${node.id}">MONITORING</div>
          </div>
        `;
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
      }
    }

    /* -------------------------------------------------------------
       Real-Time Telemetry & Visual Pulses
       ------------------------------------------------------------- */
    applyTelemetry(telemetry) {
      if (!telemetry || !this.container.classList.contains("active")) return;

      const sessions = telemetry.sessions || {};
      const targetCh = (this.selectedChannel || window.activeTab || Object.keys(sessions)[0] || "marlon").replace(/^#/, "").toLowerCase();
      const primarySession = (targetCh && sessions[targetCh]) ? sessions[targetCh] : Object.values(sessions)[0];
      if (!primarySession) return;

      // Update Stream Source Nodes
      this.nodes.forEach((node) => {
        if (node.type === "StreamSourceNode") {
          const statusEl = document.getElementById(`stream-status-${node.id}`);
          if (statusEl) {
            const isOnline = primarySession.status === "online" || primarySession.is_buffering;
            statusEl.textContent = isOnline ? "ONLINE" : "STANDBY";
            statusEl.style.color = isOnline ? "#34d399" : "#94a3b8";
          }
          const selectEl = document.getElementById(`channel-select-${node.id}`);
          if (selectEl && (!selectEl.options || selectEl.options.length !== Object.keys(sessions).length)) {
            this.populateChannelSelect(selectEl, targetCh);
          }
        } else if (node.type === "AudioMonitorNode") {
          const valEl = document.getElementById(`audio-val-${node.id}`);
          const spikeTag = document.getElementById(`audio-spike-tag-${node.id}`);
          const canvas = document.getElementById(`wave-canvas-${node.id}`);

          if (valEl && primarySession.audio_rms_db !== undefined) {
            valEl.textContent = `${primarySession.audio_rms_db.toFixed(1)} dB`;
          }

          if (primarySession.audio_spike) {
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

          if (canvas && primarySession.audio_waveform) {
            this.drawNeonWaveform(canvas, primarySession.audio_waveform);
          }
        } else if (node.type === "ChatVelocityNode") {
          const valEl = document.getElementById(`chat-val-${node.id}`);
          const spikeTag = document.getElementById(`chat-spike-tag-${node.id}`);
          const ticker = document.getElementById(`chat-ticker-${node.id}`);

          if (valEl) {
            valEl.textContent = `${(primarySession.v_instant || 0).toFixed(1)} msgs/s (${(primarySession.spike_ratio || 1.0).toFixed(1)}x)`;
          }

          if (primarySession.is_spiking) {
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

          if (ticker && primarySession.recent_messages && primarySession.recent_messages.length) {
            ticker.innerHTML = primarySession.recent_messages
              .slice(-4)
              .map(
                (m) => `<div class="node-chat-msg"><span class="chat-user">${m.user}:</span><span class="chat-text">${m.text}</span></div>`
              )
              .join("");
            ticker.scrollTop = ticker.scrollHeight;
          }
        } else if (node.type === "OCRVisionNode") {
          const valEl = document.getElementById(`ocr-val-${node.id}`);
          if (valEl) {
            valEl.textContent = `${primarySession.ocr_multiplier || "1.0x"} (${primarySession.ocr_balance || "$0.00"})`;
          }
          const ocrImg = document.getElementById(`ocr-live-img-${node.id}`);
          const ocrPlaceholder = document.getElementById(`ocr-placeholder-${node.id}`);
          const frameB64 = primarySession.stream_frame_b64 || primarySession.cv_thumbnail_b64;
          if (ocrImg && frameB64) {
            ocrImg.src = frameB64;
            ocrImg.style.display = "block";
            if (ocrPlaceholder) ocrPlaceholder.style.display = "none";
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

          const frameB64 = primarySession.stream_frame_b64 || primarySession.cv_thumbnail_b64;
          if (faceImg && frameB64) {
            faceImg.src = frameB64;
            faceImg.style.display = "block";
            if (facePlaceholder) facePlaceholder.style.display = "none";
          }

          if (primarySession.emotion_tilt !== undefined) {
            const tilt = primarySession.emotion_tilt;
            if (tiltNum) tiltNum.textContent = tilt.toFixed(1);
            if (topVal) topVal.textContent = (primarySession.emotion_top || "neutral").toUpperCase();
            if (euphoriaVal && primarySession.emotion_euphoria !== undefined) {
              euphoriaVal.textContent = `${primarySession.emotion_euphoria.toFixed(0)}%`;
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

            if (primarySession.is_tilting) {
              document.getElementById(`node-${node.id}`)?.classList.add("spiking");
              this.pulseWiresFromNode(node.id);
            } else {
              document.getElementById(`node-${node.id}`)?.classList.remove("spiking");
            }
          }

          if (primarySession.emotion_valence !== undefined) {
            if (valenceVal) valenceVal.textContent = (primarySession.emotion_valence > 0 ? "+" : "") + primarySession.emotion_valence.toFixed(2);
            if (valenceInd) {
              const pct = Math.max(5, Math.min(95, ((primarySession.emotion_valence + 1.0) / 2.0) * 100));
              valenceInd.style.left = `${pct}%`;
              valenceInd.style.background = primarySession.emotion_valence >= 0 ? "#34d399" : "#ef4444";
            }
          }

          if (barsBox && primarySession.emotion_distribution) {
            const dist = primarySession.emotion_distribution;
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

          const frameB64 = primarySession.stream_frame_b64 || primarySession.cv_thumbnail_b64;
          if (gImg && frameB64) {
            gImg.src = frameB64;
            gImg.style.display = "block";
            if (gPlaceholder) gPlaceholder.style.display = "none";
          }

          if (balVal && primarySession.gambling_balance !== undefined) {
            balVal.textContent = `$${Number(primarySession.gambling_balance).toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
          }
          if (betVal && primarySession.gambling_bet !== undefined) {
            betVal.textContent = `$${Number(primarySession.gambling_bet).toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
          }
          if (winVal && primarySession.gambling_win !== undefined) {
            winVal.textContent = `$${Number(primarySession.gambling_win).toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
          }
          if (multVal && primarySession.gambling_multiplier !== undefined) {
            multVal.textContent = primarySession.gambling_multiplier ? `${primarySession.gambling_multiplier.toFixed(1)}x` : "1.0x";
          }
          if (spinBadge && primarySession.gambling_spin_state) {
            spinBadge.textContent = primarySession.gambling_spin_state;
            if (primarySession.gambling_spin_state === "WIN_CELEBRATION") {
              spinBadge.style.color = "#f59e0b";
              this.pulseWiresFromNode(node.id);
            } else if (primarySession.gambling_spin_state === "SPINNING") {
              spinBadge.style.color = "#38bdf8";
            } else {
              spinBadge.style.color = "#94a3b8";
            }
          }
        } else if (node.type === "GamblingLedgerNode") {
          const ledger = primarySession.gambling_ledger || {};
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

          if (primarySession.cv_top_label) {
            if (topValEl) {
              topValEl.textContent = `${primarySession.cv_top_label.toUpperCase()} (${(primarySession.cv_confidence * 100).toFixed(0)}%)`;
              topValEl.style.color = primarySession.cv_confidence >= 0.70 ? "#34d399" : "#38bdf8";
            }
            if (latencyTag && primarySession.cv_latency_ms) {
              latencyTag.textContent = `⚡ ${primarySession.cv_latency_ms.toFixed(1)} ms`;
            }
            if (thumbImg && primarySession.cv_thumbnail_b64) {
              thumbImg.src = primarySession.cv_thumbnail_b64;
              thumbImg.style.display = "block";
              if (thumbPlaceholder) thumbPlaceholder.style.display = "none";
            }
            if (barsBox && primarySession.cv_probabilities) {
              const sorted = Object.entries(primarySession.cv_probabilities).sort((a, b) => b[1] - a[1]).slice(0, 3);
              barsBox.innerHTML = sorted.map(([label, prob]) => `
                <div class="cv-prob-row">
                  <span class="cv-prob-label">${label}</span>
                  <div class="cv-prob-track"><div class="cv-prob-fill" style="width: ${Math.round(prob * 100)}%;"></div></div>
                  <span class="cv-prob-pct">${Math.round(prob * 100)}%</span>
                </div>
              `).join("");
            }
            if (primarySession.cv_confidence >= 0.75) {
              this.pulseWiresFromNode(node.id);
            }
          }
        } else if (node.type === "GateEvaluatorNode") {
          const scoreEl = document.getElementById(`gate-score-${node.id}`);
          const statusEl = document.getElementById(`gate-status-${node.id}`);
          const score = primarySession.spike_ratio > 3.0 || primarySession.audio_spike ? 8 : 1;

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
      }

      const newNode = {
        id: newId,
        type: type,
        title: catalogItem ? catalogItem.title : type,
        category: catalogItem ? catalogItem.category : "stream",
        position: [x, y],
        properties: {},
        inputs: inputs,
        outputs: outputs,
      };

      this.nodes.set(newId, newNode);
      this.renderNodeDOM(newNode);
      this.renderWires();
      this.syncGraphDebounced();
    }

    autoLayout() {
      // Clean left-to-right columnar alignment
      let streamX = 60, col2X = 460, col3X = 860, col4X = 1240, col5X = 1600;
      let yCounters = { col1: 140, col2: 60, col3: 160, col4: 160, col5: 160 };

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
            const ch = (this.selectedChannel || window.activeTab || n.properties?.channel || "marlon").replace(/^#/, "").toLowerCase();
            n.properties = n.properties || {};
            n.properties.channel = ch;
            n.title = `Twitch Source: #${ch}`;
          }
          this.nodes.set(n.id, n);
          this.renderNodeDOM(n);
        });

        this.updateTransform();
      } catch (err) {
        console.warn("[NodeStudio] Failed to load graph from backend:", err);
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
