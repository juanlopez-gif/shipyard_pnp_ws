(function () {
  "use strict";

  const layout = window.ShipyardLayout;
  const catalog = window.ShipyardRunCatalog || {};
  const runs = (catalog.runs && catalog.runs.length ? catalog.runs : [window.ShipyardSampleRun]).filter(Boolean);
  let run = runs.find((candidate) => candidate.id === catalog.defaultRunId) || runs[0];
  const svg = document.getElementById("layout-svg");
  const playToggle = document.getElementById("play-toggle");
  const restartButton = document.getElementById("restart");
  const runSelect = document.getElementById("run-select");
  const timeline = document.getElementById("timeline");
  const speed = document.getElementById("speed");
  const timeNow = document.getElementById("time-now");
  const duration = document.getElementById("duration");
  const runContext = document.getElementById("run-context");
  const orderStrip = document.getElementById("order-strip");
  const decisionsList = document.getElementById("decisions-list");
  const conditionsList = document.getElementById("conditions-list");
  const statusGrid = document.getElementById("status-grid");
  const sourceList = document.getElementById("source-list");

  const nodeById = new Map(layout.nodes.map((node) => [node.id, node]));
  let pieceMeta = new Map((run?.pieces || []).map((piece) => [piece.id, piece]));
  let storageSlotLookup = new Map();
  let currentTime = 0;
  let teachTime = 0;
  let teachSelectedResource = "xarm2";
  let teachSelectedActionId = "teach_xarm2_red_to_c1";
  let teachAnimating = false;
  let playing = false;
  let lastTick = 0;
  let routeFilter = "all";
  const TEACH_DEMO_DURATION = 4.2;

  const STATUS_CLASS = {
    IDLE: "idle",
    STOPPED: "stopped",
    CLOSED: "closed",
    EMPTY: "empty",
    WORKING: "working",
    RUNNING: "running",
    MOVING: "moving",
    PREPARING: "preparing",
    OPENING: "opening",
    CLOSING: "closing",
    READY: "ready",
    CLEAR: "clear",
    AVAILABLE: "available",
    FREE: "free",
    FINISHED: "finished",
    ON: "on",
    OPEN: "open",
    BLOCKED: "blocked",
    WAITING: "waiting",
    OCCUPIED: "occupied",
    HOLDING: "holding",
    ERROR: "error"
  };

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function statusName(value) {
    const key = String(value || "UNKNOWN").toUpperCase();
    return STATUS_CLASS[key] || "unknown";
  }

  function stateLabel(value) {
    const text = String(value || "Unknown").replace(/_/g, " ").toLowerCase();
    return text.replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function resourceState(resources, key) {
    const value = resources?.[key];
    if (value && typeof value === "object") return value.state || "UNKNOWN";
    return value || "UNKNOWN";
  }

  function resourceDetail(resources, details, key) {
    const value = details?.[key] || resources?.[key];
    if (value && typeof value === "object") return value.detail || value.state || "UNKNOWN";
    return value || "UNKNOWN";
  }

  function isTeachMode() {
    return routeFilter === "teach";
  }

  function nodeForResource(id) {
    return nodeById.get(id) || layout.nodes.find((node) => node.statusKey === id) || null;
  }

  function visualNodeIdForResource(id) {
    return nodeById.has(id) ? id : nodeForResource(id)?.id || id;
  }

  function resourceKeyForCondition(condition) {
    if (condition.resource) return condition.resource;
    const aliases = {
      "xArm1": "xarm1",
      "xArm2": "xarm2",
      "Niryo 1": "robot1",
      "Niryo 2": "robot2",
      "Initial Stack": "initial_stack",
      "Laser engraver": "laser",
      "Laser bed": "laser",
      "Bantam CNC": "bantam",
      "CNC bed": "bantam",
      "Blue Buffer": "intermediate_blue_stack",
      "Red Final": "final_red_stack",
      "Blue Final": "final_blue_stack",
      "Green Final": "final_green_stack",
      "Conveyor 1": "conveyor1",
      "Conveyor 1 entry": "conveyor1",
      "Conveyor 1 exit": "conveyor1",
      "Conveyor 2": "conveyor2",
      "Conveyor 2 entry": "conveyor2",
      "Conveyor 2 exit": "conveyor2",
      "Conveyor 3": "conveyor3",
      "Conveyor 3 entry": "conveyor3",
      "Conveyor 3 exit": "conveyor3",
      "Conveyor 4": "conveyor4",
      "Conveyor 4 entry": "conveyor4",
      "Conveyor 4 exit": "conveyor4"
    };
    return aliases[condition.label] || null;
  }

  function teachingActions() {
    return layout.teachingActions || [];
  }

  function actionsForResource(resourceId) {
    return teachingActions().filter((action) =>
      action.actor === resourceId || (action.highlightResources || []).includes(resourceId)
    );
  }

  function sortTeachActions(actions) {
    return [...actions].sort((a, b) => {
      const conflictDelta = Number(Boolean(b.deferredActions?.length)) - Number(Boolean(a.deferredActions?.length));
      if (conflictDelta) return conflictDelta;
      return (a.priorityOrder || 50) - (b.priorityOrder || 50);
    });
  }

  function currentTeachActions() {
    const direct = teachingActions().filter((action) => action.actor === teachSelectedResource);
    return sortTeachActions(direct.length ? direct : actionsForResource(teachSelectedResource));
  }

  function currentTeachAction() {
    const actions = currentTeachActions();
    return actions.find((action) => action.id === teachSelectedActionId) || actions[0] || null;
  }

  function teachDecisionForAction(action) {
    if (!action) return null;
    return {
      title: labelForActor(action.actor),
      actor: action.actor,
      focus: action.actor,
      state: "Teaching",
      summary: action.label,
      flow: {
        condition: action.condition,
        decision: action.decision,
        action: action.label
      },
      conditions: (action.conditions || []).map((condition) => condition.value || condition.label),
      highlightResources: action.highlightResources || [],
      feasibleActions: [action],
      selected: action.id,
      selectedReason: action.decision
    };
  }

  function teachResourcesAndDetails(action) {
    const resources = {
      xarm1: "IDLE",
      xarm2: "IDLE",
      robot1: "IDLE",
      robot2: "IDLE",
      laser: "IDLE",
      bantam: "IDLE",
      conveyor1: "STOPPED",
      conveyor2: "STOPPED",
      conveyor3: "STOPPED",
      conveyor4: "STOPPED",
      c3: "CLEAR",
      c4: "CLEAR",
      initial_stack: "READY",
      intermediate_blue_stack: "EMPTY",
      final_red_stack: "EMPTY",
      final_blue_stack: "EMPTY",
      final_green_stack: "EMPTY"
    };
    const details = { ...resources };
    if (!action) return { resources, details };

    (action.conditions || []).forEach((condition) => {
      const key = resourceKeyForCondition(condition);
      if (!key) return;
      resources[key] = condition.state || resources[key] || "READY";
      details[key] = condition.value ? `${condition.label}: ${condition.value}` : condition.label;
    });

    (action.highlightResources || []).forEach((id) => {
      const node = nodeById.get(id);
      const state = resources[node?.statusKey];
      if (!node?.statusKey || !["IDLE", "STOPPED", "EMPTY", "CLEAR"].includes(state)) return;
      resources[node.statusKey] = "READY";
      details[node.statusKey] = "Required";
    });

    const moving = teachTime > 0 && teachTime < TEACH_DEMO_DURATION;
    if (action.actor) {
      resources[action.actor] = action.type === "work" && moving ? "WORKING" : moving ? "MOVING" : "READY";
      details[action.actor] = moving ? action.title : "Selected";
    }
    if (action.type === "work" && action.at) {
      const node = nodeById.get(action.at);
      if (node?.statusKey) {
        resources[node.statusKey] = moving ? "WORKING" : "READY";
        details[node.statusKey] = moving ? `Processing ${action.color}` : `${action.color} piece loaded`;
      }
    }
    return { resources, details };
  }

  function compactText(value, maxLength) {
    const text = String(value || "UNKNOWN");
    if (text.length <= maxLength) return text;
    return `${text.slice(0, Math.max(1, maxLength - 3))}...`;
  }

  function wrapWords(value, maxChars, maxLines) {
    const words = String(value || "Unknown").split(/\s+/).filter(Boolean);
    const lines = [];
    let line = "";
    words.forEach((word) => {
      const next = line ? `${line} ${word}` : word;
      if (next.length <= maxChars || !line) {
        line = next;
        return;
      }
      lines.push(line);
      line = word;
    });
    if (line) lines.push(line);
    return lines.slice(0, maxLines || lines.length);
  }

  function stackGridMetrics(node) {
    const rows = 3;
    const cols = 6;
    const gap = 10;
    const left = node.x + 18;
    const top = node.y + 58;
    const cellW = (node.w - 36 - gap * (cols - 1)) / cols;
    const cellH = (node.h - 76 - gap * (rows - 1)) / rows;
    return { rows, cols, gap, left, top, cellW, cellH };
  }

  function storageGridMetrics(node) {
    const layoutConfig = node.slotLayout || {};
    const rows = layoutConfig.rows || 1;
    const cols = layoutConfig.cols || layoutConfig.capacity || 1;
    const gap = layoutConfig.gap == null ? 6 : layoutConfig.gap;
    const padX = layoutConfig.padX == null ? 10 : layoutConfig.padX;
    const padY = layoutConfig.padY == null ? 30 : layoutConfig.padY;
    const left = node.x + padX;
    const top = node.y + padY;
    const cellW = (node.w - padX * 2 - gap * (cols - 1)) / cols;
    const cellH = (node.h - padY - 10 - gap * (rows - 1)) / rows;
    return { rows, cols, gap, left, top, cellW, cellH };
  }

  function buildStorageSlotLookup() {
    storageSlotLookup = new Map();
    layout.nodes.filter((node) => node.slotLayout).forEach((node) => {
      const entries = [];
      (run.pieces || []).forEach((piece) => {
        const frames = keyframesForPiece(piece.id);
        const firstArrival = frames.find((frame) => frame.location === node.id);
        if (firstArrival) {
          entries.push({ pieceId: piece.id, time: firstArrival.time });
        }
      });
      entries.sort((a, b) => a.time - b.time || a.pieceId.localeCompare(b.pieceId));
      const capacity = node.slotLayout.capacity || node.slotLayout.rows * node.slotLayout.cols || entries.length || 1;
      const slots = new Map();
      entries.forEach((entry, index) => {
        slots.set(entry.pieceId, index % capacity);
      });
      storageSlotLookup.set(node.id, slots);
    });
  }

  function storageSlotPosition(node, pieceId) {
    const { cols, left, top, cellW, cellH, gap } = storageGridMetrics(node);
    const index = storageSlotLookup.get(node.id)?.get(pieceId) || 0;
    const col = index % cols;
    const row = Math.floor(index / cols);
    return {
      x: left + col * (cellW + gap) + cellW / 2,
      y: top + row * (cellH + gap) + cellH / 2
    };
  }

  function centerOf(id) {
    const node = nodeById.get(id);
    if (!node) return { x: 0, y: 0 };
    if (node.kind === "anchor") return { x: node.x, y: node.y };
    if (node.w && node.h) return { x: node.x + node.w / 2, y: node.y + node.h / 2 };
    if (node.kind === "robot") return { x: node.x, y: node.y };
    return { x: node.x + node.w / 2, y: node.y + node.h / 2 };
  }

  function drawResourceBadge(node, resources, details, routeOnly) {
    if (routeOnly || !node.statusKey) return "";
    const status = resourceState(resources, node.statusKey);
    const detail = resourceDetail(resources, details, node.statusKey);
    const cls = statusName(status);
    const center = centerOf(node.id);
    const badge = node.statusBadge || { x: center.x, y: node.y + node.h + 18, w: 118 };
    const width = badge.w || 118;
    const left = badge.align === "left" ? badge.x : badge.x - width / 2;
    const maxLength = Math.max(16, Math.floor((width - 24) / 5.7));
    const display = detail && detail !== status ? detail : stateLabel(status);
    const lines = wrapWords(display, maxLength, badge.maxLines || 3);
    const lineHeight = 11;
    const height = lines.length * lineHeight + 9;
    const top = badge.y - 14;
    const text = lines.map((line, index) =>
      `<tspan x="${left + 18}" dy="${index === 0 ? 0 : lineHeight}">${esc(line)}</tspan>`
    ).join("");
    const transform = badge.rotate ? ` transform="rotate(${badge.rotate} ${badge.x} ${badge.y})"` : "";
    return `
      <g class="resource-state"${transform}>
        <title>${esc(node.label)}: ${esc(display)}</title>
        <rect class="resource-state-bg" x="${left}" y="${top}" width="${width}" height="${height}" rx="5"></rect>
        <circle class="resource-state-dot status-${cls}" cx="${left + 8}" cy="${top + 11}" r="4"></circle>
        <text class="resource-state-text" x="${left + 18}" y="${top + 15}">${text}</text>
      </g>
    `;
  }

  function selectedAction(frame) {
    const decision = frame.decision || {};
    return (decision.feasibleActions || []).find((action) => action.id === decision.selected) || null;
  }

  function frameIndexAt(time) {
    let index = 0;
    for (let i = 0; i < run.frames.length; i += 1) {
      if (run.frames[i].time <= time) index = i;
    }
    return index;
  }

  function frameAt(time) {
    return run.frames[frameIndexAt(time)];
  }

  function nextFrameAt(time) {
    const next = run.frames[frameIndexAt(time) + 1];
    return next || null;
  }

  function pieceState(frame, id) {
    return (frame.pieces || []).find((piece) => piece.id === id) || null;
  }

  function labelForActor(id) {
    const node = nodeForResource(id);
    return node?.label ? node.label.replace(/\n/g, " ") : id;
  }

  function slotPosition(node, slot) {
    if (node.slotPositions && node.slotPositions[slot]) {
      return node.slotPositions[slot];
    }
    const match = String(slot || "").match(/^s([1-3])\.([1-6])$/);
    const row = match ? Number(match[1]) - 1 : 0;
    const col = match ? Number(match[2]) - 1 : 0;
    const { gap, left, top, cellW, cellH } = stackGridMetrics(node);
    return {
      x: left + col * (cellW + gap) + cellW / 2,
      y: top + row * (cellH + gap) + cellH / 2
    };
  }

  function pointForLocation(location, id, slot) {
    const node = nodeById.get(location);
    if (!node) return null;
    if (node.slotPositions && node.slotPositions[id]) {
      return node.slotPositions[id];
    }
    if (node.slotPositions && slot && node.slotPositions[slot]) {
      return node.slotPositions[slot];
    }
    if (node.slotLayout) {
      return storageSlotPosition(node, id);
    }
    if (location === "initial_stack") {
      return slotPosition(node, slot || pieceMeta.get(id)?.slot);
    }
    return centerOf(location);
  }

  function keyframesForPiece(id) {
    const keyframes = run.pieceKeyframes || {};
    return keyframes[id] || [];
  }

  function pieceVisualStateAt(time, id) {
    const keyframes = keyframesForPiece(id);
    if (!keyframes.length) return null;
    let currentKeyframe = keyframes[0];
    for (let i = 1; i < keyframes.length; i += 1) {
      if (keyframes[i].time <= time) currentKeyframe = keyframes[i];
      else break;
    }
    return currentKeyframe;
  }

  function pointForKeyframe(keyframe, id) {
    return pointForLocation(keyframe.location || keyframe.at, id, keyframe.slot);
  }

  function teachPointForLocation(location) {
    const slot = location === "initial_stack" ? "s1.1" : null;
    return pointForLocation(location, "teach-piece", slot);
  }

  function teachPiecePosition(action) {
    if (!action) return null;
    const path = action.demoPath && action.demoPath.length ? action.demoPath : [action.from || action.at, action.to || action.at].filter(Boolean);
    const points = path.map(teachPointForLocation).filter(Boolean);
    if (!points.length) return null;
    if (points.length === 1) return points[0];

    const progress = Math.max(0, Math.min(1, teachTime / TEACH_DEMO_DURATION));
    const scaled = progress * (points.length - 1);
    const index = Math.min(points.length - 2, Math.floor(scaled));
    const local = scaled - index;
    const eased = local < 0.5 ? 2 * local * local : 1 - Math.pow(-2 * local + 2, 2) / 2;
    const from = points[index];
    const to = points[index + 1];
    return {
      x: from.x + (to.x - from.x) * eased,
      y: from.y + (to.y - from.y) * eased
    };
  }

  function drawTeachPiece(action) {
    if (!action) return "";
    const position = teachPiecePosition(action);
    if (!position) return "";
    const color = String(action.color || "blue").toLowerCase();
    const usesGripper = (action.demoPath || []).some((location) => String(location).endsWith("_gripper"));
    const held = usesGripper && action.type !== "work" && teachTime > TEACH_DEMO_DURATION * 0.2 && teachTime < TEACH_DEMO_DURATION * 0.82;
    const size = 13;
    const workPulse = action.type === "work" && teachTime > 0 && teachTime < TEACH_DEMO_DURATION ? " piece-demo-work" : "";
    return `
      <g class="piece piece-demo ${held ? "piece-held" : ""}${workPulse}" transform="translate(${position.x} ${position.y})">
        <title>Didactic ${esc(action.color)} piece</title>
        ${held ? `
          <g class="piece-gripper">
            <line x1="${-size - 7}" y1="${-size - 3}" x2="${-size - 2}" y2="${-size + 8}"></line>
            <line x1="${size + 7}" y1="${-size - 3}" x2="${size + 2}" y2="${-size + 8}"></line>
          </g>
        ` : ""}
        <circle class="piece-token piece-${color}" cx="0" cy="0" r="${size}"></circle>
        <text class="piece-label" x="0" y="4">${esc(String(action.color || "?").slice(0, 1))}</text>
      </g>
    `;
  }

  function drawTeachConflictPieces(action) {
    return (action?.conflictPieces || []).map((piece, index) => {
      const id = piece.id || `teach-conflict-${index}`;
      const position = pointForLocation(piece.location, id, piece.slot);
      if (!position) return "";
      const color = String(piece.color || "blue").toLowerCase();
      const size = piece.size || 12;
      const label = piece.label || String(piece.color || "?").slice(0, 1);
      const labelText = piece.note || "deferred";
      const offset = piece.labelOffset || { x: 18, y: -22 };
      const labelWidth = Math.max(68, labelText.length * 6 + 20);
      return `
        <g class="piece piece-conflict" transform="translate(${position.x} ${position.y})">
          <title>${esc(labelText)}: ${esc(piece.color || "piece")} at ${esc(labelForActor(piece.location))}</title>
          <circle class="piece-conflict-ring" cx="0" cy="0" r="${size + 8}"></circle>
          <circle class="piece-token piece-${color}" cx="0" cy="0" r="${size}"></circle>
          <text class="piece-label" x="0" y="4">${esc(label)}</text>
          <g class="conflict-piece-label" transform="translate(${offset.x} ${offset.y})">
            <rect x="0" y="-13" width="${labelWidth}" height="20" rx="5"></rect>
            <text x="${labelWidth / 2}" y="1">${esc(labelText)}</text>
          </g>
        </g>
      `;
    }).join("");
  }

  function piecePositionAt(time, id) {
    const keyframes = keyframesForPiece(id);
    if (keyframes.length) {
      if (time <= keyframes[0].time) return pointForKeyframe(keyframes[0], id);

      let currentKeyframe = keyframes[0];
      let nextKeyframe = null;
      for (let i = 1; i < keyframes.length; i += 1) {
        if (keyframes[i].time <= time) {
          currentKeyframe = keyframes[i];
        } else {
          nextKeyframe = keyframes[i];
          break;
        }
      }

      const from = pointForKeyframe(currentKeyframe, id);
      if (!from || !nextKeyframe) return from;

      const to = pointForKeyframe(nextKeyframe, id);
      if (!to) return from;

      const sameLocation = (currentKeyframe.location || currentKeyframe.at) === (nextKeyframe.location || nextKeyframe.at);
      const sameSlot = (currentKeyframe.slot || "") === (nextKeyframe.slot || "");
      if (sameLocation && sameSlot) return from;

      const span = Math.max(0.1, nextKeyframe.time - currentKeyframe.time);
      const raw = Math.max(0, Math.min(1, (time - currentKeyframe.time) / span));
      const eased = raw < 0.5 ? 2 * raw * raw : 1 - Math.pow(-2 * raw + 2, 2) / 2;
      return {
        x: from.x + (to.x - from.x) * eased,
        y: from.y + (to.y - from.y) * eased
      };
    }

    const current = frameAt(time);
    const next = nextFrameAt(time);
    const currentState = pieceState(current, id);
    if (!currentState) return null;

    const from = pointForLocation(currentState.location, id, currentState.slot);
    if (!from) return null;

    const nextState = next ? pieceState(next, id) : null;
    if (!nextState || nextState.location === currentState.location) {
      return from;
    }

    const to = pointForLocation(nextState.location, id, nextState.slot);
    if (!to) return from;

    const span = Math.max(0.1, next.time - current.time);
    const raw = (time - current.time) / span;
    const eased = raw < 0.5 ? 2 * raw * raw : 1 - Math.pow(-2 * raw + 2, 2) / 2;
    return {
      x: from.x + (to.x - from.x) * eased,
      y: from.y + (to.y - from.y) * eased
    };
  }

  function pathForRoute(route) {
    return route.nodes.map((id, index) => {
      const point = centerOf(id);
      return `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`;
    }).join(" ");
  }

  function segmentPath(fromId, toId) {
    const from = centerOf(fromId);
    const to = centerOf(toId);
    return `M ${from.x} ${from.y} L ${to.x} ${to.y}`;
  }

  function segmentKey(routeId, fromId, toId) {
    return `${routeId}:${fromId}->${toId}`;
  }

  function routeForAction(action) {
    const color = String(action?.color || "").toLowerCase();
    if (!color) return null;
    return layout.routes.find((route) => route.id === color) || null;
  }

  function routeSegmentsForAction(action) {
    if (!action?.from || !action?.to) return [];
    const color = String(action.color || "").toLowerCase();
    const routes = layout.routes.filter((route) =>
      route.id === color || String(route.color || "").toLowerCase() === color
    );
    for (const route of routes) {
      const fromIndex = route.nodes.indexOf(action.from);
      const toIndex = route.nodes.indexOf(action.to);
      if (fromIndex < 0 || toIndex < 0 || fromIndex >= toIndex) continue;
      return route.nodes.slice(fromIndex, toIndex).map((fromId, index) => ({
        routeId: route.id,
        fromId,
        toId: route.nodes[fromIndex + index + 1]
      }));
    }
    return [];
  }

  function curvePath(fromId, toId) {
    const from = centerOf(fromId);
    const to = centerOf(toId);
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const cx = from.x + dx * 0.5 - dy * 0.12;
    const cy = from.y + dy * 0.5 + dx * 0.12;
    return `M ${from.x} ${from.y} Q ${cx} ${cy} ${to.x} ${to.y}`;
  }

  function drawDefs() {
    return `
      <defs>
        <marker id="flow-red" markerWidth="18" markerHeight="18" refX="16" refY="9" orient="auto" markerUnits="userSpaceOnUse">
          <path d="M 3 3 L 16 9 L 3 15 z" fill="#d94848"></path>
        </marker>
        <marker id="flow-blue" markerWidth="18" markerHeight="18" refX="16" refY="9" orient="auto" markerUnits="userSpaceOnUse">
          <path d="M 3 3 L 16 9 L 3 15 z" fill="#2d6cdf"></path>
        </marker>
        <marker id="flow-green" markerWidth="18" markerHeight="18" refX="16" refY="9" orient="auto" markerUnits="userSpaceOnUse">
          <path d="M 3 3 L 16 9 L 3 15 z" fill="#2c9a58"></path>
        </marker>
      </defs>
    `;
  }

  function drawRoute(route, activeSegments) {
    const active = routeFilter === "all" || routeFilter === route.id;
    const decisionOnly = routeFilter === "decision";
    const hasActiveDecisionSegment = Boolean(activeSegments?.size);
    return route.nodes.slice(0, -1).map((fromId, index) => {
      const toId = route.nodes[index + 1];
      const decisionActive = activeSegments?.has(segmentKey(route.id, fromId, toId));
      const contextOnly = active && !decisionOnly && hasActiveDecisionSegment && !decisionActive;
      const cls = [
        "route-line",
        `route-${route.id}`,
        decisionActive ? "route-decision-active" : "",
        decisionActive ? "route-strong" : contextOnly ? "route-context" : active && !decisionOnly ? "route-strong" : "route-dim"
      ].join(" ");
      return `<path class="${cls}" d="${segmentPath(fromId, toId)}"></path>`;
    }).join("");
  }

  function drawRouteFlowSegment(route, fromId, toId, index) {
    return `
      <path
        class="route-flow route-flow-${route.id}"
        d="${curvePath(fromId, toId)}"
        marker-end="url(#flow-${route.id})"
        style="--route-index:${index}"
      ></path>
    `;
  }

  function drawRouteOnlyView() {
    const routeSegments = layout.routes.flatMap((route) =>
      route.nodes.slice(0, -1).map((fromId, index) => drawRouteFlowSegment(route, fromId, route.nodes[index + 1], index))
    ).join("");

    const markers = (layout.pickDropoffMarkers || []).map((id) => {
      const point = centerOf(id);
      return `
        <g class="pickup-marker">
          <line x1="${point.x - 7}" y1="${point.y - 7}" x2="${point.x + 7}" y2="${point.y + 7}"></line>
          <line x1="${point.x + 7}" y1="${point.y - 7}" x2="${point.x - 7}" y2="${point.y + 7}"></line>
        </g>
      `;
    }).join("");

    return `${routeSegments}${markers}`;
  }

  function drawStatusDot(x, y, status) {
    const cls = statusName(status);
    return `<circle class="status-dot status-${cls}" cx="${x}" cy="${y}" r="7"></circle>`;
  }

  function drawRobot(node, resources, details, routeOnly) {
    const status = resourceState(resources, node.statusKey);
    const cls = statusName(status);
    const bodyClass = node.robotType === "niryo" ? "niryo-body" : "xarm-body";
    return `
      <g class="resource">
        <title>${esc(node.label)}: ${esc(status)}</title>
        <rect class="resource-shadow" x="${node.x + 4}" y="${node.y + 5}" width="${node.w}" height="${node.h}" rx="2"></rect>
        <rect class="${bodyClass} status-outline-${cls}" x="${node.x}" y="${node.y}" width="${node.w}" height="${node.h}" rx="1"></rect>
        <text class="resource-label" x="${node.x + node.w / 2}" y="${node.y + node.h / 2 + 5}">${esc(node.label)}</text>
        ${drawResourceBadge(node, resources, details, routeOnly)}
      </g>
    `;
  }

  function drawStack(node, resources, details, routeOnly) {
    const status = resourceState(resources, node.statusKey);
    const cls = statusName(status);
    let slots = "";
    const gap = 6;
    const cellW = (node.w - 28 - gap * 2) / 3;
    const cellH = (node.h - 58 - gap * 5) / 6;
    for (let col = 0; col < 3; col += 1) {
      for (let row = 0; row < 6; row += 1) {
        const x = node.x + 14 + col * (cellW + gap);
        const y = node.y + 44 + row * (cellH + gap);
        slots += `<rect class="stack-slot" x="${x}" y="${y}" width="${cellW}" height="${cellH}" rx="4"></rect>`;
      }
    }
    return `
      <g class="resource">
        <title>${esc(node.label)}: ${esc(status)}</title>
        <rect class="resource-shadow" x="${node.x + 5}" y="${node.y + 7}" width="${node.w}" height="${node.h}" rx="8"></rect>
        <rect class="resource-body status-outline-${cls}" x="${node.x}" y="${node.y}" width="${node.w}" height="${node.h}" rx="8"></rect>
        <text class="resource-label" x="${node.x + node.w / 2}" y="${node.y + 26}">${esc(node.label)}</text>
        ${slots}
        ${drawResourceBadge(node, resources, details, routeOnly)}
      </g>
    `;
  }

  function drawItemStack(node, resources, details, routeOnly) {
    const status = resourceState(resources, node.statusKey);
    const cls = statusName(status);
    const center = centerOf(node.id);
    const { rows, cols, gap, left, top, cellW, cellH } = stackGridMetrics(node);
    let slots = "";
    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < cols; col += 1) {
        const x = left + col * (cellW + gap);
        const y = top + row * (cellH + gap);
        slots += `<rect class="initial-stack-slot" x="${x}" y="${y}" width="${cellW}" height="${cellH}" rx="5"></rect>`;
      }
    }
    return `
      <g class="resource">
        <title>${esc(node.label)}: ${esc(status)}</title>
        <rect class="resource-shadow" x="${node.x + 5}" y="${node.y + 7}" width="${node.w}" height="${node.h}" rx="6"></rect>
        <rect class="initial-stack-body status-outline-${cls}" x="${node.x}" y="${node.y}" width="${node.w}" height="${node.h}" rx="6"></rect>
        ${multilineLabel(node.label, center.x, node.y + 28, 18, "resource-label stack-title")}
        ${slots}
        ${drawResourceBadge(node, resources, details, routeOnly)}
      </g>
    `;
  }

  function drawStorageNode(node, resources, details, routeOnly, bodyClass) {
    const status = resourceState(resources, node.statusKey);
    const cls = statusName(status);
    const center = centerOf(node.id);
    const { rows, cols, gap, left, top, cellW, cellH } = storageGridMetrics(node);
    const colorClass = node.stackColor ? `storage-${node.stackColor}` : "";
    let slots = "";
    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < cols; col += 1) {
        const x = left + col * (cellW + gap);
        const y = top + row * (cellH + gap);
        slots += `<rect class="storage-slot ${colorClass}" x="${x}" y="${y}" width="${cellW}" height="${cellH}" rx="5"></rect>`;
      }
    }
    return `
      <g class="resource storage-resource">
        <title>${esc(node.label)}: ${esc(status)}</title>
        <rect class="resource-shadow" x="${node.x + 4}" y="${node.y + 5}" width="${node.w}" height="${node.h}" rx="6"></rect>
        <rect class="${bodyClass} status-outline-${cls}" x="${node.x}" y="${node.y}" width="${node.w}" height="${node.h}" rx="6"></rect>
        ${multilineLabel(node.label, center.x, node.y + 22, 13, "resource-label storage-title")}
        ${slots}
        ${drawResourceBadge(node, resources, details, routeOnly)}
      </g>
    `;
  }

  function drawConveyor(node, resources, details, routeOnly) {
    const status = resourceState(resources, node.statusKey);
    const cls = statusName(status);
    const rollers = [];
    const vertical = node.h > node.w * 1.4;
    if (vertical) {
      for (let y = node.y + 24; y < node.y + node.h - 10; y += 24) {
        rollers.push(`<line class="conveyor-roller" x1="${node.x + 12}" y1="${y}" x2="${node.x + node.w - 12}" y2="${y}"></line>`);
      }
    } else {
      for (let x = node.x + 25; x < node.x + node.w - 10; x += 24) {
        rollers.push(`<line class="conveyor-roller" x1="${x}" y1="${node.y + 12}" x2="${x}" y2="${node.y + node.h - 12}"></line>`);
      }
    }
    const sensors = (node.sensors || []).map((sensor) => {
      const sx = sensor.x == null ? node.x + node.w * sensor.at : sensor.x;
      const sy = sensor.y == null ? node.y + node.h + 8 : sensor.y;
      const label = sensor.label ? `<text class="sensor-label" x="${sx}" y="${sy + 20}">${esc(sensor.label)}</text>` : "";
      return `
        <g>
          <circle class="ir-sensor" cx="${sx}" cy="${sy}" r="8"></circle>
          ${label}
        </g>
      `;
    }).join("");
    const center = centerOf(node.id);
    const transform = node.labelRotation ? ` transform="rotate(${node.labelRotation} ${center.x} ${center.y})"` : "";
    return `
      <g class="resource">
        <title>${esc(node.label)}: ${esc(status)}</title>
        <rect class="resource-shadow" x="${node.x + 4}" y="${node.y + 5}" width="${node.w}" height="${node.h}" rx="2"></rect>
        <rect class="conveyor-body status-outline-${cls}" x="${node.x}" y="${node.y}" width="${node.w}" height="${node.h}" rx="1"></rect>
        ${rollers.join("")}
        <text class="resource-label"${transform} x="${center.x}" y="${center.y + 5}">${esc(node.label)}</text>
        ${sensors}
        ${drawResourceBadge(node, resources, details, routeOnly)}
      </g>
    `;
  }

  function multilineLabel(label, x, y, lineHeight, className) {
    const lines = String(label || "").split("\n");
    const start = y - ((lines.length - 1) * lineHeight) / 2;
    return lines.map((line, index) =>
      `<text class="${className}" x="${x}" y="${start + index * lineHeight}">${esc(line)}</text>`
    ).join("");
  }

  function drawBoxNode(node, resources, details, routeOnly, bodyClass) {
    const hasStatus = Boolean(node.statusKey);
    const status = hasStatus ? resourceState(resources, node.statusKey) : "";
    const cls = statusName(status);
    const center = centerOf(node.id);
    return `
      <g class="resource">
        <title>${esc(node.label)}${hasStatus ? `: ${esc(status)}` : ""}</title>
        <rect class="resource-shadow" x="${node.x + 4}" y="${node.y + 5}" width="${node.w}" height="${node.h}" rx="2"></rect>
        <rect class="${bodyClass} ${hasStatus ? `status-outline-${cls}` : ""}" x="${node.x}" y="${node.y}" width="${node.w}" height="${node.h}" rx="1"></rect>
        ${multilineLabel(node.label, center.x, center.y + 4, 20, "resource-label")}
        ${drawResourceBadge(node, resources, details, routeOnly)}
      </g>
    `;
  }

  function drawHandoff(node, resources, details, routeOnly) {
    const status = resourceState(resources, node.statusKey);
    const cls = statusName(status);
    return `
      <g class="resource">
        <title>${esc(node.label)}: ${esc(status)}</title>
        <rect class="sensor-mark status-outline-${cls}" x="${node.x}" y="${node.y}" width="${node.w}" height="${node.h}" rx="8"></rect>
        <text class="resource-label" x="${node.x + node.w / 2}" y="${node.y + node.h / 2 + 5}">${esc(node.label)}</text>
        ${drawResourceBadge(node, resources, details, routeOnly)}
      </g>
    `;
  }

  function drawFiducial(node) {
    return `
      <g class="resource">
        <title>${esc(node.label)}</title>
        <circle class="fiducial-marker" cx="${node.x}" cy="${node.y}" r="${node.r || 7}"></circle>
      </g>
    `;
  }

  function drawSubmarine(node) {
    const cx = node.x + node.w / 2;
    const cy = node.y + node.h / 2;
    return `
      <g class="resource">
        <title>${esc(node.label)}</title>
        <ellipse class="submarine-body" cx="${cx}" cy="${cy}" rx="${node.w / 2}" ry="${node.h / 2}"></ellipse>
        <rect class="submarine-side" x="${node.x + node.w * 0.64}" y="${node.y + 8}" width="${node.w * 0.28}" height="${node.h - 16}" rx="18"></rect>
        <line class="submarine-leg" x1="${node.x + 28}" y1="${node.y + node.h * 0.64}" x2="${node.x + 8}" y2="${node.y + node.h + 16}"></line>
        <line class="submarine-leg" x1="${node.x + 50}" y1="${node.y + node.h * 0.68}" x2="${node.x + 28}" y2="${node.y + node.h + 16}"></line>
      </g>
    `;
  }

  function drawNode(node, resources, details, routeOnly) {
    if (node.visible === false) return "";
    if (node.kind === "anchor") return "";
    if (node.slotLayout && node.kind !== "item_stack") {
      const bodyClass = node.kind === "ibs" ? "ibs-body" : "output-stack-body";
      return drawStorageNode(node, resources, details, routeOnly, bodyClass);
    }
    if (node.kind === "robot") return drawRobot(node, resources, details, routeOnly);
    if (node.kind === "item_stack") return drawItemStack(node, resources, details, routeOnly);
    if (node.kind === "stack") return drawStack(node, resources, details, routeOnly);
    if (node.kind === "conveyor") return drawConveyor(node, resources, details, routeOnly);
    if (node.kind === "handoff") return drawHandoff(node, resources, details, routeOnly);
    if (node.kind === "laser") return drawBoxNode(node, resources, details, routeOnly, "laser-body");
    if (node.kind === "bantam") return drawBoxNode(node, resources, details, routeOnly, "bantam-body");
    if (node.kind === "ibs") return drawBoxNode(node, resources, details, routeOnly, "ibs-body");
    if (node.kind === "submarine") return drawSubmarine(node);
    if (node.kind === "fiducial") return drawFiducial(node);
    if (node.kind === "machine") return drawBoxNode(node, resources, details, routeOnly, "machine-body");
    if (node.kind === "camera") return drawBoxNode(node, resources, details, routeOnly, "camera-body");
    if (node.kind === "sink") return drawBoxNode(node, resources, details, routeOnly, "sink-body");
    if (node.kind === "buffer" || node.kind === "door") return drawBoxNode(node, resources, details, routeOnly, "buffer-body");
    return drawBoxNode(node, resources, details, routeOnly, "resource-body");
  }

  function svgPointFromEvent(event) {
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const matrix = svg.getScreenCTM();
    return matrix ? point.matrixTransform(matrix.inverse()) : { x: 0, y: 0 };
  }

  function isVisibleTeachingNode(node) {
    return node.visible !== false && node.kind !== "anchor" && node.kind !== "fiducial";
  }

  function nodeContainsPoint(node, point) {
    if (!isVisibleTeachingNode(node)) return false;
    if (node.w && node.h) {
      return point.x >= node.x && point.x <= node.x + node.w && point.y >= node.y && point.y <= node.y + node.h;
    }
    if (node.r) {
      const dx = point.x - node.x;
      const dy = point.y - node.y;
      return Math.hypot(dx, dy) <= node.r;
    }
    return false;
  }

  function nodeAtEvent(event) {
    const point = svgPointFromEvent(event);
    return [...layout.nodes].reverse().find((node) => nodeContainsPoint(node, point)) || null;
  }

  function selectTeachResource(resourceId) {
    const node = nodeById.get(resourceId);
    teachSelectedResource = node?.statusKey || resourceId;
    const actions = currentTeachActions();
    teachSelectedActionId = actions[0]?.id || null;
    teachTime = 0;
    teachAnimating = false;
    playing = false;
    updatePlaybackButton();
    syncRunControls();
    renderOrderStrip();
    render();
  }

  function drawDecisionEndpoint(point, label, kind, chosen) {
    const markerClass = chosen ? "decision-endpoint chosen" : "decision-endpoint";
    return `
      <g class="${markerClass}">
        <circle class="decision-endpoint-ring ${kind}" cx="${point.x}" cy="${point.y}" r="${chosen ? 18 : 14}"></circle>
        <text class="decision-endpoint-label" x="${point.x}" y="${point.y - 22}">${esc(label)}</text>
      </g>
    `;
  }

  function drawAction(action, chosen, index) {
    if (action.type === "wait" || action.type === "work") {
      const at = centerOf(action.at || "robot2");
      const label = action.type === "work" ? "WORK" : "WAIT";
      const radius = action.radius || (action.type === "work" ? 58 : chosen ? 92 : 78);
      return `
        <g>
          <circle class="wait-ring" cx="${at.x}" cy="${at.y}" r="${radius}"></circle>
          ${chosen ? drawActionLabel(at.x, at.y - radius - 4, label) : ""}
        </g>
      `;
    }
    if (!action.from || !action.to) return "";
    const from = centerOf(action.from);
    const to = centerOf(action.to);
    const color = String(action.color || "").toLowerCase();
    const colorClass = chosen && color ? `decision-color-${color}` : "";
    const cls = chosen ? `decision-chosen ${colorClass}` : "decision-candidate";
    const label = chosen ? "SELECTED" : `OPTION ${index + 1}`;
    const mid = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 - 14 };
    return `
      <g>
        <path class="decision-link ${cls}" d="${curvePath(action.from, action.to)}"></path>
        ${drawDecisionEndpoint(from, "PICK", "pick", chosen)}
        ${drawDecisionEndpoint(to, "PLACE", "place", chosen)}
        ${chosen ? drawActionLabel(mid.x, mid.y, label) : ""}
      </g>
    `;
  }

  function drawActionLabel(x, y, text) {
    return `
      <g>
        <rect class="decision-label-bg" x="${x - 38}" y="${y - 15}" width="76" height="26" rx="6"></rect>
        <text class="decision-label" x="${x}" y="${y + 3}">${esc(text)}</text>
      </g>
    `;
  }

  function drawActorBadge(decision) {
    const actor = visualNodeIdForResource(decision.actor || decision.focus);
    if (!actor) return "";
    const at = centerOf(actor);
    const label = `${labelForActor(decision.actor || actor)} decides`;
    const width = 112;
    const y = at.y - 52;
    return `
      <g class="actor-badge">
        <circle class="decision-halo" cx="${at.x}" cy="${at.y}" r="48"></circle>
        <rect class="actor-badge-bg" x="${at.x - width / 2}" y="${y - 17}" width="${width}" height="28" rx="6"></rect>
        <text class="actor-badge-text" x="${at.x}" y="${y + 2}">${esc(label)}</text>
      </g>
    `;
  }

  function drawDecisionActions(decisions) {
    return decisions.map((decision) => {
      const selected = selectedActionForDecision(decision);
      if (!selected) return drawActorBadge(decision);
      const alternatives = routeFilter === "decision"
        ? (decision.feasibleActions || [])
          .filter((action) => action.id !== selected.id)
          .map((action, index) => drawAction(action, false, index))
          .join("")
        : "";
      return `${alternatives}${drawAction(selected, true, 0)}${drawActorBadge(decision)}`;
    }).join("");
  }

  function selectedActionForDecision(decision) {
    if (!decision) return null;
    return (decision.feasibleActions || []).find((action) => action.id === decision.selected) || (decision.feasibleActions || [])[0] || null;
  }

  function nodeHighlightGeometry(id) {
    const node = nodeById.get(id);
    if (!node) return null;
    if (node.kind === "anchor") {
      const point = centerOf(id);
      return { kind: "circle", x: point.x, y: point.y, r: 18 };
    }
    if (node.w && node.h) {
      return {
        kind: "rect",
        x: node.x - 8,
        y: node.y - 8,
        w: node.w + 16,
        h: node.h + 16
      };
    }
    const point = centerOf(id);
    return { kind: "circle", x: point.x, y: point.y, r: 24 };
  }

  function drawNodeHighlight(id, kind) {
    const geometry = nodeHighlightGeometry(id);
    if (!geometry) return "";
    const cls = `physical-focus ${kind || "related"}`;
    const node = nodeById.get(id);
    const title = node ? node.label : id;
    if (geometry.kind === "rect") {
      return `
        <g class="${cls}">
          <title>${esc(title)}</title>
          <rect x="${geometry.x}" y="${geometry.y}" width="${geometry.w}" height="${geometry.h}" rx="10"></rect>
        </g>
      `;
    }
    return `
      <g class="${cls}">
        <title>${esc(title)}</title>
        <circle cx="${geometry.x}" cy="${geometry.y}" r="${geometry.r}"></circle>
      </g>
    `;
  }

  function drawDecisionFocus(decision) {
    const action = selectedActionForDecision(decision);
    const ids = [];
    if (decision.actor) ids.push({ id: visualNodeIdForResource(decision.actor), kind: "actor" });
    (decision.highlightResources || []).forEach((id) => ids.push({ id, kind: "related" }));
    if (action?.at) ids.push({ id: action.at, kind: "target" });
    if (action?.from) ids.push({ id: action.from, kind: "source" });
    if (action?.to) ids.push({ id: action.to, kind: "target" });

    if (routeFilter === "decision") {
      (decision.feasibleActions || []).forEach((candidate) => {
        if (candidate.at) ids.push({ id: candidate.at, kind: candidate.id === decision.selected ? "target" : "candidate" });
        if (candidate.from) ids.push({ id: candidate.from, kind: candidate.id === decision.selected ? "source" : "candidate" });
        if (candidate.to) ids.push({ id: candidate.to, kind: candidate.id === decision.selected ? "target" : "candidate" });
      });
    }

    const seen = new Set();
    return ids
      .filter((entry) => {
        const key = `${entry.id}:${entry.kind}`;
        if (!entry.id || seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .map((entry) => drawNodeHighlight(entry.id, entry.kind))
      .join("");
  }

  function drawPieces(time) {
    return run.pieces.map((piece) => {
      const position = piecePositionAt(time, piece.id);
      if (!position) return "";
      const visualState = pieceVisualStateAt(time, piece.id);
      const held = String(visualState?.location || "").endsWith("_gripper");
      const colorClass = `piece-${String(piece.color || "").toLowerCase()}`;
      const label = piece.id.replace("piece-", "P");
      const isCircle = piece.shape === "CIRCLE";
      const size = piece.size || 12;
      const token = isCircle
        ? `<circle class="piece-token ${colorClass}" cx="0" cy="0" r="${size}"></circle>`
        : `<rect class="piece-token ${colorClass}" x="${-size}" y="${-size}" width="${size * 2}" height="${size * 2}" rx="3"></rect>`;
      const gripper = held
        ? `
          <g class="piece-gripper">
            <line x1="${-size - 7}" y1="${-size - 3}" x2="${-size - 2}" y2="${-size + 8}"></line>
            <line x1="${size + 7}" y1="${-size - 3}" x2="${size + 2}" y2="${-size + 8}"></line>
          </g>
        `
        : "";
      return `
        <g class="piece ${held ? "piece-held" : ""}" transform="translate(${position.x} ${position.y})">
          <title>${esc(piece.id)} ${esc(piece.color)} ${esc(piece.shape)}</title>
          ${gripper}
          ${token}
          <text class="piece-label" x="0" y="4">${esc(label)}</text>
        </g>
      `;
    }).join("");
  }

  function drawSvg() {
    const frame = frameAt(currentTime);
    const teachAction = currentTeachAction();
    const teachState = teachResourcesAndDetails(teachAction);
    const decisions = isTeachMode()
      ? [teachDecisionForAction(teachAction)].filter(Boolean)
      : frame.activeDecisions || (frame.decision ? [frame.decision] : []);
    const routeOnly = routeFilter === "routes";
    const activeSegments = new Set(decisions
      .flatMap((decision) => routeSegmentsForAction(selectedActionForDecision(decision)))
      .map((segment) => segmentKey(segment.routeId, segment.fromId, segment.toId)));
    const focusMarkup = decisions.map(drawDecisionFocus).join("");
    const routes = routeOnly ? drawRouteOnlyView() : layout.routes.map((route) => drawRoute(route, activeSegments)).join("");
    const resources = isTeachMode() ? teachState.resources : frame.resources || {};
    const details = isTeachMode() ? teachState.details : frame.resourceDetails || {};
    const nodes = layout.nodes.map((node) => drawNode(node, resources, details, routeOnly)).join("");
    const pieces = routeOnly ? "" : isTeachMode() ? `${drawTeachConflictPieces(teachAction)}${drawTeachPiece(teachAction)}` : drawPieces(currentTime);
    svg.setAttribute("viewBox", `0 0 ${layout.viewBox.width} ${layout.viewBox.height}`);
    svg.classList.toggle("teach-mode", isTeachMode());
    svg.innerHTML = `
      ${drawDefs()}
      <text class="floor-label" x="42" y="42">${isTeachMode() ? "Didactic action explorer" : "Physical cell overview"}</text>
      ${routeOnly ? "" : routes}
      ${nodes}
      ${routeOnly ? "" : focusMarkup}
      ${routeOnly ? routes : ""}
      ${pieces}
    `;
  }

  function renderTeachFlowCard(action) {
    if (!action) return "";
    return `
      <article class="decision-card teach-flow-card">
        <div class="decision-card-head">
          <strong>${esc(action.title)}</strong>
          <span>Demo</span>
        </div>
        <ol class="decision-flow-list">
          <li><b>Condition</b><span>${esc(action.condition)}</span></li>
          <li><b>Decision</b><span>${esc(action.decision)}</span></li>
          <li><b>Action</b><span>${esc(action.label)}</span></li>
        </ol>
        ${action.priority ? `
          <div class="teach-priority-block">
            <h3>Fixed Priority</h3>
            <p>${esc(action.priority)}</p>
          </div>
        ` : ""}
        ${action.deferredActions?.length ? `
          <div class="teach-priority-block deferred">
            <h3>Deferred In Fixed</h3>
            <ul>
              ${action.deferredActions.map((deferred) => `
                <li>
                  <strong>${esc(deferred.label)}</strong>
                  <span>${esc(deferred.reason)}</span>
                </li>
              `).join("")}
            </ul>
          </div>
        ` : ""}
      </article>
    `;
  }

  function renderTeachPanel() {
    if (!decisionsList) return;
    const actions = currentTeachActions();
    const selected = currentTeachAction();
    if (!actions.length) {
      decisionsList.innerHTML = `
        <article class="decision-card quiet">
          <div class="decision-card-head">
            <strong>${esc(labelForActor(teachSelectedResource))}</strong>
            <span>No Actions</span>
          </div>
          <p class="decision-card-summary">No didactic action has been mapped for this element yet.</p>
        </article>
      `;
      return;
    }

    decisionsList.innerHTML = `
      <article class="decision-card teach-selected-card">
        <div class="decision-card-head">
          <strong>${esc(labelForActor(teachSelectedResource))}</strong>
          <span>Selected</span>
        </div>
        <p class="decision-card-summary">Fixed-priority action explorer for this resource.</p>
      </article>
      <div class="teach-action-list">
        ${actions.map((action) => {
          const color = String(action.color || "unknown").toLowerCase();
          const active = action.id === selected?.id ? " active" : "";
          const conflict = action.deferredActions?.length ? " teach-conflict" : "";
          const meta = [labelForActor(action.actor), action.caseType || "Fixed action"].filter(Boolean).join(" | ");
          return `
            <button class="teach-action-button teach-${esc(color)}${conflict}${active}" type="button" data-teach-action="${esc(action.id)}">
              <span class="teach-action-title">
                <span class="teach-color-dot teach-color-${esc(color)}"></span>
                ${esc(action.title)}
              </span>
              <span class="teach-action-copy">${esc(action.label)}</span>
              <span class="teach-action-meta">${esc(meta)}</span>
            </button>
            ${action.id === selected?.id ? renderTeachFlowCard(action) : ""}
          `;
        }).join("")}
      </div>
    `;
  }

  function renderDecisionPanel() {
    const frame = frameAt(currentTime);
    const decisions = frame.activeDecisions || (frame.decision ? [frame.decision] : []);
    if (!decisionsList) return;
    if (isTeachMode()) {
      renderTeachPanel();
      return;
    }
    if (!decisions.length) {
      decisionsList.innerHTML = `
        <article class="decision-card quiet">
          <p class="decision-card-summary">Waiting for the next physical decision.</p>
        </article>
      `;
      return;
    }

    decisionsList.innerHTML = decisions.map((decision) => {
      const selected = selectedActionForDecision(decision);
      const flow = decision.flow || {};
      const remaining = Number.isFinite(decision.displayEnd) ? decision.displayEnd - currentTime : 10;
      const fading = remaining > 0 && remaining < 2 ? " fading" : "";
      const possibleActions = (decision.feasibleActions || []).length > 1
        ? `
          <div class="possible-actions">
            <h3>Possible Actions</h3>
            <ul>
              ${(decision.feasibleActions || []).map((action) => {
                const chosen = action.id === decision.selected ? " class=\"chosen\"" : "";
                return `<li${chosen}>${esc(action.label)}</li>`;
              }).join("")}
            </ul>
          </div>
        `
        : "";

      return `
        <article class="decision-card${fading}">
          <div class="decision-card-head">
            <strong>${esc(decision.title || labelForActor(decision.actor))}</strong>
            <span>${esc(decision.state || "Active")}</span>
          </div>
          <p class="decision-card-summary">${esc(decision.summary || selected?.label || "A resource is selecting its next action.")}</p>
          <ol class="decision-flow-list">
            <li><b>Condition</b><span>${esc(flow.condition || (decision.conditions || [])[0] || "A physical condition is present.")}</span></li>
            <li><b>Decision</b><span>${esc(flow.decision || decision.selectedReason || "The resource can continue with the next operation.")}</span></li>
            <li><b>Action</b><span>${esc(flow.action || selected?.label || "The selected action starts.")}</span></li>
          </ol>
          ${possibleActions}
        </article>
      `;
    }).join("");
  }

  function renderConditions() {
    const frame = frameAt(currentTime);
    const teachAction = currentTeachAction();
    const conditions = isTeachMode() ? teachAction?.conditions || [] : frame.physicalConditions || [];
    if (!conditionsList) return;
    if (!conditions.length) {
      conditionsList.innerHTML = `<li class="condition-item muted">No active physical condition to highlight.</li>`;
      return;
    }

    conditionsList.innerHTML = conditions.map((condition) => {
      const state = statusName(condition.state || condition.status || "UNKNOWN");
      return `
        <li class="condition-item">
          <span class="condition-dot status-${state}"></span>
          <span class="condition-copy">
            <strong>${esc(condition.label)}</strong>
            <span>${esc(condition.value || condition.detail || "")}</span>
          </span>
        </li>
      `;
    }).join("");
  }

  function renderStatusGrid() {
    if (!statusGrid) return;
    const teachAction = currentTeachAction();
    const resources = isTeachMode() ? teachResourcesAndDetails(teachAction).resources : frameAt(currentTime).resources || {};
    const keys = [
      "xarm2",
      "xarm1",
      "robot2",
      "robot1",
      "laser",
      "bantam",
      "conveyor1",
      "conveyor2",
      "conveyor3",
      "conveyor4",
      "c3",
      "c4",
      "intermediate_blue_stack"
    ];
    statusGrid.innerHTML = keys.map((key) => {
      const state = resourceState(resources, key);
      return `
        <div class="status-cell">
          <div class="status-name">${esc(key)}</div>
          <span class="status-pill status-${statusName(state)}">${esc(state)}</span>
        </div>
      `;
    }).join("");
  }

  function renderSources() {
    if (!sourceList) return;
    sourceList.innerHTML = [
      ...layout.sourceRefs,
      ...(run.sourceRefs || []),
      ...layout.notes,
      ...(run.notes || [])
    ].map((item) => `<li>${esc(item)}</li>`).join("");
  }

  function renderOrderStrip() {
    if (!orderStrip) return;
    if (isTeachMode()) {
      const action = currentTeachAction();
      const color = String(action?.color || "unknown").toLowerCase();
      orderStrip.innerHTML = `
        <div class="order-group">
          <span class="order-label">Selected element</span>
          <span class="teach-chip">${esc(labelForActor(teachSelectedResource))}</span>
        </div>
        <div class="order-group">
          <span class="order-label">Teaching policy</span>
          <span class="teach-chip">Fixed priority</span>
        </div>
        <div class="order-group">
          <span class="order-label">Teaching action</span>
          <span class="teach-chip">
            <span class="teach-color-dot teach-color-${esc(color)}"></span>
            ${esc(action?.title || "No mapped action")}
          </span>
        </div>
      `;
      return;
    }
    const stackOrder = [...run.pieces].sort((a, b) => (a.initialPosition || 0) - (b.initialPosition || 0));
    const systemEntryOrder = [...run.pieces].sort((a, b) => firstSystemEntryTime(a.id) - firstSystemEntryTime(b.id));
    const chips = (pieces) => pieces.map((piece, index) => {
      const color = String(piece.color || "unknown").toLowerCase();
      const text = String(piece.color || "?").slice(0, 1).toUpperCase();
      const title = `${index + 1}. ${piece.color || "Unknown"} ${piece.id.replace("piece-", "P")}`;
      return `<span class="order-chip order-${color}" title="${esc(title)}">${esc(text)}</span>`;
    }).join("");
    orderStrip.innerHTML = `
      <div class="order-group">
        <span class="order-label">Stack order</span>
        <div class="order-chips">${chips(stackOrder)}</div>
      </div>
      <div class="order-group">
        <span class="order-label">System entry</span>
        <div class="order-chips">${chips(systemEntryOrder)}</div>
      </div>
    `;
  }

  function runOptionLabel(candidate) {
    const meta = candidate.meta || {};
    const group = meta.group || `${candidate.pieces?.length || 0} parts`;
    const mode = meta.mode === "dynamic" ? "Dynamic" : meta.mode === "fixed" ? "Fixed" : stateLabel(meta.mapMode || "run");
    const source = runSourceLabel(candidate);
    const sourceId = meta.sourceType === "simulation" && meta.physicalRunId
      ? `sim of ${meta.physicalRunId}`
      : candidate.id;
    return `${source} | ${group} | ${mode} | ${sourceId}`;
  }

  function runSourceType(candidate) {
    return (candidate.meta?.sourceType || "real").toLowerCase();
  }

  function runSourceLabel(candidate) {
    const type = runSourceType(candidate);
    if (candidate.meta?.sourceLabel) return candidate.meta.sourceLabel;
    return type === "simulation" ? "Simulation" : "Real cell";
  }

  function renderRunContext() {
    if (!runContext) return;
    if (isTeachMode()) {
      runContext.innerHTML = `<span class="origin-pill origin-teach">Teach</span> Fixed-priority teaching mode | independent of the selected production run.`;
      return;
    }
    const meta = run.meta || {};
    const type = runSourceType(run);
    const title = (meta.title || run.label || `${run.pieces.length} pieces`).replace(/ - Simulation$/, "");
    const durationText = type === "simulation"
      ? `${Number(run.duration || 0).toFixed(1)} s simulated`
      : `${Number(run.duration || 0).toFixed(3)} s real`;
    const counterpart = type === "simulation" && meta.realCounterpartS
      ? ` | real counterpart ${Number(meta.realCounterpartS).toFixed(3)} s`
      : "";
    const suffix = type === "simulation" ? "SimPy replay." : "MES replay.";
    runContext.innerHTML = `
      <span class="origin-pill origin-${esc(type)}">${esc(runSourceLabel(run))}</span>
      ${esc(title)}: ${esc(durationText)}${esc(counterpart)}. ${esc(suffix)}
    `;
  }

  function syncRunControls() {
    const maxTime = isTeachMode() ? TEACH_DEMO_DURATION : run.duration;
    timeline.min = "0";
    timeline.max = String(maxTime);
    timeline.step = "0.001";
    duration.textContent = maxTime.toFixed(1);
    if (runSelect) {
      runSelect.value = run.id;
      runSelect.disabled = isTeachMode() || runs.length < 2;
    }
    renderRunContext();
  }

  function populateRunSelector() {
    if (!runSelect) return;
    const groups = [
      ["real", "Physical cell runs"],
      ["simulation", "Simulated runs"],
    ];
    const groupedOptions = groups.map(([type, label]) => {
      const options = runs
        .filter((candidate) => runSourceType(candidate) === type)
        .map((candidate) => `<option value="${esc(candidate.id)}">${esc(runOptionLabel(candidate))}</option>`)
        .join("");
      return options ? `<optgroup label="${esc(label)}">${options}</optgroup>` : "";
    }).join("");
    const uncategorized = runs
      .filter((candidate) => !["real", "simulation"].includes(runSourceType(candidate)))
      .map((candidate) => `<option value="${esc(candidate.id)}">${esc(runOptionLabel(candidate))}</option>`)
      .join("");
    runSelect.innerHTML = groupedOptions + uncategorized;
    runSelect.disabled = isTeachMode() || runs.length < 2;
  }

  function selectRun(runId) {
    const nextRun = runs.find((candidate) => candidate.id === runId);
    if (!nextRun || nextRun === run) return;
    run = nextRun;
    pieceMeta = new Map(run.pieces.map((piece) => [piece.id, piece]));
    buildStorageSlotLookup();
    currentTime = 0;
    playing = false;
    teachAnimating = false;
    lastTick = 0;
    updatePlaybackButton();
    syncRunControls();
    renderOrderStrip();
    renderSources();
    render();
  }

  function firstSystemEntryTime(pieceId) {
    const frames = keyframesForPiece(pieceId);
    const entry = frames.find((frame) => frame.location !== "initial_stack");
    return entry ? entry.time : Number.POSITIVE_INFINITY;
  }

  function render() {
    const displayTime = isTeachMode() ? teachTime : currentTime;
    timeline.value = String(displayTime);
    timeNow.textContent = displayTime.toFixed(1);
    drawSvg();
    renderDecisionPanel();
    renderConditions();
    renderStatusGrid();
  }

  function setTime(value) {
    currentTime = Math.max(0, Math.min(run.duration, value));
    if (currentTime >= run.duration) {
      playing = false;
      updatePlaybackButton();
    }
    render();
  }

  function setTeachTime(value) {
    teachTime = Math.max(0, Math.min(TEACH_DEMO_DURATION, value));
    if (teachTime >= TEACH_DEMO_DURATION) {
      teachAnimating = false;
    }
    updatePlaybackButton();
    render();
  }

  function startTeachAnimation() {
    if (!isTeachMode()) setRouteFilter("teach");
    playing = false;
    teachTime = 0;
    teachAnimating = Boolean(currentTeachAction());
    lastTick = 0;
    updatePlaybackButton();
    renderOrderStrip();
    render();
  }

  function updatePlaybackButton() {
    if (!playToggle) return;
    playToggle.textContent = isTeachMode() ? teachAnimating ? "Stop" : "Animate" : playing ? "Pause" : "Play";
  }

  function selectTeachAction(actionId, animate) {
    if (!teachingActions().some((action) => action.id === actionId)) return;
    teachSelectedActionId = actionId;
    teachTime = 0;
    teachAnimating = false;
    updatePlaybackButton();
    renderOrderStrip();
    render();
    if (animate) startTeachAnimation();
  }

  function setRouteFilter(nextFilter) {
    routeFilter = nextFilter || "all";
    playing = false;
    teachAnimating = false;
    if (isTeachMode()) {
      teachTime = 0;
      if (!currentTeachAction()) {
        teachSelectedResource = "xarm2";
        teachSelectedActionId = "teach_xarm2_red_to_c1";
      }
    }
    document.querySelectorAll(".route-tab").forEach((tab) => {
      tab.classList.toggle("active", (tab.dataset.route || "all") === routeFilter);
    });
    updatePlaybackButton();
    syncRunControls();
    renderOrderStrip();
    render();
  }

  function tick(ts) {
    if (!lastTick) lastTick = ts;
    const elapsed = (ts - lastTick) / 1000;
    lastTick = ts;
    if (isTeachMode() && teachAnimating) {
      setTeachTime(teachTime + elapsed * Number(speed.value || 1));
    } else if (playing) {
      setTime(currentTime + elapsed * Number(speed.value || 1));
    }
    window.requestAnimationFrame(tick);
  }

  function bindControls() {
    playToggle.addEventListener("click", () => {
      if (isTeachMode()) {
        if (teachAnimating) {
          teachAnimating = false;
          updatePlaybackButton();
          render();
          return;
        }
        startTeachAnimation();
        return;
      }
      playing = !playing;
      updatePlaybackButton();
      if (playing && currentTime >= run.duration) setTime(0);
    });

    restartButton.addEventListener("click", () => {
      playing = false;
      teachAnimating = false;
      if (isTeachMode()) {
        setTeachTime(0);
        return;
      }
      updatePlaybackButton();
      setTime(0);
    });

    timeline.addEventListener("input", (event) => {
      playing = false;
      teachAnimating = false;
      updatePlaybackButton();
      if (isTeachMode()) {
        setTeachTime(Number(event.target.value));
        return;
      }
      setTime(Number(event.target.value));
    });

    if (runSelect) {
      runSelect.addEventListener("change", (event) => {
        selectRun(event.target.value);
      });
    }

    document.querySelectorAll(".route-tab").forEach((button) => {
      button.addEventListener("click", () => {
        setRouteFilter(button.dataset.route || "all");
      });
    });

    svg.addEventListener("click", (event) => {
      if (!isTeachMode()) return;
      const node = nodeAtEvent(event);
      if (node) selectTeachResource(node.id);
    });

    if (decisionsList) {
      decisionsList.addEventListener("click", (event) => {
        if (!isTeachMode()) return;
        const button = event.target.closest("[data-teach-action]");
        if (!button) return;
        selectTeachAction(button.dataset.teachAction, true);
      });
    }
  }

  function init() {
    if (!run) return;
    populateRunSelector();
    syncRunControls();
    buildStorageSlotLookup();
    bindControls();
    renderOrderStrip();
    renderSources();
    render();
    window.requestAnimationFrame(tick);
  }

  init();
}());
