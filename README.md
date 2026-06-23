# Shipyard Pick & Place — Factory Automation System

**Document date:** 19 June 2026
**Stack:** ROS 2 Jazzy · Python 3.12 · Ubuntu 24.04
**Architecture:** Plug-and-Plan (FS → VS · Command / Ack / Status)

---

## Table of Contents

1. [Overview](#1-overview)
2. [System Architecture](#2-system-architecture)
3. [Hardware and Network](#3-hardware-and-network)
4. [ROS 2 Nodes](#4-ros-2-nodes)
5. [Communication Protocol](#5-communication-protocol)
6. [Production Routes by Colour](#6-production-routes-by-colour)
7. [Factory Supervisor — Coordination Core](#7-factory-supervisor--coordination-core)
8. [Planner — Rules per Module](#8-planner--rules-per-module)
9. [Sovereign Sensor Principle](#9-sovereign-sensor-principle)
10. [Vendor Supervisors — Hardware Layer](#10-vendor-supervisors--hardware-layer)
11. [Internal Trackers](#11-internal-trackers)
12. [Configuration](#12-configuration)
13. [System Startup](#13-system-startup)
14. [Database](#14-database)
15. [SimPy Production Order Optimizer](#15-simpy-production-order-optimizer)
16. [Resolved Bugs](#16-resolved-bugs)
17. [Current Status and Pending Work](#17-current-status-and-pending-work)

---

## 1. Overview

Pick & Place factory automation system that processes pieces of three colours (RED, GREEN, BLUE) through a robotised production line. The system uses a two-layer architecture:

- **Factory Supervisor (FS):** MES-level coordinator. Makes all planning decisions, tracks pieces and cycles, and sends commands to hardware domains.
- **Vendor Supervisors (VS):** One ROS 2 node per hardware domain. Receives commands from the FS, executes real work on the hardware, and publishes state back.

The FS does not know *how* an arm moves; the VS does not know *why* a piece moves. The separation is strict.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     FACTORY SUPERVISOR                          │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ PieceTracker│  │ StateTracker │  │    CycleTracker       │  │
│  └─────────────┘  └──────────────┘  └───────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                      PLANNER                               │ │
│  │  initialization · feeding · conveyor · processing         │ │
│  │  classification · unloading · shutdown                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │               VendorClient × 7                             │ │
│  │  (niryo · ufactory · laser · globalvision ·               │ │
│  │   green_conveyors · arduino_vacuum · bantam)               │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────┬───────────────────────────────────────────────┘
                  │  ROS 2 topics  (command / ack / status)
   ┌──────────────┼──────────────────────────────────────┐
   │              │                                      │
   ▼              ▼                                      ▼
NiryoVS    UFactoryVS    LaserVS   GlobalVisionVS   GreenConveyorsVS
                                   ArduinoVacuumVS   BantamVS
```

### Command Flow

```
FS.send_command()
   └─► VendorClient.send_command()   ← publishes JSON on /{domain}_factory/command
         └─► VS._on_command_raw()    ← receives, validates, calls handle_task()
               └─► publish_ack()     ← /{domain}_factory/ack
               └─► TaskRunner.run()  ← hardware thread
                     └─► publish_status() RUNNING / COMPLETED / FAILED
                                          /{domain}_factory/status
FS.on_status()
   └─► VendorClient.on_status_received()
         └─► on_complete callback()  ← next step of the rule
   └─► evaluate_rules()              ← if terminal OR sensor_updated
```

---

## 3. Hardware and Network

| Device | Model | IP | Port / Connection |
|---|---|---|---|
| Niryo Robot 1 | Ned2 | 192.168.0.195 | /robot1 namespace |
| Niryo Robot 2 | Ned2 | 192.168.0.244 | /robot2 namespace |
| xArm 1 | UFACTORY Lite6 | 192.168.0.254 | /xarm1 namespace |
| xArm 2 | UFACTORY Lite6 | 192.168.0.168 | /xarm2 namespace |
| Laser | HTTP API | 192.168.0.173 | HTTP REST |
| Bantam CNC | Simulated + ZMQ door | 192.168.0.171:5555 | ZMQ REQ/REP |
| Arduino (vacuum) | Serial | /dev/ttyACM1 | 9600 baud |
| Arduino (green belts) | Serial | /dev/ttyACM0 | 115200 baud |
| Global camera | USB OpenCV | /dev/video0 | camera_index=0 |

### Physical IR Sensors (active LOW)

| Sensor | Belt | Niryo Pin | Description |
|---|---|---|---|
| c1s1 | Conveyor 1 | DI5 (robot1) | Conveyor 1 entry — piece deposited by xArm2 |
| c1s2 | Conveyor 1 | DI1 (robot1) | Conveyor 1 exit — piece ready for xArm1 |
| c2s1 | Conveyor 2 | DI5 (robot2) | Conveyor 2 entry — piece deposited by xArm1 |
| c2s2 | Conveyor 2 | DI1 (robot2) | Conveyor 2 exit — piece ready for robot2 |

### Virtual Sensors (no IR hardware)

| Sensor | Written by | Description |
|---|---|---|
| c3 | `feeding_rules` | robot1 pickup position for GREEN pieces |
| c4 | `classification_rules` | robot1 pickup position for RED/BLUE pieces |

---

## 4. ROS 2 Nodes

### factory_supervisor
- **Executable:** `factory_supervisor`
- **Description:** Main coordinator. Phases: BOOT → RUNNING → SHUTTING_DOWN → STOPPED.
- **Timers:** planner 0.5 s · watchdog 1.0 s · system_state_pub 2.0 s
- **Callback groups:** ReentrantCallbackGroup (ack/status) · MutuallyExclusiveCallbackGroup (planner, watchdog, dashboard, order)
- **Executor:** MultiThreadedExecutor(num_threads=4)
- **Subscribed topics:** `/{domain}_factory/ack`, `/{domain}_factory/status`, `/supervisor/set_optimized_order`
- **Published topics:** `/{domain}_factory/command`, `/factory/system_state`

### niryo_vendor_supervisor
- **Executable:** `niryo_vendor_supervisor`
- **Mode:** `hardware` (configured in hardware_ports.yaml)
- **Managed resources:** robot1, robot2, conveyor1, conveyor2, vision_robot1, vision_robot2, robot2_niryo_vacuum
- **Parameters:** mode, robot1_namespace, robot1_ip, robot2_namespace, robot2_ip, service_wait_timeout_sec (10 s), command_timeout_sec (45 s), settle_time_sec (0.2 s), vacuum_delay_sec (0.5 s), sensor_poll_interval_sec (0.2 s), conveyor_run_timeout_sec (30 s)
- **Independent TaskRunners:** robot1 · robot2 · conveyor1 · conveyor2 (concurrent execution)
- **IR sensor polling timer:** every 0.2 s in hardware mode
- **Executor:** MultiThreadedExecutor(num_threads=4)

### ufactory_vendor_supervisor
- **Executable:** `ufactory_vendor_supervisor`
- **Mode:** `hardware`
- **Resources:** xarm1, xarm2
- **Parameters:** mode, xarm1_namespace (/xarm1), xarm2_namespace (/xarm2), command_timeout_sec (35 s), default_speed (30.0), default_acc (100.0), settle_time_sec (0.5 s), gripper_delay_sec (0.5 s)
- **TaskRunners:** one per xArm, parallel
- **Executor:** MultiThreadedExecutor(num_threads=4)

### laser_vendor_supervisor
- **Executable:** `laser_vendor_supervisor`
- **Mode:** HTTP API
- **Parameters:** laser_ip (192.168.0.173), gcode_dir, default_gcode (happyface.gcode), job_duration_sec (2.0), wait_time_before_start_sec (2.0), http_timeout_sec (10.0)
- **Safety:** gcode file whitelist, fragment blacklist (blocks S25)
- **FS timeout:** 300 s for RUN_JOB

### globalvision_vendor_supervisor
- **Executable:** `globalvision_vendor_supervisor`
- **Description:** USB camera + OpenCV. Detects slot_id, colour and shape of pieces in the initial stack.
- **Parameters:** camera_index (0), color_threshold_pct (5.0%), show_window (false by default)
- **Supported tasks:** INITIALIZE_DOMAIN, SCAN_STACK, LOCATE_NEXT_PIECE, GET_INVENTORY, RESET
- **Preview window:** enable with `--ros-args -p show_window:=true` (20 fps, Q/ESC closes)

### green_conveyors_vendor_supervisor
- **Executable:** `green_conveyors_vendor_supervisor`
- **Description:** Controls Arduino output belts (conveyor3 channel B, conveyor4 channel A)
- **Parameters:** port (/dev/ttyACM0), baudrate (115200), conveyor3_speed (9000), conveyor4_speed (9000), conveyor3_direction (REV), conveyor4_direction (FWD)
- **Tasks:** RUN_CONVEYOR, STOP_CONVEYOR, SET_SPEED

### arduino_vacuum_vendor_supervisor
- **Executable:** `arduino_vacuum_vendor_supervisor`
- **Description:** Arduino vacuum system control for robot1
- **Parameters:** port (/dev/ttyACM1), baudrate (9600), pick_hold_sec (0.5), release_hold_sec (0.3)
- **Tasks:** PICK, RELEASE, OFF

### bantam_vendor_supervisor
- **Executable:** `bantam_vendor_supervisor`
- **Description:** Bantam CNC with ZMQ door control and simulated machining
- **Parameters:** processing_time_sec (25.0 — simulated), door_timeout_sec (12 s), door_zmq_address (tcp://192.168.0.171:5555)
- **FS timeout:** 600 s for RUN_JOB

### dashboard_node
- **Executable:** `dashboard_node`
- **Description:** HTTP server on port 8080. Launched automatically with the full system.
- **Features:**
  - Live system topology panel (sourced from `/factory/system_state`)
  - SimPy production order optimizer (see Section 17)
  - DB analytics panel (cycle times, throughput — sourced from remote PostgreSQL)
  - Live camera streams: robot1, robot2, globalvision (`/stream/{key}.jpg`)
- **API endpoints:**
  - `GET /` — main dashboard HTML
  - `GET /camera` — camera view page
  - `GET /api/state` — current system snapshot (JSON)
  - `POST /api/optimize` — launch optimizer in background thread
  - `GET /api/optimize_status` — optimizer progress and result
  - `POST /api/start_production` — apply optimized order and start production
  - `GET /stream/{key}.jpg` — MJPEG frame for robot1 / robot2 / globalvision
- **Parameters:** `port` (default 8080)

---

## 5. Communication Protocol

### Topics per Domain

```
/{domain}_factory/command   →  FS publishes, VS subscribes
/{domain}_factory/ack       →  VS publishes, FS subscribes
/{domain}_factory/status    →  VS publishes, FS subscribes
```

Domains: `niryo`, `ufactory`, `laser`, `globalvision`, `green_conveyors`, `arduino_vacuum`, `bantam`

### Command Structure

```json
{
  "command_id": "niryo-0042-1718755800.123",
  "domain_id": "niryo",
  "resource_id": "conveyor1",
  "task": "RUN_NIRYO_CONVEYOR",
  "piece_id": "piece-001",
  "source": "C1S1",
  "target": "C1S2",
  "route": "RED",
  "parameters": {"conveyor_id": "conveyor1"},
  "correlation_id": null,
  "hmac": "..."
}
```

### ACK Structure

```json
{
  "command_id": "niryo-0042-...",
  "domain_id": "niryo",
  "resource_id": "conveyor1",
  "accepted": true,
  "reason": null
}
```

### STATUS Structure

```json
{
  "command_id": "niryo-0042-...",
  "domain_id": "niryo",
  "resource_id": "conveyor1",
  "task": "RUN_NIRYO_CONVEYOR",
  "task_state": "COMPLETED",
  "resource_state": "STOPPED",
  "piece_id": "piece-001",
  "source": "C1S1",
  "target": "C1S2",
  "route": "RED",
  "result": {
    "code": "STOPPED_AT_EXIT_SENSOR",
    "sensor_id": "c1s2",
    "state": "OCCUPIED"
  }
}
```

### Task States

`RECEIVED` → `RUNNING` → `COMPLETED` | `FAILED` | `REJECTED` | `TIMEOUT` | `CANCELED`

Terminal states: COMPLETED, FAILED, REJECTED, TIMEOUT, CANCELED.

### Autonomous SENSOR_UPDATE

Niryo VS emits autonomous STATUS messages with `command_id="AUTO"` when sensor polling detects a change:

```json
{
  "command_id": "AUTO",
  "task": "SENSOR_UPDATE",
  "task_state": "COMPLETED",
  "resource_id": "c1s2",
  "resource_state": "OCCUPIED",
  "result": {"code": "SENSOR_UPDATE", "sensor_id": "c1s2", "state": "OCCUPIED"}
}
```

These messages are ignored by `VendorClient.on_status_received()` (no correlation with pending commands) but processed directly by `FactorySupervisor._apply_sensor_result()`, which updates the StateTracker and triggers `evaluate_rules()` immediately.

### HMAC (Phases 1–5: warn-only)

The system includes HMAC infrastructure in `shared/messages.py` and `config/hmac_secrets.yaml`. In the current phases (1–5) an HMAC failure generates a WARNING but does NOT reject the command. Strict enforcement will be activated in later phases.

---

## 6. Production Routes by Colour

```
RED:   initial_stack → conveyor1 → laser_bed → conveyor2 → c4_location → final_red_stack
BLUE:  initial_stack → conveyor1 → conveyor2 → bantam_bed → c4_location → final_blue_stack
GREEN: initial_stack → c3_location → final_green_stack
```

### Detailed Description per Colour

**RED:**
1. xArm2 picks from stack (globalvision provides slot_id)
2. xArm2 deposits at c1s1 (conveyor 1 entry)
3. Conveyor 1 starts when c1s1=OCCUPIED and c1s2=FREE → stops when c1s2=OCCUPIED
4. xArm1 picks from c1s2 → deposits at LASER_BED
5. Laser engraves (happyface.gcode)
6. xArm1 picks from LASER_BED → deposits at c2s1 (waits if c2s1=OCCUPIED)
7. Conveyor 2 starts when c2s1=OCCUPIED and (c2s2=FREE or _c2s2_committed) → stops at c2s2
8. Robot2 performs local vision at c2s2
9. Robot2 picks from c2s2 → deposits at c4_location, starts conveyor4
10. Robot1 classifies and picks from c4 (waits c4_settle_sec=14.5 s) → vacuum → deposits at final_red_stack

**BLUE:**
1–4. Same as RED up to c1s2
4. xArm1 picks from c1s2 → deposits directly at c2s1 (no laser)
5–7. Same as RED
8. Robot2 performs local vision → decides BANTAM
9. Robot2 deposits at bantam_bed, Bantam machines (25 s simulated)
10. Robot2 picks from bantam_bed → deposits at c4_location
11. Robot1 same as RED

**GREEN:**
1. xArm2 picks from stack → deposits directly at c3_location
2. Conveyor3 starts → stops after c3_settle_sec=10 s
3. Robot1 classifies and picks from c3 → deposits at final_green_stack (bypasses conveyor1, xArm1, conveyor2, robot2 entirely)

---

## 7. Factory Supervisor — Coordination Core

**File:** `factory/factory_supervisor.py`

### Planner State

```python
self.planner_phase         # PlannerPhase: BOOT | RUNNING | SHUTTING_DOWN | STOPPED
self._feeding_state        # "IDLE" | "WAITING_VISION" | "WAITING_XARM2_PICK" | ...
self._processing_state     # "IDLE" | "WAITING_XARM1_TO_LASER" | "WAITING_LASER" |
                           # "LASER_DONE_WAITING_C2S1" | "WAITING_XARM1_TO_C2S1" | ...
self._classification_state # "IDLE" | "WAITING_VISION" | "WAITING_ROBOT2_TO_C4" | ...
self._unloading_state      # "IDLE" | "WAITING_CLASSIFY_PICK" | "WAITING_VACUUM_PICK" | ...
self._shutdown_state       # "IDLE" | current shutdown step
```

### Critical State Fields

```python
self._c2s2_committed: bool     # True: robot2 is committed to picking from c2s2 → conveyor2 can start
self._pending_laser_piece_id   # piece ID when laser finishes and c2s1 is occupied
self._c3_deposit_time: float   # timestamp of last deposit at c3 (settle guard)
self._c4_deposit_time: float   # timestamp of last deposit at c4 (settle guard)
self.c3_settle_sec: float      # 10.0 s — time robot1 waits before picking from c3
self.c4_settle_sec: float      # 14.5 s — time robot1 waits before picking from c4
```

### Main Loop

```
Timer 0.5 s → evaluate_rules()
  BOOT:         initialization_rules.evaluate()
  RUNNING:      feeding → conveyor → processing → classification → unloading
  SHUTTING_DOWN: shutdown_rules.evaluate()
```

Additionally, `evaluate_rules()` fires IMMEDIATELY when `on_status()` receives:
- A message with a terminal `task_state` (COMPLETED/FAILED/REJECTED/TIMEOUT/CANCELED)
- A `SENSOR_UPDATE` with a state change (`sensor_updated=True`)

This ensures a physical IR sensor change triggers rule evaluation without waiting for the 500 ms timer.

### Watchdog (1 s)

Calls `VendorClient.check_timeout()` on all domains. If a command exceeds its timeout (default 120 s, per-task overrides) it is completed with `TIMEOUT`.

### Per-task Timeouts

| Task | Timeout |
|---|---|
| INITIALIZE_DOMAIN | 30 s |
| SCAN_STACK | 15 s |
| LOCATE_NEXT_PIECE | 10 s |
| GOTO_PICK_POSITION | 60 s |
| LIFT_AND_PLACE | 60 s |
| RETURN_HOME | 60 s |
| RUN_NIRYO_CONVEYOR | 30 s |
| PICK / RELEASE | 5 s |
| RUN_JOB (laser) | 300 s |
| RUN_JOB (bantam) | 600 s |
| Default | 120 s |

### Periodic State Log (every 10 s in RUNNING)

```
[state] proc=IDLE feed=IDLE class=IDLE unload=IDLE |
        c1s1=FREE c1s2=OCCUPIED c2s1=FREE c2s2=FREE c4=FREE |
        xarm1=IDLE xarm2=IDLE robot1=IDLE robot2=IDLE |
        conv1=1 laser=0 conv2=0
```

### Initial Stack (hardcoded in factory_supervisor.py)

```python
INITIAL_STACK_ORDER = [
    {"id": "piece-001", "color": "RED", "shape": None},
    {"id": "piece-002", "color": "RED", "shape": None},
    {"id": "piece-003", "color": "RED", "shape": None},
    {"id": "piece-003", "color": "RED", "shape": None},
]
```

Colour/shape are hints for globalvision. If set to `None`, globalvision detects them automatically.

---

## 8. Planner — Rules per Module

### 8.1 initialization_rules.py

Start-up sequence in dependency order:

```
arduino_vacuum → green_conveyors → globalvision → ufactory → niryo → laser → bantam → RUNNING
```

Each domain waits for COMPLETED before starting the next. If a domain fails, it retries on the next tick. If the VS has no subscriber yet (not started), it waits and warns without blocking.

### 8.2 feeding_rules.py

**Preconditions to start:**
- `_feeding_state == "IDLE"`
- `initial_stack` has pieces
- `xarm2 == IDLE` and not busy in ufactory
- `c1s1 == FREE` (hardware IR — sovereign sensor)
- globalvision not busy
- If next piece is GREEN: `c3 == FREE`

**Flow:**
1. `LOCATE_NEXT_PIECE` (globalvision) → obtains slot_id, colour, shape
2. If GREEN: `MOVE_PIECE xarm2 → C3` → `c3=OCCUPIED` (virtual), starts conveyor3, waits HOME
3. If not GREEN: `MOVE_PIECE xarm2 → C1S1`

**Callback `_on_xarm2_to_c1_complete`:**
- `pieces.transfer("initial_stack", "conveyor1")`
- `cycles.start_cycle(piece_id)`
- `xarm2 = IDLE`
- **Does NOT write c1s1=OCCUPIED** (the hardware IR sensor already did or will; writing it here creates a race condition)

### 8.3 conveyor_rules.py

**Conveyor 1:**
- Starts when: `c1s1=OCCUPIED`, `conveyor1=STOPPED`, `c1s2=FREE`
- Stops automatically when the VS detects `c1s2=OCCUPIED` (the VS manages the polling loop internally)

**Conveyor 2:**
- Starts when: `c2s1=OCCUPIED`, `conveyor2=STOPPED`, and (`c2s2=FREE` OR `_c2s2_committed=True`)
- `_c2s2_committed` is set in `_on_vision_complete` (robot2 has committed to picking)
- Cleared when `_conveyor2_rules` actually starts the belt
- This allows conveyor2 to start ~14 s before the physical sensor detects the piece has been picked

**Callback `_on_conveyor_done`:**
- Only updates `conveyor_id = STOPPED`
- **Does not write any sensor** (sovereign sensors)

### 8.4 processing_rules.py

**Preconditions:**
- `_processing_state == "IDLE"`
- `conveyor1` has pieces
- `c1s2 == OCCUPIED`
- `xarm1 == IDLE` and not busy in ufactory

**Decision by colour:**

```python
if color == "RED":
    # c2s1 NOT checked here — goes to laser, not to c2s1
    _send_xarm1_to_laser(fs, piece_id)
else:
    if c2s1 != FREE:
        return  # wait
    _send_xarm1_direct_to_c2(fs, piece_id, color)
```

**State `LASER_DONE_WAITING_C2S1`:**

When the laser finishes but c2s1 is still occupied, the processor enters this state. The next `evaluate_rules()` tick (triggered when c2s1 changes to FREE via the IR sensor) sends xArm1 from LASER_BED to C2S1.

```python
if fs._processing_state == "LASER_DONE_WAITING_C2S1":
    if c2s1 == FREE and not xarm1.is_busy():
        _send_xarm1_laser_to_c2(fs, fs._pending_laser_piece_id)
    return
```

**Processing logs:**
```
[processing] xarm1 → LASER_BED: piece=piece-001
[processing] xarm1 LASER_BED → C2S1: piece=piece-001
```

### 8.5 classification_rules.py

**Preconditions:**
- `_classification_state == "IDLE"`
- `conveyor2` has pieces
- `c2s2 == OCCUPIED`
- `c4 == FREE`
- `robot2 == IDLE` and not busy in niryo

**Flow:**
1. `CAPTURE_LOCAL_VISION` (robot2 at C2S2) → obtains colour, shape
2. In `_on_vision_complete`: sets `_c2s2_committed = True`, logs `c2s2_committed=True`
3. Routes by colour:
   - RED/GREEN → `MOVE_PIECE robot2 C2S2 → C4`
   - BLUE + bantam free → `MOVE_PIECE robot2 C2S2 → BANTAM_BED`
   - BLUE + bantam busy, or UNKNOWN → `MOVE_PIECE robot2 C2S2 → SCRAP`

**`_on_robot2_to_c4_complete`:**
- `pieces.transfer("conveyor2", "c4_location")`
- `state.update_sensor("c4", OCCUPIED)` ← c4 is virtual, OK
- `_c4_deposit_time = time.time()`
- Starts conveyor4 + auto-stop after c4_settle_sec
- Sends robot2 to HOME

**Does not write c2s2** in any callback (sovereign sensor).

### 8.6 unloading_rules.py

**Preconditions:**
- `_unloading_state == "IDLE"`
- `robot1 == IDLE` and not busy
- arduino_vacuum not busy

**Selection logic:**
- Prioritises c4 over c3
- Respects settle time (`c4_settle_sec=14.5 s`, `c3_settle_sec=10 s`)

**Flow:**
1. `CLASSIFY_AND_PICK` (robot1 at C4 or C3): robot1 goes to position, performs local vision, picks
2. `PICK` (arduino_vacuum): activates suction
3. In `_on_vacuum_pick_complete`: writes `c3/c4 = FREE` (virtual — piece is now in the air)
4. `LIFT_AND_PLACE` (robot1): carries piece to final destination
5. `RELEASE` (arduino_vacuum)
6. `RETURN_HOME` (robot1)
7. `cycles.complete_cycle()` → `db.insert_cycle_complete()`

**Final destinations by colour and shape:**

| Colour | Shape | Destination |
|---|---|---|
| RED | any | FINAL_RED_STACK |
| RED | CIRCLE | FINAL_RED_CIRCLE |
| GREEN | any | FINAL_GREEN_STACK |
| GREEN | CIRCLE | FINAL_GREEN_CIRCLE |
| BLUE | any | FINAL_BLUE_STACK |
| BLUE | CIRCLE | FINAL_BLUE_CIRCLE |
| UNKNOWN | — | SCRAP |

### 8.7 shutdown_rules.py

Activated when `pieces.all_pieces_finished() == True` (initial_stack empty AND all intermediate locations empty). Sends STOP/RESET to all domains in reverse order.

---

## 9. Sovereign Sensor Principle

### Fundamental Rule

**Physical sensors c1s1, c1s2, c2s1, c2s2 are SOVEREIGN. No robot callback, no planner rule, and no VS other than the Niryo VS is permitted to write their state.**

The sole source of truth for these sensors is the IR hardware, read by `NiryoConveyorAdapter.poll_sensors()` every 200 ms and published as an autonomous SENSOR_UPDATE.

### Why This Rule Exists

Before implementing it, robot callbacks manually wrote sensor states to "help" the planner. This caused fatal race conditions:

**Example of the critical c1s1 bug:**
```
t=0:   hardware c1s1 → OCCUPIED  (xArm2 deposited the piece)
t=0:   conveyor1 starts immediately
t=2:   hardware c1s1 → FREE  (piece moved to c1s2)
t=3:   _on_xarm2_to_c1_complete() fires LATE
t=3:   ← wrote c1s1=OCCUPIED  (WRONG — piece is no longer here)
t=3:   conveyor adapter has _last_sensor_states["c1s1"]="FREE"
       never re-emits FREE because it is already "FREE"
t=3:   supervisor left with c1s1=OCCUPIED permanently
t=33:  conveyor1 timeout — 30 s with no piece
t=33:  xArm2 can never deposit the next piece
RESULT: only 1 of 4 pieces processed
```

### Sensors and Who Writes Them

| Sensor | Type | Written by |
|---|---|---|
| c1s1 | Physical IR | `niryo_vendor_supervisor._publish_auto_sensor()` |
| c1s2 | Physical IR | `niryo_vendor_supervisor._publish_auto_sensor()` |
| c2s1 | Physical IR | `niryo_vendor_supervisor._publish_auto_sensor()` |
| c2s2 | Physical IR | `niryo_vendor_supervisor._publish_auto_sensor()` |
| c3 | Virtual | `feeding_rules._on_xarm2_to_c3_complete()` and `unloading_rules._on_vacuum_pick_complete()` |
| c4 | Virtual | `classification_rules._on_robot2_to_c4_complete()` and `unloading_rules._on_vacuum_pick_complete()` |

### Verification

```bash
grep -rn 'update_sensor.*c1s1\|update_sensor.*c1s2\|update_sensor.*c2s1\|update_sensor.*c2s2' \
     src/shipyard_pnp/shipyard_pnp/factory/planner/
# Result: zero occurrences
```

### `_c2s2_committed` Mechanism

The `_c2s2_committed` flag resolves the conveyor2 delay problem without violating the sovereign sensors:

**Problem:** The c2s2 sensor transitions from OCCUPIED to FREE when robot2 physically lifts the piece. This happens ~14 s after vision completes. If conveyor2 waits until hardware confirms c2s2=FREE, the belt is delayed 14 s unnecessarily.

**Solution:** In `_on_vision_complete`, when robot2 confirms it will pick the piece:
```python
fs._c2s2_committed = True
# c2s2=FREE is NOT written — the hardware will do it when true
```

In `_conveyor2_rules`:
```python
c2s2_clear = c2s2 == SensorState.FREE or fs._c2s2_committed
if c2s1 == OCCUPIED and conveyor2 == STOPPED and c2s2_clear:
    fs._c2s2_committed = False  # consume the flag
    # start conveyor2
```

---

## 10. Vendor Supervisors — Hardware Layer

### BaseVendorSupervisor

**File:** `vendors/common/base_vendor_supervisor.py`

Abstract base class for all VS. Provides:
- ROS 2 wiring: `cmd_sub`, `ack_pub`, `status_pub`
- JSON parsing and validation of incoming commands
- HMAC verification (warn-only in phases 1–5)
- `publish_ack()` and `publish_status()` helpers
- Base `TaskRunner` for optional use by subclasses
- Base `InternalBus` (for internal inter-adapter use)
- Abstract interface `handle_task(cmd) → (accepted, reason)`

### TaskRunner

**File:** `vendors/common/task_runner.py`

Executes hardware functions in a daemon thread. Does not block the ROS 2 thread. Provides `is_running()`, `run(task_fn, on_complete, on_error)` and `join()`.

### NiryoConveyorAdapter

**File:** `vendors/niryo/niryo_conveyor_adapter.py`

Manages a Niryo belt with IR sensors:
- `run_until_exit_sensor()`: starts the belt, polls sensors until the exit sensor activates, stops the belt. On timeout: **stops the physical hardware before raising TimeoutError** (important fix).
- `poll_sensors()`: reads all configured pins, compares with `_last_sensor_states`, emits only changes. Returns list of dicts with `sensor_id, state, raw, pin, active_low`.
- `initialize()`: initialises belt, stops, forces sensor read with `force=True`.

**Pin logic:**
```python
raw_value = driver.read_digital_io(cfg["pin"])
active_low = cfg.get("active_low", True)   # true for these sensors
occupied = not raw_value if active_low else raw_value
```

### NiryoVendorSupervisor — Autonomous Sensor Polling

```python
# Timer every 200 ms (hardware mode only)
def _poll_sensors_once(self):
    for conveyor in self.conveyors.values():
        updates = conveyor.poll_sensors(self._publish_auto_sensor)

def _publish_auto_sensor(self, sensor_id, state):
    self.get_logger().info(f"[sensor] {sensor_id} → {state}")
    self.publish_status(command_id="AUTO", task="SENSOR_UPDATE", ...)
```

Each sensor change appears in terminal:
```
[sensor] c1s2 → OCCUPIED
[sensor] c1s1 → FREE
```

To see the raw pin level:
```bash
ros2 run shipyard_pnp niryo_vendor_supervisor --ros-args \
     --log-level niryo_vendor_supervisor:=DEBUG
```

### LocalVisionAdapter (robot1 and robot2)

**File:** `vendors/niryo/local_vision_adapter.py`

Subscribes to the Niryo compressed video topic (`/robot2/niryo_robot_vision/compressed_video_stream`). Takes N captures (default: 15) with configurable timeout (8 s) and detection threshold (0.03). In dry_run returns the colour configured in `vision_default_color`.

### Robot2Adapter

**File:** `vendors/niryo/robot2_adapter.py`

Implements `capture_local_vision()` and `move_piece(source, target)`. Internally orchestrates vision_adapter and robot2_niryo_vacuum_adapter in the correct sequence. Robot2 and its resources share the same TaskRunner in the VS.

### Robot1Adapter

**File:** `vendors/niryo/robot1_adapter.py`

Implements `classify_and_goto_pick(position)`, `lift_and_place(target)`, `move_home()`. Coordinates internally with vision_robot1. Uses the Arduino vacuum externally (the FS serialises the calls).

### XArm1Adapter / XArm2Adapter

**Files:** `vendors/ufactory/xarm1_adapter.py`, `vendors/ufactory/xarm2_adapter.py`

Wrapping of the Lite6 driver. XArm1 implements `move_piece(source, target, route)` for routes C1S2→LASER_BED, LASER_BED→C2S1, C1S2→C2S1. XArm2 implements `move_piece(pick_slot, target)` for INITIAL_STACK→C1S1 and INITIAL_STACK→C3.

### Lite6ServiceDriver

**File:** `vendors/ufactory/lite6_service_driver.py`

Low-level driver for UFACTORY Lite6 via ROS 2 service calls (`xarm_api`). In dry_run simulates realistic timing without moving hardware.

### GlobalVisionCameraAdapter

**File:** `vendors/globalvision/camera_adapter.py`

OpenCV + SlotInventory. Detects pieces in the initial stack. `LOCATE_NEXT_PIECE` returns `slot_id`, `colour`, `shape` for the next piece to be processed.

---

## 11. Internal Trackers

### StateTracker

**File:** `factory/state_tracker.py`

Coarse state table for all resources. Not thread-safe — protected by `FactorySupervisor._state_lock`.

Categories: robots, conveyors, sensors, machines, vacuum, vision, domain_online.

Method `apply_resource_state(resource_id, state_str)`: used by `on_status()` to dispatch incoming resource_state updates.

### PieceTracker

**File:** `factory/piece_tracker.py`

Single source of truth for the location of all pieces. Uses `deque` per location. Locations:

```
initial_stack → xarm2_gripper → c3_location → conveyor1 → xarm1_gripper →
laser_bed → conveyor2 → robot2_gripper → c4_location → bantam_bed →
robot1_gripper → final_red_stack / final_blue_stack / final_green_stack /
               final_red_circle / final_blue_circle / final_green_circle /
               robot1_scrap / robot2_scrap
```

`all_pieces_finished()`: True when initial_stack is empty AND all intermediate locations are empty (sinks excluded).

Each `transfer_piece()` calls `db.insert_piece_transfer()`.

### CycleTracker

**File:** `factory/cycle_tracker.py`

Measures cycle time per piece. `start_cycle(piece_id)` when xArm2 deposits at c1s1. `complete_cycle(piece_id, color, shape, route)` when robot1 completes the final deposit.

Provides `get_throughput_last_n(20)` in pieces/hour and `snapshot()` with statistics.

---

## 12. Configuration

### hardware_ports.yaml

Main hardware configuration file at `src/shipyard_pnp/config/hardware_ports.yaml`.

Each VS loads its corresponding section, searching first at the source path (`../../../config/hardware_ports.yaml` relative to the VS) and then in the ament share.

### factory_layout.yaml

Defines pipeline locations and per-colour routes. Not loaded at runtime (it is architecture documentation), but the planner logic implements it faithfully.

### vendor_registry.yaml

Defines the resources per domain. Reference for understanding what each VS manages.

### topic_acl.yaml

Whitelist of allowed topics per domain (for security auditing).

### globalvision_rois.yaml

Region of Interest configuration for the global camera. Example available in `globalvision_rois.example.yaml`.

---

## 13. System Startup

### Build

```bash
cd /home/isecapstone/shipyard_pnp_ws
colcon build --packages-select shipyard_pnp
source install/setup.bash
```

### Launch Full System (hardware)

```bash
ros2 launch shipyard_pnp pnp_full_system.launch.py \
    niryo_mode:=hardware \
    ufactory_mode:=hardware \
    globalvision_camera_device:=/dev/video0 \
    globalvision_show_window:=false
```

### Launch in Simulation Mode (dry_run)

```bash
ros2 launch shipyard_pnp pnp_full_system.launch.py \
    niryo_mode:=dry_run \
    ufactory_mode:=dry_run
```

### Launch Individual Vendor Supervisors

```bash
ros2 launch shipyard_pnp vendor_niryo.launch.py
ros2 launch shipyard_pnp vendor_ufactory.launch.py
ros2 launch shipyard_pnp vendor_globalvision.launch.py
ros2 launch shipyard_pnp vendor_green_conveyors.launch.py
```

### IR Sensor Diagnostics (raw level)

```bash
ros2 run shipyard_pnp niryo_vendor_supervisor \
    --ros-args --log-level niryo_vendor_supervisor:=DEBUG
```

### Monitor Sensors in Real Time

```bash
ros2 topic echo /niryo_factory/status | grep SENSOR_UPDATE
```

### Send Optimised Order Externally

```bash
ros2 topic pub /supervisor/set_optimized_order std_msgs/msg/String \
    '{"data": "{\"order\": [\"piece-001\", \"piece-003\", \"piece-002\"]}"}'
```

---

## 14. Database

### Architecture

`factory/db_writer.py` provides two writers:
- `StubDBWriter` — log-only, used in unit tests and offline runs (no DB required)
- `RealDBWriter` — live PostgreSQL, active in production

### Remote PostgreSQL Connection

Connection via environment variables (defaults shown):

```bash
PGHOST=100.118.157.20
PGUSER=juan_lopez
PGPASSWORD=twin2025
PGPORT=5432
PGDATABASE=digital_twin_db
PGSCHEMA=remote_database_capstone
```

The `RealDBWriter` bootstraps automatically on first run: creates the schema and all tables with `CREATE … IF NOT EXISTS`. All DB calls are wrapped in `try/except` so a network failure never crashes the factory.

### Schema Tables

| Table | Description |
|---|---|
| `production_run` | One row per system startup: run_id, initial stack, git commit, start/end timestamps |
| `piece` | One row per piece: colour, shape, position in initial stack |
| `piece_transfer` | Every location change: piece_id, from/to, timestamp |
| `piece_outcome` | Final disposition: route, final location, total time |
| `cycle_event` | Complete cycle per piece: start/end, cycle_time_s, route, colour, shape |
| `robot_task` | Every robot command: command_id, robot_id, task, source, target, duration, result |
| `machine_job` | Laser and Bantam jobs: door times, processing duration, result |
| `vision_detection` | Every vision call: system, detected colour/shape, slot_id, duration |
| `resource_state_change` | State transitions for every resource with dwell time |
| `queue_depth_sample` | Periodic snapshot of pieces per location |
| `command` / `ack` / `status` | Full DDS message log (every command, ack and status published) |
| `optimizer_result` | Optimizer runs: original vs best order, time saving, method, permutations evaluated |
| `alarm` | Raised/resolved alarms with severity and context snapshot |
| `operator_event` | Manual operator actions (order applied, system start/stop) |

### Activating RealDBWriter

In `factory_supervisor.py`, replace:
```python
self.db = StubDBWriter()
```
with:
```python
self.db = RealDBWriter(initial_stack_order=self._initial_stack)
```

The dashboard reads the same DB for its analytics panel (cycle times, throughput, last N cycles).

---

## 15. SimPy Production Order Optimizer

**File:** `nodes/shipyard_sim.py` (simulation core) + `nodes/dashboard_node.py` (optimizer thread)

### Purpose

Before starting production, the operator can run the optimizer from the dashboard. It finds the piece processing order that minimises total production time by simulating all permutations (or a heuristic subset for large stacks) using a SimPy discrete-event model of the full factory.

### How It Works

1. Operator clicks **Run Optimizer** on the dashboard.
2. A background thread starts (`_run_optimizer_thread`).
3. For each candidate permutation of the initial stack:
   - A full SimPy simulation of the factory is run (xArm2, conveyors, laser, robot2, bantam, robot1 — all modelled with realistic durations from `Config`).
   - Total production time is recorded.
4. The best permutation is returned with estimated time saving vs. the original order.
5. Operator sees the result and clicks **Confirm & Apply** to publish the optimized order to `/supervisor/set_optimized_order`.

### Enumeration Strategy

| Stack size | Method |
|---|---|
| ≤ 8 pieces | All permutations (`itertools.permutations`) |
| > 8 pieces | Heuristic candidates: sort by colour groups (GREEN first, then RED, then BLUE), plus random shuffles |

### SimPy Config Timings (seconds)

| Resource | Key durations |
|---|---|
| xArm2 | pick=2.5, place C1S1=6.5, place C3=9.5 |
| Conveyor 1 | transport=6.0 |
| Conveyor 2 | transport=9.0 |
| xArm1 | pick C1S2=2.5+4.0, place laser=10.5, place C2S1=11.0 |
| Laser | heating=30.0, processing=23.5 |
| Robot2 | vision=3.0–13.5, pick C2S2=8.0, place C4=16.0 |
| Bantam | close door=10.0, machining=25.0, open door=14.0 |
| C3 station | 10.0 |
| C4 station | 12.0 |
| Robot1 | vision=13.0, pick=8.5, place final=10.0 |

### Dashboard Integration

- Progress is polled via `GET /api/optimize_status` (returns `status`, `progress`, `total`, `best_so_far`, `result`).
- On completion the result is shown: best order, estimated time, saving vs. original.
- `POST /api/start_production` publishes the order to ROS 2 and starts the FS.
- The optimizer result is also logged to the `optimizer_result` DB table.

---

## 16. Resolved Bugs

### Bug 1 — xArm1 did not pick the next RED piece from c1s2

**Symptom:** xArm1 waited for the previous piece to reach c2s2 before going to pick the next red piece at c1s2.

**Cause:** `processing_rules.evaluate()` checked `c2s1 != FREE → return` before evaluating colour. For RED pieces (going to the laser, not c2s1), this check was incorrect.

**Fix:** The c2s1 check is now only applied to non-RED pieces. The `LASER_DONE_WAITING_C2S1` state was added for the post-laser moment.

---

### Bug 2 — conveyor2 with ~22 s delay

**Symptom:** Conveyor2 did not start until ~22 s after robot2 picked the piece.

**Cause:** The old code cleared c2s2=FREE only when robot2 completed the deposit at c4, not when it picked from c2s2. The physical sensor took ~14 s more to change.

**Fix:** The `_c2s2_committed` flag allows conveyor2 to start immediately when robot2 confirms it will pick, without falsifying the physical sensor state.

---

### Bug 3 — c1s1=OCCUPIED when physically FREE (critical bug)

**Symptom:** xArm2 only processed 1 of 4 pieces. c1s1 remained permanently OCCUPIED. 30 s timeout on conveyor1 with no piece.

**Cause:** Race condition timeline:
```
t=0:  hardware c1s1 → OCCUPIED  (piece deposited)
t=0:  conveyor1 starts immediately
t=2:  hardware c1s1 → FREE  (piece at c1s2)
t=3:  _on_xarm2_to_c1_complete() fires (LATE)
t=3:  wrote fs.state.update_sensor("c1s1", OCCUPIED)  ← stale!
t=3:  conveyor adapter _last_sensor_states["c1s1"] is already "FREE"
      never re-emits the correction
t=33: conveyor1 timeout → xArm2 blocked permanently
```

**Fix:** Completely removed `fs.state.update_sensor("c1s1", SensorState.OCCUPIED)` from `_on_xarm2_to_c1_complete`. The IR sensor already handles (or will handle) reporting the correct state.

---

### Bug 4 — conveyor timeout did not stop the physical motor

**Symptom:** On timeout in `run_until_exit_sensor()`, the belt motor continued running physically.

**Fix:** Added `driver.control_conveyor(control_on=False)` call before raising `TimeoutError`.

---

### Bug 5 — c1s1 missing from periodic state log

**Symptom:** The `[state]` log showed c1s2, c2s1, c2s2, c4 but not c1s1.

**Fix:** Added `c1s1={self.state.get_sensor('c1s1').name}` to the log format string.

---

### Bug 6 — evaluate_rules() not triggered on sensor changes

**Symptom:** The planner took up to 500 ms to react to IR sensor changes.

**Fix:** `on_status()` now fires `evaluate_rules()` immediately if `task_state` is terminal OR if `_apply_sensor_result()` detected a sensor change (`sensor_updated=True`):
```python
trigger = terminal or sensor_updated
if trigger:
    self.evaluate_rules()
```

---

## 17. Current Status and Pending Work

### Implemented and Functional

- [x] Full Plug-and-Plan architecture with 7 domains
- [x] Command/Ack/Status protocol with correlation by command_id
- [x] HMAC infrastructure with strict enforcement (AclGuard, 4-gate check)
- [x] Sequential domain initialisation with retry
- [x] RED, BLUE, GREEN routes fully implemented and verified on hardware
- [x] Sovereign sensors — c1s1/c1s2/c2s1/c2s2 hardware-only
- [x] Virtual sensors c3/c4 written by logic
- [x] `_c2s2_committed` flag for conveyor2 without delay
- [x] `LASER_DONE_WAITING_C2S1` state for xArm1 post-laser
- [x] Immediate rule trigger on sensor change
- [x] `[sensor] {id} → {STATE}` log on every change
- [x] Periodic state log every 10 s (includes c1s1)
- [x] Raw pin log at DEBUG
- [x] Conveyor timeout stops motor before raising error
- [x] PieceTracker with full location history
- [x] CycleTracker with throughput and statistics
- [x] RealDBWriter active — remote PostgreSQL, 14-table schema, auto-bootstrap
- [x] Settle time guards for c3 (10 s) and c4 (14.5 s)
- [x] Robot1 with local vision and destination by colour+shape (includes CIRCLE)
- [x] Robot2 with local vision at c2s2
- [x] Bantam CNC with ZMQ door and fallback to SCRAP
- [x] Conveyor3 and Conveyor4 Arduino with timer auto-stop
- [x] GlobalVision with optional preview
- [x] xArm1 and xArm2 in hardware mode (UFACTORY Lite6)
- [x] xArm2 parallel to xArm1 (independent TaskRunners in UFactory VS)
- [x] Robot1 parallel to robot2 (independent TaskRunners in Niryo VS)
- [x] Watchdog timeouts on all domains
- [x] Dashboard node — HTTP port 8080, live topology, camera streams, DB analytics
- [x] SimPy optimizer — finds optimal piece order before production starts

### Pending / Not Implemented

- [ ] **Full BLUE route with real Bantam** — Bantam door ZMQ tested but full end-to-end run pending
- [ ] **LASER_DONE_WAITING_C2S1 multi-piece stress test** — path verified in single-piece runs, not yet stress-tested with 4+ RED pieces in parallel pipeline
- [ ] **dashboard_node — DB analytics panel** — live cycle table functional; historical charts (matplotlib/chart.js) not yet implemented
