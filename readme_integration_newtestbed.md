# mujoco_pkg — Digital Twin Integration Guide

ROS 2 MuJoCo digital twin for a manufacturing testbed. The package mirrors real hardware (robotic arms, conveyors, Bantam CNC, laser engraver) into a live MuJoCo simulation driven entirely by ROS topics.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Installation & Build](#installation--build)
5. [ROS Topics](#ros-topics)
6. [Configuration File](#configuration-file)
7. [Executables](#executables)
8. [Running the Digital Twin](#running-the-digital-twin)
9. [Stimulators (Testing without Hardware)](#stimulators-testing-without-hardware)
10. [DB Replay (PostgreSQL Telemetry)](#db-replay-postgresql-telemetry)
11. [Scene Files](#scene-files)
12. [Component Types](#component-types)
13. [Vacuum Gripper — How It Works](#vacuum-gripper--how-it-works)
14. [Viewer Keyboard Shortcuts](#viewer-keyboard-shortcuts)
15. [Adding a New Component Type](#adding-a-new-component-type)

---

## Overview

`mujoco_pkg` is a ROS 2 (ament_python) package that subscribes to live hardware topics and drives a MuJoCo physics simulation as a real-time digital twin. It supports:

| Hardware | Model |
|---|---|
| 6-DOF robotic arms | xArm Lite 6 (×2), Niryo Ned2 (×2) |
| Conveyors | 2 main + 2 small |
| CNC machine | Bantam CNC (door actuation) |
| Laser engraver | XY-axis positioning |
| Vision system | Stack/slot occupancy via JSON topic |

Parts (pick-and-place targets) are procedurally injected at startup using coordinates defined in the config YAML. Vacuum grippers use MuJoCo site-based weld constraints for snap-free grabbing.

---

## Architecture

```
Real Hardware / MES
        │
        │  ROS 2 topics
        ▼
 ┌─────────────────────┐
 │   DigitalTwin Node  │  twin_node_5.py
 │                     │
 │  Subscribers:       │
 │   JointState ──────►│──► robot joint ctrl[]
 │   String    ──────►│──► conveyor / CNC / laser / vacuum
 │   String(JSON)────►│──► stack part placement
 │                     │
 │  Sim thread:        │
 │   mj_step() 100 Hz  │
 │   viewer.sync()     │
 └─────────────────────┘
        │
        ▼
  MuJoCo Viewer (passive)
```

The node runs MuJoCo in a dedicated daemon thread. All ROS callbacks only write data into a shared dict; the simulation timer (`0.01 s`) reads that dict and applies it to `mjData` before each `mj_step()`.

---

## Prerequisites

| Requirement | Version |
|---|---|
| ROS 2 | Humble or newer |
| Python | 3.10+ |
| MuJoCo | 3.3.7 (see `requirements.txt`) |
| numpy | 2.x |
| PyYAML | 6.x |
| psycopg2 | Only for `db_replay` |

Install Python dependencies (inside your virtual env or system-wide):

```bash
pip install mujoco numpy pyyaml
# Only if using db_replay:
pip install psycopg2-binary
```

---

## Installation & Build

```bash
cd ~/ros2_ws
colcon build --packages-select mujoco_pkg
source install/setup.bash
```

All MuJoCo XML scene files and YAML configs are installed automatically under
`share/mujoco_pkg/mujoco/` via the recursive data installer in `setup.py`.

---

## ROS Topics

### Subscribed Topics (production config — `twin_pickup.yaml`)

#### Robot Joint States — `sensor_msgs/JointState`

| Topic | Robot |
|---|---|
| `/xarm1/joint_states` | xArm Lite 6 (position 1) |
| `/xarm2/joint_states` | xArm Lite 6 (position 2) |
| `/robot1/joint_states` | Niryo Ned2 (position 1) |
| `/robot2/joint_states` | Niryo Ned2 (position 2) |

The `position[]` array maps to MuJoCo `ctrl[]` at the indices listed under `joint_indices` in the config.

#### Vacuum Gripper — `std_msgs/String`

| Topic | Robot | Grab value | Release value |
|---|---|---|---|
| `/xarm1/vacuum_state` | xArm 1 | `"ON"` | `"OFF"` |
| `/xarm2/vacuum_state` | xArm 2 | `"ON"` | `"OFF"` |
| `/robot1/vacuum_state` | Niryo 1 | `"ON"` | `"OFF"` |
| `/robot2/vacuum_state` | Niryo 2 | `"ON"` | `"OFF"` |

Alternatively, a `std_msgs/Bool` topic can be used — `True` = grab, `False` = release. Configured via `pickup_status` / `release_status` in the YAML (see [Configuration File](#configuration-file)).

#### Machine Status — `std_msgs/String`

| Topic | Device | Relevant values |
|---|---|---|
| `/factory/conveyor_1/status` | Main conveyor 1 | `"RUNNING"`, `"STOPPED"` |
| `/factory/conveyor_2/status` | Main conveyor 2 | `"RUNNING"`, `"STOPPED"` |
| `/factory/conveyor_small/status` | Small conveyors | `"RUNNING"`, `"STOPPED"` |
| `/bantam/door_state` | Bantam CNC door | `"OPEN"`, `"MOVING_TO_OPEN"`, anything else = closed |
| `/laser/status` | Laser engraver | `"IDLE"`, `"FINISHED"` = home; anything else = engrave |

#### Vision / Stack State — `std_msgs/String` (JSON)

| Topic | Description |
|---|---|
| `/stack_status` | JSON payload mapping slot keys (`"s1.1"` … `"s3.6"`) to part descriptors (`"red_square"`, `"green_circle"`, `null`) |

Example payload:
```json
{
  "s1.1": "red_square",
  "s1.2": "green_circle",
  "s2.1": null
}
```

### Published Topics

This package does **not** publish any topics by default. It is a pure subscriber / simulation driver.

> The stimulator nodes (`twin_stimulator`, `twin_stimulator_3`) publish all the topics listed above for testing purposes.

---

## Configuration File

The digital twin is fully config-driven. The default config is:

```
share/mujoco_pkg/mujoco/config/twin_pickup.yaml
```

You can pass a custom config path as a command-line argument (see [Running the Digital Twin](#running-the-digital-twin)).

### Config Structure

```yaml
scene:
  file: "final_scene.xml"          # Scene XML relative to share/mujoco_pkg/mujoco/

stack_status_topic: "/stack_status" # Topic for vision slot updates (std_msgs/String JSON)

stacks:
  euler: [0, 0.36, 0]              # Shared orientation for all spawned parts
  stack1:
    slots:
      1: [x, y, z]                 # World-frame position of each slot
      2: [x, y, z]
      # ... up to slot 6

parts:
  mass: 0.10                        # kg, applied to all parts
  items:
    - name: part_A
      stack: 1                      # which stack (1-3)
      slot: 1                       # which slot (1-6)
      color: red                    # red | green | blue
      shape: square                 # square | cylinder

components:
  xarm_1:
    type: robot
    topic: "/xarm1/joint_states"
    joint_indices: [6, 7, 8, 9, 10, 11]  # MuJoCo ctrl[] indices
    vacuum_topic: "/xarm1/vacuum_state"   # optional — omit if no gripper
    vacuum_body: xarm1_link6              # MuJoCo body name that owns gripper geom
    gripper_site: xarm1_end_effector      # MuJoCo site name (weld anchor)
    grab_radius: 0.07                     # metres — proximity threshold for grab
    pickup_status: "ON"                   # String value(s) that trigger grab
    release_status: "OFF"                 # String value(s) that trigger release

  conveyor_1:
    type: conveyor
    topic: "/factory/conveyor_1/status"
    joint_indices: [24]
    run_status: "RUNNING"
    stop_status: "STOPPED"
    speed: -0.65                          # ctrl value when running

  bantam_cnc:
    type: bantam_cnc
    topic: "/bantam/door_state"
    joint_indices: [31]
    open_status: ["OPEN", "MOVING_TO_OPEN"]

  laser_engraver:
    type: laser_engraver
    topic: "/laser/status"
    joint_indices: [26, 27]               # [x_axis, y_axis]
    home_status: ["IDLE", "FINISHED"]
    home_coordinates: [0.265, 0.305]      # ctrl values at home

  small_conveyor_1:
    type: conveyor
    topic: "/factory/conveyor_small/status"
    joint_indices: [32]
    run_status: "RUNNING"
    speed: 0.0588
    always_on: true                       # runs continuously, ignores topic
```

### Vacuum Topic — Bool vs. String

| Scenario | Config |
|---|---|
| Simple bool | Set `vacuum_topic`, omit `pickup_status` / `release_status` → expects `std_msgs/Bool` |
| Hardware status string | Set `pickup_status` and/or `release_status` → expects `std_msgs/String` |

---

## Executables

| Executable | Source | Description |
|---|---|---|
| `twin_node_5` | `twin_node_5.py` | **Production** digital twin node (full feature set) |
| `twin_node_4` | `twin_node_4.py` | Previous generation twin node |
| `twin_node_3` | `twin_node_3.py` | Earlier iteration |
| `twin_node_2` | `twin_node_2.py` | Earlier iteration |
| `twin_node` | `twin_node.py` | Minimal prototype (no config, no scene) |
| `twin_node_debug` | `twin_node_debug.py` | Debug variant |
| `twin_stimulator_3` | `twin_stimulator_3.py` | Config-driven random stimulator |
| `twin_stimulator_2` | `twin_stimulator_2.py` | Earlier stimulator |
| `twin_stimulator` | `twin_stimulator.py` | Simple stimulator (hardcoded 2 robots, 1 conveyor) |
| `pick_place_test` | `pick_place_test.py` | Scripted pick-and-place sequence test |

> **Use `twin_node_5` for all new integrations.** The earlier nodes are kept for reference.

---

## Running the Digital Twin

```bash
# Default config (twin_pickup.yaml + final_scene.xml)
ros2 run mujoco_pkg twin_node_5

# Custom config
ros2 run mujoco_pkg twin_node_5 /absolute/path/to/my_config.yaml
```

The MuJoCo passive viewer opens automatically. Close it to shut down the node.

---

## Stimulators (Testing without Hardware)

Use the stimulators to verify the twin responds correctly before connecting real hardware.

```bash
# Config-driven stimulator (reads twin_config.yaml by default)
ros2 run mujoco_pkg twin_stimulator_3

# Simple stimulator — publishes random JointState on robot_0/joint_states,
# robot_1/joint_states and random Int32 on conveyor_0
ros2 run mujoco_pkg twin_stimulator
```

The stimulators publish at 10 Hz with small random incremental joint movements.

---

## DB Replay (PostgreSQL Telemetry)

`db_replay` reads historical telemetry from a PostgreSQL database and re-publishes it on the same ROS topics the twin subscribes to, enabling offline session replay.

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PGHOST` | `100.115.213.16` | PostgreSQL host |
| `PGUSER` | `twin_mes_db` | Database user |
| `PGPASSWORD` | `postgres` | Database password |
| `PGPORT` | `5432` | Database port |
| `PGDATABASE` | `twin_mes_db` | Database name |
| `PGSCHEMA` | `public` | Schema name |

### Database Tables Expected

| Table | Content |
|---|---|
| `xarm1_joint_telemetry` | Joint positions/velocities/efforts |
| `xarm2_joint_telemetry` | same |
| `robot1_joint_telemetry` | same |
| `robot2_joint_telemetry` | same |
| `conveyor1_status` | String status column `status` |
| `conveyor2_status` | same |
| `bantam_door_status` | same |
| `laser_status` | same |
| `xarm1_vacuum_state` | same |
| `xarm2_vacuum_state` | same |
| `robot1_vacuum_state` | same |
| `robot2_vacuum_state` | same |
| `vision_slot_snapshot` | Columns `s1_1` … `s3_6` per slot |

All tables must have a `ts` column (`timestamptz`) and optionally a `run_id` column.

### Usage

```bash
# Interactive mode
python3 mujoco_pkg/db_replay.py

# By time window
python3 mujoco_pkg/db_replay.py --start "2026-04-15 20:30:00-04" --end "2026-04-15 20:50:00-04"

# By run ID
python3 mujoco_pkg/db_replay.py --run-id "run_20260415_001"

# 2× speed
python3 mujoco_pkg/db_replay.py --run-id "run_20260415_001" --speed 2.0

# Custom DB
python3 mujoco_pkg/db_replay.py --db-host myserver --db-name prod_db --run-id "run_001"
```

---

## Scene Files

Located in `resource/mujoco/` (installed to `share/mujoco_pkg/mujoco/`):

| File | Description |
|---|---|
| `final_scene.xml` | **Production scene** — full testbed with all components |
| `mvp3_scene.xml` | MVP3 scene (earlier version) |
| `bantam_test.xml` | Isolated Bantam CNC test |
| `pickup_test.xml` | Pick-and-place test setup |
| `placement_test.xml` | Part placement test |

### Component XML Fragments (`resources/xml/components/`)

| File | Description |
|---|---|
| `xarmlite6.xml` | xArm Lite 6 arm model |
| `xarm5.xml` | xArm5 arm model |
| `niryo_arm.xml` | Niryo Ned2 arm model |
| `conveyor.xml` | Main conveyor model |
| `small_conveyor.xml` | Small conveyor model |
| `bantam_cnc.xml` | Bantam CNC model |
| `laser_engraver.xml` | Laser engraver model |
| `slot_table.xml` | Slot table model |
| `item_stack.xml` | Item stack model |
| `ir_sensor.xml` | IR sensor model |
| `vision_plate.xml` | Vision plate model |
| `table.xml` | Workbench table model |
| `sub_module.xml` / `sub_module_v2.xml` | Modular substation models |

---

## Component Types

### `robot`

Drives a 6-DOF arm by writing `msg.position[i]` into `data.ctrl[joint_indices[i]]`.

Required fields: `topic`, `joint_indices`
Optional fields: `vacuum_topic`, `vacuum_body`, `gripper_site`, `grab_radius`, `pickup_status`, `release_status`

### `conveyor`

Sets `data.ctrl[jid]` to `speed` when the topic string matches `run_status`, otherwise `0.0`.
A position-reset mechanism prevents the conveyor slide joint from drifting past 1 cm.

Required fields: `topic`, `joint_indices`, `run_status`, `speed`
Optional: `always_on: true` — runs at `speed` every tick without waiting for a topic message.

### `bantam_cnc`

Controls a door joint. Sets ctrl to `0` (open) when the topic string matches any value in `open_status`, otherwise sets it to `2.75` (closed).

Required fields: `topic`, `joint_indices`, `open_status`

### `laser_engraver`

Controls X and Y axis joints. Sends to `home_coordinates` when status matches `home_status`, otherwise sends `[0, 0]`.

Required fields: `topic`, `joint_indices`, `home_status`, `home_coordinates`

---

## Vacuum Gripper — How It Works

The vacuum gripper uses **MuJoCo site-based weld constraints**. This is the correct MuJoCo approach for attaching a part at the gripper's current pose without snapping.

### Grab sequence (runs in sim thread via `tick()`):
1. Find the nearest `part_site_i` within `grab_radius` of `gripper_site`.
2. Express the gripper site's world pose in the part body's local frame.
3. Write that local pose into `model.site_pos[part_site_id]` and `model.site_quat[part_site_id]`.
4. Set `data.eq_active[suction_weld_arm_i] = 1` — both sites already coincide, nothing moves.

### Thread safety:
- ROS callbacks (any thread) only set `_pending_activate` / `_pending_deactivate` flags.
- `tick()` is called by the simulation timer (sim thread) after every `mj_step()` — all MuJoCo reads and writes happen here with guaranteed-consistent kinematics.

### XML requirements per arm:
- A site named `gripper_site` must exist inside the gripper body in the arm XML.
- Weld constraints (`suction_weld_<arm>_<i>`) are injected automatically by `build_scene()` at startup.

---

## Viewer Keyboard Shortcuts

When the passive MuJoCo viewer is open:

| Key | Action |
|---|---|
| `G` | Activate vacuum gripper on the first arm |
| `R` | Release vacuum gripper on the first arm |
| `1` – `9` | Toggle grab/release on arm N (by config order) |

---

## Adding a New Component Type

1. Add the component definition in your YAML config under `components`.
2. Add an `elif ctype == "your_type":` branch in `_setup_subscribers()` in `twin_node_5.py` to create the subscription with the correct message type.
3. Add the corresponding `elif ctype == "your_type":` branch in `_apply_components()` to map the message data to `data.ctrl[]` or `data.qvel[]`.

---

## Package Summary

```
mujoco_pkg/
├── mujoco_pkg/
│   ├── twin_node_5.py       ← production digital twin node
│   ├── twin_node_*.py       ← earlier iterations
│   ├── twin_stimulator_3.py ← config-driven test stimulator
│   ├── twin_stimulator*.py  ← simpler stimulators
│   ├── db_replay.py         ← PostgreSQL telemetry replayer
│   ├── pick_place_test.py   ← scripted pick-and-place test
│   └── scene_viewer.py      ← standalone scene viewer
├── resource/mujoco/
│   ├── final_scene.xml      ← production scene
│   ├── config/
│   │   ├── twin_pickup.yaml ← production config (default)
│   │   └── twin_config.yaml ← basic config (no vacuum)
│   └── resources/
│       ├── xml/components/  ← arm, conveyor, CNC XML fragments
│       └── meshes/          ← STL mesh files
├── package.xml
├── setup.py
└── requirements.txt
```
