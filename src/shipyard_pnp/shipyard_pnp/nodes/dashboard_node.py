#!/usr/bin/env python3
"""
Shipyard 4.0 — Dashboard Node

HTTP server on port 8080 with:
  - Live system topology from /factory/system_state
  - Door state from /bantam_factory/status
  - SimPy optimizer for production order
  - Optional DB analytics (PostgreSQL)
  - Camera streams from Niryo robots
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

try:
    from sensor_msgs.msg import CompressedImage
    _HAS_COMPRESSED_IMAGE = True
except ImportError:
    _HAS_COMPRESSED_IMAGE = False

try:
    import psycopg2
    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False

# ── DB credentials (same as database_node.py) ────────────────────
DB_HOST     = os.environ.get("PGHOST",     "100.118.157.20")
DB_USER     = os.environ.get("PGUSER",     "juan_lopez")
DB_PASSWORD = os.environ.get("PGPASSWORD", "twin2025")
DB_PORT     = int(os.environ.get("PGPORT", "5432"))
DB_NAME     = os.environ.get("PGDATABASE", "digital_twin_db")
DB_SCHEMA   = os.environ.get("PGSCHEMA",   "remote_database_capstone")

# ── Optimizer global state ────────────────────────────────────────
_OPT_STATE = {
    "status": "idle", "progress": 0, "total": 0,
    "best_so_far": None, "result": None, "error": None,
}
_OPT_LOCK = threading.Lock()


# ─────────────────────────────────────────────────────────────────
# OPTIMIZER THREAD
# ─────────────────────────────────────────────────────────────────

def _run_optimizer_thread(order: list) -> None:
    import io
    import contextlib
    from itertools import permutations
    from collections import Counter
    from math import factorial

    try:
        import simpy
        from shipyard_pnp.nodes.shipyard_sim import (
            System,
            bantam_machine_process, xarm2_process,
            conveyor1_process, conveyor1_control,
            conveyor2_process, conveyor2_control,
            xarm1_process, robot2_process, robot1_process,
        )
    except Exception as exc:
        with _OPT_LOCK:
            _OPT_STATE.update({"status": "error", "error": f"Import error: {exc}"})
        return

    SIM_UNTIL = 2000

    def run_silent(seq):
        env = simpy.Environment()
        system = System(env, list(seq))
        env.process(bantam_machine_process(env, system))
        env.process(xarm2_process(env, system))
        env.process(conveyor1_process(env, system))
        env.process(conveyor1_control(env, system))
        env.process(conveyor2_process(env, system))
        env.process(conveyor2_control(env, system))
        env.process(xarm1_process(env, system))
        env.process(robot2_process(env, system))
        env.process(robot1_process(env, system))
        with contextlib.redirect_stdout(io.StringIO()):
            env.run(until=SIM_UNTIL)
        return max((ch["time"] for ch in system.state_changes), default=float(env.now))

    def count_unique(items):
        counts = Counter(items)
        denom = 1
        for c in counts.values():
            for i in range(1, c + 1):
                denom *= i
        n = len(items)
        total = 1
        for i in range(1, n + 1):
            total *= i
        return total // denom

    def unique_permutations(items):
        seen = set()
        for p in permutations(items):
            if p not in seen:
                seen.add(p)
                yield p

    def generate_heuristic_candidates(items):
        counts = Counter(items)
        present = [c for c in ["BLUE", "RED", "GREEN"] if counts.get(c, 0) > 0]
        seen = set()
        cands = []

        def add(seq):
            t = tuple(seq)
            if t not in seen:
                seen.add(t)
                cands.append(list(seq))

        for prio in permutations(present):
            seq = []
            for c in prio:
                seq.extend([c] * counts[c])
            add(seq)

        for prio in permutations(present):
            pools = {c: counts[c] for c in present}
            seq = []
            while sum(pools.values()) > 0:
                for c in prio:
                    if pools.get(c, 0) > 0:
                        seq.append(c)
                        pools[c] -= 1
            add(seq)

        for b_chunk, r_chunk, g_chunk in [(2,1,1),(1,2,1),(1,1,2),(2,2,1),(2,1,2),(1,2,2),(3,1,1),(1,3,1)]:
            for start_prio in [["BLUE","RED","GREEN"],["BLUE","GREEN","RED"],["RED","BLUE","GREEN"]]:
                pools = {c: counts.get(c, 0) for c in present}
                chunk_map = {"BLUE": b_chunk, "RED": r_chunk, "GREEN": g_chunk}
                seq = []
                while sum(pools.values()) > 0:
                    for c in start_prio:
                        for _ in range(min(chunk_map.get(c, 1), pools.get(c, 0))):
                            seq.append(c)
                            pools[c] -= 1
                add(seq)

        n_blue = counts.get("BLUE", 0)
        n = len(items)
        if n_blue > 0:
            for rg_order in [["RED","GREEN"], ["GREEN","RED"]]:
                rest = []
                for c in rg_order:
                    rest.extend([c] * counts.get(c, 0))
                step = max(1, (n - n_blue) // (n_blue + 1))
                seq = list(rest)
                for i in range(n_blue):
                    pos = min((i + 1) * step + i, len(seq))
                    seq.insert(pos, "BLUE")
                add(seq)

        add(list(items))
        return cands

    BRUTE_FORCE_THRESHOLD = 100

    try:
        orig_time = run_silent(order)
        n_perms   = count_unique(order)

        if n_perms <= BRUTE_FORCE_THRESHOLD:
            with _OPT_LOCK:
                _OPT_STATE.update({"status": "running", "total": n_perms,
                                   "progress": 0, "best_so_far": orig_time})
            best_order, best_time = list(order), orig_time
            for i, perm in enumerate(unique_permutations(order)):
                t = run_silent(list(perm))
                if t < best_time:
                    best_time, best_order = t, list(perm)
                with _OPT_LOCK:
                    _OPT_STATE.update({"progress": i + 1, "best_so_far": best_time})
        else:
            candidates = generate_heuristic_candidates(order)
            with _OPT_LOCK:
                _OPT_STATE.update({"status": "running", "total": len(candidates),
                                   "progress": 0, "best_so_far": orig_time})
            best_order, best_time = list(order), orig_time
            for i, cand in enumerate(candidates):
                t = run_silent(cand)
                if t < best_time:
                    best_time, best_order = t, list(cand)
                with _OPT_LOCK:
                    _OPT_STATE.update({"progress": i + 1, "best_so_far": best_time})

        result = {
            "original_order": list(order),
            "original_time":  orig_time,
            "best_order":     best_order,
            "best_time":      best_time,
        }
        with _OPT_LOCK:
            _OPT_STATE.update({"status": "done", "result": result})

    except Exception as exc:
        import traceback
        with _OPT_LOCK:
            _OPT_STATE.update({"status": "error", "error": traceback.format_exc()})


# ─────────────────────────────────────────────────────────────────
# EMBEDDED CSS
# ─────────────────────────────────────────────────────────────────

_CSS = r"""
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f0f2f5; color: #333; overflow-x: hidden; }
.topbar { display: flex; justify-content: space-between; align-items: center; background: linear-gradient(135deg, #2c3e50, #3498db); color: white; padding: 12px 20px; box-shadow: 0 2px 10px rgba(0,0,0,.1); position: sticky; top: 0; z-index: 1000; gap: 16px; flex-wrap: wrap; }
.topbar h1 { font-size: 1.6rem; font-weight: 600; }
.topbar-center,.topbar-right { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.system-status,.ros-status,.topbar-right .datetime { background: rgba(255,255,255,.18); padding: 6px 14px; border-radius: 20px; font-weight: 500; font-size: .9rem; }
.nav-button { background: rgba(255,255,255,.2); color: white; text-decoration: none; padding: 7px 14px; border-radius: 20px; font-weight: 500; border: 2px solid rgba(255,255,255,.2); transition: all .2s; }
.nav-button:hover { background: rgba(255,255,255,.35); }
.dashboard-main { padding: 18px; display: flex; flex-direction: column; gap: 18px; }
.top-row { display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 18px; min-height: 320px; }
.bottom-row { width: 100%; min-height: 500px; }
.card { background: white; border: 2px solid #e0e6ed; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,.08); overflow: hidden; }
.section-header { background: linear-gradient(135deg, #34495e, #2c3e50); color: white; padding: 11px 18px; display: flex; justify-content: space-between; align-items: center; }
.section-header h2,.section-header h3 { font-weight: 600; font-size: 1.1rem; }
.status-indicator { background: rgba(255,255,255,.2); padding: 3px 10px; border-radius: 12px; font-size: .82rem; }
.topology-container { padding: 14px; background: #f8f9fa; }
.topology-grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 10px; }
.topology-node { border-radius: 10px; padding: 12px 14px; color: white; box-shadow: 0 4px 14px rgba(0,0,0,.1); }
.node-robot    { background: linear-gradient(135deg, #2980b9, #3498db); }
.node-machine  { background: linear-gradient(135deg, #c0392b, #e74c3c); }
.node-vision   { background: linear-gradient(135deg, #8e44ad, #9b59b6); }
.node-conveyor { background: linear-gradient(135deg, #16a085, #1abc9c); }
.node-sensor   { background: linear-gradient(135deg, #d68910, #f39c12); }
.node-door     { background: linear-gradient(135deg, #2c3e50, #7f8c8d); }
.node-title  { font-size: .95rem; font-weight: 700; margin-bottom: 6px; }
.node-line   { font-size: .82rem; opacity: .93; margin-top: 3px; }
.alerts-container { padding: 14px; max-height: 300px; overflow: auto; background: #f8f9fa; }
.alert { border-left: 5px solid #3498db; background: white; border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; box-shadow: 0 2px 8px rgba(0,0,0,.05); }
.alert-warning { border-left-color: #f39c12; }
.alert-danger  { border-left-color: #e74c3c; }
.alert-success { border-left-color: #27ae60; }
.alert-info    { border-left-color: #3498db; }
.alert-header  { display: flex; justify-content: space-between; margin-bottom: 4px; font-size: .78rem; color: #666; }
.alert-id      { font-weight: 700; color: #2c3e50; }
.carousel-wrap { position: relative; display: flex; align-items: center; height: 100%; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,.1); }
.carousel      { flex: 1; overflow: hidden; position: relative; height: 100%; }
.carousel-track { display: flex; height: 100%; transition: transform .4s cubic-bezier(.4,0,.2,1); }
.carousel-slide { flex-shrink: 0; width: 100%; height: 100%; display: flex; gap: 16px; padding: 0 8px; }
.carousel-slide .data-section { flex: 1; height: 100%; background: white; border-radius: 12px; border: 2px solid #e0e6ed; box-shadow: 0 4px 20px rgba(0,0,0,.08); overflow: hidden; }
.carousel-arrow { position: absolute; top: 50%; transform: translateY(-50%); background: rgba(44,62,80,.9); color: white; border: none; width: 44px; height: 44px; border-radius: 50%; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: bold; z-index: 10; transition: all .2s; box-shadow: 0 4px 12px rgba(0,0,0,.3); }
.carousel-arrow:hover { background: rgba(44,62,80,1); transform: translateY(-50%) scale(1.08); }
.carousel-arrow-left  { left: 12px; }
.carousel-arrow-right { right: 12px; }
.data-content { padding: 14px; display: flex; flex-direction: column; gap: 14px; height: calc(100% - 50px); overflow: auto; }
.metrics-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.metric { background: #f8f9fa; border-radius: 8px; padding: 9px 11px; border: 1px solid #e0e6ed; }
.metric label { display: block; font-size: .73rem; color: #667; margin-bottom: 4px; text-transform: uppercase; letter-spacing: .04em; }
.metric span  { font-size: .9rem; font-weight: 600; display: block; line-height: 1.3; }
.subpanel { background: #f8f9fa; border-radius: 8px; border: 1px solid #e0e6ed; padding: 11px; }
.subpanel h4 { margin-bottom: 8px; color: #2c3e50; font-size: .92rem; }
.card-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
.card-table th,.card-table td { padding: 7px 8px; border-bottom: 1px solid #e5e9ef; text-align: left; vertical-align: top; }
.card-table th { color: #6b7785; font-size: .72rem; text-transform: uppercase; letter-spacing: .06em; }
.small-list  { display: flex; flex-wrap: wrap; gap: 7px; }
.chip { background: #eef4fb; color: #2c3e50; border: 1px solid #d5e0ee; border-radius: 999px; padding: 5px 9px; font-size: .82rem; font-weight: 600; }
.vision-grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 8px; }
.vision-card { background: white; border: 1px solid #dfe6ee; border-radius: 8px; padding: 9px; }
.vision-card h5 { color: #2c3e50; font-size: .88rem; margin-bottom: 5px; }
.vision-line { font-size: .8rem; color: #52606d; margin-top: 3px; line-height: 1.3; }
.stack-visual-wrap { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-start; padding: 4px 0; }
.stack-col-group { display: flex; flex-direction: column; align-items: center; gap: 3px; }
.stack-col-label { font-size: .68rem; font-weight: 700; color: #6b7785; text-transform: uppercase; margin-bottom: 2px; }
.stack-slot { width: 54px; height: 44px; border-radius: 8px; display: flex; flex-direction: column; align-items: center; justify-content: center; border: 2px solid rgba(0,0,0,.12); box-shadow: 0 2px 5px rgba(0,0,0,.1); cursor: default; transition: transform .13s; }
.stack-slot:hover { transform: scale(1.07); z-index: 2; }
.stack-slot.empty { background: #eef1f5; border-color: #d3dae3; box-shadow: none; }
.stack-slot-text { font-size: .56rem; font-weight: 700; color: white; text-shadow: 0 1px 2px rgba(0,0,0,.3); margin-top: 1px; }
.stack-slot-key  { font-size: .52rem; color: #b0bec9; margin-top: 1px; }
.gantt-chart { display: flex; flex-direction: column; gap: 8px; min-height: 180px; }
.gantt-row   { display: grid; grid-template-columns: 160px 1fr; align-items: center; gap: 8px; }
.gantt-label { font-size: .78rem; color: #2c3e50; line-height: 1.3; }
.gantt-track { position: relative; height: 30px; border-radius: 8px; background: linear-gradient(90deg,#f6f8fb,#eef3f8); border: 1px solid #d8e1ea; overflow: hidden; }
.gantt-phase { position: absolute; top: 4px; height: 20px; border-radius: 5px; color: white; font-size: .7rem; font-weight: 700; display: flex; align-items: center; justify-content: center; padding: 0 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; box-shadow: 0 2px 5px rgba(0,0,0,.14); }
.gantt-meta  { font-size: .72rem; color: #708090; margin-top: 2px; }
.gantt-empty { display: flex; align-items: center; justify-content: center; min-height: 160px; color: #61717f; background: #f8fafc; border-radius: 8px; border: 1px dashed #d6dfe8; }
.opt-panel { background: white; border: 2px solid #e0e6ed; border-radius: 10px; padding: 16px 18px; box-shadow: 0 4px 18px rgba(0,0,0,.07); }
.opt-panel h4 { font-size: .96rem; font-weight: 700; color: #2c3e50; margin-bottom: 10px; display: flex; align-items: center; gap: 7px; }
.opt-btn { padding: 9px 18px; border: none; border-radius: 7px; font-size: .9rem; font-weight: 700; cursor: pointer; transition: all .18s; }
.opt-btn-run     { background: linear-gradient(135deg,#8e44ad,#9b59b6); color: white; }
.opt-btn-run:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(142,68,173,.4); }
.opt-btn-run:disabled { opacity: .5; cursor: not-allowed; }
.opt-btn-confirm { background: linear-gradient(135deg,#27ae60,#2ecc71); color: white; }
.opt-btn-confirm:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(39,174,96,.4); }
.opt-btn-confirm:disabled { opacity: .5; cursor: not-allowed; }
.opt-progress-bar-wrap { background: #eef3f8; border-radius: 6px; height: 9px; margin: 9px 0; overflow: hidden; }
.opt-progress-bar { height: 100%; background: linear-gradient(90deg,#8e44ad,#3498db); border-radius: 6px; transition: width .35s ease; }
.opt-result-box { background: #f4f9f4; border: 1.5px solid #27ae60; border-radius: 9px; padding: 12px 14px; margin-top: 10px; }
.opt-seq { display: flex; flex-wrap: wrap; gap: 5px; margin: 7px 0 3px; }
.opt-seq-chip { padding: 3px 9px; border-radius: 18px; font-size: .78rem; font-weight: 700; color: white; }
.opt-seq-chip.RED   { background: #e74c3c; }
.opt-seq-chip.GREEN { background: #27ae60; }
.opt-seq-chip.BLUE  { background: #2980b9; }
.opt-saving { font-size: .84rem; color: #27ae60; font-weight: 700; margin-top: 4px; }
.opt-status-text { font-size: .82rem; color: #607284; margin-top: 5px; }
"""

# ─────────────────────────────────────────────────────────────────
# EMBEDDED HTML
# ─────────────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Shipyard 4.0 Dashboard</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header class="topbar">
  <h1>Shipyard 4.0</h1>
  <div class="topbar-center">
    <span class="system-status">State: <span id="sys-state">...</span></span>
    <span class="ros-status">Phase: <span id="planner-phase">—</span></span>
    <span class="ros-status">Updated: <span id="ros-ts">—</span></span>
  </div>
  <div class="topbar-right">
    <a href="/camera" class="nav-button">Camera</a>
    <span class="datetime" id="datetime"></span>
  </div>
</header>

<div id="waiting-banner" style="display:none;background:linear-gradient(135deg,#8e44ad,#2980b9);color:white;text-align:center;padding:14px 20px;font-size:1.05rem;font-weight:600;letter-spacing:.02em">
  &#9888; System ready — run the optimizer and click <strong>Confirm &amp; Apply</strong> to start production
</div>
<main class="dashboard-main">
  <div class="top-row">
    <div class="card">
      <div class="section-header">
        <h2>System Topology</h2>
        <span class="status-indicator">Live</span>
      </div>
      <div class="topology-container">
        <div class="topology-grid" id="topo-grid"></div>
      </div>
    </div>
    <div class="card">
      <div class="section-header">
        <h2>Alerts</h2>
        <span class="status-indicator" id="alert-count">0</span>
      </div>
      <div class="alerts-container" id="alerts"></div>
    </div>
  </div>

  <div class="bottom-row">
    <div class="carousel-wrap">
      <button class="carousel-arrow carousel-arrow-left" id="btn-prev">&#8249;</button>
      <div class="carousel">
        <div class="carousel-track" id="carousel-track">

          <!-- SLIDE 0: Robots & Optimizer -->
          <div class="carousel-slide">
            <div class="data-section">
              <div class="section-header"><h3>Robots</h3><span class="status-indicator" id="robots-badge">—</span></div>
              <div class="data-content">
                <div class="metrics-grid" id="robot-metrics"></div>
                <div class="subpanel">
                  <h4>Piece Queue (initial stack)</h4>
                  <div class="small-list" id="init-order"></div>
                </div>
                <div class="subpanel">
                  <h4>Pipeline Locations</h4>
                  <div id="piece-tracker"></div>
                </div>
              </div>
            </div>
            <div class="data-section">
              <div class="section-header"><h3>Sequence Optimizer</h3></div>
              <div class="data-content">
                <div class="opt-panel">
                  <h4>&#9889; Order Optimizer
                    <span id="opt-badge" style="font-size:.72rem;padding:2px 8px;border-radius:10px;background:#e74c3c;color:white;font-weight:600">PENDING</span>
                  </h4>
                  <div style="display:flex;gap:9px;flex-wrap:wrap;align-items:center">
                    <button class="opt-btn opt-btn-run" id="opt-run" onclick="runOptimizer()">Optimize Order</button>
                    <button class="opt-btn opt-btn-confirm" id="opt-confirm" onclick="confirmOrder()" disabled>Confirm &amp; Apply</button>
                  </div>
                  <div id="opt-progress-wrap" style="display:none;margin-top:9px">
                    <div class="opt-progress-bar-wrap"><div class="opt-progress-bar" id="opt-bar" style="width:0%"></div></div>
                    <div class="opt-status-text" id="opt-status">Launching optimizer...</div>
                  </div>
                  <div id="opt-result" style="display:none"></div>
                </div>
                <div class="subpanel">
                  <h4>Cycles</h4>
                  <table class="card-table">
                    <thead><tr><th>Piece</th><th>Color</th><th>Route</th><th>Time</th></tr></thead>
                    <tbody id="cycles-table"></tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>

          <!-- SLIDE 1: Machines, Vision, Door, Sensors -->
          <div class="carousel-slide">
            <div class="data-section">
              <div class="section-header"><h3>Machines &amp; Door</h3><span class="status-indicator" id="mach-badge">—</span></div>
              <div class="data-content">
                <div class="metrics-grid" id="mach-metrics"></div>
                <div class="subpanel">
                  <h4>Vision Systems</h4>
                  <div class="vision-grid" id="vision-grid"></div>
                </div>
                <div class="subpanel">
                  <h4>Sensors</h4>
                  <table class="card-table">
                    <thead><tr><th>Sensor</th><th>State</th><th>Occupied</th></tr></thead>
                    <tbody id="sensors-table"></tbody>
                  </table>
                </div>
              </div>
            </div>
            <div class="data-section">
              <div class="section-header"><h3>Conveyors &amp; Domains</h3></div>
              <div class="data-content">
                <div class="subpanel">
                  <h4>Conveyors</h4>
                  <table class="card-table">
                    <thead><tr><th>Conveyor</th><th>State</th></tr></thead>
                    <tbody id="conveyors-table"></tbody>
                  </table>
                </div>
                <div class="subpanel">
                  <h4>Domain Online Status</h4>
                  <table class="card-table">
                    <thead><tr><th>Domain</th><th>Online</th><th>Busy</th></tr></thead>
                    <tbody id="domains-table"></tbody>
                  </table>
                </div>
                <div class="subpanel">
                  <h4>DB Analytics</h4>
                  <div id="db-status" style="font-size:.82rem;color:#607284;margin-bottom:8px">Checking...</div>
                  <table class="card-table">
                    <thead><tr><th>Entity</th><th>Task</th><th>Count</th><th>Avg</th></tr></thead>
                    <tbody id="cycle-timing"></tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>

          <!-- SLIDE 2: Transfers & Discards -->
          <div class="carousel-slide">
            <div class="data-section">
              <div class="section-header"><h3>Recent Transfers</h3></div>
              <div class="data-content">
                <div class="subpanel">
                  <table class="card-table">
                    <thead><tr><th>Piece</th><th>From</th><th>To</th><th>When</th></tr></thead>
                    <tbody id="transfers-table"></tbody>
                  </table>
                </div>
              </div>
            </div>
            <div class="data-section">
              <div class="section-header"><h3>Discarded Cycles</h3></div>
              <div class="data-content">
                <div id="discarded-summary"></div>
              </div>
            </div>
          </div>

        </div><!-- /carousel-track -->
      </div><!-- /carousel -->
      <button class="carousel-arrow carousel-arrow-right" id="btn-next">&#8250;</button>
    </div>
  </div>
</main>

<script>
let _slide = 0;

function updateDateTime() {
  document.getElementById("datetime").textContent = new Date().toLocaleString();
}

function nextSlide(dir) {
  const track = document.getElementById("carousel-track");
  const n = track.children.length;
  _slide = (_slide + dir + n) % n;
  track.style.transform = "translateX(-" + (_slide * 100) + "%)";
}

document.getElementById("btn-prev").addEventListener("click", () => nextSlide(-1));
document.getElementById("btn-next").addEventListener("click", () => nextSlide(1));

function fmtS(v) {
  if (v === null || v === undefined) return "n/a";
  return Number(v).toFixed(1) + "s";
}

function computeState(data) {
  const robots = Object.values(data.robots || {});
  const machines = Object.values(data.machines || {});
  if (robots.some(r => r.status === "ERROR") || machines.some(m => m.status === "ERROR")) return "ATTENTION";
  if (robots.some(r => !["IDLE","HOME","NOT_INITIALIZED"].includes(r.status)) ||
      machines.some(m => !["IDLE","FINISHED","NOT_INITIALIZED"].includes(m.status))) return "RUNNING";
  return "IDLE";
}

function buildAlerts(data) {
  const out = [];
  if ((data.planner_phase || "") === "WAITING_FOR_ORDER")
    out.push({level:"warning", title:"Awaiting Order", msg:"All domains online. Run optimizer and click Confirm & Apply to start production."});
  for (const [name, s] of Object.entries(data.sensors || {})) {
    if ((s.occupied_duration_s || 0) > 25)
      out.push({level:"warning", title:`Sensor ${name}`, msg:`Occupied ${fmtS(s.occupied_duration_s)}`});
  }
  if ((data.door?.controller_state || "").includes("MOVING"))
    out.push({level:"info", title:"Bantam Door", msg:`Door is ${data.door.controller_state}`});
  for (const [name, r] of Object.entries(data.robots || {})) {
    if (r.status === "ERROR")
      out.push({level:"danger", title:`Robot ${name}`, msg:"Robot in ERROR state"});
  }
  if (!out.length) out.push({level:"success", title:"System", msg:"No active alerts — system looks healthy."});
  return out.slice(0, 8);
}

function renderTopo(data) {
  const nodes = [];
  const n = (cls, title, lines) =>
    nodes.push(`<div class="topology-node ${cls}"><div class="node-title">${title}</div>${lines.map(l=>`<div class="node-line">${l}</div>`).join("")}</div>`);

  n("node-robot",    "Robot1",        [`${data.robots?.robot1?.status||"n/a"}`, `${fmtS(data.robots?.robot1?.status_duration_s)}`]);
  n("node-robot",    "Robot2",        [`${data.robots?.robot2?.status||"n/a"}`, `${fmtS(data.robots?.robot2?.status_duration_s)}`]);
  n("node-robot",    "xArm1 / xArm2",[`${data.robots?.xarm1?.status||"n/a"}`, `${data.robots?.xarm2?.status||"n/a"}`]);
  n("node-machine",  "Laser",         [`${data.machines?.laser?.status||"n/a"}`, `${fmtS(data.machines?.laser?.status_duration_s)}`]);
  n("node-machine",  "Bantam",        [`${data.machines?.bantam?.status||"n/a"}`, `${fmtS(data.machines?.bantam?.status_duration_s)}`]);
  n("node-door",     "Bantam Door",   [`${data.door?.controller_state||"n/a"}`, `${data.door?.status||""}`]);
  n("node-vision",   "Vision",        [`V1 ${data.vision?.visionrobot1?.status||"n/a"}`,`V2 ${data.vision?.visionrobot2?.status||"n/a"}`,`GV ${data.vision?.globalvision?.status||"n/a"}`]);
  n("node-conveyor", "Conveyors",     [`C1 ${data.conveyors?.conveyor1?.status||"n/a"}`, `C2 ${data.conveyors?.conveyor2?.status||"n/a"}`]);
  n("node-sensor",   "C3 / C4",       [`C3: ${data.sensors?.c3?.status||"n/a"} (${fmtS(data.sensors?.c3?.occupied_duration_s)})`, `C4: ${data.sensors?.c4?.status||"n/a"} (${fmtS(data.sensors?.c4?.occupied_duration_s)})`]);

  document.getElementById("topo-grid").innerHTML = nodes.join("");
}

function renderAlerts(data) {
  const alerts = buildAlerts(data);
  document.getElementById("alert-count").textContent = alerts.length;
  document.getElementById("alerts").innerHTML = alerts.map((a,i) =>
    `<div class="alert alert-${a.level}"><div class="alert-header"><span class="alert-id">${a.title}</span><span>#${i+1}</span></div><div>${a.msg}</div></div>`
  ).join("");
}

function renderRobots(data) {
  const robots = data.robots || {};
  const busy = Object.values(robots).filter(r => !["IDLE","HOME","NOT_INITIALIZED"].includes(r.status)).length;
  document.getElementById("robots-badge").textContent = `${busy} busy`;
  document.getElementById("robot-metrics").innerHTML = Object.entries(robots).map(([name,r]) =>
    `<div class="metric"><label>${name}</label><span>${r.status}</span><span>${fmtS(r.status_duration_s)}</span></div>`
  ).join("");

  const order = data.initial_order || [];
  document.getElementById("init-order").innerHTML = order.map((c,i) =>
    `<span class="chip">${i+1}. ${c}</span>`
  ).join("") || "<span style='color:#aaa;font-size:.82rem'>No order</span>";

  const locs = data.locations || {};
  const active = Object.entries(locs).filter(([,v]) => v.count > 0);
  document.getElementById("piece-tracker").innerHTML = active.length
    ? active.map(([loc,v]) =>
        `<div class="metric" style="margin-bottom:7px"><label>${loc}</label><span>${v.pieces.map(p=>`${p.id} ${p.color||"?"}`).join(", ")}</span></div>`
      ).join("")
    : `<div style="color:#aaa;font-size:.82rem;padding:6px">No pieces in pipeline</div>`;

  const cycles = (data.cycles?.last_five_cycles || []).reverse();
  document.getElementById("cycles-table").innerHTML = cycles.map(c =>
    `<tr><td>${c.piece_id}</td><td>${c.color||"?"}</td><td>${c.route||"?"}</td><td>${fmtS(c.cycle_time_sec)}</td></tr>`
  ).join("") || `<tr><td colspan="4" style="color:#aaa">No completed cycles</td></tr>`;
}

function renderMachines(data) {
  const mach = data.machines || {};
  const door = data.door || {};
  document.getElementById("mach-badge").textContent =
    `L:${mach.laser?.status||"n/a"} B:${mach.bantam?.status||"n/a"}`;

  document.getElementById("mach-metrics").innerHTML = [
    ...Object.entries(mach).map(([n,m]) =>
      `<div class="metric"><label>${n}</label><span>${m.status}</span><span>${fmtS(m.status_duration_s)}</span></div>`),
    `<div class="metric"><label>Door</label><span>${door.controller_state||"n/a"}</span><span>${door.status||""}</span></div>`,
  ].join("");

  const vis = data.vision || {};
  document.getElementById("vision-grid").innerHTML = [
    ["Robot1 Vision","visionrobot1"],
    ["Robot2 Vision","visionrobot2"],
    ["Global Vision","globalvision"],
  ].map(([label, key]) => {
    const v = vis[key] || {};
    return `<div class="vision-card"><h5>${label}</h5>
      <div class="vision-line">Status: <strong>${v.status||"n/a"}</strong></div>
      <div class="vision-line">Age: ${fmtS(v.status_duration_s)}</div></div>`;
  }).join("");

  document.getElementById("sensors-table").innerHTML = Object.entries(data.sensors||{}).map(([name,s]) =>
    `<tr><td>${name}</td><td>${s.status}</td><td>${fmtS(s.occupied_duration_s)}</td></tr>`
  ).join("");
}

function renderConveyors(data) {
  document.getElementById("conveyors-table").innerHTML = Object.entries(data.conveyors||{}).map(([n,c]) =>
    `<tr><td>${n}</td><td>${c.status}</td></tr>`
  ).join("");

  const domains = data.domains || {};
  document.getElementById("domains-table").innerHTML = Object.entries(domains).map(([name,d]) =>
    `<tr><td>${name}</td><td>${d.online?"&#10003;":"&#10007;"}</td><td>${d.busy?"busy":""}</td></tr>`
  ).join("");
}

function renderAnalytics(data) {
  const an = data.analytics || {};
  const db = an.db || {};
  document.getElementById("db-status").textContent = db.connected
    ? `DB online (${db.last_refresh||""})`
    : "DB offline";
  document.getElementById("cycle-timing").innerHTML = (an.cycle_timing||[]).map(r =>
    `<tr><td>${r.entity}</td><td>${r.task_name}</td><td>${r.count}</td><td>${fmtS(r.avg_duration_s)}</td></tr>`
  ).join("") || `<tr><td colspan="4" style="color:#aaa">No data</td></tr>`;

  document.getElementById("transfers-table").innerHTML = (an.recent_transfers||[]).map(r =>
    `<tr><td>${r.piece_id}</td><td>${r.from_loc}</td><td>${r.to_loc}</td><td>${r.ts||"n/a"}</td></tr>`
  ).join("") || `<tr><td colspan="4" style="color:#aaa">No transfers</td></tr>`;

  const disc = an.discarded_summary || [];
  document.getElementById("discarded-summary").innerHTML = disc.length
    ? disc.map(r => `<div class="chip" style="margin:4px">${r.entity}/${r.task_name}: ${r.count}</div>`).join("")
    : `<div style="color:#aaa;padding:12px;font-size:.85rem">No discarded cycles</div>`;
}

async function refreshDashboard() {
  try {
    const resp = await fetch("/api/state", {cache:"no-store"});
    const data = await resp.json();
    const phase = data.planner_phase || "UNKNOWN";
    document.getElementById("sys-state").textContent = computeState(data);
    document.getElementById("planner-phase").textContent = phase;
    document.getElementById("ros-ts").textContent = (data.generated_at || "n/a").substring(11,19);
    const banner = document.getElementById("waiting-banner");
    if (phase === "WAITING_FOR_ORDER") {
      banner.style.display = "block";
      if (_slide !== 0) nextSlide(-_slide); // go to optimizer slide
    } else {
      banner.style.display = "none";
    }
    renderTopo(data);
    renderAlerts(data);
    renderRobots(data);
    renderMachines(data);
    renderConveyors(data);
    renderAnalytics(data);
    _syncOptimizerBadge(data);
  } catch(e) {
    console.error("Dashboard refresh error:", e);
  }
}

// ── Optimizer UI ────────────────────────────────────────────────
let _optPoll = null;
let _optDone = false;

function _chipHtml(c) { return `<span class="opt-seq-chip ${c}">${c}</span>`; }

async function runOptimizer() {
  document.getElementById("opt-run").disabled = true;
  document.getElementById("opt-confirm").disabled = true;
  document.getElementById("opt-progress-wrap").style.display = "block";
  document.getElementById("opt-result").style.display = "none";
  document.getElementById("opt-status").textContent = "Launching...";
  document.getElementById("opt-bar").style.width = "2%";

  try {
    const resp = await fetch("/api/optimize", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
    const j = await resp.json();
    if (!j.ok) { document.getElementById("opt-status").textContent = "Error: " + (j.error||"?"); document.getElementById("opt-run").disabled=false; return; }
    if (j.already_done) { await pollOptimizer(); return; }
  } catch(e) { document.getElementById("opt-status").textContent = "Network error"; document.getElementById("opt-run").disabled=false; return; }

  if (_optPoll) clearInterval(_optPoll);
  _optPoll = setInterval(pollOptimizer, 1500);
}

async function pollOptimizer() {
  try {
    const resp = await fetch("/api/optimize_status", {cache:"no-store"});
    const s = await resp.json();
    const bar = document.getElementById("opt-bar");
    const txt = document.getElementById("opt-status");

    if (s.status === "running") {
      const pct = s.total > 0 ? Math.round(100*s.progress/s.total) : 0;
      bar.style.width = Math.max(pct,3)+"%";
      txt.textContent = s.total > 0
        ? `${s.progress}/${s.total} permutations (${pct}%) — best: ${s.best_so_far?s.best_so_far.toFixed(1)+"s":"..."}`
        : `Heuristic ${s.progress}/${s.total||"?"} — best: ${s.best_so_far?s.best_so_far.toFixed(1)+"s":"..."}`;
    } else if (s.status === "done") {
      clearInterval(_optPoll);
      _optDone = true;
      bar.style.width = "100%";
      txt.textContent = "Optimization complete.";
      const r = s.result;
      const saving = (r.original_time - r.best_time).toFixed(1);
      const pct = (100*(r.original_time-r.best_time)/r.original_time).toFixed(1);
      const box = document.getElementById("opt-result");
      box.className = "opt-result-box";
      box.innerHTML = `
        <div style="font-size:.78rem;color:#607284;margin-bottom:5px">Original (${r.original_time.toFixed(1)}s)</div>
        <div class="opt-seq">${r.original_order.map(_chipHtml).join("")}</div>
        <hr style="border:none;border-top:1px solid #dde6ee;margin:9px 0">
        <div style="font-size:.78rem;color:#607284;margin-bottom:5px">Optimal (${r.best_time.toFixed(1)}s)</div>
        <div class="opt-seq">${r.best_order.map(_chipHtml).join("")}</div>
        <div class="opt-saving">&#10003; Saving: ${saving}s (${pct}% less makespan)</div>`;
      box.style.display = "block";
      document.getElementById("opt-confirm").disabled = false;
      document.getElementById("opt-run").disabled = false;
    } else if (s.status === "error") {
      clearInterval(_optPoll);
      txt.textContent = "Error: " + (s.error||"?").substring(0,120);
      document.getElementById("opt-run").disabled = false;
    }
  } catch(e) {}
}

async function confirmOrder() {
  document.getElementById("opt-confirm").disabled = true;
  try {
    const resp = await fetch("/api/start_production", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
    const j = await resp.json();
    if (j.ok) {
      const badge = document.getElementById("opt-badge");
      badge.textContent = "APPLIED";
      badge.style.background = "#27ae60";
      document.getElementById("waiting-banner").style.display = "none";
      document.getElementById("opt-status").textContent =
        "Order sent — supervisor starting production with: " + (j.order || []).join(" → ");
    } else {
      alert("Error: " + (j.error||"?"));
      document.getElementById("opt-confirm").disabled = false;
    }
  } catch(e) { document.getElementById("opt-confirm").disabled=false; }
}

function _syncOptimizerBadge(data) {
  if (data.optimization_approved && !_optDone) {
    const badge = document.getElementById("opt-badge");
    if (badge) { badge.textContent = "APPLIED"; badge.style.background = "#27ae60"; }
  }
}

updateDateTime();
setInterval(updateDateTime, 1000);
refreshDashboard();
setInterval(refreshDashboard, 1000);
</script>
</body>
</html>
"""

_CAMERA_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Camera — Shipyard 4.0</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header class="topbar">
  <h1>Camera Monitoring</h1>
  <div class="topbar-right">
    <a href="/" class="nav-button">Dashboard</a>
    <span class="datetime" id="datetime"></span>
  </div>
</header>
<main style="padding:20px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px">
  <div class="card" id="cam-robot1"></div>
  <div class="card" id="cam-robot2"></div>
  <div class="card" id="cam-global"></div>
</main>
<script>
function updateDateTime() { document.getElementById("datetime").textContent = new Date().toLocaleString(); }
function camCard(title, key) {
  return `<div style="background:linear-gradient(135deg,#34495e,#2c3e50);color:white;padding:10px 16px;font-weight:600">${title}</div>
    <div style="margin:12px;border:2px dashed #b9c6d3;border-radius:8px;min-height:200px;display:flex;align-items:center;justify-content:center;overflow:hidden">
      <img src="/stream/${key}.jpg?t=${Date.now()}" style="width:100%;height:100%;object-fit:cover" onerror="this.style.display='none';this.parentElement.innerHTML='<div style=\'color:#888;padding:20px\'>No stream</div>'">
    </div>`;
}
document.getElementById("cam-robot1").innerHTML = camCard("Robot1 Vision", "robot1");
document.getElementById("cam-robot2").innerHTML = camCard("Robot2 Vision", "robot2");
document.getElementById("cam-global").innerHTML = camCard("Global Vision", "globalvision");
updateDateTime();
setInterval(updateDateTime, 1000);
</script>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────
# DEFAULT SNAPSHOT
# ─────────────────────────────────────────────────────────────────

def _default_snapshot():
    return {
        "generated_at": None,
        "robots": {},
        "machines": {},
        "vision": {},
        "conveyors": {},
        "sensors": {},
        "door": {"status": "UNKNOWN", "controller_state": "UNKNOWN"},
        "locations": {},
        "initial_order": [],
        "domains": {},
        "cycles": {},
        "analytics": {"db": {"connected": False, "last_refresh": None},
                      "cycle_timing": [], "recent_cycles": [],
                      "discarded_summary": [], "recent_transfers": []},
    }


# ─────────────────────────────────────────────────────────────────
# HTTP HANDLER
# ─────────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    state_fn    = None   # callable → dict
    image_fn    = None   # callable(key) → bytes|None
    order_pub   = None   # ROS publisher

    def _json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, content, ct):
        body = content.encode()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, body, ct):
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._text(_HTML, "text/html; charset=utf-8")
        elif path == "/camera":
            self._text(_CAMERA_HTML, "text/html; charset=utf-8")
        elif path == "/static/style.css":
            self._text(_CSS, "text/css; charset=utf-8")
        elif path == "/api/state":
            self._json(_Handler.state_fn() if _Handler.state_fn else _default_snapshot())
        elif path == "/api/optimize_status":
            with _OPT_LOCK:
                self._json(dict(_OPT_STATE))
        elif path.startswith("/stream/"):
            key = path.split("/")[-1].replace(".jpg", "")
            img = _Handler.image_fn(key) if _Handler.image_fn else None
            if img:
                self._bytes(img, "image/jpeg")
            else:
                self.send_response(404); self.end_headers()
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        path   = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length)) if length else {}

        if path == "/api/optimize":
            with _OPT_LOCK:
                status = _OPT_STATE["status"]
                if status in ("running", "done"):
                    self._json({"ok": True,
                                "already_running": status == "running",
                                "already_done":    status == "done"})
                    return
                snap  = _Handler.state_fn() if _Handler.state_fn else {}
                order = snap.get("initial_order", [])
                if not order:
                    self._json({"ok": False, "error": "initial_order empty — supervisor not publishing yet"})
                    return
                _OPT_STATE.update({"status": "running", "progress": 0, "total": 0,
                                   "best_so_far": None, "result": None, "error": None})
            threading.Thread(target=_run_optimizer_thread, args=(order,), daemon=True).start()
            self._json({"ok": True, "order": order})

        elif path == "/api/start_production":
            with _OPT_LOCK:
                result = _OPT_STATE.get("result")
            if not result:
                self._json({"ok": False, "error": "No optimizer result yet"})
                return
            pub = _Handler.order_pub
            if not pub:
                self._json({"ok": False, "error": "ROS publisher not available"})
                return
            msg = String()
            msg.data = json.dumps({"order": result["best_order"]})
            pub.publish(msg)
            self._json({"ok": True, "order": result["best_order"]})

        else:
            self.send_response(404); self.end_headers()

    def log_message(self, fmt, *args):
        pass  # silence access logs


# ─────────────────────────────────────────────────────────────────
# DASHBOARD ROS2 NODE
# ─────────────────────────────────────────────────────────────────

class DashboardNode(Node):
    def __init__(self):
        super().__init__("dashboard_node")
        self.declare_parameter("host", "0.0.0.0")
        self.declare_parameter("port", 8080)

        self._lock            = threading.Lock()
        self._snapshot        = _default_snapshot()
        self._door_state      = {"status": "UNKNOWN", "controller_state": "UNKNOWN"}
        self._analytics       = _default_snapshot()["analytics"]
        self._images          = {"robot1": None, "robot2": None, "globalvision": None}
        self._db_conn         = None
        self._initial_order_captured: list = []

        # Subscribe to factory system state
        self.create_subscription(String, "/factory/system_state", self._on_system_state, 10)

        # Subscribe to bantam status for door tracking
        self.create_subscription(String, "/bantam_factory/status", self._on_bantam_status, 10)

        # Camera streams (Niryo robots)
        if _HAS_COMPRESSED_IMAGE:
            for key, topic in [
                ("robot1",      "/robot1/niryo_robot_vision/compressed_video_stream"),
                ("robot2",      "/robot2/niryo_robot_vision/compressed_video_stream"),
                ("globalvision","/globalvision/compressed_video_stream"),
            ]:
                self.create_subscription(
                    CompressedImage, topic,
                    lambda msg, k=key: self._on_image(k, msg), 1,
                )

        # DB analytics refresh every 10s
        self.create_timer(10.0, self._refresh_analytics)

        # ROS publisher for optimized order → supervisor
        self._order_pub = self.create_publisher(String, "/supervisor/set_optimized_order", 10)

        # Wire HTTP handler
        _Handler.state_fn  = self.get_snapshot
        _Handler.image_fn  = self._get_image
        _Handler.order_pub = self._order_pub

        # Start HTTP server
        host = self.get_parameter("host").value
        port = int(self.get_parameter("port").value)
        self._httpd = ThreadingHTTPServer((host, port), _Handler)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

        self.get_logger().info(f"Dashboard ready at http://{host}:{port}")
        self._refresh_analytics()

    # ── inbound ROS callbacks ──────────────────────────────────────

    def _on_system_state(self, msg: String) -> None:
        try:
            raw = json.loads(msg.data)
        except Exception:
            return

        io_from_pub = raw.get("initial_order", [])
        with self._lock:
            if io_from_pub and not self._initial_order_captured:
                self._initial_order_captured = list(io_from_pub)
            snap = self._normalize(raw)
            snap["analytics"] = self._analytics
            self._snapshot = snap

    def _on_bantam_status(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
        except Exception:
            return
        resource_state = payload.get("resource_state", "")
        code = (payload.get("result") or {}).get("code", "")
        if code == "CLOSING_DOOR":
            ctrl = "MOVING_TO_CLOSED"
        elif code in ("OPENING_DOOR_AFTER_JOB",):
            ctrl = "MOVING_TO_OPEN"
        elif code == "JOB_COMPLETE" or resource_state == "IDLE":
            ctrl = "OPEN"
        elif resource_state == "WORKING":
            ctrl = "CLOSED"
        else:
            return  # keep current
        with self._lock:
            self._door_state = {"status": code or resource_state, "controller_state": ctrl}

    def _on_image(self, key: str, msg) -> None:
        with self._lock:
            self._images[key] = bytes(msg.data)

    # ── normalization ──────────────────────────────────────────────

    def _normalize(self, raw: dict) -> dict:
        """Transform /factory/system_state v1 → dashboard JS format."""
        resources = raw.get("resources", {})
        pipeline  = raw.get("pipeline", {})
        queues    = pipeline.get("queues", {})
        state_since = resources.get("state_since", {})
        now = time.time()

        def dur(key):
            ts = state_since.get(key)
            return round(now - ts, 1) if ts else None

        # Robots
        robots = {
            name: {"status": state, "wait_reason": "n/a", "status_duration_s": dur(name)}
            for name, state in resources.get("robots", {}).items()
        }

        # Machines
        machines = {
            name: {"status": state, "status_duration_s": dur(name)}
            for name, state in resources.get("machines", {}).items()
        }

        # Vision — remap internal names to JS names
        vis = resources.get("vision", {})
        vision = {
            "visionrobot1": {"status": vis.get("vision_robot1",      "UNKNOWN"), "status_duration_s": dur("vision_robot1")},
            "visionrobot2": {"status": vis.get("vision_robot2",      "UNKNOWN"), "status_duration_s": dur("vision_robot2")},
            "globalvision":  {"status": vis.get("globalvision_camera","UNKNOWN"), "status_duration_s": dur("globalvision_camera")},
        }

        # Conveyors
        conveyors = {
            name: {"status": state, "status_duration_s": dur(name)}
            for name, state in resources.get("conveyors", {}).items()
        }

        # Sensors
        sensors = {
            name: {
                "status": state,
                "occupied_duration_s": dur(name) if state == "OCCUPIED" else None,
            }
            for name, state in resources.get("sensors", {}).items()
        }

        # Locations
        locations = {
            loc: {
                "count": len(pieces),
                "pieces": [
                    {"id": p["id"], "color": p.get("color"), "shape": p.get("shape")}
                    for p in pieces
                ],
            }
            for loc, pieces in queues.items()
            if pieces
        }

        return {
            "generated_at":  raw.get("published_at"),
            "planner_phase": raw.get("planner_phase", "UNKNOWN"),
            "robots":        robots,
            "machines":      machines,
            "vision":        vision,
            "conveyors":     conveyors,
            "sensors":       sensors,
            "door":          dict(self._door_state),
            "locations":     locations,
            "initial_order": self._initial_order_captured or raw.get("initial_order", []),
            "domains":       raw.get("domains", {}),
            "cycles":        raw.get("cycles", {}),
        }

    # ── public accessors ───────────────────────────────────────────

    def get_snapshot(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._snapshot))

    def _get_image(self, key: str):
        with self._lock:
            return self._images.get(key)

    # ── DB analytics ───────────────────────────────────────────────

    def _refresh_analytics(self) -> None:
        if not _HAS_PSYCOPG2:
            return
        analytics = _default_snapshot()["analytics"]
        try:
            if self._db_conn is None or self._db_conn.closed:
                self._db_conn = psycopg2.connect(
                    host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                    user=DB_USER, password=DB_PASSWORD, connect_timeout=4,
                )
                self._db_conn.autocommit = True
                with self._db_conn.cursor() as cur:
                    cur.execute(f"SET search_path TO {DB_SCHEMA}, public;")

            with self._db_conn.cursor() as cur:
                cur.execute("""
                    SELECT entity, task_name, COUNT(*),
                           ROUND(AVG(total_duration_s)::numeric,2)
                    FROM cycle_event WHERE is_discarded=FALSE
                    GROUP BY entity, task_name ORDER BY entity, task_name;
                """)
                analytics["cycle_timing"] = [
                    {"entity": r[0], "task_name": r[1], "count": r[2],
                     "avg_duration_s": float(r[3]) if r[3] else None}
                    for r in cur.fetchall()
                ]

                cur.execute("""
                    SELECT ts, entity, task_name, total_duration_s, is_discarded
                    FROM cycle_event ORDER BY ts DESC LIMIT 10;
                """)
                analytics["recent_cycles"] = [
                    {"ts": r[0].strftime("%H:%M:%S") if r[0] else None,
                     "entity": r[1], "task_name": r[2],
                     "total_duration_s": float(r[3]) if r[3] else None,
                     "is_discarded": r[4]}
                    for r in cur.fetchall()
                ]

                cur.execute("""
                    SELECT entity, task_name, COUNT(*) FROM cycle_event
                    WHERE is_discarded=TRUE GROUP BY entity, task_name
                    ORDER BY COUNT(*) DESC LIMIT 10;
                """)
                analytics["discarded_summary"] = [
                    {"entity": r[0], "task_name": r[1], "count": r[2]}
                    for r in cur.fetchall()
                ]

                cur.execute("""
                    SELECT ts, piece_id, color, from_loc, to_loc
                    FROM piece_transfer_event ORDER BY ts DESC LIMIT 12;
                """)
                analytics["recent_transfers"] = [
                    {"ts": r[0].strftime("%H:%M:%S") if r[0] else None,
                     "piece_id": r[1], "color": r[2],
                     "from_loc": r[3], "to_loc": r[4]}
                    for r in cur.fetchall()
                ]

            analytics["db"] = {"connected": True, "last_refresh": time.strftime("%H:%M:%S")}

        except Exception as exc:
            self.get_logger().warning(f"[dashboard] DB offline: {exc}")
            try:
                if self._db_conn:
                    self._db_conn.close()
            except Exception:
                pass
            self._db_conn = None

        with self._lock:
            self._analytics = analytics
            self._snapshot["analytics"] = analytics

    # ── cleanup ────────────────────────────────────────────────────

    def destroy_node(self):
        if hasattr(self, "_httpd"):
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._db_conn and not self._db_conn.closed:
            try:
                self._db_conn.close()
            except Exception:
                pass
        super().destroy_node()


# ─────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────

def main(args=None):
    rclpy.init(args=args)
    node = DashboardNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
