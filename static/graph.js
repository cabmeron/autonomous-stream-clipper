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

      // Preset Templates
      this.nodeCatalog = [
        { type: "StreamSourceNode", category: "stream", title: "Twitch Stream Source", icon: "🔴", desc: "Live HLS, PCM Audio, & IRC Chat" },
        { type: "AudioMonitorNode", category: "audio", title: "Audio Decibel Monitor", icon: "🔊", desc: "RMS dB jump & volume spikes" },
        { type: "ChatVelocityNode", category: "chat", title: "Chat Velocity Engine", icon: "💬", desc: "Messages/sec & spike ratio" },
        { type: "OCRVisionNode", category: "ocr", title: "OCR / Vision Engine", icon: "🔍", desc: "Multiplier & slot balance detection" },
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
          <div class="node-roi-container">
            <div style="position:absolute; width:100%; height:100%; display:flex; align-items:center; justify-content:center; color:#475569; font-size:11px;">
              Live Screen Frame ROI
            </div>
            <div class="roi-overlay-box" style="left:70%; top:80%; width:28%; height:16%;">
              <div class="roi-handle"></div>
            </div>
          </div>
        `;
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

    /* -------------------------------------------------------------
       Floating Toolbar & Spawn Palette
       ------------------------------------------------------------- */
    initToolbar() {
      const tb = document.getElementById("studio-toolbar");
      if (!tb) return;

      document.getElementById("btn-add-node")?.addEventListener("click", () => {
        this.openSpawnPalette(window.innerWidth / 2 - 130, 160);
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

      const renderItems = (filterText = "") => {
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

      renderItems();

      search?.addEventListener("input", (e) => {
        renderItems(e.target.value);
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
        } else if (["AudioMonitorNode", "ChatVelocityNode", "OCRVisionNode", "ScreenSummarizerNode"].includes(node.type)) {
          node.position = [col2X, yCounters.col2];
          yCounters.col2 += 220;
        } else if (node.type === "GateEvaluatorNode") {
          node.position = [col3X, yCounters.col3];
          yCounters.col3 += 200;
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
