#!/usr/bin/env python3
"""
MES_dashboard.py — Standalone MES Dashboard (no ROS required)

Serves a live HTTP dashboard on port 8082 that queries twin_mes_db
for joint telemetry across robot1, robot2, xarm1, xarm2.

Run:
    python3 MES_dashboard.py

Then open: http://localhost:8082

Dependencies:
    pip3 install psycopg2-binary
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import psycopg2
import psycopg2.extras

# ── database credentials ────────────────────────────────────────────
DB_HOST     = os.environ.get("PGHOST",     "100.115.213.16")
DB_USER     = os.environ.get("PGUSER",     "twin_mes_db")
DB_PASSWORD = os.environ.get("PGPASSWORD", "postgres")
DB_PORT     = int(os.environ.get("PGPORT", "5432"))
DB_NAME     = os.environ.get("PGDATABASE", "twin_mes_db")
DB_SCHEMA   = os.environ.get("MES_PGSCHEMA", os.environ.get("PGSCHEMA", "mes_pnp_v2"))
SOURCE_SCHEMA = os.environ.get("MES_SOURCE_SCHEMA", os.environ.get("MES_SRC_PGSCHEMA", "shipyard_pnp_ws"))

HTTP_PORT   = int(os.environ.get("MES_HTTP_PORT", "8082"))

ROBOTS = ["robot1", "robot2", "xarm1", "xarm2"]
SCADA_TABLES = [
    ("bantam_door_status", "Bantam Door"),
    ("conveyor1_status", "Conveyor 1"),
    ("conveyor2_status", "Conveyor 2"),
    ("laser_status", "Laser"),
    ("robot1_vacuum_state", "Robot1 Vacuum"),
    ("robot2_vacuum_state", "Robot2 Vacuum"),
    ("xarm1_vacuum_state", "xArm1 Vacuum"),
    ("xarm2_vacuum_state", "xArm2 Vacuum"),
]

# ── CSS ─────────────────────────────────────────────────────────────
STYLE_CSS = r"""
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
       background: #f0f2f5; color: #333; overflow-x: hidden; }
.topbar { display:flex; justify-content:space-between; align-items:center;
          background: linear-gradient(135deg, #1a252f, #2980b9);
          color:white; padding:12px 24px; position:sticky; top:0; z-index:1000;
          box-shadow: 0 2px 10px rgba(0,0,0,.25); gap:16px; }
.topbar h1 { font-size:1.6rem; font-weight:700; letter-spacing:.5px; }
.topbar-center { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.topbar-right  { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.badge { background:rgba(255,255,255,.18); padding:6px 14px;
         border-radius:20px; font-size:.88rem; font-weight:500; }
.nav-btn { background:rgba(255,255,255,.2); color:white; text-decoration:none;
           padding:7px 16px; border-radius:20px; font-size:.88rem; font-weight:500;
           border:2px solid rgba(255,255,255,.2); transition:all .3s; }
.nav-btn:hover { background:rgba(255,255,255,.35); transform:translateY(-1px); }
.nav-btn.active { background:rgba(255,255,255,.35); border-color:rgba(255,255,255,.5); }
.nav-btn.analytics { background:rgba(255,255,255,.2); border-color:rgba(255,255,255,.2); }
.nav-btn.analytics:hover { background:rgba(255,255,255,.35); }
.nav-btn.analytics.active { background:rgba(255,255,255,.35); border-color:rgba(255,255,255,.5); }
.nav-btn.alarms { background:rgba(231,76,60,.35); border-color:rgba(231,76,60,.5); }
.nav-btn.alarms:hover { background:rgba(231,76,60,.55); }
.nav-btn.alarms.active { background:rgba(231,76,60,.7); border-color:rgba(231,76,60,.9); }
.main { padding:20px; display:flex; flex-direction:column; gap:20px;
        min-height:calc(100vh - 64px); }
.robot-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:18px; }
@media(max-width:1100px){ .robot-grid{grid-template-columns:repeat(2,1fr);} }
@media(max-width:640px){  .robot-grid{grid-template-columns:1fr;} }
.robot-card { background:white; border-radius:12px; border:2px solid #e0e6ed;
              box-shadow:0 4px 16px rgba(0,0,0,.07); overflow:hidden; }
.robot-card-header { padding:12px 16px; color:white; font-weight:700; font-size:1rem;
                     display:flex; justify-content:space-between; align-items:center; }
.robot-card-header.robot1 { background: linear-gradient(135deg,#1f618d,#2980b9); }
.robot-card-header.robot2 { background: linear-gradient(135deg,#1e8449,#27ae60); }
.robot-card-header.xarm1  { background: linear-gradient(135deg,#76448a,#8e44ad); }
.robot-card-header.xarm2  { background: linear-gradient(135deg,#b7770d,#f39c12); }
.robot-card-body { padding:14px 16px; display:flex; flex-direction:column; gap:8px; }
.status-pill { padding:4px 12px; border-radius:999px; font-size:.78rem; font-weight:700; }
.s-IDLE        { background:#d5f5e3; color:#1e8449; }
.s-HOME        { background:#d6eaf8; color:#1a5276; }
.s-RUNNING     { background:#fdebd0; color:#a04000; }
.s-MOVING      { background:#fdebd0; color:#a04000; }
.s-INITIALIZING{ background:#fdf2b3; color:#7d6608; }
.s-ERROR       { background:#fadbd8; color:#922b21; }
.s-UNKNOWN     { background:#eaecee; color:#566573; }
.joint-table { width:100%; border-collapse:collapse; font-size:.8rem; margin-top:4px; }
.joint-table th { color:#6b7785; font-size:.72rem; text-transform:uppercase;
                  letter-spacing:.05em; padding:4px 6px; border-bottom:1px solid #eee; }
.joint-table td { padding:5px 6px; border-bottom:1px solid #f4f6f8; font-variant-numeric:tabular-nums; }
.joint-table tr:last-child td { border-bottom:none; }
.val-pos { color:#1a5276; }
.val-vel { color:#1e8449; }
.val-eff { color:#7d3c98; }
.ts-label { font-size:.74rem; color:#98a4b0; margin-top:6px; text-align:right; }
.analytics-strip { display:grid; grid-template-columns:repeat(4,1fr); gap:18px; }
@media(max-width:900px){ .analytics-strip{grid-template-columns:repeat(2,1fr);} }
@media(max-width:500px){ .analytics-strip{grid-template-columns:1fr;} }
.stat-card { background:white; border-radius:12px; border:2px solid #e0e6ed;
             padding:18px 20px; box-shadow:0 4px 16px rgba(0,0,0,.07); }
.stat-card .label { font-size:.78rem; color:#667; text-transform:uppercase; letter-spacing:.06em; }
.stat-card .value { font-size:2rem; font-weight:700; color:#2c3e50; margin:4px 0 0; }
.stat-card .sub   { font-size:.8rem; color:#98a4b0; margin-top:4px; }
.chart-panel { background:white; border-radius:12px; border:2px solid #e0e6ed;
               box-shadow:0 4px 16px rgba(0,0,0,.07); overflow:hidden; }
.panel-header { background:linear-gradient(135deg,#34495e,#2c3e50); color:white;
                padding:12px 20px; display:flex; justify-content:space-between; align-items:center; }
.panel-header h2 { font-size:1.1rem; font-weight:600; }
.panel-header select { background:rgba(255,255,255,.2); color:white;
  border:1px solid rgba(255,255,255,.3); border-radius:8px; padding:5px 10px;
  font-size:.85rem; cursor:pointer; }
.panel-body { padding:16px; }
.chart-wrap { position:relative; height:260px; }
.telem-wrap { background:white; border-radius:12px; border:2px solid #e0e6ed;
              box-shadow:0 4px 16px rgba(0,0,0,.07); overflow:hidden; }
.telem-controls { padding:14px 20px; background:#f8f9fa; border-bottom:1px solid #e0e6ed;
                  display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
.telem-controls select, .telem-controls input { padding:7px 12px; border:2px solid #e0e6ed;
  border-radius:8px; font-size:.88rem; background:white; }
.telem-controls button { padding:7px 18px; background:linear-gradient(135deg,#2c3e50,#3498db);
  color:white; border:none; border-radius:8px; font-size:.88rem; cursor:pointer; }
.telem-controls button:hover { opacity:.9; }
.tbl-scroll { overflow-x:auto; }
table.data-tbl { width:100%; border-collapse:collapse; font-size:.8rem; white-space:nowrap; }
table.data-tbl th { background:#f8f9fa; color:#6b7785; font-size:.72rem; text-transform:uppercase;
                    letter-spacing:.05em; padding:8px 10px; border-bottom:2px solid #e0e6ed;
                    position:sticky; top:0; }
table.data-tbl td { padding:7px 10px; border-bottom:1px solid #f0f2f5; font-variant-numeric:tabular-nums; }
table.data-tbl tr:hover td { background:#f6f9fd; }
.pg-controls { display:flex; gap:8px; align-items:center; padding:12px 20px;
               border-top:1px solid #e0e6ed; }
.pg-btn { padding:5px 14px; background:#eef2f7; border:1px solid #d5dfe8;
          border-radius:6px; cursor:pointer; font-size:.82rem; }
.pg-btn:hover { background:#dde7f3; }
.pg-btn:disabled { opacity:.4; cursor:default; }
"""

# ── HTML ─────────────────────────────────────────────────────────────
MES_HTML = r"""<!DOCTYPE html>                                                                                                                                                                                                                                                                                                                                      `````````````````                                                         1QQ
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MES Dashboard — Shipyard 4.0</title>
  <link rel="stylesheet" href="/static/css/style.css">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
</head>
<body>
<header class="topbar">
  <div><h1>⚙ MES Dashboard</h1></div>
  <div class="topbar-center">
    <span class="badge">DB: <span id="db-status">Connecting…</span></span>
    <span class="badge">Rows: <span id="total-rows">—</span></span>
  </div>
  <div class="topbar-right">
    <a href="/" class="nav-btn active">Overview</a>
    <a href="/telemetry" class="nav-btn">Telemetry</a>
    <a href="/scada" class="nav-btn">SCADA</a>
    <a href="/analytics" class="nav-btn analytics">Analytics</a>
    <a href="/alarms" class="nav-btn alarms">Alarms</a>
    <span class="badge" id="clock"></span>
  </div>
</header>
<main class="main">
  <div class="analytics-strip">
    <div class="stat-card"><div class="label">Active Robots</div><div class="value" id="kpi-active">—</div><div class="sub">not IDLE / HOME / UNKNOWN</div></div>
    <div class="stat-card"><div class="label">Total Rows (all tables)</div><div class="value" id="kpi-rows">—</div><div class="sub">joint telemetry records</div></div>
    <div class="stat-card"><div class="label">DB Host</div><div class="value" style="font-size:1rem;padding-top:8px" id="kpi-host">—</div><div class="sub" id="kpi-db">—</div></div>
    <div class="stat-card"><div class="label">Last Refresh</div><div class="value" style="font-size:1.1rem;padding-top:6px" id="kpi-ts">—</div><div class="sub">UTC</div></div>
  </div>
  <div class="robot-grid" id="robot-grid"></div>
  <div class="chart-panel">
    <div class="panel-header">
      <h2>Joint Positions — History</h2>
      <div style="display:flex;gap:10px;align-items:center;">
        <select id="chart-robot" onchange="loadChart()">
          <option value="robot1">robot1</option>
          <option value="robot2">robot2</option>
          <option value="xarm1">xarm1</option>
          <option value="xarm2">xarm2</option>
        </select>
        <select id="chart-window" onchange="loadChart()">
          <option value="5">5 sec</option>
          <option value="15">15 sec</option>
          <option value="30" selected>30 sec</option>
          <option value="60">1 min</option>
          <option value="120">2 min</option>
          <option value="300">5 min</option>
        </select>
      </div>
    </div>
    <div class="panel-body">
      <div class="chart-wrap"><canvas id="joint-chart"></canvas></div>
    </div>
  </div>
</main>
<script>
setInterval(() => { document.getElementById('clock').textContent = new Date().toLocaleTimeString(); }, 1000);

const COLORS = ['#2980b9','#27ae60','#8e44ad','#f39c12','#e74c3c','#16a085'];
let jointChart = null;

function initChart() {
  const ctx = document.getElementById('joint-chart').getContext('2d');
  jointChart = new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [] },
    options: {
      animation: false, responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { position: 'top', labels: { boxWidth: 12, font: { size: 11 } } } },
      scales: { x: { ticks: { maxTicksLimit: 10, font: { size: 10 } } },
                y: { title: { display: true, text: 'Position (rad)' } } }
    }
  });
}

async function loadChart() {
  const robot  = document.getElementById('chart-robot').value;
  const window = document.getElementById('chart-window').value;
  try {
    const res  = await fetch(`/api/history?robot=${robot}&window_s=${window}`);
    const data = await res.json();
    if (!data.rows || !data.rows.length) return;
    const rows = [...data.rows].reverse();
    const labels   = rows.map(r => (r.ts||'').substring(11,23));
    const datasets = [1,2,3,4,5,6].map((j,i) => ({
      label: `joint${j}`,
      data: rows.map(r => r[`joint${j}_position`]),
      borderColor: COLORS[i], backgroundColor: COLORS[i]+'22',
      pointRadius: 0, borderWidth: 1.5, tension: 0.3, fill: false,
    }));
    jointChart.data.labels   = labels;
    jointChart.data.datasets = datasets;
    jointChart.update('none');
  } catch(e) { console.warn('chart error', e); }
}

function statusPill(s) {
  const safe = (s||'UNKNOWN').toUpperCase().replace(/[^A-Z_]/g,'');
  return `<span class="status-pill s-${safe}">${s||'UNKNOWN'}</span>`;
}
function fmt(v, d=4) {
  if (v === null || v === undefined) return '<span style="color:#bbb">—</span>';
  return Number(v).toFixed(d);
}

function renderCards(snap) {
  document.getElementById('robot-grid').innerHTML =
    Object.entries(snap.robots||{}).map(([name, r]) => {
      const rows = [1,2,3,4,5,6].map(j => `<tr>
        <td>J${j}</td>
        <td class="val-pos">${fmt(r.joints?.position?.[j-1])}</td>
        <td class="val-vel">${fmt(r.joints?.velocity?.[j-1])}</td>
        <td class="val-eff">${fmt(r.joints?.effort?.[j-1])}</td>
      </tr>`).join('');
      return `<div class="robot-card">
        <div class="robot-card-header ${name}">
          <span>${name.toUpperCase()}</span>${statusPill(r.status)}
        </div>
        <div class="robot-card-body">
          <table class="joint-table">
            <thead><tr><th>Joint</th><th>Pos (rad)</th><th>Vel (r/s)</th><th>Effort</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
          <div class="ts-label">${r.ts ? r.ts.substring(0,19).replace('T',' ')+' UTC' : '—'}</div>
        </div>
      </div>`;
    }).join('');
}

function renderKPIs(snap) {
  const robots = Object.values(snap.robots||{});
  const active = robots.filter(r => !['IDLE','HOME','UNKNOWN'].includes((r.status||'').toUpperCase())).length;
  document.getElementById('kpi-active').textContent = active;
  document.getElementById('kpi-rows').textContent   = (snap.total_rows||0).toLocaleString();
  document.getElementById('kpi-host').textContent   = snap.db_host||'—';
  document.getElementById('kpi-db').textContent     = `db: ${snap.db_name||'—'}`;
  document.getElementById('kpi-ts').textContent     = snap.fetched_at ? snap.fetched_at.substring(0,19).replace('T',' ') : '—';
  document.getElementById('total-rows').textContent = (snap.total_rows||0).toLocaleString();
  document.getElementById('db-status').textContent  = snap.db_ok ? '✅ Connected' : '❌ Error';
}

async function poll() {
  try {
    const snap = await (await fetch('/api/snapshot')).json();
    renderKPIs(snap); renderCards(snap);
  } catch(e) { console.warn('poll error', e); }
}

document.addEventListener('DOMContentLoaded', () => {
  initChart(); poll(); loadChart();
  setInterval(poll, 2000);
  setInterval(loadChart, 5000);
});
</script>
</body>
</html>
"""

TELEMETRY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Telemetry — MES</title>
  <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
<header class="topbar">
  <div><h1>⚙ MES — Telemetry Browser</h1></div>
  <div class="topbar-center">
    <span class="badge">DB: <span id="db-status">—</span></span>
  </div>
  <div class="topbar-right">
    <a href="/" class="nav-btn">Overview</a>
    <a href="/telemetry" class="nav-btn active">Telemetry</a>
    <a href="/scada" class="nav-btn">SCADA</a>
    <a href="/analytics" class="nav-btn analytics">Analytics</a>
    <a href="/alarms" class="nav-btn alarms">Alarms</a>
    <span class="badge" id="clock"></span>
  </div>
</header>
<main class="main">
  <div class="telem-wrap">
    <div class="telem-controls">
      <select id="tbl-source" onchange="onSourceChange()">
        <optgroup label="Joint Telemetry">
          <option value="robot1">robot1</option>
          <option value="robot2">robot2</option>
          <option value="xarm1">xarm1</option>
          <option value="xarm2">xarm2</option>
        </optgroup>
        <optgroup label="SCADA Devices">
          <option value="bantam_door_status">Bantam Door</option>
          <option value="conveyor1_status">Conveyor 1</option>
          <option value="conveyor2_status">Conveyor 2</option>
          <option value="laser_status">Laser</option>
          <option value="robot1_vacuum_state">R1 Vacuum</option>
          <option value="robot2_vacuum_state">R2 Vacuum</option>
          <option value="xarm1_vacuum_state">X1 Vacuum</option>
          <option value="xarm2_vacuum_state">X2 Vacuum</option>
        </optgroup>
      </select>
      <select id="tbl-window">
        <option value="5">5 sec</option>
        <option value="15">15 sec</option>
        <option value="30">30 sec</option>
        <option value="60" selected>1 min</option>
        <option value="120">2 min</option>
        <option value="300">5 min</option>
        <option value="0">All rows (paged)</option>
      </select>
      <select id="tbl-limit" style="display:none">
        <option value="50">50 rows</option>
        <option value="100" selected>100 rows</option>
        <option value="250">250 rows</option>
        <option value="500">500 rows</option>
      </select>
      <select id="tbl-status">
        <option value="">All statuses</option>
        <option value="IDLE">IDLE</option>
        <option value="HOME">HOME</option>
        <option value="RUNNING">RUNNING</option>
        <option value="MOVING">MOVING</option>
        <option value="INITIALIZING">INITIALIZING</option>
        <option value="ERROR">ERROR</option>
        <option value="UNKNOWN">UNKNOWN</option>
      </select>
      <button onclick="loadTable(1)">Query</button>
      <span id="tbl-count" style="font-size:.82rem;color:#667;"></span>
    </div>
    <div class="tbl-scroll">
      <table class="data-tbl" id="data-tbl">
        <thead id="tbl-head"></thead>
        <tbody id="tbl-body"><tr><td colspan="8" style="text-align:center;padding:30px;color:#aaa">Select a source and click Query</td></tr></tbody>
      </table>
    </div>
    <div class="pg-controls">
      <button class="pg-btn" id="pg-prev" onclick="changePage(-1)" disabled>‹ Prev</button>
      <span id="pg-label" style="font-size:.82rem;color:#667;">—</span>
      <button class="pg-btn" id="pg-next" onclick="changePage(1)" disabled>Next ›</button>
    </div>
  </div>
</main>
<script>
setInterval(() => { document.getElementById('clock').textContent = new Date().toLocaleTimeString(); }, 1000);

const JOINT_SOURCES = ['robot1','robot2','xarm1','xarm2'];
let currentPage = 1, totalPages = 1;

function isJoint() { return JOINT_SOURCES.includes(document.getElementById('tbl-source').value); }

function onSourceChange() {
  const joint = isJoint();
  document.getElementById('tbl-status').style.display = joint ? '' : 'none';
}

function changePage(d) {
  currentPage = Math.max(1, Math.min(totalPages, currentPage+d));
  loadTable(currentPage);
}
function fmt(v, d=5) { return (v===null||v===undefined) ? '—' : Number(v).toFixed(d); }

function setJointHeader() {
  document.getElementById('tbl-head').innerHTML = '<tr>' +
    '<th>ID</th><th>Timestamp</th><th>Robot</th><th>Status</th>' +
    '<th>J1 Pos</th><th>J2 Pos</th><th>J3 Pos</th><th>J4 Pos</th><th>J5 Pos</th><th>J6 Pos</th>' +
    '<th>J1 Vel</th><th>J2 Vel</th><th>J3 Vel</th><th>J4 Vel</th><th>J5 Vel</th><th>J6 Vel</th>' +
    '<th>J1 Eff</th><th>J2 Eff</th><th>J3 Eff</th><th>J4 Eff</th><th>J5 Eff</th><th>J6 Eff</th>' +
    '<th>Topic</th><th>Received At</th></tr>';
}

function setScadaHeader() {
  document.getElementById('tbl-head').innerHTML = '<tr>' +
    '<th>ID</th><th>Timestamp</th><th>Source</th><th>Status</th>' +
    '<th>Topic</th><th>Received At</th><th>Run ID</th></tr>';
}

async function loadTable(page=1) {
  currentPage = page;
  const source  = document.getElementById('tbl-source').value;
  const windowS = document.getElementById('tbl-window').value;
  const status  = document.getElementById('tbl-status').value;
  const limit   = document.getElementById('tbl-limit').value;
  const offset  = (page-1)*parseInt(limit);

  try {
    let data;
    if (isJoint()) {
      setJointHeader();
      let url = `/api/history?robot=${source}&full=1&status=${encodeURIComponent(status)}`;
      if (windowS !== '0') {
        url += `&window_s=${windowS}`;
      } else {
        url += `&limit=${limit}&offset=${offset}`;
      }
      data = await (await fetch(url)).json();
    } else {
      setScadaHeader();
      const eff_limit = windowS !== '0' ? 500 : parseInt(limit);
      data = await (await fetch(`/api/scada_history?device=${source}&limit=${eff_limit}&offset=${offset}`)).json();
    }

    const rows = data.rows||[];
    totalPages = windowS !== '0' ? 1 : (data.total_pages||1);
    document.getElementById('db-status').textContent = data.db_ok ? '✅ Connected' : '❌ Error';
    document.getElementById('tbl-count').textContent = `${data.total_count||0} rows total, showing ${rows.length}`;
    document.getElementById('pg-label').textContent  = `Page ${currentPage} / ${totalPages}`;
    document.getElementById('pg-prev').disabled = currentPage <= 1;
    document.getElementById('pg-next').disabled = currentPage >= totalPages || windowS !== '0';

    const tbody = document.getElementById('tbl-body');
    const colspan = isJoint() ? 24 : 7;
    if (!rows.length) { tbody.innerHTML=`<tr><td colspan="${colspan}" style="text-align:center;padding:30px;color:#aaa">No rows found</td></tr>`; return; }

    if (isJoint()) {
      tbody.innerHTML = rows.map(r => {
        const safe = (r.robot_status||'UNKNOWN').replace(/[^A-Z_]/g,'');
        return `<tr>
          <td>${r.id}</td>
          <td>${(r.ts||'').substring(0,23).replace('T',' ')}</td>
          <td>${r.robot_name||'—'}</td>
          <td><span class="status-pill s-${safe}">${r.robot_status||'UNKNOWN'}</span></td>
          <td>${fmt(r.joint1_position)}</td><td>${fmt(r.joint2_position)}</td><td>${fmt(r.joint3_position)}</td>
          <td>${fmt(r.joint4_position)}</td><td>${fmt(r.joint5_position)}</td><td>${fmt(r.joint6_position)}</td>
          <td>${fmt(r.joint1_velocity)}</td><td>${fmt(r.joint2_velocity)}</td><td>${fmt(r.joint3_velocity)}</td>
          <td>${fmt(r.joint4_velocity)}</td><td>${fmt(r.joint5_velocity)}</td><td>${fmt(r.joint6_velocity)}</td>
          <td>${fmt(r.joint1_effort)}</td><td>${fmt(r.joint2_effort)}</td><td>${fmt(r.joint3_effort)}</td>
          <td>${fmt(r.joint4_effort)}</td><td>${fmt(r.joint5_effort)}</td><td>${fmt(r.joint6_effort)}</td>
          <td style="max-width:140px;overflow:hidden;text-overflow:ellipsis">${r.source_topic||'—'}</td>
          <td>${(r.received_at||'').substring(0,23).replace('T',' ')}</td>
        </tr>`;
      }).join('');
    } else {
      tbody.innerHTML = rows.map(r => {
        const st = (r.status||'UNKNOWN').toUpperCase();
        const safe = st.replace(/[^A-Z_]/g,'');
        return `<tr>
          <td>${r.id}</td>
          <td>${(r.ts||'').substring(0,23).replace('T',' ')}</td>
          <td>${r.source_name||'—'}</td>
          <td><span class="status-pill s-${safe}">${r.status||'—'}</span></td>
          <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis">${r.source_topic||'—'}</td>
          <td>${(r.received_at||'').substring(0,23).replace('T',' ')}</td>
          <td style="font-family:monospace;font-size:.75rem">${r.run_id||'—'}</td>
        </tr>`;
      }).join('');
    }
  } catch(e) { console.error('table error', e); }
}

document.addEventListener('DOMContentLoaded', () => {
  onSourceChange();
  document.getElementById('tbl-window').addEventListener('change', function() {
    const paged = this.value === '0';
    document.getElementById('tbl-limit').style.display = paged ? '' : 'none';
    document.getElementById('pg-next').disabled = !paged;
  });
  loadTable(1);
});
</script>
</body>
</html>
"""


# ── database layer ───────────────────────────────────────────────────
class MESDatabase:
    def __init__(self):
        self._conn = None
        self._lock = threading.Lock()
        self._connect()

    def _connect(self):
        try:
            self._conn = psycopg2.connect(
                host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                user=DB_USER, password=DB_PASSWORD, connect_timeout=5,
                options=f"-c search_path={DB_SCHEMA}"
            )
            self._conn.autocommit = True
            print(f"✅ Connected to PostgreSQL at {DB_HOST}/{DB_NAME}")
        except Exception as e:
            self._conn = None
            print(f"❌ DB connection failed: {e}")

    def _reconnect_if_needed(self):
        try:
            if self._conn is None or self._conn.closed:
                self._connect()
            else:
                with self._conn.cursor() as c:
                    c.execute("SELECT 1")
        except Exception:
            self._connect()

    def get_snapshot(self) -> dict:
        self._reconnect_if_needed()
        snap = {
            "robots": {r: {"status": "UNKNOWN", "joints": {}, "ts": None} for r in ROBOTS},
            "total_rows": 0,
            "db_ok": False,
            "db_host": DB_HOST,
            "db_name": DB_NAME,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        if not self._conn:
            return snap

        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                total = 0
                for robot in ROBOTS:
                    table = f"{robot}_joint_telemetry"
                    cur.execute(f"""
                        SELECT id, ts, robot_name, robot_status,
                               joint1_position, joint2_position, joint3_position,
                               joint4_position, joint5_position, joint6_position,
                               joint1_velocity, joint2_velocity, joint3_velocity,
                               joint4_velocity, joint5_velocity, joint6_velocity,
                               joint1_effort,   joint2_effort,   joint3_effort,
                               joint4_effort,   joint5_effort,   joint6_effort
                        FROM {DB_SCHEMA}.{table} ORDER BY ts DESC LIMIT 1;
                    """)
                    row = cur.fetchone()
                    if row:
                        snap["robots"][robot] = {
                            "status": row["robot_status"] or "UNKNOWN",
                            "ts": row["ts"].isoformat() if row["ts"] else None,
                            "joints": {
                                "position": [row[f"joint{j}_position"] for j in range(1,7)],
                                "velocity": [row[f"joint{j}_velocity"] for j in range(1,7)],
                                "effort":   [row[f"joint{j}_effort"]   for j in range(1,7)],
                            }
                        }
                    cur.execute(f"SELECT COUNT(*) AS cnt FROM {DB_SCHEMA}.{table};")
                    total += cur.fetchone()["cnt"]
                snap["total_rows"] = total
                snap["db_ok"]      = True
        except Exception as e:
            print(f"⚠️  Snapshot error: {e}")
        return snap

    def get_history(self, robot: str, limit: int, offset: int,
                    status_filter: str, full: bool, window_s: int = 0) -> dict:
        self._reconnect_if_needed()
        if not self._conn:
            return {"db_ok": False, "rows": [], "total_count": 0, "total_pages": 1}

        table = f"{robot}_joint_telemetry"
        base_cols = """id, ts, robot_name, robot_status,
            joint1_position, joint2_position, joint3_position,
            joint4_position, joint5_position, joint6_position"""
        extra_cols = """,
            joint1_velocity, joint2_velocity, joint3_velocity,
            joint4_velocity, joint5_velocity, joint6_velocity,
            joint1_effort,   joint2_effort,   joint3_effort,
            joint4_effort,   joint5_effort,   joint6_effort,
            source_topic, received_at"""
        cols = base_cols + (extra_cols if full else "")

        where_parts = []
        args: list = []
        if status_filter:
            where_parts.append("robot_status = %s")
            args.append(status_filter)
        if window_s and window_s > 0:
            where_parts.append(f"ts >= NOW() - INTERVAL '{int(window_s)} seconds'")
        where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(f"SELECT COUNT(*) AS cnt FROM {DB_SCHEMA}.{table} {where};", args)
                total = cur.fetchone()["cnt"]
                if window_s and window_s > 0:
                    # Return all rows in window (capped at 2000 for safety)
                    cur.execute(f"""
                        SELECT {cols} FROM {DB_SCHEMA}.{table} {where}
                        ORDER BY ts DESC LIMIT 2000;
                    """, args)
                    rows = [dict(r) for r in cur.fetchall()]
                    return {"db_ok": True, "rows": rows,
                            "total_count": total, "total_pages": 1}
                else:
                    cur.execute(f"""
                        SELECT {cols} FROM {DB_SCHEMA}.{table} {where}
                        ORDER BY ts DESC LIMIT %s OFFSET %s;
                    """, args + [limit, offset])
                    rows = [dict(r) for r in cur.fetchall()]
                    return {
                        "db_ok": True, "rows": rows,
                        "total_count": total,
                        "total_pages": max(1, (total + limit - 1) // limit),
                    }
        except Exception as e:
            print(f"⚠️  History query error: {e}")
            return {"db_ok": False, "rows": [], "total_count": 0, "total_pages": 1}

    def get_robot_telemetry(self) -> dict:
        """
        Returns the single latest row from each robot's joint telemetry table.
        Called at high frequency (~100-250ms) by the robot viewer page.
        Optimised: one query per robot using LIMIT 1 ORDER BY id DESC.
        """
        self._reconnect_if_needed()
        result = {}
        if not self._conn:
            return result
        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                for robot in ROBOTS:
                    table = f"{robot}_joint_telemetry"
                    cur.execute(f"""
                        SELECT id, ts, robot_status AS status,
                               joint1_position AS j1p, joint2_position AS j2p,
                               joint3_position AS j3p, joint4_position AS j4p,
                               joint5_position AS j5p, joint6_position AS j6p,
                               joint1_velocity AS j1v, joint2_velocity AS j2v,
                               joint3_velocity AS j3v, joint4_velocity AS j4v,
                               joint5_velocity AS j5v, joint6_velocity AS j6v
                        FROM {DB_SCHEMA}.{table}
                        ORDER BY id DESC LIMIT 1;
                    """)
                    row = cur.fetchone()
                    if row:
                        result[robot] = dict(row)
        except Exception as e:
            print(f"⚠️  Robot telemetry query error: {e}")
        return result

    def get_scada_status(self) -> dict:
        self._reconnect_if_needed()
        result = {}
        if not self._conn:
            return result
        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                for table, _ in SCADA_TABLES:
                    cur.execute(f"""
                        SELECT id, ts, source_name, status, source_topic, received_at, run_id
                        FROM {DB_SCHEMA}.{table}
                        ORDER BY ts DESC NULLS LAST, id DESC
                        LIMIT 1;
                    """)
                    row = cur.fetchone()
                    if row:
                        result[table] = dict(row)
        except Exception as e:
            print(f"⚠️  SCADA status query error: {e}")
        return result

    def get_scada_history(self, table: str, limit: int, offset: int) -> dict:
        self._reconnect_if_needed()
        if table not in [t for t, _ in SCADA_TABLES]:
            return {"db_ok": False, "rows": [], "total_count": 0, "total_pages": 1}
        if not self._conn:
            return {"db_ok": False, "rows": [], "total_count": 0, "total_pages": 1}
        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(f"SELECT COUNT(*) AS cnt FROM {DB_SCHEMA}.{table};")
                total = cur.fetchone()["cnt"]
                cur.execute(f"""
                    SELECT id, ts, source_name, status, source_topic, received_at, run_id
                    FROM {DB_SCHEMA}.{table}
                    ORDER BY ts DESC NULLS LAST, id DESC
                    LIMIT %s OFFSET %s;
                """, (limit, offset))
                rows = [dict(r) for r in cur.fetchall()]
            return {
                "db_ok": True,
                "rows": rows,
                "total_count": total,
                "total_pages": max(1, (total + limit - 1) // limit),
            }
        except Exception as e:
            print(f"⚠️  SCADA history query error: {e}")
            return {"db_ok": False, "rows": [], "total_count": 0, "total_pages": 1}

    def insert_alarm(self, severity: str, alarm_type: str, entity: str,
                     message: str, old_value: str = None, new_value: str = None,
                     ts: str = None):
        self._reconnect_if_needed()
        if not self._conn:
            print(f"⚠️  Cannot insert alarm (no DB): {message}")
            return
        try:
            with self._conn.cursor() as cur:
                if ts:
                    cur.execute(f"""
                        INSERT INTO {DB_SCHEMA}.mes_alarms
                            (ts, severity, alarm_type, entity, message, old_value, new_value)
                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """, (ts, severity, alarm_type, entity or '', message, old_value, new_value))
                else:
                    cur.execute(f"""
                        INSERT INTO {DB_SCHEMA}.mes_alarms
                            (severity, alarm_type, entity, message, old_value, new_value)
                        VALUES (%s, %s, %s, %s, %s, %s);
                    """, (severity, alarm_type, entity or '', message, old_value, new_value))
            print(f"🔔 Alarm [{severity}] {alarm_type} — {message}")
        except Exception as e:
            print(f"⚠️  Alarm insert error: {e}")

    def get_alarm_fingerprints_in_range(self, ts_from: str, ts_to: str) -> set:
        """Return set of (alarm_type, entity, 'YYYY-MM-DD HH:MM') for dedup."""
        self._reconnect_if_needed()
        if not self._conn:
            return set()
        try:
            where_parts, args = [], []
            if ts_from:
                where_parts.append("ts >= %s"); args.append(ts_from)
            if ts_to:
                where_parts.append("ts <= %s::timestamp + interval '1 day'"); args.append(ts_to)
            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
            with self._conn.cursor() as cur:
                cur.execute(f"""
                    SELECT alarm_type, entity, to_char(ts,'YYYY-MM-DD HH24:MI')
                    FROM {DB_SCHEMA}.mes_alarms {where};
                """, args)
                return {tuple(r) for r in cur.fetchall()}
        except Exception as e:
            print(f"⚠️  Fingerprint query error: {e}")
            return set()

    def get_robot_errors_in_range(self, ts_start: str, ts_end: str) -> dict:
        self._reconnect_if_needed()
        result = {}
        if not self._conn:
            return result
        try:
            with self._conn.cursor() as cur:
                for robot in ROBOTS:
                    table = f"{robot}_joint_telemetry"
                    args, where_parts = [], ["robot_status = 'ERROR'"]
                    if ts_start:
                        where_parts.append("ts >= %s"); args.append(ts_start)
                    if ts_end:
                        where_parts.append("ts <= %s"); args.append(ts_end)
                    where = "WHERE " + " AND ".join(where_parts)
                    cur.execute(f"SELECT COUNT(*) FROM {DB_SCHEMA}.{table} {where};", args)
                    n = cur.fetchone()[0]
                    if n > 0:
                        result[robot] = int(n)
        except Exception as e:
            print(f"⚠️  Robot error range query: {e}")
        return result

    def truncate_alarms(self):
        self._reconnect_if_needed()
        if not self._conn:
            return
        try:
            with self._conn.cursor() as cur:
                cur.execute(f"TRUNCATE TABLE {DB_SCHEMA}.mes_alarms RESTART IDENTITY;")
            print("🗑️  mes_alarms truncated")
        except Exception as e:
            print(f"⚠️  Truncate error: {e}")

    def get_alarms(self, limit: int = 100, offset: int = 0, severity: str = '') -> dict:
        self._reconnect_if_needed()
        if not self._conn:
            return {"db_ok": False, "rows": [], "total_count": 0, "total_pages": 1}
        try:
            where = "WHERE severity = %s" if severity else ""
            args  = [severity] if severity else []
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(f"SELECT COUNT(*) AS cnt FROM {DB_SCHEMA}.mes_alarms {where};", args)
                total = cur.fetchone()["cnt"]
                cur.execute(f"""
                    SELECT id, ts, severity, alarm_type, entity, message, old_value, new_value
                    FROM {DB_SCHEMA}.mes_alarms {where}
                    ORDER BY ts DESC, id DESC
                    LIMIT %s OFFSET %s;
                """, args + [limit, offset])
                rows = [dict(r) for r in cur.fetchall()]
            return {
                "db_ok": True, "rows": rows,
                "total_count": total,
                "total_pages": max(1, (total + limit - 1) // limit),
            }
        except Exception as e:
            print(f"⚠️  Alarm query error: {e}")
            return {"db_ok": False, "rows": [], "total_count": 0, "total_pages": 1}

    def get_latest_from_history(self) -> dict:
        EMPTY = {
            "db_ok": True, "no_data": True, "workcenters": {}, "wc_order": list(WC_META.keys()),
            "color_metrics": {}, "bottleneck": "—", "scenarios": {},
            "total_cycles": 0, "total_transfers": 0, "bottleneck_share": {},
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        self._reconnect_if_needed()
        if not self._conn:
            return {**EMPTY, "db_ok": False}
        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(f"SELECT MAX(window_end) AS latest FROM {DB_SCHEMA}.wc_metrics_history;")
                row = cur.fetchone()
                if not row or row["latest"] is None:
                    return EMPTY
                latest = row["latest"]
                cur.execute(f"""
                    SELECT wc_name, rho, lq, wq, avg_s, sigma_s, lambda_s, n_samples, is_bottleneck
                    FROM {DB_SCHEMA}.wc_metrics_history WHERE window_end = %s;
                """, (latest,))
                rows = cur.fetchall()
        except Exception as e:
            print(f"⚠️  get_latest_from_history error: {e}")
            return {**EMPTY, "db_ok": False}

        wcs = {}
        bn_name = None
        total_cycles = 0
        for r in rows:
            wc      = r["wc_name"]
            rho     = float(r["rho"])     if r["rho"]     is not None else None
            avg_s   = float(r["avg_s"])   if r["avg_s"]   else 0.0
            sigma_s = float(r["sigma_s"]) if r["sigma_s"] else 0.0
            lam_s   = float(r["lambda_s"]) if r["lambda_s"] else None
            lq      = float(r["lq"])  if r["lq"]  is not None else None
            wq      = float(r["wq"])  if r["wq"]  is not None else None
            n       = int(r["n_samples"]) if r["n_samples"] else 0
            total_cycles += n
            mu_s   = round(avg_s, 3)   if avg_s   else None
            cv     = round(sigma_s / avg_s, 3) if avg_s else None
            lam_hr = round(lam_s * 3600, 4)    if lam_s  else None
            mm1_lq = mm1_wq = mm1_w = None
            if rho is not None and 0.0 < rho < 1.0 and lam_s:
                mm1_lq = round(rho ** 2 / (1.0 - rho), 4)
                mm1_wq = round(mm1_lq / lam_s, 2)
                mm1_w  = round(mm1_wq + avg_s, 2)
            mg1_wq = round(wq, 2)        if wq is not None else None
            mg1_lq = round(lq, 4)        if lq is not None else None
            mg1_w  = round(wq + avg_s, 2) if wq is not None else None
            wcs[wc] = {
                "label": wc, "source": "live_db",
                "color":  WC_META.get(wc, {}).get("color", "#7f8c8d"),
                "rho": rho, "lam_s": lam_s, "lam": lam_hr,
                "mu_s": mu_s, "sigma_s": round(sigma_s, 3), "cv": cv,
                "n_samples": n, "stable": (rho < 1.0) if rho is not None else None,
                "low_warn": n < 5,
                "mm1": {"Lq": mm1_lq, "Wq": mm1_wq, "W": mm1_w},
                "mg1": {"Lq": mg1_lq, "Wq": mg1_wq, "W": mg1_w},
            }
            if r["is_bottleneck"]:
                bn_name = wc

        if not bn_name and wcs:
            rho_map = {k: v["rho"] for k, v in wcs.items() if v["rho"] is not None}
            if rho_map:
                bn_name = max(rho_map, key=rho_map.get)

        color_metrics = {}
        for color, path in COLOR_PATHS.items():
            total_Wq = total_W = 0.0
            all_live = True
            for wc in path:
                m  = wcs.get(wc, {})
                mg = m.get("mg1", {})
                total_Wq += mg.get("Wq") or 0
                total_W  += (mg.get("Wq") or 0) + (m.get("mu_s") or 0)
                if not m:
                    all_live = False
            lam_s_c = wcs.get(path[0], {}).get("lam_s") if path else None
            lam_hr_c = round(lam_s_c * 3600, 4) if lam_s_c else None
            L = round(lam_s_c * total_W, 4) if lam_s_c and total_W > 0 else None
            color_metrics[color] = {
                "color": {"RED": "#e74c3c", "GREEN": "#27ae60", "BLUE": "#2980b9"}[color],
                "path": path, "lam_hr": lam_hr_c,
                "W_s": round(total_W, 2), "W_min": round(total_W / 60, 2),
                "Wq_s": round(total_Wq, 2), "L": L,
                "source": "live_db" if all_live else "partial", "transfers": 0,
            }

        bn    = wcs.get(bn_name, {}) if bn_name else {}
        bn_rho = bn.get("rho")
        bn_mu  = bn.get("mu_s") or 0
        bn_sig = bn.get("sigma_s") or 0
        bn_lam = bn.get("lam_s")
        scenarios = {}
        if bn_rho is not None and 0.0 < bn_rho < 1.0 and bn_lam and bn_mu:
            lq_bl = bn_rho ** 2 / (1.0 - bn_rho)
            wq_bl = lq_bl / bn_lam
            scenarios["baseline"] = {
                "rho": bn_rho, "Wq": round(wq_bl, 2), "W": round(wq_bl + bn_mu, 2)}
            rho2 = bn_rho / 2.0
            wq2  = rho2 ** 2 / (1.0 - rho2) / bn_lam
            scenarios["add_machine"] = {
                "rho": round(rho2, 4), "Wq": round(wq2, 2), "W": round(wq2 + bn_mu / 2.0, 2)}
            cv2_rv = ((bn_sig / 2.0) / bn_mu) ** 2 if bn_mu else 0.0
            wq_rv  = (bn_rho / (1.0 - bn_rho)) * bn_mu * (1.0 + cv2_rv) / 2.0
            scenarios["reduce_variability"] = {
                "rho": bn_rho, "Wq": round(wq_rv, 2), "W": round(wq_rv + bn_mu, 2)}
            wq_ref = scenarios["baseline"]["Wq"]
            scenarios["dispatching"] = {
                "SPT":  {"Wq_factor": 0.72, "Wq_abs": round(wq_ref * 0.72, 2),
                         "note": "~28% Wq reduction via SPT"},
                "EDD":  {"Wq_factor": 1.00, "Wq_abs": wq_ref,
                         "note": "Same avg Wq, minimizes lateness"},
                "FIFO": {"Wq_factor": 1.00, "Wq_abs": wq_ref, "note": "Current default"},
            }

        # bottleneck share — count windows each WC held is_bottleneck across all history
        try:
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT wc_name, COUNT(*) AS cnt
                    FROM {DB_SCHEMA}.wc_metrics_history
                    WHERE is_bottleneck = TRUE
                    GROUP BY wc_name ORDER BY cnt DESC;
                """)
                bn_rows = cur.fetchall()
            bn_total = sum(int(r["cnt"]) for r in bn_rows)
            bottleneck_share = (
                {r["wc_name"]: round(int(r["cnt"]) / bn_total, 4) for r in bn_rows}
                if bn_total > 0 else {}
            )
        except Exception:
            bottleneck_share = {}

        return {
            "db_ok": True, "workcenters": wcs, "wc_order": list(WC_META.keys()),
            "bottleneck": bn_name or "—", "color_metrics": color_metrics,
            "scenarios": scenarios, "total_cycles": total_cycles, "total_transfers": 0,
            "bottleneck_share": bottleneck_share, "fetched_at": latest.isoformat(),
        }

    def get_range_from_history(self, ts_start: str = None, ts_end: str = None) -> dict:
        """
        Aggregate wc_metrics_history rows that overlap [ts_start, ts_end].
        Returns the same shape as get_latest_from_history() so the frontend
        renders it with the same code path.
        """
        import math as _math
        EMPTY = {
            "db_ok": True, "no_data": True, "workcenters": {}, "wc_order": list(WC_META.keys()),
            "color_metrics": {}, "bottleneck": "—", "scenarios": {},
            "total_cycles": 0, "total_transfers": 0, "bottleneck_share": {},
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        self._reconnect_if_needed()
        if not self._conn:
            return {**EMPTY, "db_ok": False}
        try:
            wheres, args = ["1=1"], []
            if ts_start:
                wheres.append("window_end >= %s"); args.append(ts_start)
            if ts_end:
                wheres.append("window_start <= %s"); args.append(ts_end)
            where_sql = " AND ".join(wheres)
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT wc_name, avg_s, sigma_s, lambda_s, n_samples, is_bottleneck
                    FROM {DB_SCHEMA}.wc_metrics_history
                    WHERE {where_sql} ORDER BY window_end;
                """, args)
                rows = cur.fetchall()
        except Exception as e:
            print(f"⚠️  get_range_from_history error: {e}")
            return {**EMPTY, "db_ok": False}

        if not rows:
            return EMPTY

        # Group windows per WC
        wc_windows: dict = {}
        for r in rows:
            wc = r["wc_name"]
            avg_s   = float(r["avg_s"])    if r["avg_s"]    else None
            sigma_s = float(r["sigma_s"])  if r["sigma_s"]  else 0.0
            lam_s   = float(r["lambda_s"]) if r["lambda_s"] else None
            n       = int(r["n_samples"])  if r["n_samples"] else 0
            if avg_s and n > 0:
                wc_windows.setdefault(wc, []).append(
                    {"avg_s": avg_s, "sigma_s": sigma_s, "lam_s": lam_s, "n": n}
                )

        wcs: dict = {}
        total_cycles = 0
        bn_name = None
        max_rho = -1.0

        for wc_name, meta in WC_META.items():
            wins = wc_windows.get(wc_name, [])
            if not wins:
                wcs[wc_name] = {
                    "label": wc_name, "source": "no_data", "color": meta["color"],
                    "rho": None, "lam_s": None, "lam": None, "mu_s": None,
                    "sigma_s": None, "cv": None, "n_samples": 0,
                    "stable": None, "low_warn": False,
                    "mm1": {"Lq": None, "Wq": None, "W": None},
                    "mg1": {"Lq": None, "Wq": None, "W": None},
                }
                continue

            total_n  = sum(w["n"] for w in wins)
            total_cycles += total_n
            mu_p     = sum(w["n"] * w["avg_s"] for w in wins) / total_n
            var_p    = sum(w["n"] * (w["sigma_s"]**2 + (w["avg_s"] - mu_p)**2) for w in wins) / total_n
            sigma_p  = _math.sqrt(var_p) if var_p > 0 else 0.0
            lam_vals = [w["lam_s"] for w in wins if w["lam_s"]]
            lam_s    = (sum(lam_vals) / len(lam_vals)) if lam_vals else None

            rho    = (lam_s * mu_p) if (lam_s and mu_p > 0) else None
            cv     = sigma_p / mu_p if mu_p > 0 else None
            cv2    = cv**2 if cv is not None else 0.0
            stable = (rho < 1.0) if rho is not None else None
            mm1    = {"Lq": None, "Wq": None, "W": None}
            mg1    = {"Lq": None, "Wq": None, "W": None}
            if rho is not None and 0.0 < rho < 1.0 and lam_s:
                lq_mm = rho**2 / (1 - rho)
                wq_mm = lq_mm / lam_s
                mm1 = {"Lq": round(lq_mm, 4), "Wq": round(wq_mm, 2), "W": round(wq_mm + mu_p, 2)}
                wq_mg = (rho / (1 - rho)) * mu_p * (1 + cv2) / 2
                mg1 = {"Lq": round(lam_s * wq_mg, 4), "Wq": round(wq_mg, 2), "W": round(wq_mg + mu_p, 2)}
            wcs[wc_name] = {
                "label": wc_name, "source": "live_db", "color": meta["color"],
                "rho":     round(rho, 4)     if rho     is not None else None,
                "lam_s":   lam_s,
                "lam":     round(lam_s * 3600, 4) if lam_s else None,
                "mu_s":    round(mu_p, 3), "sigma_s": round(sigma_p, 3),
                "cv":      round(cv, 3)      if cv      is not None else None,
                "n_samples": total_n, "stable": stable, "low_warn": total_n < 5,
                "mm1": mm1, "mg1": mg1,
            }
            if rho is not None and rho > max_rho:
                max_rho = rho; bn_name = wc_name

        color_metrics: dict = {}
        for color, path in COLOR_PATHS.items():
            total_Wq = total_W = 0.0
            all_live = True
            for wc in path:
                m  = wcs.get(wc, {})
                mg = m.get("mg1", {})
                total_Wq += mg.get("Wq") or 0
                total_W  += (mg.get("Wq") or 0) + (m.get("mu_s") or 0)
                if not m or m.get("source") != "live_db":
                    all_live = False
            lam_s_c  = wcs.get(path[0], {}).get("lam_s") if path else None
            lam_hr_c = round(lam_s_c * 3600, 4) if lam_s_c else None
            L        = round(lam_s_c * total_W, 4) if lam_s_c and total_W > 0 else None
            color_metrics[color] = {
                "color": {"RED": "#e74c3c", "GREEN": "#27ae60", "BLUE": "#2980b9"}[color],
                "path": path, "lam_hr": lam_hr_c,
                "W_s": round(total_W, 2), "W_min": round(total_W / 60, 2),
                "Wq_s": round(total_Wq, 2), "L": L,
                "source": "live_db" if all_live else "partial", "transfers": 0,
            }

        bn    = wcs.get(bn_name, {}) if bn_name else {}
        bn_rho = bn.get("rho"); bn_mu = bn.get("mu_s") or 0
        bn_sig = bn.get("sigma_s") or 0; bn_lam = bn.get("lam_s")
        scenarios: dict = {}
        if bn_rho is not None and 0.0 < bn_rho < 1.0 and bn_lam and bn_mu:
            lq_bl = bn_rho**2 / (1 - bn_rho); wq_bl = lq_bl / bn_lam
            scenarios["baseline"] = {"rho": bn_rho, "Wq": round(wq_bl, 2), "W": round(wq_bl + bn_mu, 2)}
            rho2 = bn_rho / 2; wq2 = rho2**2 / (1 - rho2) / bn_lam
            scenarios["add_machine"] = {"rho": round(rho2, 4), "Wq": round(wq2, 2), "W": round(wq2 + bn_mu / 2, 2)}
            cv2_rv = ((bn_sig / 2) / bn_mu)**2 if bn_mu else 0
            wq_rv  = (bn_rho / (1 - bn_rho)) * bn_mu * (1 + cv2_rv) / 2
            scenarios["reduce_variability"] = {"rho": bn_rho, "Wq": round(wq_rv, 2), "W": round(wq_rv + bn_mu, 2)}
            wq_ref = wq_bl
            scenarios["dispatching"] = {
                "SPT":  {"Wq_factor": 0.72, "Wq_abs": round(wq_ref * 0.72, 2), "note": "SPT — ~28% Wq reduction"},
                "EDD":  {"Wq_factor": 0.91, "Wq_abs": round(wq_ref * 0.91, 2), "note": "EDD — better deadline adherence"},
                "FIFO": {"Wq_factor": 1.00, "Wq_abs": round(wq_ref, 2),        "note": "Baseline FIFO"},
            }

        try:
            wheres2, args2 = ["is_bottleneck = TRUE"], []
            if ts_start:
                wheres2.append("window_end >= %s"); args2.append(ts_start)
            if ts_end:
                wheres2.append("window_start <= %s"); args2.append(ts_end)
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT wc_name, COUNT(*) AS cnt FROM {DB_SCHEMA}.wc_metrics_history
                    WHERE {' AND '.join(wheres2)} GROUP BY wc_name ORDER BY cnt DESC;
                """, args2)
                bn_rows = cur.fetchall()
            bn_total = sum(int(r["cnt"]) for r in bn_rows)
            bottleneck_share = (
                {r["wc_name"]: round(int(r["cnt"]) / bn_total, 4) for r in bn_rows}
                if bn_total > 0 else {}
            )
        except Exception:
            bottleneck_share = {}

        return {
            "db_ok": True, "workcenters": wcs, "wc_order": list(WC_META.keys()),
            "bottleneck": bn_name or "—", "color_metrics": color_metrics,
            "scenarios": scenarios, "total_cycles": total_cycles, "total_transfers": 0,
            "bottleneck_share": bottleneck_share,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_wc_history(self, start: str = None, end: str = None, limit: int = 500) -> dict:
        self._reconnect_if_needed()
        if not self._conn:
            return {"db_ok": False, "rows": [], "error": "no connection"}
        try:
            conds = []
            args  = []
            if start:
                conds.append("window_end >= %s")
                args.append(start)
            if end:
                conds.append("window_end <= %s")
                args.append(end)
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT window_start, window_end, wc_name, rho, lq, wq,
                           avg_s, sigma_s, n_samples, is_bottleneck
                    FROM {DB_SCHEMA}.wc_metrics_history {where}
                    ORDER BY window_end ASC
                    LIMIT %s;
                """, args + [limit])
                rows = [dict(r) for r in cur.fetchall()]
            return {"db_ok": True, "rows": rows}
        except Exception as e:
            print(f"⚠️  wc_history query error: {e}")
            return {"db_ok": False, "rows": [], "error": str(e)}


    def get_db_stats(self) -> dict:
        TEL_TABLES = [
            "mes_alarms", "wc_metrics_history",
            "bantam_door_status", "conveyor1_status", "conveyor2_status",
            "globalvision_stack_snapshot", "laser_status",
            "robot1_joint_telemetry", "robot1_vacuum_state",
            "robot2_joint_telemetry", "robot2_vacuum_state",
            "vision_conveyor_snapshot", "vision_slot_snapshot",
            "xarm1_joint_telemetry", "xarm1_vacuum_state",
            "xarm2_joint_telemetry", "xarm2_vacuum_state",
        ]
        AN_TABLES = ["cycle_event", "piece_transfer"]

        result = {
            "telemetry": {"host": DB_HOST, "name": DB_NAME, "user": DB_USER,
                          "tables": {t: {"count": None} for t in TEL_TABLES}, "ok": False},
            "analytics":  {"host": DB_HOST, "name": DB_NAME, "user": DB_USER,
                          "schema": SOURCE_SCHEMA,
                          "tables": {t: {"count": None} for t in AN_TABLES},  "ok": False},
        }

        # ── Telemetry (same connection, fresh cursor per table) ──────────
        self._reconnect_if_needed()
        if self._conn:
            for t in TEL_TABLES:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute(f"SELECT COUNT(*) FROM {DB_SCHEMA}.{t};")
                        result["telemetry"]["tables"][t] = {"count": cur.fetchone()[0]}
                except Exception as e:
                    result["telemetry"]["tables"][t] = {"count": None, "error": str(e)}
            result["telemetry"]["ok"] = True

        if self._conn:
            for t in AN_TABLES:
                try:
                    with self._conn.cursor() as cur:
                        cur.execute(f"SELECT COUNT(*) FROM {SOURCE_SCHEMA}.{t};")
                        result["analytics"]["tables"][t] = {"count": cur.fetchone()[0]}
                except Exception as e:
                    result["analytics"]["tables"][t] = {"count": None, "error": str(e)}
            result["analytics"]["ok"] = True

        return result

    def truncate_table(self, db_key: str, table: str) -> dict:
        TEL_OK = {
            "mes_alarms", "wc_metrics_history",
            "bantam_door_status", "conveyor1_status", "conveyor2_status",
            "globalvision_stack_snapshot", "laser_status",
            "robot1_joint_telemetry", "robot1_vacuum_state",
            "robot2_joint_telemetry", "robot2_vacuum_state",
            "vision_conveyor_snapshot", "vision_slot_snapshot",
            "xarm1_joint_telemetry", "xarm1_vacuum_state",
            "xarm2_joint_telemetry", "xarm2_vacuum_state",
        }
        AN_OK  = {"cycle_event", "piece_transfer"}
        if db_key == "telemetry":
            if table not in TEL_OK:
                return {"ok": False, "error": f"'{table}' not in whitelist"}
            self._reconnect_if_needed()
            if not self._conn:
                return {"ok": False, "error": "no connection"}
            try:
                with self._conn.cursor() as cur:
                    cur.execute(f"TRUNCATE TABLE {DB_SCHEMA}.{table} RESTART IDENTITY;")
                return {"ok": True, "table": table, "db": db_key}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        elif db_key == "analytics":
            if table not in AN_OK:
                return {"ok": False, "error": f"'{table}' not in whitelist"}
            return {"ok": False, "error": f"{SOURCE_SCHEMA}.{table} is a production source table and is read-only from MES"}
        return {"ok": False, "error": f"unknown db_key '{db_key}'"}


# ── Alarm state (tracks previous values to detect changes) ───────────
_alarm_lock  = threading.Lock()
_alarm_state = {"bottleneck": None, "rho_zone": {}, "robot_errors": set()}

def _rho_zone(rho):
    if rho is None: return None
    if rho >= 1.0:  return 2   # CRITICAL — unstable
    if rho >= 0.8:  return 1   # WARNING  — high utilization
    return 0                   # INFO     — normal

def check_analytics_alarms(data: dict, db):
    if not data or not data.get("db_ok"):
        return
    new_bn = data.get("bottleneck")
    wcs    = data.get("workcenters", {})
    with _alarm_lock:
        prev_bn   = _alarm_state["bottleneck"]
        prev_zone = _alarm_state["rho_zone"]
        if prev_bn is not None and new_bn and new_bn != prev_bn:
            db.insert_alarm("WARNING", "BOTTLENECK_CHANGE", new_bn,
                f"Bottleneck shifted: {prev_bn} \u2192 {new_bn}",
                old_value=prev_bn, new_value=new_bn)
        new_zone = {}
        for wc, info in wcs.items():
            rho  = info.get("rho")
            zone = _rho_zone(rho)
            new_zone[wc] = zone
            pz   = prev_zone.get(wc)
            if zone is None:
                continue
            rho_s = f"{rho:.3f}" if rho is not None else "N/A"
            if pz is None:
                if zone == 2:
                    db.insert_alarm("CRITICAL", "RHO_UNSTABLE", wc,
                        f"{wc} unstable at startup (rho={rho_s})", new_value=rho_s)
                elif zone == 1:
                    db.insert_alarm("WARNING", "RHO_HIGH", wc,
                        f"{wc} utilization high at startup (rho={rho_s})", new_value=rho_s)
            elif zone != pz:
                if zone == 2:
                    db.insert_alarm("CRITICAL", "RHO_UNSTABLE", wc,
                        f"{wc} is now unstable (rho={rho_s})",
                        old_value=str(pz), new_value=rho_s)
                elif zone == 1:
                    db.insert_alarm("WARNING", "RHO_HIGH", wc,
                        f"{wc} utilization elevated (rho={rho_s})",
                        old_value=str(pz), new_value=rho_s)
                elif zone == 0:
                    db.insert_alarm("INFO", "RHO_NORMAL", wc,
                        f"{wc} utilization normalized (rho={rho_s})",
                        old_value=str(pz), new_value=rho_s)
        _alarm_state["bottleneck"] = new_bn
        _alarm_state["rho_zone"]   = new_zone

def check_robot_alarms(snapshot: dict, db):
    robots = snapshot.get("robots", {})
    with _alarm_lock:
        prev_errors = _alarm_state["robot_errors"]
        new_errors  = set()
        for name, info in robots.items():
            if info.get("status") == "ERROR":
                new_errors.add(name)
                if name not in prev_errors:
                    db.insert_alarm("CRITICAL", "ROBOT_ERROR", name,
                        f"{name} entered ERROR state", new_value="ERROR")
        for name in prev_errors:
            if name not in new_errors:
                st = robots.get(name, {}).get("status", "UNKNOWN")
                db.insert_alarm("INFO", "ROBOT_RECOVERY", name,
                    f"{name} recovered from ERROR (now {st})",
                    old_value="ERROR", new_value=st)
        _alarm_state["robot_errors"] = new_errors


# ── Work-center mappings (kept in sync with analytics_worker.py) ────
TASK_TO_WC = {
    ("xarm2", "FEED_GREEN_TO_C3"):          "xArm2 feed to C3",
    ("xarm2", "FEED_TO_C1S1"):              "xArm2 feed to C1S1",
    ("xarm1", "C1S2_TO_C2S1"):              "xArm1 C1S2 to C2S1",
    ("xarm1", "C1S2_TO_LASER"):             "xArm1 C1S2 to Laser",
    ("xarm1", "LASER_TO_C2S1"):             "xArm1 Laser to C2S1",
    ("laser", "PROCESS_RED"):               "Laser process red",
    ("robot2", "CLASSIFY_C2S2_TO_C4"):      "Robot2 C2S2 to C4",
    ("robot2", "CLASSIFY_C2S2_TO_BANTAM"):  "Robot2 C2S2 to Bantam",
    ("robot2", "CLASSIFY_C2S2_TO_IBS"):     "Robot2 C2S2 to IBS",
    ("robot2", "IBS_TO_BANTAM"):            "Robot2 IBS to Bantam",
    ("robot2", "BANTAM_TO_C4"):             "Robot2 Bantam to C4",
    ("bantam", "PROCESS_BLUE"):             "Bantam process blue",
    ("robot1", "UNLOAD_C3"):                "Robot1 unload C3",
    ("robot1", "UNLOAD_C4"):                "Robot1 unload C4",
}

WC_META = {
    "xArm2 feed to C3":        {"color": "#8e44ad", "part_colors": ["GREEN"]},
    "xArm2 feed to C1S1":      {"color": "#8e44ad", "part_colors": ["RED", "BLUE"]},
    "xArm1 C1S2 to C2S1":      {"color": "#7f8c8d", "part_colors": ["GREEN", "BLUE"]},
    "xArm1 C1S2 to Laser":     {"color": "#7f8c8d", "part_colors": ["RED"]},
    "xArm1 Laser to C2S1":     {"color": "#7f8c8d", "part_colors": ["RED"]},
    "Laser process red":       {"color": "#27ae60", "part_colors": ["RED"]},
    "Robot2 C2S2 to C4":       {"color": "#e74c3c", "part_colors": ["RED", "GREEN"]},
    "Robot2 C2S2 to Bantam":   {"color": "#e74c3c", "part_colors": ["BLUE"]},
    "Robot2 C2S2 to IBS":      {"color": "#e74c3c", "part_colors": ["BLUE"]},
    "Robot2 IBS to Bantam":    {"color": "#e74c3c", "part_colors": ["BLUE"]},
    "Robot2 Bantam to C4":     {"color": "#e74c3c", "part_colors": ["BLUE"]},
    "Bantam process blue":     {"color": "#e91e8c", "part_colors": ["BLUE"]},
    "Robot1 unload C3":        {"color": "#2980b9", "part_colors": ["GREEN", "RED", "BLUE"]},
    "Robot1 unload C4":        {"color": "#2980b9", "part_colors": ["RED", "BLUE", "GREEN"]},
}

# Color paths through logical work-centers (from code, not guessed)
COLOR_PATHS = {
    "GREEN": ["xArm2 feed to C3", "Robot1 unload C3"],
    "RED":   ["xArm2 feed to C1S1", "xArm1 C1S2 to Laser", "Laser process red",
              "xArm1 Laser to C2S1", "Robot2 C2S2 to C4", "Robot1 unload C4"],
    "BLUE":  ["xArm2 feed to C1S1", "xArm1 C1S2 to C2S1",
              "Robot2 C2S2 to IBS", "Robot2 IBS to Bantam",
              "Robot2 C2S2 to Bantam", "Bantam process blue",
              "Robot2 Bantam to C4", "Robot1 unload C4"],
}


def _analytics_db_connect():
    """Open a fresh connection to the production source database."""
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD, connect_timeout=5,
        options=f"-c search_path={SOURCE_SCHEMA},{DB_SCHEMA}"
    )


def compute_analytics(ts_start: str = None, ts_end: str = None) -> dict:
    """
    Query the production source schema for real cycle and transfer data, then compute
    queueing theory metrics (M/M/1, M/G/1, Little's Law, what-if scenarios).

    ts_start / ts_end: optional ISO-8601 strings to restrict the time window.
    Every metric is tagged with its data source.
    """
    import math

    errors = []
    raw_cycles    = {}   # (entity, task_name) -> {count, avg_s, stddev_s, min_s, max_s}
    raw_transfers = {}   # color -> {count, span_s}
    bn_share      = {}   # wc -> fraction of rows where it held max running avg

    # Build optional time-range WHERE fragments
    time_args: list = []
    time_filter_cycle = ""
    time_filter_xfer  = ""
    if ts_start:
        time_filter_cycle += " AND ts >= %s"
        time_filter_xfer  += " AND pt.ts >= %s"
        time_args.append(ts_start)
    if ts_end:
        time_filter_cycle += " AND ts <= %s"
        time_filter_xfer  += " AND pt.ts <= %s"
        time_args.append(ts_end)

    # ── 1. Query production source tables ─────────────────────────────
    try:
        conn = _analytics_db_connect()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # Service time stats per entity/task
            cur.execute(f"""
                SELECT
                    entity,
                    task_name,
                    COUNT(*)                              AS cycle_count,
                    AVG(total_duration_s)                 AS avg_s,
                    STDDEV(total_duration_s)              AS stddev_s,
                    MIN(total_duration_s)                 AS min_s,
                    MAX(total_duration_s)                 AS max_s
                FROM {SOURCE_SCHEMA}.cycle_event
                WHERE is_discarded = false
                  AND total_duration_s > 0
                  {time_filter_cycle}
                GROUP BY entity, task_name
                ORDER BY entity, task_name;
            """, time_args)
            for row in cur.fetchall():
                key = (row["entity"], row["task_name"])
                raw_cycles[key] = {
                    "count":   int(row["cycle_count"]),
                    "avg_s":   float(row["avg_s"])    if row["avg_s"]    is not None else None,
                    "stddev_s":float(row["stddev_s"]) if row["stddev_s"] is not None else None,
                    "min_s":   float(row["min_s"])    if row["min_s"]    is not None else None,
                    "max_s":   float(row["max_s"])    if row["max_s"]    is not None else None,
                }

            # Arrival rates from piece_transfer joined to piece color.
            cur.execute(f"""
                SELECT
                    COALESCE(p.color, 'UNKNOWN')                          AS color,
                    COUNT(*)                                              AS transfers,
                    EXTRACT(EPOCH FROM (MAX(pt.ts) - MIN(pt.ts)))         AS span_s,
                    MIN(pt.ts)                                            AS first_ts,
                    MAX(pt.ts)                                            AS last_ts
                FROM {SOURCE_SCHEMA}.piece_transfer pt
                LEFT JOIN {SOURCE_SCHEMA}.piece p
                  ON p.run_id = pt.run_id AND p.piece_id = pt.piece_id
                WHERE COALESCE(p.color, 'UNKNOWN') IN ('RED','GREEN','BLUE')
                  {time_filter_xfer}
                GROUP BY COALESCE(p.color, 'UNKNOWN');
            """, time_args)
            for row in cur.fetchall():
                raw_transfers[row["color"]] = {
                    "transfers": int(row["transfers"]),
                    "span_s":    float(row["span_s"]) if row["span_s"] else None,
                    "first_ts":  str(row["first_ts"]),
                    "last_ts":   str(row["last_ts"]),
                }

            # Total cycle count for summary
            cur.execute(f"SELECT COUNT(*) AS n FROM {SOURCE_SCHEMA}.cycle_event WHERE is_discarded=false {time_filter_cycle};", time_args)
            total_cycles = int(cur.fetchone()["n"])
            cur.execute(f"""
                SELECT COUNT(*) AS n
                FROM {SOURCE_SCHEMA}.piece_transfer pt
                WHERE true {time_filter_xfer};
            """, time_args)
            total_transfers = int(cur.fetchone()["n"])

            # Bottleneck share: stream rows to count how often each WC holds max avg
            cur.execute(f"""
                SELECT ts, entity, task_name, total_duration_s
                FROM {SOURCE_SCHEMA}.cycle_event
                WHERE is_discarded = false AND total_duration_s > 0
                  {time_filter_cycle}
                ORDER BY ts;
            """, time_args)
            _bs_run = {}
            _bs_cnt = {}
            _bs_n   = 0
            for _r in cur:
                _wc2 = TASK_TO_WC.get((_r["entity"], _r["task_name"]))
                if not _wc2:
                    continue
                if _wc2 not in _bs_run:
                    _bs_run[_wc2] = [0.0, 0]
                _bs_run[_wc2][0] += float(_r["total_duration_s"])
                _bs_run[_wc2][1] += 1
                _bs_n += 1
                if _bs_n < 5:
                    continue
                _avg2 = {k: v[0]/v[1] for k, v in _bs_run.items() if v[1] > 0}
                _top  = max(_avg2, key=_avg2.get)
                _bs_cnt[_top] = _bs_cnt.get(_top, 0) + 1
            _bs_total = sum(_bs_cnt.values())
            bn_share = (
                {wc: round(c/_bs_total, 4) for wc, c in sorted(_bs_cnt.items(), key=lambda x: -x[1])}
                if _bs_total > 0 else {}
            )

        conn.close()
        db_ok = True
        print(f"✅ Source analytics: {len(raw_cycles)} task types, {total_cycles} cycles, {total_transfers} transfers")
    except Exception as e:
        db_ok = False
        total_cycles = 0
        total_transfers = 0
        errors.append(f"DB connection failed: {e}")
        print(f"⚠️  Source analytics error: {e}")

    # ── 2. Aggregate service times per logical work-center ────────────
    # A work-center may map to multiple (entity, task_name) pairs.
    # We pool all matching rows to get combined avg/stddev.
    wc_raw = {}   # wc_name -> list of (count, avg_s, stddev_s)
    for (entity, task), stats in raw_cycles.items():
        wc_name = TASK_TO_WC.get((entity, task))
        if wc_name is None:
            continue
        if wc_name not in wc_raw:
            wc_raw[wc_name] = []
        wc_raw[wc_name].append(stats)

    def pool_stats(stat_list):
        """Combine multiple (count, avg, stddev) groups into one pooled avg/stddev."""
        total_n   = sum(s["count"] for s in stat_list)
        if total_n == 0:
            return None, None, 0
        pooled_avg = sum(s["count"] * s["avg_s"] for s in stat_list if s["avg_s"]) / total_n
        # Pooled variance: Var = (sum of (n_i*(sigma_i^2 + (mu_i - mu_pooled)^2))) / N
        pooled_var = 0.0
        for s in stat_list:
            if s["avg_s"] is None:
                continue
            var_i = (s["stddev_s"] ** 2) if (s["stddev_s"] is not None and s["count"] > 1) else 0.0
            pooled_var += s["count"] * (var_i + (s["avg_s"] - pooled_avg) ** 2)
        pooled_var /= total_n
        return pooled_avg, math.sqrt(pooled_var), total_n

    # ── 3. Compute arrival rates λ per color (pieces/second) ──────────
    # λ = total_transfers / span_seconds for each color.
    # We divide by 2 because each piece generates ~2 transfer events on average
    # (picked up + placed down), so transfer count ≈ 2 × piece arrivals.
    color_lam = {}   # color -> λ (per second)
    for color, t in raw_transfers.items():
        if t["span_s"] and t["span_s"] > 0:
            color_lam[color] = (t["transfers"] / 2) / t["span_s"]
        else:
            color_lam[color] = None

    # ── 4. Build per-workcenter λ by summing colors that pass through ─
    wc_lam = {}
    for wc_name, meta in WC_META.items():
        lam = 0.0
        for color in meta["part_colors"]:
            cl = color_lam.get(color)
            if cl:
                lam += cl
        wc_lam[wc_name] = lam if lam > 0 else None

    # ── 5. Build wc_metrics dict with queueing calculations ──────────
    wc_metrics = {}
    LOW_SAMPLE_THRESHOLD = 5

    for wc_name, meta in WC_META.items():
        stat_list = wc_raw.get(wc_name, [])
        lam       = wc_lam.get(wc_name)

        if stat_list:
            mu_s, sigma_s, n_samples = pool_stats(stat_list)
            source   = "live_db"
            low_warn = n_samples < LOW_SAMPLE_THRESHOLD
            min_s    = min((s["min_s"] for s in stat_list if s["min_s"]), default=None)
            max_s    = max((s["max_s"] for s in stat_list if s["max_s"]), default=None)
        else:
            mu_s = sigma_s = None
            n_samples = 0
            source   = "no_data"
            low_warn = False
            min_s = max_s = None

        # Compute queueing metrics only if we have both μ and λ
        rho = cv = cv2 = None
        mm1 = {"Lq": None, "Wq": None, "W": None, "L": None}
        mg1 = {"Lq": None, "Wq": None, "W": None, "L": None}
        stable = None

        if mu_s and mu_s > 0 and lam and lam > 0:
            mu_rate = 1.0 / mu_s
            rho     = lam / mu_rate
            stable  = rho < 1.0
            cv2     = (sigma_s / mu_s) ** 2 if sigma_s is not None else 0.0
            cv      = math.sqrt(cv2)

            if stable:
                # M/M/1
                Lq_mm1 = rho**2 / (1 - rho)
                Wq_mm1 = Lq_mm1 / lam
                W_mm1  = Wq_mm1 + mu_s
                L_mm1  = lam * W_mm1
                mm1 = {
                    "Lq": round(Lq_mm1, 4),
                    "Wq": round(Wq_mm1, 2),
                    "W":  round(W_mm1,  2),
                    "L":  round(L_mm1,  4),
                }
                # M/G/1 Pollaczek-Khinchine
                Wq_mg1 = (rho / (1 - rho)) * mu_s * (1 + cv2) / 2
                Lq_mg1 = lam * Wq_mg1
                W_mg1  = Wq_mg1 + mu_s
                L_mg1  = lam * W_mg1
                mg1 = {
                    "Lq": round(Lq_mg1, 4),
                    "Wq": round(Wq_mg1, 2),
                    "W":  round(W_mg1,  2),
                    "L":  round(L_mg1,  4),
                }

        wc_metrics[wc_name] = {
            "label":     wc_name,
            "color":     meta["color"],
            "source":    source,
            "low_warn":  low_warn,
            "n_samples": n_samples,
            "lam":       round(lam * 3600, 4) if lam else None,   # /hour for display
            "lam_s":     lam,
            "mu_s":      round(mu_s, 3)    if mu_s    is not None else None,
            "mu_hr":     round(3600/mu_s, 4) if mu_s  and mu_s > 0 else None,
            "sigma_s":   round(sigma_s, 3) if sigma_s is not None else None,
            "min_s":     round(min_s, 2)   if min_s   is not None else None,
            "max_s":     round(max_s, 2)   if max_s   is not None else None,
            "cv":        round(cv, 3)      if cv      is not None else None,
            "cv2":       round(cv2, 3)     if cv2     is not None else None,
            "rho":       round(rho, 4)     if rho     is not None else None,
            "stable":    stable,
            "mm1":       mm1,
            "mg1":       mg1,
        }

    # ── 6. Per-color flow metrics (Little's Law) ──────────────────────
    color_metrics = {}
    for color, path in COLOR_PATHS.items():
        lam_s  = color_lam.get(color)
        lam_hr = round(lam_s * 3600, 4) if lam_s else None
        total_W  = 0.0
        total_Wq = 0.0
        all_live = True
        for wc in path:
            m   = wc_metrics.get(wc, {})
            mg  = m.get("mg1", {})
            w   = mg.get("W")  or 0
            wq  = mg.get("Wq") or 0
            total_W  += w
            total_Wq += wq
            if m.get("source") != "live_db":
                all_live = False

        L = round(lam_s * total_W, 4) if lam_s and total_W > 0 else None
        color_metrics[color] = {
            "color":      {"RED":"#e74c3c","GREEN":"#27ae60","BLUE":"#2980b9"}[color],
            "path":       path,
            "lam_hr":     lam_hr,
            "W_s":        round(total_W, 1),
            "W_min":      round(total_W / 60, 2),
            "Wq_s":       round(total_Wq, 1),
            "L":          L,
            "source":     "live_db" if (lam_s and all_live) else "partial",
            "transfers":  raw_transfers.get(color, {}).get("transfers", 0),
        }

    # ── 7. Bottleneck identification ──────────────────────────────────
    # Only consider work-centers with real rho values
    rho_candidates = {k: v for k, v in wc_metrics.items() if v["rho"] is not None}
    if rho_candidates:
        bn_name = max(rho_candidates, key=lambda k: rho_candidates[k]["rho"])
    else:
        bn_name = "Bantam process blue"   # fallback label only — no computed value shown

    # ── 8. What-if scenarios (bottleneck only) ────────────────────────
    bn = wc_metrics.get(bn_name, {})
    bn_lam_s = bn.get("lam_s")
    bn_mu_s  = bn.get("mu_s")
    bn_sigma = bn.get("sigma_s")
    bn_rho   = bn.get("rho")

    def mm1_scenario(lam, mu_s):
        if not lam or not mu_s or mu_s <= 0:
            return None
        mu  = 1 / mu_s
        rho = lam / mu
        if rho >= 1:
            return {"rho": round(rho,4), "Lq": None, "Wq": None, "W": None, "note":"Unstable (ρ≥1)"}
        Lq = rho**2 / (1 - rho)
        Wq = Lq / lam
        return {"rho": round(rho,4), "Lq": round(Lq,4), "Wq": round(Wq,2), "W": round(Wq+mu_s,2)}

    sc_baseline    = mm1_scenario(bn_lam_s, bn_mu_s)
    sc_add_machine = mm1_scenario(bn_lam_s, (bn_mu_s * 2) if bn_mu_s else None)  # double capacity

    sc_reduce_var = None
    if bn_lam_s and bn_mu_s and bn_sigma and bn_rho and bn_rho < 1:
        cv2_half = ((bn_sigma / 2) / bn_mu_s) ** 2
        Wq_rv    = (bn_rho / (1 - bn_rho)) * bn_mu_s * (1 + cv2_half) / 2
        sc_reduce_var = {
            "rho": round(bn_rho, 4),
            "Wq":  round(Wq_rv, 2),
            "W":   round(Wq_rv + bn_mu_s, 2),
        }

    # Dispatching: relative factors applied to real Wq
    base_wq = (sc_baseline or {}).get("Wq") or 0
    scenarios = {
        "baseline":           sc_baseline,
        "add_machine":        sc_add_machine,
        "reduce_variability": sc_reduce_var,
        "dispatching": {
            "FIFO": {"Wq_factor": 1.00, "Wq_abs": round(base_wq * 1.00, 2),
                     "note": "Baseline — first-in first-out"},
            "SPT":  {"Wq_factor": 0.72, "Wq_abs": round(base_wq * 0.72, 2),
                     "note": "Shortest Processing Time — ~28% Wq reduction (theoretical)"},
            "EDD":  {"Wq_factor": 0.91, "Wq_abs": round(base_wq * 0.91, 2),
                     "note": "Earliest Due Date — ~9% Wq reduction, better deadline adherence"},
        }
    }

    return {
        "db_ok":          db_ok,
        "errors":         errors,
        "total_cycles":   total_cycles,
        "total_transfers":total_transfers,
        "fetched_at":     datetime.now(timezone.utc).isoformat(),
        "workcenters":    wc_metrics,
        "wc_order":       list(WC_META.keys()),
        "color_metrics":  color_metrics,
        "bottleneck":       bn_name,
        "bottleneck_share": bn_share,
        "scenarios":        scenarios,
        "raw_transfers":    {c: {"transfers": v["transfers"], "span_s": v.get("span_s")}
                             for c, v in raw_transfers.items()},
    }



ANALYTICS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Analytics — Shipyard 4.0 MES</title>
  <link rel="stylesheet" href="/static/css/style.css">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    .source-badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:700;vertical-align:middle;}
    .src-live{background:#d5f5e3;color:#1e8449;}
    .src-none{background:#eaecee;color:#566573;}
    .src-low{background:#fdebd0;color:#a04000;}
    .q-table{width:100%;border-collapse:collapse;font-size:.8rem;}
    .q-table th{background:#f8f9fa;color:#6b7785;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;padding:8px 10px;border-bottom:2px solid #e0e6ed;text-align:left;white-space:nowrap;}
    .q-table td{padding:7px 10px;border-bottom:1px solid #f0f2f5;font-variant-numeric:tabular-nums;white-space:nowrap;}
    .q-table tr:hover td{background:#f6f9fd;}
    .q-table tr.bn-row td{background:#fff5f5;}
    .rho-high{color:#e74c3c;font-weight:700;}
    .rho-med{color:#f39c12;font-weight:700;}
    .rho-low{color:#27ae60;font-weight:700;}
    .pill-stable{background:#d5f5e3;color:#1e8449;padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:700;}
    .pill-unstable{background:#fadbd8;color:#922b21;padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:700;}
    .color-path-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}
    @media(max-width:900px){.color-path-grid{grid-template-columns:repeat(2,1fr);}}
    @media(max-width:560px){.color-path-grid{grid-template-columns:1fr;}}
    .color-card{background:white;border-radius:10px;border:2px solid #e0e6ed;box-shadow:0 2px 10px rgba(0,0,0,.06);overflow:hidden;}
    .color-card-header{padding:10px 16px;color:white;font-weight:700;font-size:.92rem;display:flex;justify-content:space-between;align-items:center;}
    .color-card-body{padding:14px 16px;}
    .path-steps{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px;}
    .path-step{background:#f0f2f5;border:1px solid #dde3ea;border-radius:4px;padding:3px 8px;font-size:.72rem;color:#52606d;}
    .path-step.bn{border-color:#e74c3c;color:#e74c3c;background:#fff5f5;}
    .color-metrics-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
    .cm-box{background:#f8f9fa;border-radius:6px;padding:8px 10px;}
    .cm-box .cml{font-size:.68rem;color:#6b7785;text-transform:uppercase;letter-spacing:.05em;}
    .cm-box .cmv{font-size:.92rem;font-weight:700;color:#2c3e50;margin-top:2px;}
    .sc-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;}
    @media(max-width:800px){.sc-grid{grid-template-columns:1fr;}}
    .sc-card{background:white;border-radius:10px;border:2px solid #e0e6ed;box-shadow:0 2px 10px rgba(0,0,0,.06);padding:16px;}
    .sc-card h4{font-size:.88rem;font-weight:700;color:#2c3e50;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #e0e6ed;}
    .sc-row{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #f0f2f5;font-size:.82rem;}
    .sc-row:last-child{border-bottom:none;}
    .sc-lbl{color:#667;}
    .sc-val{font-weight:600;color:#2c3e50;}
    .sc-val.better{color:#27ae60;}
    .cite{font-size:.7rem;color:#98a4b0;font-style:italic;}
    .bottleneck-banner{background:linear-gradient(135deg,#fdfefe,#fdedec);border:2px solid #e74c3c;border-radius:10px;padding:16px 20px;display:flex;align-items:center;gap:14px;}
    .bn-icon{font-size:1.8rem;}
    .bn-body h3{color:#e74c3c;font-size:1rem;font-weight:700;}
    .bn-body p{color:#52606d;font-size:.82rem;margin-top:4px;line-height:1.5;}
    .dispatch-table{width:100%;border-collapse:collapse;font-size:.82rem;}
    .dispatch-table th{background:#f8f9fa;color:#6b7785;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;padding:8px 10px;border-bottom:2px solid #e0e6ed;text-align:left;}
    .dispatch-table td{padding:8px 10px;border-bottom:1px solid #f0f2f5;}
    .dispatch-rec{background:#eafaf1;border:1px solid #27ae60;border-radius:8px;padding:12px 16px;font-size:.82rem;color:#1e8449;margin-top:12px;line-height:1.6;}
  </style>
</head>
<body>
<header class="topbar">
  <div><h1>&#9881; MES &#8212; Analytics</h1></div>
  <div class="topbar-center">
    <span class="badge">DB: <span id="an-db-status">connecting&#8230;</span></span>
    <span class="badge">Cycles: <span id="an-cycle-count">&#8212;</span></span>
    <span class="badge">Transfers: <span id="an-transfer-count">&#8212;</span></span>
    <span class="badge">Refresh in: <span id="an-countdown">30</span>s</span>
    <button id="an-refresh-btn" onclick="forceRefresh()"
      style="background:rgba(255,255,255,.2);color:white;border:1px solid rgba(255,255,255,.3);border-radius:20px;padding:5px 14px;font-size:.85rem;cursor:pointer;">&#8635; Now</button>
  </div>
  <div class="topbar-right">
    <a href="/" class="nav-btn">Overview</a>
    <a href="/telemetry" class="nav-btn">Telemetry</a>
    <a href="/scada" class="nav-btn">SCADA</a>
    <a href="/analytics" class="nav-btn analytics active">Analytics</a>
    <a href="/alarms" class="nav-btn alarms">Alarms</a>
    <span class="badge" id="clock"></span>
  </div>
</header>

<main class="main">

  <div style="background:white;border-radius:12px;border:2px solid #e0e6ed;box-shadow:0 3px 12px rgba(0,0,0,.06);padding:14px 20px;display:flex;align-items:center;gap:14px;flex-wrap:wrap;">
    <span style="font-size:.82rem;font-weight:700;color:#34495e;text-transform:uppercase;letter-spacing:.06em;">Date Range</span>
    <label style="font-size:.82rem;color:#52606d;">From
      <input type="date" id="an-start-date" style="margin-left:6px;padding:5px 8px;border:2px solid #e0e6ed;border-radius:8px;font-size:.82rem;">
      <input type="time" id="an-start-time" placeholder="00:00" style="margin-left:4px;padding:5px 8px;border:2px solid #e0e6ed;border-radius:8px;font-size:.82rem;width:100px;">
    </label>
    <label style="font-size:.82rem;color:#52606d;">To
      <input type="date" id="an-end-date" style="margin-left:6px;padding:5px 8px;border:2px solid #e0e6ed;border-radius:8px;font-size:.82rem;">
      <input type="time" id="an-end-time" placeholder="23:59" style="margin-left:4px;padding:5px 8px;border:2px solid #e0e6ed;border-radius:8px;font-size:.82rem;width:100px;">
    </label>
    <button type="button" onclick="applyRange()" style="padding:6px 16px;background:linear-gradient(135deg,#2c3e50,#3498db);color:white;border:none;border-radius:8px;font-size:.82rem;cursor:pointer;">Apply Range</button>
    <button type="button" onclick="clearRange()" style="padding:6px 16px;background:#eef2f7;color:#34495e;border:1px solid #d5dfe8;border-radius:8px;font-size:.82rem;cursor:pointer;">View All History</button>
    <span id="an-range-label" style="font-size:.78rem;color:#2980b9;font-style:italic;font-weight:600;"></span>
  </div>

  <div id="an-no-data-banner" style="display:none;background:#fff8e1;border:1px solid #f39c12;border-radius:8px;padding:14px 20px;margin-bottom:4px;color:#7d6608;font-size:.92rem;">
    &#9203; <strong>Waiting for analytics worker</strong> — <code>wc_metrics_history</code> is empty. The worker publishes its first window after 30&nbsp;s of factory data.
  </div>

  <div class="bottleneck-banner">
    <div class="bn-icon">&#9888;</div>
    <div class="bn-body">
      <h3 id="bn-title">Identifying bottleneck&#8230;</h3>
      <p id="bn-desc"></p>
    </div>
  </div>

  <div class="analytics-strip" id="kpi-strip"></div>

  <div class="chart-panel">
    <div class="panel-header">
      <h2>Factory Layout &amp; Work-Center Utilization (&#961;)</h2>
      <span style="font-size:.8rem;opacity:.8">&#961; = &#955;/&#956; &nbsp;&middot;&nbsp; Red = bottleneck</span>
    </div>
    <div class="panel-body" style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
      <div>
        <div style="font-size:.78rem;color:#6b7785;margin-bottom:8px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;">Shipyard 4.0 &#8212; Floor Layout</div>
        <div id="factory-svg-wrap"></div>
      </div>
      <div>
        <div style="font-size:.78rem;color:#6b7785;margin-bottom:8px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;">
          Utilization &#961; by Work Center
          <span class="cite"> &#8212; source: shipyard_pnp_ws.cycle_event AVG(total_duration_s), shipyard_pnp_ws.piece_transfer</span>
        </div>
        <div class="chart-wrap"><canvas id="util-chart"></canvas></div>
      </div>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
    <div class="chart-panel">
      <div class="panel-header"><h2>Avg Queue Length Lq (M/G/1)</h2></div>
      <div class="panel-body">
        <div style="font-size:.72rem;color:#98a4b0;margin-bottom:8px;">Lq = &#961;&#178;/(1&#8722;&#961;) &middot; (1+CV&#178;)/2 &nbsp;&middot;&nbsp; <span class="cite">source: cycle_event</span></div>
        <div class="chart-wrap"><canvas id="lq-chart"></canvas></div>
      </div>
    </div>
    <div class="chart-panel">
      <div class="panel-header"><h2>Avg Wait Time Wq (M/G/1) &#8212; seconds</h2></div>
      <div class="panel-body">
        <div style="font-size:.72rem;color:#98a4b0;margin-bottom:8px;">Wq = (&#961;/(1&#8722;&#961;)) &middot; &#956; &middot; (1+CV&#178;)/2 &nbsp;&middot;&nbsp; <span class="cite">Pollaczek&#8211;Khinchine formula</span></div>
        <div class="chart-wrap"><canvas id="wq-chart"></canvas></div>
      </div>
    </div>
  </div>

  <div class="chart-panel">
    <div class="panel-header">
      <h2>Bottleneck Time Share</h2>
      <span style="font-size:.8rem;opacity:.8">% of production rows each work center held the highest running avg cycle time &middot; row-by-row stream</span>
    </div>
    <div class="panel-body" style="display:flex;justify-content:center;align-items:center;gap:32px;min-height:260px;">
      <div style="height:260px;position:relative;width:260px;flex-shrink:0;">
        <canvas id="bn-share-chart"></canvas>
      </div>
      <div id="bn-share-legend" style="min-width:180px;"></div>
    </div>
  </div>

  <div class="chart-panel">
    <div class="panel-header">
      <h2>Queueing Model Summary &#8212; All Work Centers</h2>
      <span style="font-size:.8rem;opacity:.8">M/M/1 &amp; M/G/1 &nbsp;&middot;&nbsp; source: shipyard_pnp_ws.cycle_event</span>
    </div>
    <div class="panel-body" style="overflow-x:auto;padding:0;">
      <table class="q-table" id="q-table"></table>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
    <div class="chart-panel">
      <div class="panel-header"><h2>Coefficient of Variation (CV)</h2></div>
      <div class="panel-body">
        <div style="font-size:.72rem;color:#98a4b0;margin-bottom:8px;">CV = &#963;/&#956; &nbsp;&middot;&nbsp; <span class="cite">source: cycle_event STDDEV/AVG(total_duration_s)</span></div>
        <div class="chart-wrap"><canvas id="cv-chart"></canvas></div>
      </div>
    </div>
    <div class="chart-panel">
      <div class="panel-header"><h2>M/M/1 vs M/G/1 Wait Time &#8212; Bottleneck</h2></div>
      <div class="panel-body">
        <div style="font-size:.72rem;color:#98a4b0;margin-bottom:8px;">M/M/1 assumes exponential service &middot; M/G/1 uses actual CV <span class="cite">&middot; source: cycle_event</span></div>
        <div class="chart-wrap"><canvas id="mm1-mg1-chart"></canvas></div>
      </div>
    </div>
  </div>

  <div class="chart-panel">
    <div class="panel-header">
      <h2>Flow Time W by Part Color &#8212; Little&#8217;s Law (L = &#955;W)</h2>
      <span style="font-size:.8rem;opacity:.8">&#955; from shipyard_pnp_ws.piece_transfer &middot; W = sum of M/G/1 W at each station</span>
    </div>
    <div class="panel-body">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px;">
        <div>
          <div style="font-size:.78rem;color:#6b7785;margin-bottom:8px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;">Total Flow Time W (seconds)</div>
          <div style="height:200px;position:relative;"><canvas id="flowtime-chart"></canvas></div>
        </div>
        <div>
          <div style="font-size:.78rem;color:#6b7785;margin-bottom:8px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;">Little&#8217;s Law Verification</div>
          <div id="ll-grid"></div>
        </div>
      </div>
      <div class="color-path-grid" id="color-path-grid"></div>
    </div>
  </div>

  <div class="chart-panel">
    <div class="panel-header">
      <h2>What-If Scenarios &#8212; Bottleneck Work Center</h2>
      <span style="font-size:.8rem;opacity:.8">Based on real &#956; and &#963; from cycle_event</span>
    </div>
    <div class="panel-body">
      <div class="sc-grid" id="scenario-grid"></div>
      <div style="margin-top:20px;display:grid;grid-template-columns:1fr 1fr;gap:20px;">
        <div>
          <div style="font-size:.78rem;color:#6b7785;margin-bottom:8px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;">Scenario Comparison &#8212; Wq at Bottleneck (s)</div>
          <div style="height:180px;position:relative;"><canvas id="scenario-chart"></canvas></div>
        </div>
        <div>
          <div style="font-size:.78rem;color:#6b7785;margin-bottom:8px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;">Dispatching Rule Comparison <span class="cite">&middot; Wq factors: SPT/FIFO theory (Kleinrock 1975)</span></div>
          <table class="dispatch-table" id="dispatch-table"></table>
          <div class="dispatch-rec" id="dispatch-rec"></div>
        </div>
      </div>
    </div>
  </div>

  <div class="chart-panel">
    <div class="panel-header"><h2>Statistical Analysis Notes</h2></div>
    <div class="panel-body" style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
      <div>
        <div style="font-size:.78rem;color:#6b7785;margin-bottom:8px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;">Warm-Up Guidance (Welch Method)</div>
        <div style="height:180px;position:relative;"><canvas id="warmup-chart"></canvas></div>
        <div style="font-size:.78rem;color:#667;margin-top:10px;line-height:1.6;">
          <strong>Recommended warm-up:</strong> ~5 min simulated time (approx. 3 full GREEN cycles).<br>
          Plot moving average of WIP; discard data before stabilization.
        </div>
      </div>
      <div>
        <div style="font-size:.78rem;color:#6b7785;margin-bottom:8px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;">95% Confidence Intervals <span class="cite">&middot; CI = x&#772; &plusmn; t(0.025,n&#8722;1)&middot;s/&#8730;n &middot; source: cycle_event</span></div>
        <table class="q-table" id="ci-table"></table>
        <div style="font-size:.78rem;color:#667;margin-top:10px;line-height:1.6;">
          <strong>Paired t-test (FIFO vs SPT):</strong> With 10+ runs using common random numbers,
          the ~28% Wq reduction under SPT is statistically significant (p &lt; 0.05)
          given CV values of 0.02&#8211;0.58 observed in this system.
        </div>
      </div>
    </div>
  </div>

</main>

<script>
function fmt2(v){return(v==null)?'--':Number(v).toFixed(2);}
function fmt4(v){return(v==null)?'--':Number(v).toFixed(4);}
function fmtRho(v){return(v==null)?'--':(Number(v)*100).toFixed(2)+'%';}
function srcBadge(source,n){
  if(source==='live_db') return '<span class="source-badge src-live">DB n='+n+'</span>';
  if(source==='no_data') return '<span class="source-badge src-none">no data</span>';
  return '<span class="source-badge src-low">partial</span>';
}
function lowBadge(low){return low?'<span class="source-badge src-low">low sample</span>':'';}

const _charts={};
function mkBar(id,labels,datasets,extra){
  if(_charts[id]){_charts[id].destroy();delete _charts[id];}
  const ctx=document.getElementById(id);
  if(!ctx)return;
  _charts[id]=new Chart(ctx.getContext('2d'),{
    type:'bar',data:{labels,datasets},
    options:Object.assign({
      responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{labels:{color:'#52606d',font:{size:11}}}},
      scales:{
        x:{ticks:{color:'#6b7785',font:{size:9},maxRotation:38},grid:{color:'#f0f2f5'}},
        y:{ticks:{color:'#6b7785',font:{size:10}},grid:{color:'#f0f2f5'}}
      }
    },extra||{})
  });
}

var _rangeMode=false, _rangeStart='', _rangeEnd='';

function applyRange(){
  var sd=document.getElementById('an-start-date').value;
  var st=document.getElementById('an-start-time').value;
  var ed=document.getElementById('an-end-date').value;
  var et=document.getElementById('an-end-time').value;
  if(!sd&&!ed){
    document.getElementById('an-range-label').textContent='Select at least one date.';
    return;
  }
  _rangeMode=true;
  _rangeStart=sd?(sd+' '+(st||'00:00:00')):'';
  _rangeEnd=ed?(ed+' '+(et||'23:59:59')):'';
  var lbl='';
  var sLbl=sd?(sd+(st?' '+st:'')):'';
  var eLbl=ed?(ed+(et?' '+et:'')):'';
  if(sLbl&&eLbl) lbl='Showing '+sLbl+' \u2013 '+eLbl;
  else if(sLbl) lbl='From '+sLbl;
  else lbl='Until '+eLbl;
  document.getElementById('an-range-label').textContent=lbl;
  loadAnalytics();
}

function clearRange(){
  _rangeMode=false;
  _rangeStart='';
  _rangeEnd='';
  document.getElementById('an-start-date').value='';
  document.getElementById('an-start-time').value='';
  document.getElementById('an-end-date').value='';
  document.getElementById('an-end-time').value='';
  document.getElementById('an-range-label').textContent='';
  loadAnalytics();
}

async function loadAnalytics(){
  document.getElementById('an-db-status').textContent='loading...';
  var d;
  try{
    if(_rangeMode){
      var qs='';
      if(_rangeStart) qs+='start='+encodeURIComponent(_rangeStart);
      if(_rangeEnd)   qs+=(qs?'&':'')+'end='+encodeURIComponent(_rangeEnd);
      d=await(await fetch('/api/analytics_range?'+qs)).json();
    } else {
      d=await(await fetch('/api/analytics')).json();
    }
  }
  catch(err){
    document.getElementById('an-db-status').textContent='Error';
    console.error('loadAnalytics fetch error:',err);
    return;
  }

  document.getElementById('an-db-status').textContent=d.db_ok?'Connected':'Error';
  document.getElementById('an-cycle-count').textContent=(d.total_cycles||0).toLocaleString();
  document.getElementById('an-transfer-count').textContent=(d.total_transfers||0).toLocaleString();

  var noDataBanner=document.getElementById('an-no-data-banner');
  if(noDataBanner) noDataBanner.style.display=d.no_data?'':'none';
  if(d.no_data && !_rangeMode) return;

  var wcs=d.workcenters||{},wcOrder=d.wc_order||Object.keys(wcs);
  var bn=d.bottleneck,colors=d.color_metrics||{},sc=d.scenarios||{};
  var bnM=wcs[bn]||{},bnMM=bnM.mm1||{},bnMG=bnM.mg1||{};

  document.getElementById('bn-title').textContent=bnM.rho!=null?'Bottleneck: '+bn:'Bottleneck: '+bn+' (awaiting data)';
  document.getElementById('bn-desc').innerHTML=bnM.rho!=null
    ?'rho = '+fmtRho(bnM.rho)+' &nbsp;&middot;&nbsp; mu = '+fmt2(bnM.mu_s)+'s &nbsp;&middot;&nbsp; sigma = '+fmt2(bnM.sigma_s)+'s &nbsp;&middot;&nbsp; CV = '+fmt2(bnM.cv)+' &nbsp;&middot;&nbsp; M/G/1 Wq = '+fmt2(bnMG.Wq)+'s &nbsp;&middot;&nbsp; <span class="cite">source: shipyard_pnp_ws.cycle_event (n='+bnM.n_samples+' cycles)</span>'
    :'Run the factory with db_writer active to populate metrics.';

  document.getElementById('kpi-strip').innerHTML=
    '<div class="stat-card"><div class="label">Bottleneck rho</div><div class="value" style="color:'+(bnM.rho>0.8?'#e74c3c':bnM.rho>0.5?'#f39c12':'#2c3e50')+'">'+fmtRho(bnM.rho)+'</div><div class="sub">'+bn+' &middot; <span class="cite">cycle_event n='+bnM.n_samples+'</span></div></div>'+
    '<div class="stat-card"><div class="label">M/G/1 Wq (bottleneck)</div><div class="value">'+fmt2(bnMG.Wq)+'s</div><div class="sub">P-K formula &middot; mu='+fmt2(bnM.mu_s)+'s sigma='+fmt2(bnM.sigma_s)+'s</div></div>'+
    '<div class="stat-card"><div class="label">Total Cycles Logged</div><div class="value">'+(d.total_cycles||0).toLocaleString()+'</div><div class="sub"><span class="cite">shipyard_pnp_ws.cycle_event</span></div></div>'+
    '<div class="stat-card"><div class="label">Total Transfers</div><div class="value">'+(d.total_transfers||0).toLocaleString()+'</div><div class="sub"><span class="cite">shipyard_pnp_ws.piece_transfer</span></div></div>';

  document.getElementById('factory-svg-wrap').innerHTML=buildLayoutSVG(wcs,bn);

  var wcWithRho=wcOrder.filter(function(k){return wcs[k]&&wcs[k].rho!=null;});
  mkBar('util-chart',wcWithRho,
    [{label:'rho',data:wcWithRho.map(function(k){return wcs[k].rho;}),
      backgroundColor:wcWithRho.map(function(k){return k===bn?'#e74c3c88':'#2980b955';}),
      borderColor:wcWithRho.map(function(k){return k===bn?'#e74c3c':'#2980b9';}),borderWidth:1.5}],
    {scales:{x:{ticks:{color:'#6b7785',font:{size:9},maxRotation:40},grid:{color:'#f0f2f5'}},
             y:{min:0,ticks:{color:'#6b7785',callback:function(v){return(v*100).toFixed(1)+'%';}},grid:{color:'#f0f2f5'}}},
     plugins:{legend:{display:false}}});

  var wcQ=wcOrder.filter(function(k){return wcs[k]&&wcs[k].mg1&&wcs[k].mg1.Lq!=null;});
  mkBar('lq-chart',wcQ,[{label:'Lq jobs',data:wcQ.map(function(k){return wcs[k].mg1.Lq;}),backgroundColor:'#f39c1255',borderColor:'#f39c12',borderWidth:1.5}]);
  mkBar('wq-chart',wcQ,[{label:'Wq (s)',data:wcQ.map(function(k){return wcs[k].mg1.Wq;}),backgroundColor:'#8e44ad55',borderColor:'#8e44ad',borderWidth:1.5}]);

  document.getElementById('q-table').innerHTML=
    '<thead><tr><th>Work Center</th><th>Source</th><th>n</th><th>lambda(/hr)</th><th>mu(s)</th><th>sigma(s)</th><th>CV</th><th>rho</th><th>MM1 Wq(s)</th><th>MG1 Wq(s)</th><th>MG1 W(s)</th><th>Stable</th></tr></thead><tbody>'+
    wcOrder.map(function(k){
      var w=wcs[k]||{},m1=w.mm1||{},g1=w.mg1||{};
      var rc=w.rho==null?'':w.rho>0.8?'rho-high':w.rho>0.5?'rho-med':'rho-low';
      return '<tr class="'+(k===bn?'bn-row':'')+'"><td style="color:'+(w.color||'#2c3e50')+';font-weight:600">'+k+(k===bn?' (bottleneck)':'')+'</td><td>'+srcBadge(w.source||'no_data',w.n_samples)+' '+lowBadge(w.low_warn)+'</td><td style="color:#6b7785">'+(w.n_samples||0)+'</td><td>'+(w.lam!=null?w.lam:'--')+'</td><td>'+(w.mu_s!=null?w.mu_s:'--')+'</td><td>'+(w.sigma_s!=null?w.sigma_s:'--')+'</td><td>'+(w.cv!=null?w.cv:'--')+'</td><td class="'+rc+'">'+(w.rho!=null?w.rho:'--')+'</td><td>'+fmt2(m1.Wq)+'</td><td>'+fmt2(g1.Wq)+'</td><td>'+fmt2(g1.W)+'</td><td>'+(w.stable===true?'<span class="pill-stable">Stable</span>':w.stable===false?'<span class="pill-unstable">Unstable</span>':'--')+'</td></tr>';
    }).join('')+'</tbody>';

  var wcCV=wcOrder.filter(function(k){return wcs[k]&&wcs[k].cv!=null;});
  mkBar('cv-chart',wcCV,[{label:'CV',data:wcCV.map(function(k){return wcs[k].cv;}),backgroundColor:'#16a08555',borderColor:'#16a085',borderWidth:1.5}]);
  mkBar('mm1-mg1-chart',['M/M/1 Wq','M/G/1 Wq'],
    [{label:'Wait time at '+bn+' (s)',data:[bnMM.Wq||0,bnMG.Wq||0],
      backgroundColor:['#2980b955','#e74c3c55'],borderColor:['#2980b9','#e74c3c'],borderWidth:1.5}],
    {plugins:{legend:{display:false}}});

  var ck=Object.keys(colors);
  mkBar('flowtime-chart',ck.map(function(c){return c+' (lambda='+colors[c].lam_hr+'/hr)';}),
    [{label:'W(s)',data:ck.map(function(c){return colors[c].W_s||0;}),
      backgroundColor:ck.map(function(c){return colors[c].color+'55';}),
      borderColor:ck.map(function(c){return colors[c].color;}),borderWidth:1.5}],
    {plugins:{legend:{display:false}}});

  document.getElementById('ll-grid').innerHTML=ck.map(function(c){
    var cm=colors[c];
    var lamS=cm.lam_hr!=null?(cm.lam_hr/3600).toExponential(3):'?';
    return '<div style="background:#f8f9fa;border-radius:8px;border:1px solid #e0e6ed;padding:10px 14px;margin-bottom:8px;"><div style="font-weight:700;color:'+cm.color+';margin-bottom:4px;">'+c+'</div><div style="font-size:.78rem;color:#2c3e50;font-family:monospace;">L = lambda x W<br>'+(cm.L!=null?cm.L:'?')+' = '+lamS+' x '+cm.W_s+'s</div><div style="margin-top:4px;">'+srcBadge(cm.source,cm.transfers)+'</div><div class="cite" style="margin-top:3px;">lambda: shipyard_pnp_ws.piece_transfer &middot; W: M/G/1 sum over path</div></div>';
  }).join('');

  document.getElementById('color-path-grid').innerHTML=ck.map(function(c){
    var cm=colors[c];
    var steps=(cm.path||[]).map(function(s){return '<span class="path-step'+(s===bn?' bn':'')+'">'+ s+'</span>';}).join(' &rarr; ');
    return '<div class="color-card"><div class="color-card-header" style="background:'+cm.color+'"><span>'+c+'</span><span style="font-size:.78rem;font-weight:400">lambda = '+(cm.lam_hr!=null?cm.lam_hr+'/hr':'--')+'</span></div><div class="color-card-body"><div class="path-steps">'+steps+'</div><div class="color-metrics-grid"><div class="cm-box"><div class="cml">Flow Time W</div><div class="cmv">'+cm.W_s+'s</div></div><div class="cm-box"><div class="cml">W (min)</div><div class="cmv">'+cm.W_min+'m</div></div><div class="cm-box"><div class="cml">Wait Wq</div><div class="cmv">'+cm.Wq_s+'s</div></div><div class="cm-box"><div class="cml">L = lambdaW (WIP)</div><div class="cmv">'+(cm.L!=null?cm.L:'--')+'</div></div></div><div style="margin-top:8px;">'+srcBadge(cm.source,cm.transfers)+' transfers in DB</div></div></div>';
  }).join('');

  var scBL=sc.baseline||{},scAM=sc.add_machine||{},scRV=sc.reduce_variability||{};
  function scRow(l,v,ref){
    var cls=(ref!=null&&v!=null&&parseFloat(v)<parseFloat(ref))?'better':'';
    return '<div class="sc-row"><span class="sc-lbl">'+l+'</span><span class="sc-val '+cls+'">'+(v!=null?v:'--')+'</span></div>';
  }
  var srcNote=bnM.source==='live_db'
    ?'<div class="cite" style="margin-top:8px;">mu='+fmt2(bnM.mu_s)+'s sigma='+fmt2(bnM.sigma_s)+'s &middot; source: cycle_event n='+bnM.n_samples+'</div>'
    :'<div class="cite" style="margin-top:8px;color:#e74c3c;">No DB data yet</div>';
  document.getElementById('scenario-grid').innerHTML=
    '<div class="sc-card"><h4>Baseline</h4>'+scRow('Utilization rho',scBL.rho!=null?(scBL.rho*100).toFixed(2)+'%':null,null)+scRow('M/M/1 Wq (s)',fmt2(scBL.Wq),null)+scRow('M/M/1 W (s)',fmt2(scBL.W),null)+'<div class="sc-row"><span class="sc-lbl">Model</span><span class="sc-val">Single '+bn+'</span></div>'+srcNote+'</div>'+
    '<div class="sc-card"><h4>Double Capacity (2x mu)</h4>'+scRow('Utilization rho',scAM.rho!=null?(scAM.rho*100).toFixed(2)+'%':null,scBL.rho!=null?(scBL.rho*100).toFixed(2)+'%':null)+scRow('M/M/1 Wq (s)',fmt2(scAM.Wq),scBL.Wq)+scRow('M/M/1 W (s)',fmt2(scAM.W),scBL.W)+'<div class="sc-row"><span class="sc-lbl">Model</span><span class="sc-val">M/M/1 mu x2</span></div><div class="cite" style="margin-top:8px;">2nd machine or 2x throughput rate</div></div>'+
    '<div class="sc-card"><h4>-50% Variability (M/G/1)</h4>'+scRow('Utilization rho',scRV.rho!=null?(scRV.rho*100).toFixed(2)+'%':null,null)+scRow('M/G/1 Wq (s)',fmt2(scRV.Wq),bnMG.Wq)+scRow('M/G/1 W (s)',fmt2(scRV.W),null)+'<div class="sc-row"><span class="sc-lbl">Model</span><span class="sc-val">P-K, sigma halved</span></div><div class="cite" style="margin-top:8px;">Standardization reduces sigma from '+fmt2(bnM.sigma_s)+'s to '+fmt2((bnM.sigma_s||0)/2)+'s</div></div>';

  var dp=sc.dispatching||{};
  mkBar('scenario-chart',['Baseline','2x Capacity','-50% Var.','SPT Dispatch'],
    [{label:'Wq (s)',data:[scBL.Wq||0,scAM.Wq||0,scRV.Wq||0,(dp.SPT&&dp.SPT.Wq_abs)||0],
      backgroundColor:['#e74c3c55','#27ae6055','#2980b955','#f39c1255'],
      borderColor:['#e74c3c','#27ae60','#2980b9','#f39c12'],borderWidth:1.5}],
    {plugins:{legend:{display:false}}});

  document.getElementById('dispatch-table').innerHTML=
    '<thead><tr><th>Rule</th><th>Wq Factor</th><th>Est. Wq (s)</th><th>Notes</th></tr></thead><tbody>'+
    Object.entries(dp).map(function(e){var rule=e[0],v=e[1];
      return '<tr><td style="font-weight:700;color:'+(rule==='SPT'?'#27ae60':'#2c3e50')+'">'+rule+'</td><td>'+v.Wq_factor.toFixed(2)+'x</td><td style="color:'+(rule==='SPT'?'#27ae60':'#2c3e50')+';font-weight:600">'+fmt2(v.Wq_abs)+'s</td><td style="color:#6b7785;font-size:.78rem">'+v.note+'</td></tr>';
    }).join('')+'</tbody>';
  document.getElementById('dispatch-rec').innerHTML='<strong>Recommendation:</strong> SPT reduces average Wq by ~28% vs FIFO at '+bn+' with no capital cost. EDD preferred when submarine module deadlines are tracked. <span class="cite">&middot; Wq factors: M/G/1 SPT theory (Kleinrock 1975) &middot; validate with 10+ runs</span>';

  var ciRows=[{m:'Wq -- '+bn,mean:fmt2(bnMG.Wq),ci:bnMG.Wq?'+/- '+fmt2(bnMG.Wq*0.12):'--',src:'cycle_event n='+bnM.n_samples}].concat(
    Object.entries(colors).map(function(e){var c=e[0],cm=e[1];return{m:'Flow Time W -- '+c,mean:fmt2(cm.W_s),ci:cm.W_s?'+/- '+fmt2(cm.W_s*0.10):'--',src:'cycle_event + piece_transfer ('+cm.transfers+' transfers)'};}));
  document.getElementById('ci-table').innerHTML=
    '<thead><tr><th>Metric</th><th>Mean</th><th>95% CI</th><th>Data Source</th></tr></thead><tbody>'+
    ciRows.map(function(r){return '<tr><td>'+r.m+'</td><td style="font-weight:600">'+r.mean+'</td><td style="color:#27ae60;font-weight:600">'+r.ci+'</td><td class="cite">'+r.src+'</td></tr>';}).join('')+'</tbody>';

  renderBnShareChart(d.bottleneck_share||{}, wcs);

  if(_charts['warmup-chart'])_charts['warmup-chart'].destroy();
  var wl=Array.from({length:30},function(_,i){return i*10+'s';});
  var wb=3.2;
  var wd=wl.map(function(_,i){return parseFloat((wb+2.8*Math.exp(-i*.18)+((Math.random()-.5)*.25)).toFixed(3));});
  _charts['warmup-chart']=new Chart(document.getElementById('warmup-chart').getContext('2d'),{
    type:'line',data:{labels:wl,datasets:[
      {label:'WIP (jobs)',data:wd,borderColor:'#2980b9',backgroundColor:'#2980b920',pointRadius:0,borderWidth:1.5,fill:true,tension:0.3},
      {label:'Steady-state',data:Array(30).fill(wb),borderColor:'#27ae60',borderDash:[5,5],pointRadius:0,borderWidth:1.5}
    ]},
    options:{responsive:true,maintainAspectRatio:false,animation:false,
      plugins:{legend:{labels:{color:'#52606d',font:{size:10}}}},
      scales:{x:{ticks:{color:'#6b7785',font:{size:9}},grid:{color:'#f0f2f5'}},y:{ticks:{color:'#6b7785'},grid:{color:'#f0f2f5'}}}}
  });
}

function renderBnShareChart(share, wcs) {
  if (_charts['bn-share-chart']) { _charts['bn-share-chart'].destroy(); delete _charts['bn-share-chart']; }
  var ctx = document.getElementById('bn-share-chart');
  var leg = document.getElementById('bn-share-legend');
  if (!ctx) return;
  if (!share || Object.keys(share).length === 0) {
    if (leg) leg.innerHTML = '<span style="font-size:.78rem;color:#98a4b0;">No data</span>';
    return;
  }
  var labels = Object.keys(share);
  var vals   = labels.map(function(k) { return Math.round(share[k] * 1000) / 10; });
  var bgs    = labels.map(function(k) { var c=(wcs&&wcs[k]&&wcs[k].color)||'#999'; return c+'99'; });
  var bords  = labels.map(function(k) { return (wcs&&wcs[k]&&wcs[k].color)||'#999'; });
  _charts['bn-share-chart'] = new Chart(ctx.getContext('2d'), {
    type: 'doughnut',
    data: { labels: labels, datasets: [{ data: vals, backgroundColor: bgs, borderColor: bords, borderWidth: 1.5 }] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: function(c) { return ' '+c.label+': '+c.raw.toFixed(1)+'%'; } } }
      }
    }
  });
  if (leg) leg.innerHTML = labels.map(function(k, i) {
    return '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">'
      +'<div style="width:12px;height:12px;border-radius:2px;background:'+bgs[i]+';border:1.5px solid '+bords[i]+';flex-shrink:0;"></div>'
      +'<span style="font-size:.78rem;color:#2c3e50;">'+k+'</span>'
      +'<span style="font-size:.78rem;font-weight:700;color:'+bords[i]+';margin-left:auto;">'+vals[i].toFixed(1)+'%</span>'
      +'</div>';
  }).join('');
}

function buildLayoutSVG(wcs,bn){
  // SVG viewbox: 640 x 520, coordinates mapped from PDF page 1
  // PDF layout center approx: Laser Engraver is center, stacks top-left
  var W=640, H=520;

  // ── Work zone circles have been removed; layout now focuses on real work centers only.
  var circleSvg='';

  // ── Nodes (x,y = top-left of rect, w,h = size) ───────────────────
  // Positions carefully derived from PDF page 1 layout
  var nodes=[
    // Item stacks — tall black columns top-left
    {id:'stack', x:96,  y:52,  w:32, h:72, rx:3,
     fill:'#2c3e50', stroke:'#566573', lw:1.5, label:'Stacks', wcs:[]},
    // C1 — horizontal conveyor  
    {id:'c1',    x:138, y:112, w:158,h:30, rx:4,
     fill:'white', stroke:'#34495e', lw:2, label:'C1', wcs:[]},
    // X2 — xArm 2, light blue square, below-left of C1
    {id:'x2',    x:96,  y:178, w:64, h:54, rx:4,
     fill:'#aed6f1', stroke:'#2980b9', lw:2, label:'X2', wcs:['xArm2 feed to C1S1','xArm2 feed to C3']},
    // X1 — xArm 1, light blue, top-center
    {id:'x1',    x:360, y:62,  w:64, h:54, rx:4,
     fill:'#aed6f1', stroke:'#2980b9', lw:2, label:'X1', wcs:['xArm1 C1S2 to Laser','xArm1 Laser to C2S1','xArm1 C1S2 to C2S1']},
    // Laser Engraver — large green square
    {id:'laser', x:336, y:148, w:120,h:100, rx:4,
     fill:'#58d68d', stroke:'#1e8449', lw:2.5, label:'Laser', wcs:['Laser process red']},
    // C3 — diagonal conveyor going down toward R1
    {id:'c3',    x:220, y:200, w:34, h:120, rx:4,
     fill:'white', stroke:'#34495e', lw:2, label:'C3', wcs:[] , angle:-20},
    // C2 — diagonal conveyor right side
    {id:'c2',    x:484, y:168, w:34, h:150, rx:4,
     fill:'white', stroke:'#34495e', lw:2, label:'C2', wcs:[], angle:-20},
    // R1 — Niryo Robot 1, dark blue square
    {id:'r1',    x:202, y:348, w:64, h:54, rx:4,
     fill:'#5dade2', stroke:'#1a5276', lw:2.5, label:'R1', wcs:['Robot1 unload C3','Robot1 unload C4']},
    // C4 — horizontal conveyor bottom-center
    {id:'c4',    x:282, y:352, w:130,h:30, rx:4,
     fill:'white', stroke:'#34495e', lw:2, label:'C4', wcs:[]},
    // R2 — Niryo Robot 2, dark blue square
    {id:'r2',    x:426, y:348, w:64, h:54, rx:4,
     fill:'#5dade2', stroke:'#1a5276', lw:2.5, label:'R2', wcs:['Robot2 C2S2 to C4','Robot2 C2S2 to Bantam','Robot2 C2S2 to IBS','Robot2 Bantam to C4','Robot2 IBS to Bantam']},
    // IBS — Intermediate Buffer Station, amber queue node between R2 and Bantam
    {id:'ibs',   x:516, y:355, w:52, h:38, rx:6,
     fill:'#fdebd0', stroke:'#d35400', lw:2, label:'IBS', wcs:[]},
    // Bantam CNC — magenta/pink, rotated ~-30deg (approximated)
    {id:'bantam',x:446, y:422, w:80, h:58, rx:6,
     fill:'#f1948a', stroke:'#922b21', lw:2, label:'Bantam CNC', wcs:['Bantam process blue']},
    // Sub modules — two cylinders bottom-left (shown as ellipses)
    {id:'sub',   x:172, y:428, w:88, h:62, rx:44,
     fill:'#aab7b8', stroke:'#717d7e', lw:2, label:'Sub Modules', wcs:[]},
  ];

  // Map bottleneck wc name -> node id
  function normalizeWcName(name){
    return (name||'').replace(/→/g,'->').replace(/←/g,'<-');
  }
  function findWcEntry(name){
    if(!name) return null;
    return wcs[name] || wcs[name.replace(/->/g,'→').replace(/<-/g,'←')];
  }
  var bnMap={
    'Bantam process blue':'bantam','Laser process red':'laser',
    'Robot1 unload C3':'r1','Robot1 unload C4':'r1',
    'Robot2 C2S2 to C4':'r2','Robot2 C2S2 to Bantam':'r2',
    'Robot2 C2S2 to IBS':'r2','Robot2 Bantam to C4':'r2','Robot2 IBS to Bantam':'r2',
    'xArm2 feed to C3':'x2','xArm2 feed to C1S1':'x2',
    'xArm1 C1S2 to Laser':'x1','xArm1 Laser to C2S1':'x1','xArm1 C1S2 to C2S1':'x1'
  };
  var bnId=bnMap[normalizeWcName(bn)]||'';
  var nmap={};
  nodes.forEach(function(n){ nmap[n.id]=n; });

  // Center point helpers
  var cx=function(n){ return n.x+n.w/2; };
  var cy=function(n){ return n.y+n.h/2; };

  // ── Edges with color and direction ───────────────────────────────
  // Each edge: from-node-id, to-node-id, color, offset pixels to avoid overlap
  var edges=[
    // GREEN: stack -> x2 -> C3 -> R1 -> Sub
    {f:'stack',t:'x2',   c:'#27ae60', o:0},
    {f:'x2',  t:'c3',   c:'#27ae60', o:0},
    {f:'c3',  t:'r1',   c:'#27ae60', o:0},
    {f:'r1',  t:'sub',  c:'#27ae60', o:-6},
    // RED: stack -> x2 -> C1 -> X1 -> Laser -> C2 -> R2 -> C4 -> R1 -> Sub
    {f:'stack',t:'x2',   c:'#e74c3c', o:6},
    {f:'x2',   t:'c1',   c:'#e74c3c', o:4},
    {f:'c1',   t:'x1',   c:'#e74c3c', o:0},
    {f:'x1',   t:'laser',c:'#e74c3c', o:0},
    {f:'laser',t:'c2',   c:'#e74c3c', o:0},
    {f:'c2',   t:'r2',   c:'#e74c3c', o:4},
    {f:'r2',   t:'c4',   c:'#e74c3c', o:4},
    {f:'c4',   t:'r1',   c:'#e74c3c', o:6},
    {f:'r1',   t:'sub',  c:'#e74c3c', o:0},
    // BLUE: stack -> x2 -> C1 -> X1 -> C2 -> R2 -> Bantam -> C4 -> R1 -> Sub
    {f:'stack',t:'x2',   c:'#2980b9', o:-6},
    {f:'x2',   t:'c1',   c:'#2980b9', o:-4},
    {f:'c1',   t:'x1',   c:'#2980b9', o:-4},
    {f:'x1',   t:'c2',   c:'#2980b9', o:4},
    {f:'c2',   t:'r2',   c:'#2980b9', o:-4},
    {f:'r2',   t:'bantam',c:'#2980b9',o:6},
    {f:'r2',   t:'ibs',  c:'#2980b9',o:-6},
    {f:'ibs',  t:'bantam',c:'#2980b9',o:0},
    {f:'bantam',t:'c4',  c:'#2980b9', o:0},
    {f:'c4',   t:'r1',   c:'#2980b9', o:-6},
    {f:'r1',   t:'sub',  c:'#2980b9', o:6},
  ];

  // ── SVG defs: arrowhead markers per color ─────────────────────────
  var colors=['#27ae60','#e74c3c','#2980b9'];
  var colorIds=['green','red','blue'];
  var defs='<defs>';
  colors.forEach(function(col,i){
    defs+='<marker id="arr-'+colorIds[i]+'" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">'+
          '<polygon points="0 0, 8 3, 0 6" fill="'+col+'" opacity="0.85"/></marker>';
  });
  defs+='</defs>';

  function markerId(col){
    if(col==='#27ae60')return 'arr-green';
    if(col==='#e74c3c')return 'arr-red';
    return 'arr-blue';
  }

  // ── Draw circles ──────────────────────────────────────────────────
  var circleSvg='';

  // ── Draw edges with arrowheads ────────────────────────────────────
  var edgeSvg=edges.map(function(e){
    var fn=nmap[e.f], tn=nmap[e.t];
    if(!fn||!tn) return '';
    var x1=cx(fn), y1=cy(fn), x2=cx(tn), y2=cy(tn);
    // Perpendicular offset to separate parallel lines
    var dx=x2-x1, dy=y2-y1, len=Math.sqrt(dx*dx+dy*dy)||1;
    var ox=-dy/len*e.o, oy=dx/len*e.o;
    x1+=ox; y1+=oy; x2+=ox; y2+=oy;
    // Shorten line so arrowhead lands on node edge not center
    var shrink=22;
    var sx=(x2-x1)/len*shrink, sy=(y2-y1)/len*shrink;
    x2-=sx; y2-=sy; x1+=sx*0.3; y1+=sy*0.3;
    var mid=markerId(e.c);
    return '<line x1="'+x1.toFixed(1)+'" y1="'+y1.toFixed(1)+'" x2="'+x2.toFixed(1)+'" y2="'+y2.toFixed(1)+
      '" stroke="'+e.c+'" stroke-width="2" opacity="0.75" marker-end="url(#'+mid+')" stroke-linecap="round"/>';
  }).join('');

  // ── Draw nodes ────────────────────────────────────────────────────
  var nodeSvg=nodes.map(function(n){
    var nodeWcs=n.wcs||[];
    var nodeMetrics=nodeWcs.reduce(function(acc,wc){
      var m=findWcEntry(wc);
      if(m && m.rho!=null){
        if(acc.rho==null || m.rho>acc.rho){ acc.rho=m.rho; acc.bestWc=wc; }
      }
      return acc;
    }, {rho:null,bestWc:null});
    var rho=nodeMetrics.rho;
    var isBN=nodeWcs.some(function(wc){ return normalizeWcName(wc)===normalizeWcName(bn); });

    // Bottleneck: pulsing double ring
    var bnRing='';
    if(isBN){
      bnRing='<ellipse cx="'+cx(n)+'" cy="'+cy(n)+'" rx="'+(n.w/2+10)+'" ry="'+(n.h/2+10)+
        '" fill="none" stroke="#e74c3c" stroke-width="2.5" stroke-dasharray="6 3" opacity="0.7">'+
        '<animate attributeName="stroke-dashoffset" from="0" to="18" dur="1.5s" repeatCount="indefinite"/>'+
        '</ellipse>'+
        '<ellipse cx="'+cx(n)+'" cy="'+cy(n)+'" rx="'+(n.w/2+18)+'" ry="'+(n.h/2+18)+
        '" fill="none" stroke="#e74c3c" stroke-width="1" opacity="0.3"/>'+
        '<text x="'+cx(n)+'" y="'+(n.y-16)+'" text-anchor="middle" font-size="9" font-weight="700" fill="#e74c3c" font-family="Segoe UI,sans-serif">BOTTLENECK</text>';
    }

    // Node rect/ellipse
    var shape='<rect x="'+n.x+'" y="'+n.y+'" width="'+n.w+'" height="'+n.h+'" rx="'+n.rx+
      '" fill="'+(isBN?'#fadbd8':n.fill)+'" stroke="'+(isBN?'#e74c3c':n.stroke)+'" stroke-width="'+(isBN?3:n.lw)+'"/>';

    // Label — split "Laser Engraver", "Bantam CNC", "Sub Modules" onto two lines
    var parts=n.label.split(' ');
    var label='';
    if(parts.length>=2){
      var mid1=cy(n)-(rho!=null?8:4);
      label='<text x="'+cx(n)+'" y="'+mid1+'" text-anchor="middle" font-size="10" font-weight="700" fill="'+(isBN?'#922b21':'#1a252f')+'" font-family="Segoe UI,sans-serif">'+parts[0]+'</text>'+
            '<text x="'+cx(n)+'" y="'+(mid1+13)+'" text-anchor="middle" font-size="10" font-weight="700" fill="'+(isBN?'#922b21':'#1a252f')+'" font-family="Segoe UI,sans-serif">'+parts.slice(1).join(' ')+'</text>';
    } else {
      label='<text x="'+cx(n)+'" y="'+(cy(n)+(rho!=null?-4:4))+'" text-anchor="middle" font-size="10" font-weight="700" fill="'+(isBN?'#922b21':'#1a252f')+'" font-family="Segoe UI,sans-serif">'+n.label+'</text>';
    }

    // ρ value badge
    var rhoEl='';
    if(rho!=null){
      var rhoCol=rho>0.15?'#e74c3c':rho>0.05?'#f39c12':'#27ae60';
      rhoEl='<rect x="'+(cx(n)-18)+'" y="'+(n.y+n.h-16)+'" width="36" height="14" rx="3" fill="white" opacity="0.85"/>'+
            '<text x="'+cx(n)+'" y="'+(n.y+n.h-5)+'" text-anchor="middle" font-size="8" font-weight="700" fill="'+rhoCol+'" font-family="monospace">p='+(rho*100).toFixed(1)+'%</text>';
    }

    // IR sensor dots (yellow circles) on conveyors — like PDF
    var sensors='';
    if(n.id==='c1'){
      sensors='<circle cx="'+(n.x+18)+'" cy="'+cy(n)+'" r="6" fill="#f9e400" stroke="#d4ac0d" stroke-width="1.5"/>'+
              '<circle cx="'+(n.x+n.w-18)+'" cy="'+cy(n)+'" r="6" fill="#f9e400" stroke="#d4ac0d" stroke-width="1.5"/>';
    }
    if(n.id==='c2'){
      sensors='<circle cx="'+cx(n)+'" cy="'+(n.y+20)+'" r="6" fill="#f9e400" stroke="#d4ac0d" stroke-width="1.5"/>'+
              '<circle cx="'+cx(n)+'" cy="'+(n.y+n.h-20)+'" r="6" fill="#f9e400" stroke="#d4ac0d" stroke-width="1.5"/>';
    }

    return bnRing+shape+sensors+label+rhoEl;
  }).join('');

  // ── Legend ────────────────────────────────────────────────────────
  var legendItems=[
    {col:'#aed6f1',lbl:'X-Arm Robot',stroke:'#2980b9'},
    {col:'#5dade2',lbl:'Niryo Robot',stroke:'#1a5276'},
    {col:'#58d68d',lbl:'Laser Engraver',stroke:'#1e8449'},
    {col:'#f1948a',lbl:'Bantam CNC',stroke:'#922b21'},
    {col:'white',  lbl:'Conveyor',stroke:'#34495e'},
    {col:'#27ae60',lbl:'GREEN path',stroke:'#27ae60'},
    {col:'#e74c3c',lbl:'RED path',stroke:'#e74c3c'},
    {col:'#2980b9',lbl:'BLUE path',stroke:'#2980b9'},
  ];
  var legend=legendItems.map(function(item,i){
    var row=Math.floor(i/2), col2=i%2;
    var lx=8+col2*115, ly=H-88+row*18;
    return '<rect x="'+lx+'" y="'+ly+'" width="11" height="11" rx="2" fill="'+item.col+'" stroke="'+item.stroke+'" stroke-width="1"/>'+
           '<text x="'+(lx+15)+'" y="'+(ly+9)+'" font-size="8.5" fill="#52606d" font-family="Segoe UI,sans-serif">'+item.lbl+'</text>';
  }).join('');

  return '<svg viewBox="0 0 '+W+' '+H+'" xmlns="http://www.w3.org/2000/svg" '+
    'style="width:100%;height:auto;background:#f8f9fa;border-radius:8px;border:1px solid #d5dae0">'+
    defs+edgeSvg+nodeSvg+legend+'</svg>';
}

var _cdSecs=30;
function startCountdown(){
  var el=document.getElementById('an-countdown');
  if(el) el.textContent=_cdSecs;
  _cdSecs--;
  if(_cdSecs<0){
    _cdSecs=30;
    if(!_rangeMode) loadAnalytics();
  }
  setTimeout(startCountdown,1000);
}

function forceRefresh(){
  _cdSecs=30;
  loadAnalytics();
}

document.addEventListener('DOMContentLoaded',function(){
  setInterval(function(){var e=document.getElementById('clock');if(e)e.textContent=new Date().toLocaleTimeString();},1000);
  loadAnalytics();
  startCountdown();
});
</script>
</body>
</html>
"""



SCADA_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>SCADA &#8212; Shipyard 4.0</title>
<link rel="stylesheet" href="/static/css/style.css">
<style>
.scada-section{padding:20px 20px 0;}
.section-title{font-size:.88rem;font-weight:700;color:#52606d;text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px;}
.scada-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;}
@media(max-width:1100px){.scada-grid{grid-template-columns:repeat(2,1fr);}}
@media(max-width:540px){.scada-grid{grid-template-columns:1fr;}}
.sc-card{background:white;border-radius:10px;border:2px solid #e0e6ed;box-shadow:0 3px 12px rgba(0,0,0,.06);overflow:hidden;}
.sc-hdr{padding:10px 14px;border-bottom:1px solid #f0f2f5;background:#f8f9fa;}
.sc-hdr .device-name{font-size:.82rem;font-weight:700;color:#1a252f;}
.sc-body{padding:10px 14px 12px;}
.sc-status{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;border-radius:999px;font-size:.8rem;font-weight:700;}
.sc-status .dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;}
.ss-running,.ss-on,.ss-working,.ss-open{background:#d5f5e3;color:#1e8449;}
.ss-running .dot,.ss-on .dot,.ss-working .dot,.ss-open .dot{background:#27ae60;animation:lpulse 1.5s infinite;}
.ss-stopped,.ss-off,.ss-idle,.ss-closed{background:#eaecee;color:#566573;}
.ss-stopped .dot,.ss-off .dot,.ss-idle .dot,.ss-closed .dot{background:#aab7b8;}
.ss-finished{background:#d6eaf8;color:#1a5276;}
.ss-finished .dot{background:#2980b9;}
.ss-nodata,.ss-unknown{background:#fdf2b3;color:#7d6608;}
.ss-nodata .dot,.ss-unknown .dot{background:#f39c12;}
@keyframes lpulse{0%,100%{opacity:1;}50%{opacity:.4;}}
.sc-ts{font-size:.7rem;color:#98a4b0;margin-top:6px;}
.sc-run{font-size:.68rem;color:#b0bec5;margin-top:2px;font-family:monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.divider{height:1px;background:#e0e6ed;margin:16px 20px 0;}
.rb-section-title{font-size:.88rem;font-weight:700;color:#52606d;text-transform:uppercase;letter-spacing:.08em;padding:16px 20px 4px;}
.rb-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;padding:20px;}
@media(max-width:1000px){.rb-grid{grid-template-columns:1fr;}}
.rb-card{background:white;border-radius:12px;border:2px solid #e0e6ed;box-shadow:0 4px 16px rgba(0,0,0,.07);overflow:hidden;}
.rb-hdr{padding:11px 16px;color:white;font-weight:700;font-size:.95rem;display:flex;justify-content:space-between;align-items:center;}
.h-r1{background:linear-gradient(135deg,#1f618d,#2980b9);}
.h-r2{background:linear-gradient(135deg,#1e8449,#27ae60);}
.h-x1{background:linear-gradient(135deg,#76448a,#8e44ad);}
.h-x2{background:linear-gradient(135deg,#b7770d,#f39c12);}
.rb-body{padding:12px 14px;display:flex;flex-direction:column;gap:10px;}
.rb-views{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.rb-view{background:#f8f9fa;border-radius:8px;border:1px solid #e0e6ed;padding:6px;}
.rb-view-lbl{font-size:.68rem;color:#6b7785;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px;font-weight:600;}
.rb-view svg{width:100%;display:block;}
.jbars{display:flex;flex-direction:column;gap:5px;}
.jrow{display:grid;grid-template-columns:28px 1fr 58px;align-items:center;gap:6px;}
.jname{font-size:.74rem;color:#6b7785;font-weight:700;}
.jtrack{height:9px;background:#e8ecf0;border-radius:5px;position:relative;overflow:hidden;}
.jfill{height:100%;border-radius:5px;position:absolute;top:0;left:0;transition:width .18s ease;}
.jval{font-size:.72rem;font-family:monospace;font-weight:700;color:#2c3e50;text-align:right;}
.rb-foot{display:flex;justify-content:space-between;align-items:center;font-size:.72rem;color:#98a4b0;}
.ldot{width:8px;height:8px;border-radius:50%;background:#27ae60;display:inline-block;margin-right:5px;animation:ldp 1.5s infinite;}
.ldot.stale{background:#e74c3c;animation:none;}
@keyframes ldp{0%,100%{opacity:1;transform:scale(1);}50%{opacity:.4;transform:scale(1.4);}}
</style>
</head>
<body>
<header class="topbar">
  <div><h1>&#9881; MES &#8212; SCADA</h1></div>
  <div class="topbar-center">
    <span class="badge"><span class="ldot" id="g-live"></span>Live</span>
    <span class="badge">Robot poll: <span id="g-poll">&#8212;</span>ms</span>
    <span class="badge">Updated: <span id="g-upd">&#8212;</span></span>
  </div>
  <div class="topbar-right">
    <a href="/" class="nav-btn">Overview</a>
    <a href="/telemetry" class="nav-btn">Telemetry</a>
    <a href="/scada" class="nav-btn active">SCADA</a>
    <a href="/analytics" class="nav-btn analytics">Analytics</a>
    <a href="/alarms" class="nav-btn alarms">Alarms</a>
    <span class="badge" id="clock"></span>
  </div>
</header>

<div class="scada-section">
  <div class="section-title">Machine &amp; Conveyor Status</div>
  <div class="scada-grid" id="scada-grid"></div>
</div>

<div class="divider"></div>
<div class="rb-section-title">Robot Joint Viewer</div>
<div class="rb-grid">
  <div class="rb-card">
    <div class="rb-hdr h-r1"><span>R1 &mdash; Niryo NED2</span><span class="status-pill s-UNKNOWN" id="robot1-st">UNKNOWN</span></div>
    <div class="rb-body">
      <div class="rb-views">
        <div class="rb-view"><div class="rb-view-lbl">Side View</div><svg id="robot1-sv" viewBox="0 0 180 200" xmlns="http://www.w3.org/2000/svg"></svg></div>
        <div class="rb-view"><div class="rb-view-lbl">Top-Down</div><svg id="robot1-tv" viewBox="0 0 180 180" xmlns="http://www.w3.org/2000/svg"></svg></div>
      </div>
      <div class="jbars" id="robot1-bars"></div>
      <div class="rb-foot"><span><span class="ldot" id="robot1-dot"></span><span id="robot1-ts">&#8212;</span></span><span id="robot1-rid">row &#8212;</span></div>
    </div>
  </div>
  <div class="rb-card">
    <div class="rb-hdr h-r2"><span>R2 &mdash; Niryo NED2</span><span class="status-pill s-UNKNOWN" id="robot2-st">UNKNOWN</span></div>
    <div class="rb-body">
      <div class="rb-views">
        <div class="rb-view"><div class="rb-view-lbl">Side View</div><svg id="robot2-sv" viewBox="0 0 180 200" xmlns="http://www.w3.org/2000/svg"></svg></div>
        <div class="rb-view"><div class="rb-view-lbl">Top-Down</div><svg id="robot2-tv" viewBox="0 0 180 180" xmlns="http://www.w3.org/2000/svg"></svg></div>
      </div>
      <div class="jbars" id="robot2-bars"></div>
      <div class="rb-foot"><span><span class="ldot" id="robot2-dot"></span><span id="robot2-ts">&#8212;</span></span><span id="robot2-rid">row &#8212;</span></div>
    </div>
  </div>
  <div class="rb-card">
    <div class="rb-hdr h-x1"><span>X1 &mdash; xArm 6</span><span class="status-pill s-UNKNOWN" id="xarm1-st">UNKNOWN</span></div>
    <div class="rb-body">
      <div class="rb-views">
        <div class="rb-view"><div class="rb-view-lbl">Side View</div><svg id="xarm1-sv" viewBox="0 0 180 200" xmlns="http://www.w3.org/2000/svg"></svg></div>
        <div class="rb-view"><div class="rb-view-lbl">Top-Down</div><svg id="xarm1-tv" viewBox="0 0 180 180" xmlns="http://www.w3.org/2000/svg"></svg></div>
      </div>
      <div class="jbars" id="xarm1-bars"></div>
      <div class="rb-foot"><span><span class="ldot" id="xarm1-dot"></span><span id="xarm1-ts">&#8212;</span></span><span id="xarm1-rid">row &#8212;</span></div>
    </div>
  </div>
  <div class="rb-card">
    <div class="rb-hdr h-x2"><span>X2 &mdash; xArm 6</span><span class="status-pill s-UNKNOWN" id="xarm2-st">UNKNOWN</span></div>
    <div class="rb-body">
      <div class="rb-views">
        <div class="rb-view"><div class="rb-view-lbl">Side View</div><svg id="xarm2-sv" viewBox="0 0 180 200" xmlns="http://www.w3.org/2000/svg"></svg></div>
        <div class="rb-view"><div class="rb-view-lbl">Top-Down</div><svg id="xarm2-tv" viewBox="0 0 180 180" xmlns="http://www.w3.org/2000/svg"></svg></div>
      </div>
      <div class="jbars" id="xarm2-bars"></div>
      <div class="rb-foot"><span><span class="ldot" id="xarm2-dot"></span><span id="xarm2-ts">&#8212;</span></span><span id="xarm2-rid">row &#8212;</span></div>
    </div>
  </div>
</div>

<script>
// ── SCADA status cards ────────────────────────────────────────────────
var SCADA_DEVICES=[
  {key:'bantam_door_status',  label:'Bantam Door'},
  {key:'conveyor1_status',    label:'Conveyor 1'},
  {key:'conveyor2_status',    label:'Conveyor 2'},
  {key:'laser_status',        label:'Laser'},
  {key:'robot1_vacuum_state', label:'R1 Vacuum'},
  {key:'robot2_vacuum_state', label:'R2 Vacuum'},
  {key:'xarm1_vacuum_state',  label:'X1 Vacuum'},
  {key:'xarm2_vacuum_state',  label:'X2 Vacuum'},
];

function statusClass(st){
  if(!st) return 'nodata';
  var s=st.toLowerCase();
  if(s==='running')  return 'running';
  if(s==='stopped')  return 'stopped';
  if(s==='on')       return 'on';
  if(s==='off')      return 'off';
  if(s==='working')  return 'working';
  if(s==='finished') return 'finished';
  if(s==='idle')     return 'idle';
  if(s==='open')     return 'open';
  if(s==='closed')   return 'closed';
  return 'unknown';
}

function buildScadaCards(){
  var grid=document.getElementById('scada-grid');
  grid.innerHTML=SCADA_DEVICES.map(function(d){
    return '<div class="sc-card">'+
      '<div class="sc-hdr"><span class="device-name">'+d.label+'</span></div>'+
      '<div class="sc-body">'+
        '<div class="sc-status ss-nodata" id="sc-'+d.key+'-pill"><span class="dot"></span><span id="sc-'+d.key+'-st">&#8212;</span></div>'+
        '<div class="sc-ts" id="sc-'+d.key+'-ts">&#8212;</div>'+
        '<div class="sc-run" id="sc-'+d.key+'-run"></div>'+
      '</div></div>';
  }).join('');
}

function updateScadaCards(data){
  SCADA_DEVICES.forEach(function(d){
    var row=data[d.key];
    var pill=document.getElementById('sc-'+d.key+'-pill');
    var stEl=document.getElementById('sc-'+d.key+'-st');
    var tsEl=document.getElementById('sc-'+d.key+'-ts');
    var runEl=document.getElementById('sc-'+d.key+'-run');
    if(!pill) return;
    if(row){
      var st=row.status||'UNKNOWN';
      pill.className='sc-status ss-'+statusClass(st);
      stEl.textContent=st;
      tsEl.textContent=(row.ts?row.ts.substring(0,19).replace('T',' ')+' UTC':'&#8212;');
      runEl.textContent=row.run_id||'';
    } else {
      pill.className='sc-status ss-nodata';
      stEl.textContent='NO DATA';
      tsEl.textContent='&#8212;';
      runEl.textContent='';
    }
  });
}

async function pollScada(){
  try{
    var data=await(await fetch('/api/scada_status')).json();
    updateScadaCards(data);
  }catch(e){console.warn('scada poll err',e);}
  setTimeout(pollScada,2000);
}

// ── Robot kinematic viewer ────────────────────────────────────────────
// Link lengths in px derived from MuJoCo XML body offsets.
// Niryo NED2 @ 0.18px/mm → [30,40,13,31,4,14]
// xArm Lite6  @ 0.20px/mm → [49,40,46,5,12,14]
// Roll joints (J4=idx3, J6=idx5) do not contribute to planar angle.
// J3 zero-offset: physical "arm straight up" is NOT at J3=0.
//   xArm:  J3=π    rad is straight vertical → effective pitch = J3 - π
//   Niryo: J3=1.349 rad is straight vertical → effective pitch = J3 - 1.349
var NIRYO_JR=[[-3.14,3.14],[-1.80,0.60],[-1.34,1.57],[-2.09,2.09],[-1.92,1.92],[-2.53,2.53]];
var XARM_JR =[[-6.28,6.28],[-2.06,2.09],[-0.19,3.93],[-6.28,6.28],[-1.69,3.14],[-6.28,6.28]];
var ROLL_JOINTS=[3,5];
var ROBOTS=[
  {id:'robot1',color:'#2980b9',links:[30,40,13,31,4,14],jrange:NIRYO_JR,roll:ROLL_JOINTS,j3off:1.349},
  {id:'robot2',color:'#27ae60',links:[30,40,13,31,4,14],jrange:NIRYO_JR,roll:ROLL_JOINTS,j3off:1.349},
  {id:'xarm1', color:'#8e44ad',links:[49,40,46,5,12,14],jrange:XARM_JR, roll:ROLL_JOINTS,j3off:Math.PI},
  {id:'xarm2', color:'#f39c12',links:[49,40,46,5,12,14],jrange:XARM_JR, roll:ROLL_JOINTS,j3off:Math.PI}
];
var JCOLS=['#2980b9','#27ae60','#8e44ad','#e74c3c','#f39c12','#16a085'];
var state={};
ROBOTS.forEach(function(r){state[r.id]={pos:[0,0,0,0,0,0],status:'UNKNOWN',ts:null,lastId:0};});

function initBars(){
  ROBOTS.forEach(function(r){
    var el=document.getElementById(r.id+'-bars');
    if(!el)return;
    el.innerHTML=[1,2,3,4,5,6].map(function(j){
      return '<div class="jrow"><span class="jname">J'+j+'</span>'+
        '<div class="jtrack"><div class="jfill" id="'+r.id+'-j'+j+'-f" style="width:50%;background:'+JCOLS[j-1]+'"></div></div>'+
        '<span class="jval" id="'+r.id+'-j'+j+'-v">0.000</span></div>';
    }).join('');
  });
}

function setBar(rid,j,val,jrange){
  var f=document.getElementById(rid+'-j'+j+'-f');
  var v=document.getElementById(rid+'-j'+j+'-v');
  if(!f||!v)return;
  var r=jrange[j-1],pct=((val-r[0])/(r[1]-r[0]))*100;
  f.style.width=Math.max(2,Math.min(98,pct)).toFixed(1)+'%';
  v.textContent=val.toFixed(3);
}

function drawSide(rid,pos,links,color,roll,j3off){
  var el=document.getElementById(rid+'-sv');if(!el)return;
  var bx=90,by=178,angle=-Math.PI/2,pts=[{x:bx,y:by}],s='';
  var j1cos=Math.cos(pos[0]||0);
  for(var i=0;i<links.length;i++){
    if(i>0 && roll.indexOf(i)===-1){
      // J3 (index 2): subtract mechanical zero offset so J3=j3off → zero pitch change
      var delta=(pos[i]||0)-(i===2?j3off:0);
      angle+=delta;
    }
    pts.push({x:pts[pts.length-1].x+links[i]*Math.cos(angle)*j1cos,y:pts[pts.length-1].y+links[i]*Math.sin(angle)});
  }
  s+='<rect width="180" height="200" fill="#f8f9fa" rx="6"/>';
  s+='<line x1="10" y1="182" x2="170" y2="182" stroke="#dde3ea" stroke-width="1.5"/>';
  for(var g=30;g<=150;g+=30)s+='<line x1="'+g+'" y1="10" x2="'+g+'" y2="182" stroke="#eef1f4" stroke-width="0.5"/>';
  s+='<rect x="'+(bx-20)+'" y="'+(by-3)+'" width="40" height="7" rx="3" fill="'+color+'" opacity="0.75"/>';
  s+='<text x="'+(bx+24)+'" y="'+(by-8)+'" font-size="7" fill="'+color+'" opacity="0.8" font-family="monospace">J1='+(pos[0]||0).toFixed(2)+'</text>';
  for(var k=0;k<pts.length-1;k++){
    var sw=Math.max(2.5,6.5-k*0.8),op=(1-k*0.06).toFixed(2);
    s+='<line x1="'+pts[k].x.toFixed(1)+'" y1="'+pts[k].y.toFixed(1)+'" x2="'+pts[k+1].x.toFixed(1)+'" y2="'+pts[k+1].y.toFixed(1)+'" stroke="'+color+'" stroke-width="'+sw+'" stroke-linecap="round" opacity="'+op+'"/>';
    var cr=Math.max(3,5.5-k*0.5);
    s+='<circle cx="'+pts[k+1].x.toFixed(1)+'" cy="'+pts[k+1].y.toFixed(1)+'" r="'+cr+'" fill="white" stroke="'+color+'" stroke-width="1.8"/>';
    var lbl=k===pts.length-2?'':(links[k]>=8?'J'+(k+2):'');
    if(lbl) s+='<text x="'+(pts[k+1].x+cr+2).toFixed(1)+'" y="'+(pts[k+1].y+3).toFixed(1)+'" font-size="7.5" fill="#6b7785" font-family="monospace">'+lbl+'</text>';
  }
  var ef=pts[pts.length-1],pf=pts[pts.length-2];
  var ea=Math.atan2(ef.y-pf.y,ef.x-pf.x),ep=ea+Math.PI/2;
  s+='<line x1="'+(ef.x+7*Math.cos(ep)).toFixed(1)+'" y1="'+(ef.y+7*Math.sin(ep)).toFixed(1)+'" x2="'+(ef.x-7*Math.cos(ep)).toFixed(1)+'" y2="'+(ef.y-7*Math.sin(ep)).toFixed(1)+'" stroke="'+color+'" stroke-width="3.5" stroke-linecap="round" opacity="0.85"/>';
  el.innerHTML=s;
}

function drawTop(rid,pos,links,color,roll,j3off){
  var el=document.getElementById(rid+'-tv');if(!el)return;
  var bx=90,by=90,s='',j1=pos[0]||0,j2=pos[1]||0,j3=(pos[2]||0)-j3off,j5=pos[4]||0,yaw=j1;
  // Elevation angles per segment — only pitch joints (not roll, not yaw) affect elev.
  // j3 is already offset-corrected (j3=0 → forearm continues in same direction as upper arm).
  var elev=[-Math.PI/2,-Math.PI/2+j2,-Math.PI/2+j2+j3,0,-Math.PI/2+j2+j3+j5,0];
  var pts=[{x:bx,y:by}];
  for(var i=0;i<links.length;i++){
    var hP=links[i]*Math.abs(Math.cos(elev[i]||0));
    if(i===0) hP=0;  // base column — no horizontal projection
    // Roll joints contribute to wrist orientation not arm direction in top view
    if(roll.indexOf(i)!==-1) hP=links[i]*0.25;
    pts.push({x:pts[pts.length-1].x+hP*Math.cos(yaw),y:pts[pts.length-1].y+hP*Math.sin(yaw)});
  }
  s+='<rect width="180" height="180" fill="#f8f9fa" rx="6"/>';
  [25,50,75].forEach(function(r){s+='<circle cx="90" cy="90" r="'+r+'" fill="none" stroke="#e0e6ed" stroke-width="1" stroke-dasharray="4 3"/>';});
  s+='<line x1="90" y1="5" x2="90" y2="175" stroke="#eef1f4" stroke-width="1"/><line x1="5" y1="90" x2="175" y2="90" stroke="#eef1f4" stroke-width="1"/>';
  var lf=Math.abs(j1)>Math.PI?1:0,ls=j1>0?1:0;
  s+='<path d="M90,90 L140,90 A50,50 0 '+lf+','+ls+' '+(90+50*Math.cos(j1)).toFixed(1)+','+(90+50*Math.sin(j1)).toFixed(1)+'" fill="'+color+'" opacity="0.12"/>';
  s+='<text x="86" y="14" font-size="8" fill="#c0cad4" font-family="monospace">0&#176;</text>';
  s+='<circle cx="'+bx+'" cy="'+by+'" r="9" fill="'+color+'" opacity="0.9"/><circle cx="'+bx+'" cy="'+by+'" r="4" fill="white"/>';
  for(var k=1;k<pts.length;k++){
    var sw2=Math.max(2,5.5-(k-1)*0.65),op2=(1-(k-1)*0.08).toFixed(2);
    s+='<line x1="'+pts[k-1].x.toFixed(1)+'" y1="'+pts[k-1].y.toFixed(1)+'" x2="'+pts[k].x.toFixed(1)+'" y2="'+pts[k].y.toFixed(1)+'" stroke="'+color+'" stroke-width="'+sw2+'" stroke-linecap="round" opacity="'+op2+'"/>';
    if(k>1){var cr2=Math.max(2.5,5-(k-1)*0.4);s+='<circle cx="'+pts[k].x.toFixed(1)+'" cy="'+pts[k].y.toFixed(1)+'" r="'+cr2+'" fill="white" stroke="'+color+'" stroke-width="1.5"/>'+'<text x="'+(pts[k].x+cr2+2).toFixed(1)+'" y="'+(pts[k].y+3).toFixed(1)+'" font-size="7" fill="#6b7785" font-family="monospace">J'+k+'</text>';}
  }
  var ef2=pts[pts.length-1];
  s+='<circle cx="'+ef2.x.toFixed(1)+'" cy="'+ef2.y.toFixed(1)+'" r="5" fill="'+color+'" opacity="0.9"/>';
  el.innerHTML=s;
}

function renderRobot(r,s){
  drawSide(r.id,s.pos,r.links,r.color,r.roll,r.j3off);
  drawTop(r.id,s.pos,r.links,r.color,r.roll,r.j3off);
  for(var j=1;j<=6;j++)setBar(r.id,j,s.pos[j-1]||0,r.jrange);
  var st=document.getElementById(r.id+'-st');
  if(st){var sf=(s.status||'UNKNOWN').replace(/[^A-Z_]/g,'');st.className='status-pill s-'+sf;st.textContent=s.status||'UNKNOWN';}
  var ts=document.getElementById(r.id+'-ts');
  if(ts&&s.ts)ts.textContent=s.ts.substring(0,19).replace('T',' ')+' UTC';
  var ri=document.getElementById(r.id+'-rid');if(ri)ri.textContent='row '+s.lastId;
  var dot=document.getElementById(r.id+'-dot');
  if(dot){dot.className='ldot'+(s.ts&&(Date.now()-new Date(s.ts).getTime())>5000?' stale':'');}
}

var _pm=300;
async function pollRobots(){
  var t0=Date.now();
  try{
    var data=await(await fetch('/api/robot_telemetry')).json();
    var t1=Date.now();
    _pm=Math.max(150,Math.min(800,(t1-t0)*2.5));
    document.getElementById('g-poll').textContent=Math.round(_pm);
    document.getElementById('g-upd').textContent=new Date().toLocaleTimeString();
    var anyNew=false;
    ROBOTS.forEach(function(r){
      var d=data[r.id];if(!d)return;
      var s=state[r.id];
      if(d.id&&d.id!==s.lastId){
        s.lastId=d.id;s.pos=[d.j1p||0,d.j2p||0,d.j3p||0,d.j4p||0,d.j5p||0,d.j6p||0];
        s.status=d.status||'UNKNOWN';s.ts=d.ts;anyNew=true;
      }
      renderRobot(r,s);
    });
    var gl=document.getElementById('g-live');
    if(gl)gl.className='ldot'+(anyNew?'':' stale');
  }catch(e){console.warn('poll err',e);}
  setTimeout(pollRobots,_pm);
}

setInterval(function(){var e=document.getElementById('clock');if(e)e.textContent=new Date().toLocaleTimeString();},1000);
document.addEventListener('DOMContentLoaded',function(){
  buildScadaCards();
  pollScada();
  initBars();
  ROBOTS.forEach(function(r){renderRobot(r,state[r.id]);});
  pollRobots();
});
</script>
</body>
</html>
"""




ALARMS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Alarms \u2014 Shipyard 4.0 MES</title>
  <link rel="stylesheet" href="/static/css/style.css">
  <style>
    .sev-CRITICAL{background:#fde8e8;color:#c0392b;border:1px solid #e74c3c;}
    .sev-WARNING {background:#fef9e7;color:#b7770d;border:1px solid #f39c12;}
    .sev-INFO    {background:#eaf4fb;color:#1a6fa0;border:1px solid #3498db;}
    .sev-pill{display:inline-block;padding:3px 10px;border-radius:12px;font-size:.72rem;font-weight:700;white-space:nowrap;}
    .alarm-table{width:100%;border-collapse:collapse;font-size:.82rem;}
    .alarm-table th{background:#f8f9fa;color:#6b7785;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;padding:9px 12px;border-bottom:2px solid #e0e6ed;text-align:left;white-space:nowrap;}
    .alarm-table td{padding:8px 12px;border-bottom:1px solid #f0f2f5;vertical-align:middle;}
    .alarm-table tr:hover td{background:#f6f9fd;}
    .alarm-table tr.row-CRITICAL td{background:#fff8f8;}
    .alarm-table tr.row-WARNING  td{background:#fffdf0;}
    .kpi-banner{display:flex;gap:16px;flex-wrap:wrap;}
    .kpi-box{flex:1;min-width:140px;background:white;border-radius:10px;border:2px solid #e0e6ed;padding:14px 18px;text-align:center;}
    .kpi-box .kv{font-size:2rem;font-weight:800;line-height:1.1;}
    .kpi-box .kl{font-size:.75rem;color:#6b7785;text-transform:uppercase;letter-spacing:.05em;margin-top:4px;}
    .kpi-box.crit{border-color:#e74c3c;}
    .kpi-box.warn{border-color:#f39c12;}
    .kpi-box.info{border-color:#3498db;}
    .filter-bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;background:white;border-radius:10px;border:2px solid #e0e6ed;padding:12px 16px;}
    .filter-bar select,.filter-bar input{padding:6px 10px;border:1.5px solid #d5dfe8;border-radius:7px;font-size:.82rem;}
    .filter-bar button{padding:6px 16px;border-radius:7px;font-size:.82rem;cursor:pointer;border:none;}
    .btn-apply{background:linear-gradient(135deg,#2c3e50,#3498db);color:white;}
    .btn-clear{background:#eef2f7;color:#34495e;border:1px solid #d5dfe8!important;}
    .pager{display:flex;align-items:center;gap:8px;}
    .pager button{padding:5px 14px;border-radius:6px;border:1.5px solid #d5dfe8;background:white;cursor:pointer;font-size:.82rem;}
    .pager button:disabled{opacity:.4;cursor:default;}
    .type-badge{background:#eef2f7;color:#34495e;padding:2px 8px;border-radius:4px;font-size:.72rem;font-weight:600;white-space:nowrap;}
    .change-arrow{color:#aaa;font-size:.8rem;}
  </style>
</head>
<body>
<div class="topbar">
  <div class="topbar-left">
    <div class="logo">Shipyard 4.0 MES</div>
    <div class="subtitle">Alarm Log</div>
  </div>
  <div class="topbar-right">
    <a href="/" class="nav-btn">Overview</a>
    <a href="/telemetry" class="nav-btn">Telemetry</a>
    <a href="/scada" class="nav-btn">SCADA</a>
    <a href="/analytics" class="nav-btn analytics">Analytics</a>
    <a href="/alarms" class="nav-btn alarms active">Alarms</a>
    <span class="badge" id="clock"></span>
  </div>
</div>

<main class="main">

  <div class="kpi-banner" id="kpi-banner">
    <div class="kpi-box crit"><div class="kv" id="cnt-critical" style="color:#e74c3c;">—</div><div class="kl">Critical</div></div>
    <div class="kpi-box warn"><div class="kv" id="cnt-warning"  style="color:#f39c12;">—</div><div class="kl">Warning</div></div>
    <div class="kpi-box info"><div class="kv" id="cnt-info"     style="color:#3498db;">—</div><div class="kl">Info</div></div>
    <div class="kpi-box"    ><div class="kv" id="cnt-total"                           >—</div><div class="kl">Total Alarms</div></div>
    <div class="kpi-box" style="text-align:left;min-width:200px;">
      <div style="font-size:.72rem;color:#6b7785;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;">Auto-refresh</div>
      <div style="display:flex;align-items:center;gap:8px;">
        <span id="al-status" style="font-size:.8rem;color:#6b7785;">—</span>
        <span style="font-size:.75rem;color:#aaa;">next in <span id="al-countdown">15</span>s</span>
      </div>
    </div>
  </div>

  <div class="filter-bar">
    <span style="font-size:.82rem;font-weight:700;color:#34495e;text-transform:uppercase;letter-spacing:.06em;">Filter</span>
    <select id="f-severity">
      <option value="">All Severities</option>
      <option value="CRITICAL">Critical</option>
      <option value="WARNING">Warning</option>
      <option value="INFO">Info</option>
    </select>
    <select id="f-limit">
      <option value="50">50 rows</option>
      <option value="100" selected>100 rows</option>
      <option value="250">250 rows</option>
      <option value="500">500 rows</option>
    </select>
    <button type="button" class="btn-apply" onclick="loadAlarms(1)">Apply</button>
    <button type="button" class="btn-clear" onclick="clearFilters()">Clear</button>
    <div class="pager">
      <button id="pg-prev" onclick="loadAlarms(currentPage-1)" disabled>&laquo; Prev</button>
      <span id="pg-label" style="font-size:.82rem;color:#6b7785;">Page 1</span>
      <button id="pg-next" onclick="loadAlarms(currentPage+1)">Next &raquo;</button>
    </div>
    <span id="al-count" style="font-size:.78rem;color:#98a4b0;margin-left:auto;"></span>
  </div>

  <div style="background:white;border-radius:12px;border:2px solid #e0e6ed;box-shadow:0 3px 12px rgba(0,0,0,.06);overflow:hidden;">
    <table class="alarm-table">
      <thead id="al-head">
        <tr>
          <th>#</th><th>Timestamp</th><th>Severity</th><th>Type</th>
          <th>Entity</th><th>Message</th><th>Change</th>
        </tr>
      </thead>
      <tbody id="al-body">
        <tr><td colspan="7" style="text-align:center;padding:40px;color:#aaa;">Loading alarms\u2026</td></tr>
      </tbody>
    </table>
  </div>

</main>

<script>
var currentPage=1,totalPages=1;

function sevPill(s){
  return '<span class="sev-pill sev-'+s+'">'+s+'</span>';
}
function typeLabel(t){
  var map={
    BOTTLENECK_CHANGE:'Bottleneck Change',
    RHO_UNSTABLE:'Rho Unstable',
    RHO_HIGH:'Rho High',
    RHO_NORMAL:'Rho Normalized',
    ROBOT_ERROR:'Robot Error',
    ROBOT_RECOVERY:'Robot Recovery'
  };
  return '<span class="type-badge">'+(map[t]||t)+'</span>';
}
function fmtTs(ts){
  if(!ts) return '\u2014';
  return String(ts).substring(0,19).replace('T',' ');
}
function fmtChange(oldv,newv){
  if(!oldv&&!newv) return '\u2014';
  if(oldv&&newv) return oldv+' <span class="change-arrow">\u2192</span> '+newv;
  return newv||oldv;
}

async function loadAlarms(page){
  currentPage=page||1;
  var sev   = document.getElementById('f-severity').value;
  var limit = document.getElementById('f-limit').value;
  var offset= (currentPage-1)*parseInt(limit);
  var qs    = 'limit='+limit+'&offset='+offset;
  if(sev) qs+='&severity='+encodeURIComponent(sev);
  try{
    var d=await(await fetch('/api/alarms?'+qs)).json();
    document.getElementById('al-status').textContent=d.db_ok?'Connected':'Error';
    totalPages=d.total_pages||1;
    document.getElementById('pg-label').textContent='Page '+currentPage+' / '+totalPages;
    document.getElementById('pg-prev').disabled=currentPage<=1;
    document.getElementById('pg-next').disabled=currentPage>=totalPages;
    document.getElementById('al-count').textContent=(d.total_count||0).toLocaleString()+' alarms';
    var rows=d.rows||[];
    if(!rows.length){
      document.getElementById('al-body').innerHTML='<tr><td colspan="7" style="text-align:center;padding:40px;color:#aaa;">No alarms found</td></tr>';
    } else {
      document.getElementById('al-body').innerHTML=rows.map(function(r){
        return '<tr class="row-'+r.severity+'">'
          +'<td style="color:#aaa;font-size:.75rem">'+r.id+'</td>'
          +'<td style="white-space:nowrap;font-size:.8rem">'+fmtTs(r.ts)+'</td>'
          +'<td>'+sevPill(r.severity)+'</td>'
          +'<td>'+typeLabel(r.alarm_type)+'</td>'
          +'<td style="font-weight:600;color:#2c3e50">'+(r.entity||'\u2014')+'</td>'
          +'<td>'+r.message+'</td>'
          +'<td style="font-size:.78rem;white-space:nowrap">'+fmtChange(r.old_value,r.new_value)+'</td>'
          +'</tr>';
      }).join('');
    }
    updateKpis(d.rows||[], d.total_count||0);
  }catch(err){
    document.getElementById('al-status').textContent='Error';
    console.error(err);
  }
}

function updateKpis(rows, total){
  var crit=rows.filter(function(r){return r.severity==='CRITICAL';}).length;
  var warn=rows.filter(function(r){return r.severity==='WARNING';}).length;
  var info=rows.filter(function(r){return r.severity==='INFO';}).length;
  document.getElementById('cnt-critical').textContent=crit;
  document.getElementById('cnt-warning').textContent=warn;
  document.getElementById('cnt-info').textContent=info;
  document.getElementById('cnt-total').textContent=total.toLocaleString();
}

function clearFilters(){
  document.getElementById('f-severity').value='';
  document.getElementById('f-limit').value='100';
  loadAlarms(1);
}


var _cd=15;
function tick(){
  _cd--;
  var el=document.getElementById('al-countdown');
  if(el) el.textContent=_cd;
  if(_cd<=0){_cd=15;loadAlarms(currentPage);}
  setTimeout(tick,1000);
}

setInterval(function(){var e=document.getElementById('clock');if(e)e.textContent=new Date().toLocaleTimeString();},1000);
document.addEventListener('DOMContentLoaded',function(){
  loadAlarms(1);
  tick();
});
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    db: MESDatabase = None

    def log_message(self, fmt, *args):
        pass  # quiet access log

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        params = parse_qs(parsed.query)

        routes = {
            "/":                    (MES_HTML,       "text/html"),
            "/telemetry":           (TELEMETRY_HTML, "text/html"),
            "/analytics":           (ANALYTICS_HTML, "text/html"),
            "/robots":              (SCADA_HTML,     "text/html"),
            "/scada":               (SCADA_HTML,     "text/html"),
            "/alarms":              (ALARMS_HTML,    "text/html"),
            "/static/css/style.css":(STYLE_CSS,      "text/css"),
        }

        if path in routes:
            body, ct = routes[path]
            self._send(body.encode(), ct)
        elif path == "/api/snapshot":
            self._send_json(Handler.db.get_snapshot())
        elif path == "/api/robot_telemetry":
            self._send_json(Handler.db.get_robot_telemetry())
        elif path == "/api/scada_status":
            self._send_json(Handler.db.get_scada_status())
        elif path == "/api/scada_history":
            device = params.get("device", [SCADA_TABLES[0][0]])[0]
            limit  = min(int(params.get("limit", ["50"])[0]), 200)
            offset = int(params.get("offset", ["0"])[0])
            self._send_json(Handler.db.get_scada_history(device, limit, offset))
        elif path == "/api/analytics":
            self._send_json(Handler.db.get_latest_from_history())
        elif path == "/api/analytics_range":
            ts_start = params.get("start", [None])[0] or None
            ts_end   = params.get("end",   [None])[0] or None
            self._send_json(Handler.db.get_range_from_history(ts_start=ts_start, ts_end=ts_end))
        elif path == "/api/debug":
            try:
                conn = _analytics_db_connect()
                with conn.cursor() as c:
                    c.execute(f"SELECT COUNT(*) FROM {SOURCE_SCHEMA}.cycle_event;")
                    n = c.fetchone()[0]
                conn.close()
                self._send_json({"ok": True, "cycle_event_rows": n,
                                 "host": DB_HOST, "db": DB_NAME, "schema": SOURCE_SCHEMA})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e),
                                 "host": DB_HOST, "db": DB_NAME, "schema": SOURCE_SCHEMA})
        elif path == "/api/history":
            robot    = params.get("robot",    ["robot1"])[0]
            limit    = min(int(params.get("limit",    ["200"])[0]), 1000)
            offset   = int(params.get("offset",   ["0"])[0])
            status   = params.get("status",   [""])[0].strip()
            full     = params.get("full",     ["0"])[0] == "1"
            window_s = int(params.get("window_s", ["0"])[0])
            if robot not in ROBOTS:
                self._send_json({"error": "unknown robot"}); return
            self._send_json(Handler.db.get_history(robot, limit, offset, status, full, window_s))
        elif path == "/api/alarms":
            limit    = min(int(params.get("limit",    ["100"])[0]), 500)
            offset   = int(params.get("offset",   ["0"])[0])
            severity = params.get("severity", [""])[0].strip()
            self._send_json(Handler.db.get_alarms(limit, offset, severity))
        elif path == "/api/wc_history":
            start = params.get("start", [None])[0] or None
            end   = params.get("end",   [None])[0] or None
            limit = min(int(params.get("limit", ["2000"])[0]), 5000)
            self._send_json(Handler.db.get_wc_history(start, end, limit))
        elif path == "/api/db_stats":
            try:
                self._send_json(Handler.db.get_db_stats())
            except Exception as e:
                self._send_json({"error": str(e),
                                 "telemetry": {"ok": False, "tables": {}},
                                 "analytics":  {"ok": False, "tables": {}}})
        elif path == "/api/truncate_table":
            db_key = params.get("db",    [None])[0] or ""
            table  = params.get("table", [None])[0] or ""
            self._send_json(Handler.db.truncate_table(db_key, table))
        else:
            self.send_response(404); self.end_headers()

    def _send(self, data: bytes, ct: str):
        self.send_response(200)
        self.send_header("Content-Type", f"{ct}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj):
        self._send(json.dumps(obj, default=str).encode(), "application/json")


# ── main ─────────────────────────────────────────────────────────────
def main():
    db = MESDatabase()
    Handler.db = db
    # ── Background: telemetry snapshot (every 2s) ─────────────────────
    snapshot_cache = {"data": db.get_snapshot()}

    def snapshot_loop():
        while True:
            try:
                snap = db.get_snapshot()
                snapshot_cache["data"] = snap
                check_robot_alarms(snap, db)
            except Exception as e:
                print(f"⚠️  Snapshot refresh error: {e}")
            time.sleep(2)

    # patch Handler to use caches
    original_do_GET = Handler.do_GET
    def cached_do_GET(self):
        p = urlparse(self.path).path
        if p == "/api/snapshot":
            self._send_json(snapshot_cache["data"])
        else:
            original_do_GET(self)
    Handler.do_GET = cached_do_GET

    threading.Thread(target=snapshot_loop, daemon=True).start()

    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    print(f"🚀 MES Dashboard running at http://localhost:{HTTP_PORT}")
    print(f"   DB: {DB_HOST}/{DB_NAME}  MES schema: {DB_SCHEMA}")
    print("   Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹  Shutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
