PART A — ARCHITECTURE DECISION RECORD

ADR-001 — Greenfield package, not a migration.

Decision: build a completely new ROS2 Python package under `shipyard_plug_and_plan/shipyard_pnp/`. The existing `shipyard_core/` package is reference material only. No old node file is moved into the new package. Hardware behavior is reimplemented cleanly, using the old files only to recover exact API calls, poses, serial commands, and workflow rules.

Rationale: the current tree has old nodes, copies, simulator remnants, generated files, and mixed topic eras. A greenfield package prevents old imports and flat topics from leaking into the Plug-and-Plan architecture.

ADR-002 — Correct vendor domains.

Decision: the final coordination boundary has seven vendor domains, each with exactly three northbound topics:

- `niryo`: `/niryo_factory/command`, `/niryo_factory/ack`, `/niryo_factory/status`
- `ufactory`: `/ufactory_factory/command`, `/ufactory_factory/ack`, `/ufactory_factory/status`
- `laser`: `/laser_factory/command`, `/laser_factory/ack`, `/laser_factory/status`
- `globalvision`: `/globalvision_factory/command`, `/globalvision_factory/ack`, `/globalvision_factory/status`
- `green_conveyors`: `/green_conveyors_factory/command`, `/green_conveyors_factory/ack`, `/green_conveyors_factory/status`
- `arduino_vacuum`: `/arduino_vacuum_factory/command`, `/arduino_vacuum_factory/ack`, `/arduino_vacuum_factory/status`
- `bantam`: `/bantam_factory/command`, `/bantam_factory/ack`, `/bantam_factory/status`

Equipment inside each domain:

- `niryo`: `robot1`, `robot2`, Niryo conveyors `conveyor1` and `conveyor2`, their IR sensors `c1s1`, `c1s2`, `c2s1`, `c2s2`, local robot cameras/vision `vision_robot1`, `vision_robot2`, and robot2's Niryo vacuum pump.
- `ufactory`: `xarm1`, `xarm2` only.
- `laser`: active laser machine only.
- `globalvision`: global stack camera, ROI config, slot/color/shape inventory inference.
- `green_conveyors`: handmade/Arduino conveyors 3 and 4, currently represented by green conveyor channels A/B.
- `arduino_vacuum`: handmade Arduino vacuum used by robot1.
- `bantam`: Bantam CNC and its door controller interface.

Rationale: UFactory does not own the laser. Global vision is a camera/inference vendor. Conveyors 3/4 are not Niryo conveyors. Robot1 and robot2 vacuum behavior is different and must not be flattened.

ADR-003 — Resource identity is mandatory.

Decision: every coordination command, ACK, and status includes both `domain_id` and `resource_id`. The `command_id` is unique and readable:

`CMD-{domain_id}-{resource_id}-{YYYYMMDDTHHMMSSffffffZ}-{seq}`

Examples:

- `CMD-niryo-robot1-20260617T183000123456Z-000001`
- `CMD-niryo-robot2-20260617T183001123456Z-000002`
- `CMD-ufactory-xarm1-20260617T183002123456Z-000003`
- `CMD-ufactory-xarm2-20260617T183003123456Z-000004`
- `CMD-green_conveyors-conveyor3-20260617T183004123456Z-000005`

Routing never depends only on the free-text task. `domain_id` selects the vendor supervisor topic; `resource_id` selects the internal resource inside the vendor domain.

ADR-004 — Vacuum split.

Decision: robot2's Niryo vacuum is internal to the `niryo` domain and is controlled by the `niryo_vendor_supervisor` as part of robot2 tasks. Robot1's handmade Arduino vacuum is a separate `arduino_vacuum` vendor domain and is coordinated explicitly by the Factory Supervisor when robot1 needs pick/release.

Rationale: the code confirms this split. `robot1_node.py` uses `SetBool`/`Trigger` services for the Arduino vacuum. `robot2_node.py` uses Niryo `ToolCommand` services for the robot-attached vacuum.

ADR-005 — Local vision vs global vision.

Decision: robot-local vision stays inside `niryo` because it is part of robot1/robot2 task execution. Global vision is a separate vendor domain because it observes the initial stack and provides system-level inventory/slot facts.

Boundary rule:

- Allowed from `globalvision` to Factory Supervisor: normalized inventory facts such as `slot_id`, `color`, `shape`, `occupancy`, `confidence_class`, and `scan_id`.
- Forbidden: raw image frames, ROI pixel coordinates, HSV thresholds, masks, contours, ML logits, model paths.

ADR-006 — Rules are rewritten, not moved.

Decision: the old rule files are reference documents. The new package implements fresh planner modules that preserve the workflow semantics but do not import `shipyard_core.supervisor.rules.*`.

Rationale: importing old rules drags old state names, flat topics, and hidden assumptions into the new architecture.

ADR-007 — No incremental migration sequence.

Decision: the sequence is a greenfield build sequence. Old and new systems do not run as one mixed production graph. Hardware adapters may be tested one at a time, but the new package must never depend on old topic names as its public API.

ADR-008 — Concurrency model: MultiThreadedExecutor + ReentrantCallbackGroup.

Decision: the Factory Supervisor ROS2 node uses a `MultiThreadedExecutor` with four callback groups:
- `ack_status_cbg = ReentrantCallbackGroup()`: all seven ack subscribers + all seven status subscribers (14 subscribers total). These callbacks are short — they parse JSON, update pending_commands table, and call evaluate_rules() — so reentrant is safe.
- `planner_cbg = MutuallyExclusiveCallbackGroup()`: the 0.5s planner timer that calls `evaluate_rules()`. Mutual exclusion prevents two planner evaluations from running concurrently.
- `watchdog_cbg = MutuallyExclusiveCallbackGroup()`: the 1.0s timeout watchdog timer.
- `dashboard_cbg = MutuallyExclusiveCallbackGroup()`: the 2.0s system_state publisher timer.

All shared state inside the FS (pending_commands dict, state_tracker, piece_tracker) is protected by a single `threading.Lock` called `_state_lock`. Every method that reads or writes shared state must acquire this lock. The lock is held for the minimum time necessary — never across a ROS2 publish call.

Vendor Supervisor nodes each use a `SingleThreadedExecutor` (one per VS process). Each VS has one command subscriber and runs hardware operations in a dedicated `TaskRunner` thread so the ROS2 executor is never blocked.

Rationale: ReentrantCallbackGroup on ack/status callbacks allows the FS to receive concurrent ACKs from multiple vendors without head-of-line blocking. The planner and watchdog use MutuallyExclusiveCallbackGroup to prevent race conditions on the shared state they read and write.

Reference: old `supervisor.py` used a single-threaded `create_timer(1.0, periodic_evaluation)` which serialized everything. The new model is safe because `_state_lock` protects all mutations.

ADR-009 — Local vision color/shape results are coordination outcomes, not proprietary data.

Decision: when the niryo VS executes a `CAPTURE_LOCAL_VISION` task, the STATUS message it sends back to the FS MAY include `result.color` and `result.shape`. These are coordination outcomes (what color piece is at this station) and are explicitly permitted to cross the coordination boundary. They are NOT proprietary data (not HSV thresholds, not pixel coordinates, not camera calibration matrices).

This resolves the apparent contradiction between Theorem 3 (proprietary confinement) and the FS needing to know piece color to make routing decisions. The paper's Definition 6 defines completion reporting as one of the three coordination semantics. A color classification result IS a completion report — it reports what the task found. The forbidden data is internal implementation state, not task outcomes.

Boundary rule for niryo CAPTURE_LOCAL_VISION STATUS:
- Allowed: `{"code": "VISION_RESULT_READY", "color": "RED", "shape": "CIRCLE", "confidence": "HIGH"}`
- Forbidden: `{"hsv_range": [...], "roi_pixels": [...], "model_path": "...", "raw_frame_b64": "..."}`

The FS uses `result.color` and `result.shape` to update `piece_tracker` and then run classification routing. The local camera's internal workings (OpenCV pipeline, HSV thresholds, calibration YAML) stay entirely inside the niryo domain.

Rationale: without this decision, the FS cannot route pieces by color, which is the core production logic. The alternative (niryo VS making routing decisions internally) would require the VS to know the full production workflow, making it impossible to substitute niryo hardware without rewriting production logic — which violates Theorem 4.

ADR-010 — Robot1 arduino vacuum is orchestrated explicitly by the Factory Supervisor.

Decision: because `arduino_vacuum` is a separate vendor domain and vendor domains cannot communicate directly with each other, the FS must sequence robot1's arm movements and vacuum activations as separate commands on two separate vendor channels. The FS `unloading_rules.py` implements the following four-step sequence for every robot1 pick-and-place:

Step 1: FS sends `GOTO_PICK_POSITION` to `niryo/robot1` with `parameters.position = C4` (or C3). Robot1 arm moves to the pre-pick pose over the target and holds. Status returns `AT_PICK_POSITION`.
Step 2: FS sends `PICK` to `arduino_vacuum/arduino_vacuum`. Vacuum activates. Status returns `PICK_DONE`.
Step 3: FS sends `LIFT_AND_PLACE` to `niryo/robot1` with `parameters.target = FINAL_RED_STACK` (or whichever final destination). Robot1 lifts piece, moves to place position, lowers. Status returns `AT_PLACE_POSITION`.
Step 4: FS sends `RELEASE` to `arduino_vacuum/arduino_vacuum`. Vacuum releases. Status returns `RELEASE_DONE`.
Step 5: FS sends `RETURN_HOME` to `niryo/robot1`. Status returns `IDLE`.

This sequence is strictly serialized — each step waits for the previous STATUS before sending the next command. The `pending_commands` table and `evaluate_rules()` implement this via a state machine stored in `piece_tracker` per-piece.

Tasks added to niryo/robot1 contract: `GOTO_PICK_POSITION`, `LIFT_AND_PLACE`, `RETURN_HOME`.
Tasks already in arduino_vacuum contract: `PICK`, `RELEASE`, `OFF`.

Rationale: the alternative (embedding vacuum coordination inside niryo VS) would require the niryo VS to publish to `/arduino_vacuum_factory/command`, creating a direct domain-to-domain edge that violates Theorem 2 (fault containment). The explicit FS orchestration is the structurally correct solution.

ADR-011 — HMAC authentication is implemented but not enforced in Phases 1-5.

Decision: every command, ACK, and status message includes `nonce` and `auth` fields. `auth` is an HMAC-SHA256 hex digest of `{command_id}:{nonce}:{task}:{issued_at}` using a shared secret per domain pair. Secrets are stored in `config/hmac_secrets.yaml` (gitignored). In Phases 1 through 5, the receiver logs a warning if HMAC validation fails but does not reject the message. In Phase 6 (full integration), HMAC validation is enforced and invalid messages are dropped.

Key distribution: each VS reads its own secret from `config/hmac_secrets.yaml` at startup. The FS reads all secrets. Secrets are 32-byte random hex strings generated once and stored in the config. This is a research testbed; production deployment would use DDS Security with cryptographic key infrastructure.

Reference: `shared/time_ids.py` provides `make_nonce()`. `shared/messages.py` provides `sign_message(payload, secret)` and `verify_message(payload, secret)`.

PART B — COMPLETE GREENFIELD FILE MANIFEST

Package root:

- `shipyard_plug_and_plan/README.md` — NEW
- `shipyard_plug_and_plan/package.xml` — NEW
- `shipyard_plug_and_plan/setup.py` — NEW
- `shipyard_plug_and_plan/setup.cfg` — NEW
- `shipyard_plug_and_plan/resource/shipyard_pnp` — NEW

Launch:

- `shipyard_plug_and_plan/launch/pnp_full_system.launch.py` — NEW
- `shipyard_plug_and_plan/launch/pnp_sim_smoke.launch.py` — NEW
- `shipyard_plug_and_plan/launch/vendor_niryo.launch.py` — NEW
- `shipyard_plug_and_plan/launch/vendor_ufactory.launch.py` — NEW
- `shipyard_plug_and_plan/launch/vendor_laser.launch.py` — NEW
- `shipyard_plug_and_plan/launch/vendor_globalvision.launch.py` — NEW
- `shipyard_plug_and_plan/launch/vendor_green_conveyors.launch.py` — NEW
- `shipyard_plug_and_plan/launch/vendor_arduino_vacuum.launch.py` — NEW
- `shipyard_plug_and_plan/launch/vendor_bantam.launch.py` — NEW

Config:

- `shipyard_plug_and_plan/config/vendor_registry.yaml` — NEW
- `shipyard_plug_and_plan/config/topic_acl.yaml` — NEW
- `shipyard_plug_and_plan/config/factory_layout.yaml` — NEW
- `shipyard_plug_and_plan/config/resources.yaml` — NEW
- `shipyard_plug_and_plan/config/globalvision_rois.example.yaml` — NEW
- `shipyard_plug_and_plan/config/hardware_ports.yaml` — NEW

Shared:

- `shipyard_plug_and_plan/shipyard_pnp/__init__.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/shared/__init__.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/shared/contracts.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/shared/messages.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/shared/topic_acl.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/shared/time_ids.py` — NEW

Factory coordination:

- `shipyard_plug_and_plan/shipyard_pnp/factory/__init__.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/factory/factory_supervisor.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/factory/vendor_client.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/factory/state_tracker.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/factory/piece_tracker.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/factory/cycle_tracker.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/factory/system_state_publisher.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/factory/db_writer.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/factory/planner/__init__.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/factory/planner/initialization_rules.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/factory/planner/feeding_rules.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/factory/planner/processing_rules.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/factory/planner/classification_rules.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/factory/planner/unloading_rules.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/factory/planner/conveyor_rules.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/factory/planner/shutdown_rules.py` — NEW

Vendor common:

- `shipyard_plug_and_plan/shipyard_pnp/vendors/__init__.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/common/__init__.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/common/base_vendor_supervisor.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/common/internal_bus.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/common/task_runner.py` — NEW

Niryo vendor:

- `shipyard_plug_and_plan/shipyard_pnp/vendors/niryo/__init__.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/niryo/niryo_vendor_supervisor.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/niryo/robot1_adapter.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/niryo/robot2_adapter.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/niryo/niryo_conveyor_adapter.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/niryo/niryo_ir_adapter.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/niryo/local_vision_adapter.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/niryo/robot2_niryo_vacuum_adapter.py` — NEW

UFactory vendor:

- `shipyard_plug_and_plan/shipyard_pnp/vendors/ufactory/__init__.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/ufactory/ufactory_vendor_supervisor.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/ufactory/xarm1_adapter.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/ufactory/xarm2_adapter.py` — NEW

Laser vendor:

- `shipyard_plug_and_plan/shipyard_pnp/vendors/laser/__init__.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/laser/laser_vendor_supervisor.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/laser/laser_adapter.py` — NEW

Global vision vendor:

- `shipyard_plug_and_plan/shipyard_pnp/vendors/globalvision/__init__.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/globalvision/globalvision_vendor_supervisor.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/globalvision/camera_adapter.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/globalvision/slot_inventory.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/globalvision/calibrator.py` — NEW

Green conveyors vendor:

- `shipyard_plug_and_plan/shipyard_pnp/vendors/green_conveyors/__init__.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/green_conveyors/green_conveyors_vendor_supervisor.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/green_conveyors/shared_arduino_driver.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/green_conveyors/conveyor3_adapter.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/green_conveyors/conveyor4_adapter.py` — NEW

Arduino vacuum vendor:

- `shipyard_plug_and_plan/shipyard_pnp/vendors/arduino_vacuum/__init__.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/arduino_vacuum/arduino_vacuum_vendor_supervisor.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/arduino_vacuum/arduino_vacuum_driver.py` — NEW

Bantam vendor:

- `shipyard_plug_and_plan/shipyard_pnp/vendors/bantam/__init__.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/bantam/bantam_vendor_supervisor.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/bantam/bantam_adapter.py` — NEW
- `shipyard_plug_and_plan/shipyard_pnp/vendors/bantam/door_adapter.py` — NEW

Observability/UI:

- `shipyard_plug_and_plan/shipyard_pnp/nodes/dashboard_node.py` — NEW
- `shipyard_plug_and_plan/test/test_messages.py` — NEW
- `shipyard_plug_and_plan/test/test_acl.py` — NEW
- `shipyard_plug_and_plan/test/test_vendor_registry.py` — NEW
- `shipyard_plug_and_plan/test/test_resource_routing.py` — NEW
- `shipyard_plug_and_plan/test/test_proprietary_confinement.py` — NEW
- `shipyard_plug_and_plan/test/test_greenfield_no_old_imports.py` — NEW

PART C — FILE-BY-FILE IMPLEMENTATION SPECIFICATION

1. `shared/contracts.py`

Purpose: defines the clean, boundary-safe vocabulary. It does not contain old microstates like `APPROACHING_C4_ROBOT2`.

Classes:

- `class DomainId`: `NIRYO`, `UFACTORY`, `LASER`, `GLOBALVISION`, `GREEN_CONVEYORS`, `ARDUINO_VACUUM`, `BANTAM`
- `class ResourceId`: `ROBOT1`, `ROBOT2`, `CONVEYOR1`, `CONVEYOR2`, `VISION_ROBOT1`, `VISION_ROBOT2`, `ROBOT2_NIRYO_VACUUM`, `XARM1`, `XARM2`, `LASER`, `GLOBALVISION_CAMERA`, `CONVEYOR3`, `CONVEYOR4`, `ARDUINO_VACUUM`, `BANTAM`, `BANTAM_DOOR`
- `class TaskState`: `RECEIVED`, `RUNNING`, `COMPLETED`, `FAILED`, `REJECTED`, `TIMEOUT`, `CANCELED`
- `class RobotState`: `NOT_INITIALIZED`, `INITIALIZING`, `IDLE`, `GOING_TO_POSITION`, `WAITING_FOR_VISION`, `PICKING`, `PICK_DONE`, `PLACING`, `PLACE_DONE`, `RETURNING_HOME`, `ERROR`
- `class ConveyorState`: `STOPPED`, `RUNNING`, `ERROR`
- `class SensorState`: `FREE`, `OCCUPIED`, `ERROR`, `UNKNOWN`
- `class VisionState`: `IDLE`, `SCANNING`, `PROCESSING`, `RESULT_READY`, `ERROR`
- `class VacuumState`: `IDLE`, `PICKING`, `PICK_DONE`, `RELEASING`, `RELEASE_DONE`, `ERROR`
- `class MachineState`: `NOT_INITIALIZED`, `IDLE`, `PREPARING`, `WORKING`, `FINISHED`, `WAITING_PICKUP`, `ERROR`
- `class TaskName`: all public coordination tasks listed below.

Boundary tasks by domain:

- `niryo`: `INITIALIZE_DOMAIN`, `MOVE_ROBOT`, `MOVE_PIECE`, `CAPTURE_LOCAL_VISION`, `RUN_NIRYO_CONVEYOR`, `STOP_NIRYO_CONVEYOR`, `READ_IR_SENSOR`
- `ufactory`: `INITIALIZE_DOMAIN`, `MOVE_PIECE`, `MOVE_XARM_HOME`
- `laser`: `INITIALIZE_DOMAIN`, `PREPARE_JOB`, `RUN_JOB`, `RESET`
- `globalvision`: `SCAN_STACK`, `LOCATE_NEXT_PIECE`, `GET_INVENTORY`
- `green_conveyors`: `RUN_CONVEYOR`, `STOP_CONVEYOR`, `SET_SPEED`, `RESET`
- `arduino_vacuum`: `PICK`, `RELEASE`, `OFF`
- `bantam`: `GET_READY`, `RUN_JOB`, `RESET`, `OPEN_DOOR`, `CLOSE_DOOR`

2. `shared/messages.py`

Purpose: builds and validates all `std_msgs/String` JSON payloads. This fixes the old command ID ambiguity.

Command schema:

```json
{
  "schema": "shipyard.pnp.command.v1",
  "command_id": "CMD-niryo-robot1-20260617T183000123456Z-000001",
  "correlation_id": "CYCLE-PIECE_001-0001",
  "sender_id": "factory_supervisor",
  "domain_id": "niryo",
  "resource_id": "robot1",
  "task": "MOVE_PIECE",
  "piece_id": "PIECE_001",
  "source": "C3",
  "target": "FINAL_RED_STACK",
  "route": "C3_TO_FINAL_RED",
  "parameters": {
    "shape_policy": "MATCH_FINAL_SLOT"
  },
  "issued_at": "2026-06-17T18:30:00.123456Z",
  "nonce": "hex",
  "auth": "hmac-sha256-hex"
}
```

ACK schema:

```json
{
  "schema": "shipyard.pnp.ack.v1",
  "command_id": "CMD-niryo-robot1-20260617T183000123456Z-000001",
  "correlation_id": "CYCLE-PIECE_001-0001",
  "sender_id": "niryo_vendor_supervisor",
  "domain_id": "niryo",
  "resource_id": "robot1",
  "accepted": true,
  "reason": null,
  "accepted_at": "2026-06-17T18:30:00.223456Z",
  "nonce": "hex",
  "auth": "hmac-sha256-hex"
}
```

Status schema:

```json
{
  "schema": "shipyard.pnp.status.v1",
  "command_id": "CMD-niryo-robot1-20260617T183000123456Z-000001",
  "correlation_id": "CYCLE-PIECE_001-0001",
  "sender_id": "niryo_vendor_supervisor",
  "domain_id": "niryo",
  "resource_id": "robot1",
  "task": "MOVE_PIECE",
  "task_state": "COMPLETED",
  "resource_state": "PLACE_DONE",
  "piece_id": "PIECE_001",
  "source": "C3",
  "target": "FINAL_RED_STACK",
  "route": "C3_TO_FINAL_RED",
  "result": {
    "code": "OK"
  },
  "published_at": "2026-06-17T18:30:07.223456Z",
  "nonce": "hex",
  "auth": "hmac-sha256-hex"
}
```

Forbidden boundary keys:

- `joint`, `joint_states`, `angle`, `servo`, `register`, `gpio`, `pin`, `raw_image`, `image`, `frame`, `hsv`, `mask`, `contour`, `roi_pixels`, `gcode_line`, `serial_bytes`, `tool_torque`, `motor_current`

Allowed globalvision semantic result:

```json
{
  "code": "INVENTORY_READY",
  "scan_id": "SCAN-0001",
  "slots": [
    {"slot_id": "s1.1", "occupied": true, "color": "RED", "shape": "CIRCLE"}
  ]
}
```

3. `config/vendor_registry.yaml`

Purpose: single source of truth for domains/resources.

Required content:

```yaml
domains:
  niryo:
    supervisor_node: niryo_vendor_supervisor
    resources:
      robot1: {type: robot, model: niryo_ned2}
      robot2: {type: robot, model: niryo_ned2, internal_vacuum: robot2_niryo_vacuum}
      conveyor1: {type: niryo_conveyor, ir_sensors: [c1s1, c1s2]}
      conveyor2: {type: niryo_conveyor, ir_sensors: [c2s1, c2s2]}
      vision_robot1: {type: local_camera, owner_robot: robot1}
      vision_robot2: {type: local_camera, owner_robot: robot2}
      robot2_niryo_vacuum: {type: niryo_tool, owner_robot: robot2}
  ufactory:
    resources:
      xarm1: {type: robot, model: lite6}
      xarm2: {type: robot, model: lite6}
  laser:
    resources:
      laser: {type: machine}
  globalvision:
    resources:
      globalvision_camera: {type: camera}
  green_conveyors:
    resources:
      conveyor3: {type: arduino_conveyor, channel: A}
      conveyor4: {type: arduino_conveyor, channel: B}
  arduino_vacuum:
    resources:
      arduino_vacuum: {type: serial_vacuum, owner_robot: robot1}
  bantam:
    resources:
      bantam: {type: cnc}
      bantam_door: {type: door}
```

4. `config/topic_acl.yaml`

Purpose: proves the graph. Factory Supervisor publishes only command topics and subscribes only ack/status. Each vendor subscribes only its command topic and publishes only its ack/status topics.

Required ACL:

```yaml
nodes:
  factory_supervisor:
    publishes:
      - /niryo_factory/command
      - /ufactory_factory/command
      - /laser_factory/command
      - /globalvision_factory/command
      - /green_conveyors_factory/command
      - /arduino_vacuum_factory/command
      - /bantam_factory/command
      - /factory/system_state
    subscribes:
      - /niryo_factory/ack
      - /niryo_factory/status
      - /ufactory_factory/ack
      - /ufactory_factory/status
      - /laser_factory/ack
      - /laser_factory/status
      - /globalvision_factory/ack
      - /globalvision_factory/status
      - /green_conveyors_factory/ack
      - /green_conveyors_factory/status
      - /arduino_vacuum_factory/ack
      - /arduino_vacuum_factory/status
      - /bantam_factory/ack
      - /bantam_factory/status
  niryo_vendor_supervisor:
    subscribes: [/niryo_factory/command]
    publishes: [/niryo_factory/ack, /niryo_factory/status]
  ufactory_vendor_supervisor:
    subscribes: [/ufactory_factory/command]
    publishes: [/ufactory_factory/ack, /ufactory_factory/status]
  laser_vendor_supervisor:
    subscribes: [/laser_factory/command]
    publishes: [/laser_factory/ack, /laser_factory/status]
  globalvision_vendor_supervisor:
    subscribes: [/globalvision_factory/command]
    publishes: [/globalvision_factory/ack, /globalvision_factory/status]
  green_conveyors_vendor_supervisor:
    subscribes: [/green_conveyors_factory/command]
    publishes: [/green_conveyors_factory/ack, /green_conveyors_factory/status]
  arduino_vacuum_vendor_supervisor:
    subscribes: [/arduino_vacuum_factory/command]
    publishes: [/arduino_vacuum_factory/ack, /arduino_vacuum_factory/status]
  bantam_vendor_supervisor:
    subscribes: [/bantam_factory/command]
    publishes: [/bantam_factory/ack, /bantam_factory/status]
```

5. `factory/vendor_client.py`

Purpose: one instance per vendor domain, owned by the FS. Holds the ROS2 publisher for that domain's command topic, tracks the current pending command for that domain, and provides `send_command()` used by the FS. It is a plain Python class (not a ROS2 Node). The FS creates seven VendorClient instances at startup and stores them in `self.vendor_clients: Dict[str, VendorClient]`.

Class definition:

```python
@dataclass
class PendingCommand:
    command_id: str
    correlation_id: str
    domain_id: str
    resource_id: str
    task: str
    piece_id: Optional[str]
    source: Optional[str]
    target: Optional[str]
    parameters: dict
    issued_at: float        # time.time() when command was sent
    ack_received: bool = False
    ack_at: Optional[float] = None
    status_received: bool = False
    last_task_state: Optional[str] = None
    last_result: Optional[dict] = None
    on_complete: Optional[Callable[[str, dict], None]] = None
    # on_complete(task_state, result) called when STATUS arrives

class VendorClient:
    def __init__(self, domain_id: str, publisher: Publisher):
        self.domain_id = domain_id
        self.publisher = publisher
        self.pending: Optional[PendingCommand] = None
        self.domain_online: bool = False
        self.last_ack_time: Optional[float] = None
        self.last_status_time: Optional[float] = None

    def is_busy(self) -> bool:
        return self.pending is not None

    def send_command(self, resource_id, task, piece_id=None, source=None,
                     target=None, route=None, parameters=None,
                     correlation_id=None, on_complete=None) -> str:
        # Builds command JSON, publishes, stores PendingCommand, returns command_id.
        # Raises RuntimeError if self.pending is not None (caller must check is_busy first).
        ...

    def on_ack_received(self, ack_payload: dict):
        # Called by FS on_ack callback. Marks pending.ack_received = True.
        ...

    def on_status_received(self, status_payload: dict):
        # Called by FS on_status callback.
        # Sets pending.last_task_state, pending.last_result.
        # If task_state in (COMPLETED, FAILED, REJECTED, TIMEOUT):
        #   calls pending.on_complete(task_state, result)
        #   sets self.pending = None
        ...

    def check_timeout(self, ack_timeout_sec=5.0, status_timeout_sec=120.0):
        # Called by FS watchdog timer every 1.0s.
        # If pending and not ack_received and (now - issued_at) > ack_timeout_sec:
        #   calls on_complete("TIMEOUT", {"reason": "ACK_TIMEOUT"})
        #   sets pending = None
        #   logs ERROR
        # If pending and ack_received and not status_received and
        #   (now - ack_at) > status_timeout_sec:
        #   same but reason = "STATUS_TIMEOUT"
        ...
```

Per-task status timeouts (override default 120s where needed):
- `INITIALIZE_DOMAIN`: 30s
- `SCAN_STACK`: 15s
- `LOCATE_NEXT_PIECE`: 10s
- `RUN_JOB` (laser): 300s
- `RUN_JOB` (bantam): 600s
- `GOTO_PICK_POSITION`, `LIFT_AND_PLACE`, `RETURN_HOME`: 60s each
- `MOVE_PIECE` (xarm): 45s
- `RUN_NIRYO_CONVEYOR`: 30s
- `PICK` / `RELEASE` (vacuum): 5s

Old reference: old `supervisor.py` had no explicit timeout mechanism — `periodic_evaluation` would re-evaluate and re-send commands, causing duplicate commands. `VendorClient.check_timeout()` replaces that antipattern.

6. `factory/state_tracker.py`

Purpose: tracks the current coarse state of every resource, every sensor, and every domain's online/offline status. Uses only the simplified state vocabulary from `contracts.py`. It does NOT track piece locations — that is `piece_tracker.py`. It does NOT track timing or cycles — that is `cycle_tracker.py`.

Data structures:

```python
class StateTracker:
    # Resource states — keyed by resource_id string
    robots: Dict[str, RobotState]       # robot1, robot2, xarm1, xarm2
    conveyors: Dict[str, ConveyorState] # conveyor1, conveyor2, conveyor3, conveyor4
    sensors: Dict[str, SensorState]     # c1s1, c1s2, c2s1, c2s2, c3, c4
    machines: Dict[str, MachineState]   # laser, bantam
    vacuum: Dict[str, VacuumState]      # arduino_vacuum
    vision: Dict[str, VisionState]      # vision_robot1, vision_robot2, globalvision_camera

    # Domain-level online status (True = responding, False = degraded/offline)
    domain_online: Dict[str, bool]      # keyed by domain_id

    # Last time each resource changed state
    state_since: Dict[str, float]       # keyed by resource_id, value = time.time()
```

Initial values at `__init__`:
- All robots: `RobotState.NOT_INITIALIZED`
- All conveyors: `ConveyorState.STOPPED`
- All sensors: `SensorState.UNKNOWN`
- All machines: `MachineState.NOT_INITIALIZED`
- vacuum: `VacuumState.IDLE`
- vision: `VisionState.IDLE`
- All domain_online: `False`

Methods:

```python
def update_robot(self, resource_id: str, state: RobotState): ...
def update_conveyor(self, resource_id: str, state: ConveyorState): ...
def update_sensor(self, resource_id: str, state: SensorState): ...
def update_machine(self, resource_id: str, state: MachineState): ...
def update_vacuum(self, resource_id: str, state: VacuumState): ...
def update_vision(self, resource_id: str, state: VisionState): ...
def set_domain_online(self, domain_id: str, online: bool): ...

def get_robot(self, resource_id: str) -> RobotState: ...
def get_sensor(self, resource_id: str) -> SensorState: ...
def is_domain_online(self, domain_id: str) -> bool: ...
def all_initialized(self) -> bool:
    # Returns True when all robots are IDLE and all domains are online.
    # Used by planner to gate production start.
    ...
def snapshot(self) -> dict:
    # Returns a JSON-serializable dict of all states, used by system_state_publisher.
    ...
```

Mapping from old `state_tracker.py`: the old file's `self.robots`, `self.sensors`, `self.conveyor`, `self.machines`, `self.vision` maps directly. The difference: the new file uses the simplified state enums from the new `contracts.py` instead of the 80+ microstates. The new file has NO pipeline queues (those move to `piece_tracker.py`). The new file has NO `BUSY_PENDING` anti-state (that was a coordination hack in the old system, eliminated by the three-channel protocol).

7. `factory/piece_tracker.py`

Purpose: owns all pipeline_queues (piece locations through the production line). Calls `db_writer.insert_piece_transfer()` on every `transfer_piece()`. The only class in the factory layer that knows about piece locations.

Pipeline locations list (same as old system, verified from old `state_tracker.py`):

```python
PIPELINE_LOCATIONS = [
    "initial_stack",       # physical slot in the ASRS/stack — source
    "xarm2_gripper",       # piece held by xarm2 in transit
    "c3_location",         # C3 sensor position (secondary entry, robot1 can pick here)
    "conveyor1",           # on conveyor1 belt between C1S1 and C1S2
    "xarm1_gripper",       # piece held by xarm1 in transit
    "laser_bed",           # piece on laser machine bed
    "conveyor2",           # on conveyor2 belt between C2S1 and C2S2
    "robot2_gripper",      # piece held by robot2 in transit (Niryo vacuum)
    "c4_location",         # C4 sensor position (input for robot1)
    "bantam_bed",          # piece on Bantam CNC bed
    "intermediate_blue_stack",  # IBS — buffer for blue pieces waiting for bantam
    "robot1_gripper",      # piece held by robot1 in transit (arduino vacuum)
    "final_red_stack",     # output
    "final_blue_stack",    # output
    "final_green_stack",   # output
    "robot1_scrap",        # scrap output for robot1
    "robot2_scrap",        # scrap output for robot2
]
```

Piece data structure (same as old system):

```python
piece = {
    "id": "PIECE_001",
    "color": "RED",          # None until vision assigns it
    "shape": "CIRCLE",       # None until vision assigns it
    "slot_id": "s2.4",       # set when globalvision locates the piece
    "timestamp_created": 1718640000.0,
    "current_location": "initial_stack",
    "history": [
        {"location": "initial_stack", "timestamp": ..., "color": None, "shape": None}
    ]
}
```

Methods:

```python
def __init__(self, initial_stack_order: List[str], db_writer): ...
    # Creates pieces from initial_stack_order same as old _initialize_initial_pieces()

def transfer_piece(self, from_loc: str, to_loc: str) -> bool:
    # Pops first piece from from_loc queue, appends to to_loc queue.
    # Calls db_writer.insert_piece_transfer(piece, from_loc, to_loc).
    # Returns False if from_loc is empty.
    # Logs warning if from_loc empty — does NOT raise exception.

def assign_slot(self, slot_id: str):
    # Called when globalvision returns slot_id for next piece.
    # Updates the first piece in initial_stack with slot_id.

def assign_color_shape(self, location: str, color: str, shape: str):
    # Called when local vision returns color+shape.
    # Updates first piece at location with color and shape.

def peek_first_piece(self, location: str) -> Optional[dict]: ...
def peek_first_piece_color(self, location: str) -> Optional[str]: ...
def peek_first_piece_shape(self, location: str) -> Optional[str]: ...
def count(self, location: str) -> int: ...
def total_pieces_in_system(self) -> int: ...
def all_pieces_finished(self) -> bool:
    # True when initial_stack is empty AND all intermediate locations are empty.

def snapshot(self) -> dict:
    # Returns JSON-serializable dict of all non-empty queues with piece summaries.
```

Old reference: identical to `StateTracker.pipeline_queues` in old `state_tracker.py`. The split into its own class removes it from the monolithic StateTracker.

8. `factory/cycle_tracker.py`

Purpose: records timing for each production cycle (one piece from initial_stack to final_stack). Provides throughput metrics for the dashboard.

```python
@dataclass
class CycleRecord:
    piece_id: str
    color: str
    shape: str
    started_at: float       # when xarm2 picks from initial_stack
    completed_at: float     # when robot1 places at final stack
    cycle_time_sec: float   # completed_at - started_at
    route: str              # e.g. "RED_VIA_LASER", "GREEN_DIRECT", "BLUE_VIA_BANTAM"

class CycleTracker:
    def __init__(self): ...

    def start_cycle(self, piece_id: str): ...
    def complete_cycle(self, piece_id: str, color: str, shape: str, route: str): ...
    def get_throughput_last_n(self, n: int) -> float:
        # Returns pieces/hour based on last n completed cycles.
    def snapshot(self) -> dict:
        # Returns dict with completed_count, avg_cycle_time_sec, throughput_per_hour,
        # last_completed_piece_id, and list of last 5 cycle records.
```

Old reference: mirrors `CycleTracker` in old `supervisor/cycle_tracker.py`. Simplified — no longer needs to compensate for missing BUSY_PENDING state.

9. `factory/system_state_publisher.py`

Purpose: a helper class (not a Node) owned by the FS. Called by the FS's 2.0s timer. Builds the `/factory/system_state` JSON and publishes it.

```python
class SystemStatePublisher:
    def __init__(self, publisher: Publisher,
                 state_tracker: StateTracker,
                 piece_tracker: PieceTracker,
                 cycle_tracker: CycleTracker,
                 vendor_clients: Dict[str, VendorClient]): ...

    def publish(self):
        payload = {
            "schema": "shipyard.pnp.system_state.v1",
            "published_at": iso_now(),
            "domains": {
                domain_id: {
                    "online": vc.domain_online,
                    "busy": vc.is_busy(),
                    "last_ack": vc.last_ack_time,
                    "pending_command_id": vc.pending.command_id if vc.pending else None,
                }
                for domain_id, vc in vendor_clients.items()
            },
            "resources": {
                "robots": {k: v.value for k, v in state_tracker.robots.items()},
                "conveyors": {k: v.value for k, v in state_tracker.conveyors.items()},
                "sensors": {k: v.value for k, v in state_tracker.sensors.items()},
                "machines": {k: v.value for k, v in state_tracker.machines.items()},
                "vacuum": {k: v.value for k, v in state_tracker.vacuum.items()},
                "vision": {k: v.value for k, v in state_tracker.vision.items()},
            },
            "pipeline": piece_tracker.snapshot(),
            "cycles": cycle_tracker.snapshot(),
        }
        msg = String()
        msg.data = json.dumps(payload)
        self.publisher.publish(msg)
```

Dashboard subscription: `dashboard_node.py` subscribes to `/factory/system_state` and republishes as `/dashboard/state`. The old `build_dashboard_snapshot()` in `supervisor.py` is replaced entirely by this publisher.

10. `factory/db_writer.py`

Purpose: synchronous PostgreSQL writer. Imported by `piece_tracker.py`. Not a ROS2 node. Schema and methods specified in Part G of this document.

11. `factory/factory_supervisor.py`

Purpose: MES-level coordinator. It owns production planning, piece tracking, cycles, DB writes, dashboard system state, and command correlation. It never talks to `/robot1/command`, `/xarm1/command`, `/laser/command`, `/globalvision/command`, `/conveyorA/command`, or `/vacuum`.

Full class structure:

```python
class FactorySupervisor(Node):
    def __init__(self):
        super().__init__('factory_supervisor')

        # Callback groups (see ADR-008)
        self.ack_status_cbg = ReentrantCallbackGroup()
        self.planner_cbg = MutuallyExclusiveCallbackGroup()
        self.watchdog_cbg = MutuallyExclusiveCallbackGroup()
        self.dashboard_cbg = MutuallyExclusiveCallbackGroup()

        # Shared state lock — acquired before any read/write of the fields below
        self._state_lock = threading.Lock()

        # Core data
        self.state = StateTracker()
        self.pieces = PieceTracker(INITIAL_STACK_ORDER, db_writer)
        self.cycles = CycleTracker()

        # One VendorClient per domain
        self.vendor_clients: Dict[str, VendorClient] = {}
        self._setup_vendor_clients()

        # Planner state machine
        self.planner_phase = PlannerPhase.BOOT  # enum: BOOT, INITIALIZING, RUNNING, SHUTTING_DOWN
        self._init_domains_pending: Set[str] = set()

        # Publishers and subscribers
        self._setup_pub_sub()

        # System state publisher helper
        self.sys_state_pub = SystemStatePublisher(
            self._sys_state_ros_pub, self.state, self.pieces, self.cycles, self.vendor_clients)

        # Timers
        self.create_timer(0.5, self.evaluate_rules, callback_group=self.planner_cbg)
        self.create_timer(1.0, self.watchdog, callback_group=self.watchdog_cbg)
        self.create_timer(2.0, self.sys_state_pub.publish, callback_group=self.dashboard_cbg)

        self.get_logger().info("FactorySupervisor initialized")
```

`_setup_vendor_clients()`:
- Creates one Publisher per domain on `/{domain}_factory/command` with QoS depth=10
- Creates VendorClient for each domain, stores in `self.vendor_clients`
- `DOMAIN_IDS = ["niryo", "ufactory", "laser", "globalvision", "green_conveyors", "arduino_vacuum", "bantam"]`

`_setup_pub_sub()`:
- Creates 14 subscribers (ack + status per domain), all with `callback_group=self.ack_status_cbg`
- Each ack subscriber calls `lambda msg, d=domain_id: self.on_ack(d, msg)`
- Each status subscriber calls `lambda msg, d=domain_id: self.on_status(d, msg)`
- Creates one publisher for `/factory/system_state`
- Creates one subscriber for `/supervisor/set_optimized_order` (for dashboard optimizer integration)

`send_command(domain_id, resource_id, task, ...)`:
```python
def send_command(self, domain_id, resource_id, task,
                 piece_id=None, source=None, target=None,
                 route=None, parameters=None, correlation_id=None,
                 on_complete=None) -> str:
    with self._state_lock:
        vc = self.vendor_clients[domain_id]
        if vc.is_busy():
            raise RuntimeError(f"VendorClient {domain_id} is busy — caller must check is_busy() first")
        return vc.send_command(resource_id, task, piece_id, source, target,
                               route, parameters, correlation_id, on_complete)
```

`on_ack(domain_id, msg)`:
```python
def on_ack(self, domain_id: str, msg: String):
    try:
        payload = json.loads(msg.data)
        with self._state_lock:
            vc = self.vendor_clients[domain_id]
            vc.domain_online = True
            self.state.set_domain_online(domain_id, True)
            vc.on_ack_received(payload)
            # Update resource state to reflect command was accepted
            resource_state_from_ack = payload.get("resource_state")
            if resource_state_from_ack:
                self._apply_resource_state(domain_id, payload["resource_id"], resource_state_from_ack)
    except Exception as e:
        self.get_logger().error(f"on_ack {domain_id}: {e}")
```

`on_status(domain_id, msg)`:
```python
def on_status(self, domain_id: str, msg: String):
    try:
        payload = json.loads(msg.data)
        with self._state_lock:
            vc = self.vendor_clients[domain_id]
            vc.last_status_time = time.time()
            resource_id = payload.get("resource_id")
            resource_state = payload.get("resource_state")
            task_state = payload.get("task_state")
            result = payload.get("result", {})

            # Update coarse resource state in StateTracker
            self._apply_resource_state(domain_id, resource_id, resource_state)

            # Update piece tracker from vision results
            if result.get("color") and result.get("shape"):
                piece_loc = self._resource_to_location(resource_id)
                if piece_loc:
                    self.pieces.assign_color_shape(piece_loc, result["color"], result["shape"])

            # Forward to VendorClient (calls on_complete callback if terminal state)
            vc.on_status_received(payload)

        # Trigger planner immediately after terminal status
        if task_state in ("COMPLETED", "FAILED", "REJECTED"):
            self.evaluate_rules()

    except Exception as e:
        self.get_logger().error(f"on_status {domain_id}: {e}")
```

`_apply_resource_state(domain_id, resource_id, resource_state)`:
- Maps resource_id to the correct StateTracker.update_*() call
- E.g., resource_id="robot1" → `self.state.update_robot("robot1", RobotState(resource_state))`
- E.g., resource_id="conveyor1" → `self.state.update_conveyor("conveyor1", ConveyorState(resource_state))`
- Handles unknown resource_id with a warning log

`watchdog()`:
```python
def watchdog(self):
    with self._state_lock:
        for domain_id, vc in self.vendor_clients.items():
            vc.check_timeout()
```

`evaluate_rules()` — the planner dispatcher:
```python
def evaluate_rules(self):
    with self._state_lock:
        if self.planner_phase == PlannerPhase.BOOT:
            initialization_rules.evaluate(self)
        elif self.planner_phase == PlannerPhase.RUNNING:
            feeding_rules.evaluate(self)
            conveyor_rules.evaluate(self)
            processing_rules.evaluate(self)
            classification_rules.evaluate(self)
            unloading_rules.evaluate(self)
            if self.pieces.all_pieces_finished():
                self.planner_phase = PlannerPhase.SHUTTING_DOWN
        elif self.planner_phase == PlannerPhase.SHUTTING_DOWN:
            shutdown_rules.evaluate(self)
```

Each planner module receives `self` (the FS instance) and reads `self.state`, `self.pieces`, `self.cycles`, `self.vendor_clients` directly. They call `self.send_command(...)` to issue commands.

Subscriptions:

- `/{domain}_factory/ack` for all seven domains — `ReentrantCallbackGroup`
- `/{domain}_factory/status` for all seven domains — `ReentrantCallbackGroup`
- `/supervisor/set_optimized_order` — `MutuallyExclusiveCallbackGroup`

Publications:

- `/{domain}_factory/command` for all seven domains
- `/factory/system_state`

Old reference: replaces `supervisor.py`'s `SupervisorNode`. The old `setup_publishers()` / `setup_subscribers()` is replaced by `_setup_vendor_clients()` and `_setup_pub_sub()`. The old `periodic_evaluation()` → `evaluate_rules()`. The old `publish_dashboard_snapshot()` → `sys_state_pub.publish()`.

12. `factory/planner/initialization_rules.py`

Purpose: brings all seven domains online in dependency order. Called by `evaluate_rules()` when `planner_phase == BOOT`.

Boot order (each step waits for COMPLETED before sending the next):
1. `arduino_vacuum` — smallest risk hardware; confirm serial port responds.
2. `green_conveyors` — confirm Arduino driver responds.
3. `globalvision` — must initialize before any feeding can start.
4. `ufactory` — xArm1 and xArm2 must home before use.
5. `niryo` — robot1, robot2, Niryo conveyors must home before use. Largest domain, longest init.
6. `laser` — warm-up sequence if needed.
7. `bantam` — last because it is only needed for blue pieces.

Rule logic (Python pseudocode, caller passes FS instance `fs`):

```python
def evaluate(fs: FactorySupervisor):
    vc_map = fs.vendor_clients

    # If no init started yet, send first INITIALIZE_DOMAIN
    if not fs._init_domains_pending and not all(fs.state.domain_online.values()):
        _send_if_idle(fs, "arduino_vacuum", "arduino_vacuum", "INITIALIZE_DOMAIN",
                      on_complete=_make_init_callback(fs, "arduino_vacuum", next_domain="green_conveyors"))
        fs._init_domains_pending.add("arduino_vacuum")
        return

def _send_if_idle(fs, domain_id, resource_id, task, on_complete):
    vc = fs.vendor_clients[domain_id]
    if not vc.is_busy() and not fs.state.is_domain_online(domain_id):
        fs.send_command(domain_id, resource_id, task, on_complete=on_complete)

def _make_init_callback(fs, domain_id, next_domain=None):
    def on_complete(task_state, result):
        if task_state == "COMPLETED":
            fs.state.set_domain_online(domain_id, True)
            fs.get_logger().info(f"Domain {domain_id} online")
            if next_domain:
                next_resource = DOMAIN_INIT_RESOURCE[next_domain]
                fs.send_command(next_domain, next_resource, "INITIALIZE_DOMAIN",
                                on_complete=_make_init_callback(fs, next_domain,
                                    next_domain=INIT_SEQUENCE.get(next_domain)))
        else:
            fs.get_logger().error(f"INIT FAILED for {domain_id}: {result}")
            # Stay in BOOT phase — watchdog will retry
    return on_complete

DOMAIN_INIT_RESOURCE = {
    "arduino_vacuum": "arduino_vacuum",
    "green_conveyors": "conveyor3",   # VS initializes conveyor3 and conveyor4 together
    "globalvision": "globalvision_camera",
    "ufactory": "xarm1",              # VS initializes xarm1 then xarm2 internally
    "niryo": "robot1",                # VS initializes all Niryo resources in order
    "laser": "laser",
    "bantam": "bantam",
}

INIT_SEQUENCE = {
    "arduino_vacuum": "green_conveyors",
    "green_conveyors": "globalvision",
    "globalvision": "ufactory",
    "ufactory": "niryo",
    "niryo": "laser",
    "laser": "bantam",
    "bantam": None,  # last — after this, transition to RUNNING
}

# After bantam COMPLETED callback:
def _bantam_init_complete(fs, task_state, result):
    if task_state == "COMPLETED":
        fs.state.set_domain_online("bantam", True)
        fs.planner_phase = PlannerPhase.RUNNING
        fs.get_logger().info("ALL DOMAINS ONLINE — production starting")
```

Old reference: see `supervisor/rules/initialization_rules.py` for the old approach. The new version adds domain-ordered sequencing and online state tracking. The old version sent INITIALIZE commands in a single timer tick without tracking acknowledgment.

13. `factory/planner/feeding_rules.py`

Purpose: moves pieces from `initial_stack` to `conveyor1` via globalvision + xarm2. Called every `evaluate_rules()` cycle when `planner_phase == RUNNING`.

Preconditions for a new feed:
- `pieces.count("initial_stack") > 0`
- `state.get_robot("xarm2") == RobotState.IDLE`
- `state.get_sensor("c1s1") == SensorState.FREE` (no piece waiting at conveyor1 entry)
- `vendor_clients["ufactory"].is_busy() == False`
- `vendor_clients["globalvision"].is_busy() == False`
- The planner is not currently in the middle of a feed sequence (tracked by `fs._feeding_state`)

Feed sequence state machine (stored as `fs._feeding_state: str`):

```
IDLE
 │
 ▼ [preconditions met]
WAITING_VISION
 │ send: globalvision/globalvision_camera LOCATE_NEXT_PIECE
 │       parameters={"color": pieces.peek_first_piece_color("initial_stack")}
 │
 ▼ [globalvision STATUS COMPLETED, result has slot_id]
WAITING_XARM2_PICK
 │ pieces.assign_slot(result["slot_id"])
 │ send: ufactory/xarm2 MOVE_PIECE
 │       parameters={"pick_slot": result["slot_id"]},
 │       source="INITIAL_STACK", target="C1S1"
 │
 ▼ [xarm2 STATUS COMPLETED, resource_state=PLACE_DONE]
 │ pieces.transfer_piece("initial_stack", "conveyor1")
 │ cycles.start_cycle(piece_id)
 │ fs._feeding_state = "IDLE"
 ▼
IDLE
```

`on_complete` callbacks for each step are closures created inside `evaluate()` that advance `fs._feeding_state` and call `evaluate_rules()` to trigger the next step.

Sensor state updates (conveyor1): handled by `conveyor_rules.py`. `feeding_rules.py` only gates on `c1s1` being FREE.

Old reference: see `supervisor/rules/feeding_rules.py`. Old version used `xarm2` commands like `"pick s2.4 RED"` — the new version uses `MOVE_PIECE` with `parameters.pick_slot` from globalvision result. The slot format `"s{col}.{row}"` is passed through as a parameter (it is a task parameter, not a proprietary implementation detail).

14. `factory/planner/conveyor_rules.py`

Purpose: manages all four conveyors. Sends `RUN_NIRYO_CONVEYOR`/`STOP_NIRYO_CONVEYOR` to niryo domain for conveyors 1 and 2. Sends `RUN_CONVEYOR`/`STOP_CONVEYOR` to green_conveyors domain for conveyors 3 and 4.

Rules for conveyor1:
- RUN if: sensor c1s1 is OCCUPIED AND conveyor1 is STOPPED AND sensor c1s2 is FREE
- STOP command is sent by niryo VS internally when c1s2 becomes OCCUPIED (sensor is inside niryo domain). The FS does NOT issue a STOP command — it sees the conveyor status become STOPPED in the next STATUS update from niryo VS.
- Wait: the niryo VS reports sensor changes as STATUS messages with `task="READ_IR_SENSOR"`, `result={"sensor_id": "c1s2", "state": "OCCUPIED"}`. The FS `on_status()` handler calls `state.update_sensor("c1s2", SensorState.OCCUPIED)`.

Rules for conveyor2: identical pattern — RUN when c2s1 OCCUPIED AND c2s2 FREE.

Rules for conveyors 3 and 4: identical logic but via `green_conveyors` vendor domain. Preconditions depend on which pieces need to use those conveyors (defined in the production workflow, see Part F).

Note on sensor updates from niryo VS: the niryo VS publishes autonomously on `/niryo_factory/status` whenever an IR sensor state changes, using `task="SENSOR_UPDATE"`, `task_state="COMPLETED"`, `result={"sensor_id": "c1s1", "state": "OCCUPIED"}`. These are not command responses — the niryo VS sends them without a preceding command from FS. The FS `on_status()` handler processes them the same way as command responses.

Old reference: see `supervisor/rules/conveyor1_rules.py` and `conveyor2_rules.py`. Old logic fired conveyor commands based on sensor events. New logic is identical in semantics, different in topic routing.

15. `factory/planner/processing_rules.py`

Purpose: manages xArm1 (processor) and laser. xArm1 moves pieces from C1S2 to either laser_bed (for RED) or C2S1 (for GREEN/BLUE). Laser runs the processing job for RED pieces.

Precondition for processing trigger:
- `state.get_sensor("c1s2") == SensorState.OCCUPIED`
- `state.get_robot("xarm1") == RobotState.IDLE`
- `vendor_clients["ufactory"].is_busy() == False`

Processing sequence by color (`color = pieces.peek_first_piece_color("conveyor1")`):

GREEN or BLUE path (direct to C2S1):
```
send: ufactory/xarm1 MOVE_PIECE source=C1S2 target=C2S1
  → on COMPLETED: pieces.transfer_piece("conveyor1", "conveyor2")
                  state.update_sensor("c1s2", SensorState.FREE)
```

RED path (via laser):
```
Step 1: send ufactory/xarm1 MOVE_PIECE source=C1S2 target=LASER_BED
  → on COMPLETED: pieces.transfer_piece("conveyor1", "laser_bed")
                  state.update_sensor("c1s2", SensorState.FREE)
                  state.update_machine("laser", MachineState.PREPARING)
Step 2: send laser/laser RUN_JOB parameters={"job_type": "RED_PROCESS"}
  → on COMPLETED: state.update_machine("laser", MachineState.FINISHED)
Step 3: send ufactory/xarm1 MOVE_PIECE source=LASER_BED target=C2S1
  → on COMPLETED: pieces.transfer_piece("laser_bed", "conveyor2")
```

State machine stored as `fs._processing_state: str` with values `IDLE / WAITING_XARM1_TO_LASER / WAITING_LASER / WAITING_XARM1_TO_C2S1 / WAITING_XARM1_DIRECT`.

Key note: the ufactory VS handles BOTH xarm1 and xarm2. Since both are in the same domain, the FS must check `vendor_clients["ufactory"].is_busy()` before sending to either. If xarm2 feed is in progress, processing must wait. This is the one domain with two resources that can generate resource contention. The VS handles it internally (it has separate task queues per resource), but the FS should not send two commands simultaneously to the same domain — the VS ACKs immediately and the FS uses one pending slot per domain.

CORRECTION to previous spec: the ufactory VS CAN handle concurrent tasks for xarm1 and xarm2 because `VendorClient.is_busy()` would block the second command. Resolution: the FS sends commands to a per-resource queue inside the VS, not a per-domain queue. This means VendorClient needs to support per-resource pending slots. Alternatively (simpler for Phase 5): serialize all ufactory commands — don't feed while processing. The planner adds gate: `_feeding_state == IDLE` as precondition for processing_rules.

Old reference: see `supervisor/rules/xarm1_rules.py`. Old commands: `PICK_C1S2_RED`, `PICK_C1S2_BLUE`, `PICK_C1S2_GREEN` → replaced by `MOVE_PIECE` with source/target parameters. Old `WAIT_LASER_C1S2_RED` state eliminated — the three-channel protocol replaces wait states with status events.

16. `factory/planner/classification_rules.py`

Purpose: captures color+shape via robot2's local camera, then routes piece to C4, BANTAM, or SCRAP.

Precondition for classification trigger:
- `state.get_sensor("c2s2") == SensorState.OCCUPIED`
- `state.get_robot("robot2") == RobotState.IDLE`
- `vendor_clients["niryo"].is_busy() == False`

Classification sequence:

```
Step 1 — CAPTURE_VISION:
  send: niryo/robot2 CAPTURE_LOCAL_VISION
        parameters={"position": "C2S2"}
  → on COMPLETED:
      color = result["color"]   # "RED", "GREEN", "BLUE", or "UNKNOWN"
      shape = result["shape"]   # "CIRCLE", "SQUARE", or "UNKNOWN"
      pieces.assign_color_shape("conveyor2", color, shape)
      → route = _decide_route(color, shape)
      → go to Step 2

def _decide_route(color, shape) -> str:
    if color == "RED":   return "C4"
    if color == "GREEN": return "C4"
    if color == "BLUE":  return "BANTAM" if state.get_machine("bantam") == MachineState.IDLE else "SCRAP"
    return "SCRAP"  # UNKNOWN color

Step 2A — route == "C4":
  send: niryo/robot2 MOVE_PIECE source=C2S2 target=C4
  → on COMPLETED (PLACE_DONE):
      pieces.transfer_piece("conveyor2", "c4_location")
      state.update_sensor("c2s2", SensorState.FREE)

Step 2B — route == "BANTAM":
  send: niryo/robot2 MOVE_PIECE source=C2S2 target=BANTAM_BED
  → on COMPLETED:
      pieces.transfer_piece("conveyor2", "bantam_bed")
      state.update_sensor("c2s2", SensorState.FREE)
      → Step 3B: send bantam/bantam RUN_JOB parameters={"job_type": "BLUE_PROCESS"}
  bantam on COMPLETED:
      state.update_machine("bantam", MachineState.FINISHED)
      → Step 4B: send niryo/robot2 MOVE_PIECE source=BANTAM_BED target=C4
      → on COMPLETED: pieces.transfer_piece("bantam_bed", "c4_location")

Step 2C — route == "SCRAP":
  send: niryo/robot2 MOVE_PIECE source=C2S2 target=SCRAP
  → on COMPLETED:
      pieces.transfer_piece("conveyor2", "robot2_scrap")
      state.update_sensor("c2s2", SensorState.FREE)
```

State machine stored as `fs._classification_state: str`.

Note on bantam coordination: bantam and niryo are separate domains. The FS sends RUN_JOB to bantam and MOVE_PIECE to niryo sequentially. During RUN_JOB, the niryo client is freed (the classification state machine waits for bantam STATUS before sending the next niryo command). There is no requirement for niryo and bantam to coordinate directly.

Old reference: see `supervisor/rules/robot2_rules.py`. Old states `PROCESS_C2S2_TO_C4`, `PROCESS_C2S2_BLUE_IBS`, `PROCESS_C2S2_BLUE_BANTAM`, `PROCESS_IBS_BLUE_BANTAM`, `PROCESS_BANTAM_BLUE_TO_C4` all collapse into the sequence above. `IBS` (intermediate_blue_stack) is omitted for now — if needed, add as a `WAITING_IBS` sub-path inside classification_rules.

17. `factory/planner/unloading_rules.py`

Purpose: coordinates robot1 + arduino_vacuum to move pieces from C4 (or C3) to final stacks. Implements the four-step arm+vacuum sequence from ADR-010.

Precondition for unloading trigger:
- `state.get_sensor("c4") == SensorState.OCCUPIED` AND `state.get_robot("robot1") == RobotState.IDLE` AND `vendor_clients["niryo"].is_busy() == False` AND `vendor_clients["arduino_vacuum"].is_busy() == False`
- OR same for C3 sensor (secondary pick point)

Unloading sequence for C4 pick:

```
color = pieces.peek_first_piece_color("c4_location")
shape = pieces.peek_first_piece_shape("c4_location")
final_target = _decide_final_target(color, shape)
  # RED → "FINAL_RED_STACK", GREEN → "FINAL_GREEN_STACK",
  # BLUE → "FINAL_BLUE_STACK", UNKNOWN → "SCRAP"

Step 1: send niryo/robot1 GOTO_PICK_POSITION parameters={"position": "C4"}
  → on COMPLETED (AT_PICK_POSITION):

Step 2: send arduino_vacuum/arduino_vacuum PICK
  → on COMPLETED (PICK_DONE):

Step 3: send niryo/robot1 LIFT_AND_PLACE parameters={"target": final_target}
  → on COMPLETED (AT_PLACE_POSITION):

Step 4: send arduino_vacuum/arduino_vacuum RELEASE
  → on COMPLETED (RELEASE_DONE):
      pieces.transfer_piece("c4_location", _target_to_location(final_target))
      state.update_sensor("c4", SensorState.FREE)

Step 5: send niryo/robot1 RETURN_HOME
  → on COMPLETED (IDLE): cycles.complete_cycle(piece_id, color, shape, route)
```

State machine stored as `fs._unloading_state: str` with values:
`IDLE / WAITING_GOTO_PICK / WAITING_VACUUM_PICK / WAITING_LIFT_PLACE / WAITING_VACUUM_RELEASE / WAITING_HOME`

Note: Steps 1-4 must be strictly serialized. Step 5 (RETURN_HOME) can be issued immediately after Step 4 completes; production can continue for other pieces while robot1 returns home.

Note on niryo domain contention: if `classification_rules` is actively using robot2, `vendor_clients["niryo"].is_busy()` will be True because VendorClient is per-domain. Per ADR in VendorClient spec, the domain must be free before a new command is sent. This means robot1 and robot2 cannot operate simultaneously — both are inside the niryo domain and share the VendorClient slot.

IMPORTANT DESIGN CONSEQUENCE: because niryo is one domain with multiple resources (robot1, robot2, conveyor1, conveyor2), and VendorClient has one pending slot, the niryo VS must internally multiplex. The FS sends one command at a time to the niryo domain, specifying `resource_id` to tell the VS which resource to use. The FS serializes at the domain level — it never sends a second command to niryo until the first command's STATUS is received. This means robot1 and robot2 cannot execute simultaneously under the current architecture. If concurrent robot1+robot2 operation is needed in future, the FS would need per-resource VendorClient slots.

Old reference: see `supervisor/rules/robot1_rules.py`. Old states `AT_CAPTURE_C4`, `GOING_TO_PICK_C4`, `START_PICKING_C4`, `PICKING_C4`, `PICKING_C4_DONE` all collapse into Step 1 (`GOTO_PICK_POSITION`). Old `APPROACHING_RED_FINAL`, `PLACING_RED_FINAL` collapse into Step 3 (`LIFT_AND_PLACE`). Arduino vacuum calls that were in `robot1_node.py` move to separate Step 2 and Step 4.

18. `factory/planner/shutdown_rules.py`

Purpose: graceful system shutdown. Called when `planner_phase == SHUTTING_DOWN`.

Shutdown sequence:
1. Send `STOP_NIRYO_CONVEYOR` to niryo for conveyor1 and conveyor2.
2. Send `STOP_CONVEYOR` to green_conveyors for conveyor3 and conveyor4.
3. Send `OFF` to arduino_vacuum.
4. Send `RETURN_HOME` to niryo/robot1 (if not already IDLE).
5. Send `RETURN_HOME` to niryo/robot2 (if not already IDLE).
6. Send `MOVE_XARM_HOME` to ufactory/xarm1.
7. Send `MOVE_XARM_HOME` to ufactory/xarm2.
8. On all homed: set `planner_phase = PlannerPhase.STOPPED`. Log "Shutdown complete."

Old reference: see `supervisor/rules/ShutdownRules.py`.

C-VENDOR-COMMON-1. `vendors/common/base_vendor_supervisor.py`

Purpose: abstract base class for all seven vendor supervisors. Provides the complete three-channel ROS2 wiring, JSON parsing, HMAC validation (warning-only in Phases 1-5), and the publish_ack / publish_status helpers. Each concrete VS extends this and implements only `handle_task()`.

```python
class BaseVendorSupervisor(Node, ABC):
    def __init__(self, domain_id: str):
        super().__init__(f"{domain_id}_vendor_supervisor")
        self.domain_id = domain_id
        self._hmac_secret = self._load_hmac_secret()

        # Three-channel ROS2 wiring
        self.cmd_sub = self.create_subscription(
            String, f"/{domain_id}_factory/command",
            self._on_command_raw, 10)
        self.ack_pub = self.create_publisher(
            String, f"/{domain_id}_factory/ack", 10)
        self.status_pub = self.create_publisher(
            String, f"/{domain_id}_factory/status", 10)

        # Task runner for executing hardware operations off-thread
        self.task_runner = TaskRunner()
        # Internal event bus for adapter → VS communication
        self.bus = InternalBus()

    def _on_command_raw(self, msg: String):
        try:
            cmd = json.loads(msg.data)
        except json.JSONDecodeError as e:
            self.get_logger().error(f"Invalid JSON: {e}")
            return
        # Validate domain
        if cmd.get("domain_id") != self.domain_id:
            self.get_logger().error(f"Wrong domain_id in command: {cmd.get('domain_id')}")
            return
        # HMAC validation (warn-only until Phase 6)
        if not verify_message(cmd, self._hmac_secret):
            self.get_logger().warning(f"HMAC mismatch on {cmd.get('command_id')}")
        # Dispatch
        try:
            accepted, reason = self.handle_task(cmd)
        except Exception as e:
            self.get_logger().error(f"handle_task raised: {e}")
            accepted, reason = False, str(e)
        self.publish_ack(cmd["command_id"], cmd.get("resource_id", ""), accepted, reason)

    @abstractmethod
    def handle_task(self, cmd: dict) -> Tuple[bool, Optional[str]]:
        # Returns (accepted, rejection_reason_or_None).
        # Must NOT block — launch hardware execution via self.task_runner.run().
        ...

    def publish_ack(self, command_id: str, resource_id: str,
                    accepted: bool, reason: Optional[str] = None):
        payload = build_ack(command_id, self.domain_id, resource_id, accepted, reason)
        msg = String(); msg.data = json.dumps(payload)
        self.ack_pub.publish(msg)

    def publish_status(self, command_id: str, resource_id: str,
                       task: str, task_state: str, resource_state: str,
                       piece_id: Optional[str] = None,
                       result: Optional[dict] = None):
        payload = build_status(command_id, self.domain_id, resource_id,
                               task, task_state, resource_state, piece_id, result)
        msg = String(); msg.data = json.dumps(payload)
        self.status_pub.publish(msg)

    def _load_hmac_secret(self) -> str:
        # Reads from config/hmac_secrets.yaml, key = self.domain_id
        ...
```

C-VENDOR-COMMON-2. `vendors/common/internal_bus.py`

Purpose: lightweight in-process publish/subscribe for VS → adapters and adapters → VS communication. Not a ROS2 topic. No network. No serialization. Pure Python.

```python
class InternalBus:
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, callback: Callable[[dict], None]):
        with self._lock:
            self._subscribers[event_type].append(callback)

    def publish(self, event_type: str, payload: dict):
        with self._lock:
            callbacks = list(self._subscribers.get(event_type, []))
        for cb in callbacks:
            try:
                cb(payload)
            except Exception as e:
                print(f"InternalBus handler error for {event_type}: {e}")
```

Event types used within niryo VS:
- `"ROBOT1_AT_PICK_POSITION"` — payload: `{command_id, resource_id}`
- `"ROBOT1_AT_PLACE_POSITION"` — payload: `{command_id, resource_id}`
- `"ROBOT2_PICK_DONE"` — payload: `{command_id, color, shape, confidence}`
- `"ROBOT2_PLACE_DONE"` — payload: `{command_id, target}`
- `"CONVEYOR1_STOPPED"` — payload: `{sensor_id, state}`
- `"SENSOR_CHANGED"` — payload: `{sensor_id, state}` — published autonomously by niryo_ir_adapter
- `"VISION_RESULT"` — payload: `{color, shape, confidence}` — published by local_vision_adapter

C-VENDOR-COMMON-3. `vendors/common/task_runner.py`

Purpose: executes hardware operations in a dedicated thread so the ROS2 executor callback (`handle_task`) returns immediately. The VS calls `task_runner.run()` from `handle_task()` and returns `(True, None)` to the base class (which then publishes ACK). The thread calls the `on_complete` or `on_error` callback when done, which calls `self.publish_status()`.

```python
class TaskRunner:
    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def run(self, task_fn: Callable[[], dict],
            on_complete: Callable[[dict], None],
            on_error: Callable[[Exception], None]):
        if self.is_running():
            raise RuntimeError("TaskRunner already busy")
        def _wrapper():
            try:
                result = task_fn()
                on_complete(result)
            except Exception as e:
                on_error(e)
            finally:
                with self._lock:
                    self._thread = None
        with self._lock:
            self._thread = threading.Thread(target=_wrapper, daemon=True)
            self._thread.start()
```

Each adapter gets its own TaskRunner. The VS has one TaskRunner per resource it manages internally. This allows (in principle) robot1 and robot2 to execute hardware in parallel inside the VS while the FS sees only one pending command on the niryo domain at a time.

C-VENDOR-NIRYO-1. `vendors/niryo/niryo_vendor_supervisor.py`

Purpose: SCADA-level supervisor for robot1, robot2, Niryo conveyors 1/2, IR sensors, local cameras, and robot2's Niryo vacuum. Extends `BaseVendorSupervisor`. Owns one adapter instance per resource, each with its own TaskRunner. Dispatches commands to adapters based on `resource_id`. Publishes autonomous SENSOR_UPDATE status messages when IR sensors change state.

Full `handle_task()` dispatch:

```python
RESOURCE_TO_ADAPTER = {
    "robot1": "robot1_adapter",
    "robot2": "robot2_adapter",
    "conveyor1": "niryo_conveyor_adapter",
    "conveyor2": "niryo_conveyor_adapter",
    "vision_robot1": "local_vision_adapter",
    "vision_robot2": "local_vision_adapter",
    "robot2_niryo_vacuum": "robot2_niryo_vacuum_adapter",
}

def handle_task(self, cmd: dict) -> Tuple[bool, Optional[str]]:
    resource_id = cmd.get("resource_id")
    task = cmd.get("task")
    adapter_name = RESOURCE_TO_ADAPTER.get(resource_id)

    if adapter_name is None:
        return False, f"Unknown resource_id: {resource_id}"

    adapter = getattr(self, adapter_name)

    if adapter.task_runner.is_running():
        return False, f"Resource {resource_id} is busy"

    def on_complete(result: dict):
        self.publish_status(
            command_id=cmd["command_id"],
            resource_id=resource_id,
            task=task,
            task_state="COMPLETED",
            resource_state=result.get("resource_state", "IDLE"),
            piece_id=cmd.get("piece_id"),
            result=result,
        )

    def on_error(exc: Exception):
        self.publish_status(
            command_id=cmd["command_id"],
            resource_id=resource_id,
            task=task,
            task_state="FAILED",
            resource_state="ERROR",
            result={"code": "EXCEPTION", "message": str(exc)},
        )

    # Dispatch to adapter
    task_fn = adapter.make_task_fn(cmd)
    adapter.task_runner.run(task_fn, on_complete, on_error)
    return True, None  # ACK accepted
```

Autonomous sensor publishing (runs on a separate 0.2s ROS2 timer, not triggered by command):

```python
def _poll_sensors(self):
    for sensor_id in ["c1s1", "c1s2", "c2s1", "c2s2"]:
        new_state = self.niryo_ir_adapter.read_sensor(sensor_id)
        if new_state != self._sensor_cache[sensor_id]:
            self._sensor_cache[sensor_id] = new_state
            # Publish autonomous status (no command_id — uses a sentinel)
            self.publish_status(
                command_id="AUTO",
                resource_id=sensor_id,
                task="SENSOR_UPDATE",
                task_state="COMPLETED",
                resource_state=new_state,
                result={"sensor_id": sensor_id, "state": new_state},
            )
```

The FS `on_status()` handler detects `task="SENSOR_UPDATE"` and `command_id="AUTO"` and routes to `state.update_sensor()` without attempting to look up a pending command.

C-VENDOR-NIRYO-2. `vendors/niryo/robot1_adapter.py`

Purpose: executes robot1 arm movement tasks using Niryo ROS2 action client (`RobotMove`) and Niryo service clients. Does NOT interact with the Arduino vacuum.

ROS2 interface used (same as old `robot1_node.py`):
- Action client: `/robot1/niryo_robot_arm_commander/robot_action` type `RobotMove`
- No tool commands — robot1's gripper is the Arduino vacuum (separate domain)

Tasks handled (specified by `cmd["task"]`):
- `INITIALIZE_DOMAIN` → call Go Home sequence via RobotMove action, confirm IDLE
- `GOTO_PICK_POSITION` → `parameters["position"]` is `"C4"` or `"C3"`. Looks up pose from internal `POSITIONS` dict (ported from old `robot1_node.py`). Moves arm to pre-pick pose. Returns `{"resource_state": "AT_PICK_POSITION"}`
- `LIFT_AND_PLACE` → `parameters["target"]` is `"FINAL_RED_STACK"`, `"FINAL_GREEN_STACK"`, etc. Lifts arm (vertical move), translates to target pose, lowers. Returns `{"resource_state": "AT_PLACE_POSITION"}`
- `RETURN_HOME` → moves to home pose. Returns `{"resource_state": "IDLE"}`

`make_task_fn(cmd)` returns a callable that executes the sequence synchronously (it runs inside TaskRunner thread, so blocking is safe):

```python
def make_task_fn(self, cmd: dict) -> Callable[[], dict]:
    task = cmd["task"]
    params = cmd.get("parameters", {})

    if task == "GOTO_PICK_POSITION":
        pos_name = self._pick_pos_name(params["position"])
        def fn():
            self._move_to(pos_name)
            return {"resource_state": "AT_PICK_POSITION"}
        return fn

    if task == "LIFT_AND_PLACE":
        target = params["target"]
        place_pos = self._place_pos_name(target)
        def fn():
            self._move_to("lift_intermediate")  # intermediate pose to avoid collisions
            self._move_to(place_pos)
            return {"resource_state": "AT_PLACE_POSITION"}
        return fn

    if task == "RETURN_HOME":
        def fn():
            self._move_to("home")
            return {"resource_state": "IDLE"}
        return fn
    ...
```

`_move_to(pose_name)` uses the same joint coordinates as `robot1_node.py`'s `self.positions` dict. Copy those values directly. The function calls the `RobotMove` action client, blocks until result, raises on failure.

Old reference: `nodes/robot1_node.py` contains ALL joint positions (copy them verbatim), the action client setup, and the vacuum calls. The vacuum calls are removed here — they are now separate commands. The `wait_for_services()` pattern from old `robot1_node.py` is replicated in `robot1_adapter.__init__()`.

C-VENDOR-NIRYO-3. `vendors/niryo/robot2_adapter.py`

Purpose: executes robot2 arm + Niryo vacuum tasks. Calls `robot2_niryo_vacuum_adapter` internally for pick/release (vacuum is internal to niryo domain for robot2).

ROS2 interface (same as old `robot2_node.py`):
- Action client: `/robot2/niryo_robot_arm_commander/robot_action` type `RobotMove`
- Service clients: `/robot2/niryo_robot/tools/pull_air_vacuum_pump` and `/robot2/niryo_robot/tools/push_air_vacuum_pump` type `ToolCommand`

Tasks handled:
- `INITIALIZE_DOMAIN` → go home, confirm IDLE
- `CAPTURE_LOCAL_VISION` → `parameters["position"]` is `"C2S2"`. Moves to `at_capture_c2s2` pose. Calls `local_vision_adapter.capture(robot_id="robot2")`. Returns `{"resource_state": "IDLE", "color": detected_color, "shape": detected_shape, "confidence": "HIGH"}`
- `MOVE_PIECE` → `source` + `target` fields:
  - `source=C2S2, target=C4`: sequence = prepick → pick → [vacuum on] → approach_place_c4 → preplace_c4 → place_c4 → [vacuum off]
  - `source=C2S2, target=BANTAM_BED`: sequence uses bantam approach poses
  - `source=BANTAM_BED, target=C4`: sequence uses bantam pick poses
  - `source=C2S2, target=SCRAP`: sequence uses scrap approach poses
  - Returns `{"resource_state": "PLACE_DONE", "target": target}`
- `RETURN_HOME` → moves to home pose

Old reference: `nodes/robot2_node.py` contains all joint positions and the full movement sequence. Copy positions verbatim into `POSITIONS` dict inside `robot2_adapter.py`. The old `PICK_C2S2`, `PLACE_C4`, `PLACE_C2S2_RED`, etc. commands map to `MOVE_PIECE` with source/target parameters.

C-VENDOR-NIRYO-4. `vendors/niryo/local_vision_adapter.py`

Purpose: captures color and shape from the robot-mounted cameras (robot1's and robot2's cameras). Returns normalized result. Does NOT publish raw image data. Internal to niryo domain.

ROS2 interface: subscribes to camera topics (OpenCV via image_transport or direct topic — check old `vision_node.py` for exact topic names and callback pattern). Implements the same HSV-based detection pipeline as old `vision_node.py`.

`capture(robot_id: str, timeout_sec=5.0) -> dict`:
- Moves camera head to capture position if needed (or triggers capture callback)
- Waits for detection result (blocks, inside TaskRunner thread)
- Returns `{"color": "RED", "shape": "CIRCLE", "confidence": "HIGH"}`
- Raises `TimeoutError` if no result within timeout_sec
- NEVER returns raw pixel data, HSV values, or image frames — only the classified result

Old reference: `nodes/vision_node.py` implements the full detection pipeline. Copy the detection logic. The key difference: `vision_node.py` was a standalone ROS2 node that published results on topics (`/visionrobot1/color`, `/visionrobot1/shape`). In the new architecture, `local_vision_adapter.py` is called synchronously from `robot2_adapter.make_task_fn()` and returns the result directly — no intermediate topics exist.

C-VENDOR-NIRYO-5. `vendors/niryo/niryo_conveyor_adapter.py`

Purpose: controls Niryo conveyors 1 and 2 through the Niryo conveyor API.

ROS2 interface: Niryo conveyor control service (check old `conveyor1_node.py` for exact service names and msg types).

Tasks:
- `RUN_NIRYO_CONVEYOR` → `parameters["conveyor_id"]` is `"conveyor1"` or `"conveyor2"`. Calls start service. Polls c1s2 (or c2s2) sensor via `niryo_ir_adapter`. When sensor becomes OCCUPIED, calls stop service. Publishes autonomous SENSOR_UPDATE via bus. Returns `{"resource_state": "STOPPED", "reason": "SENSOR_TRIGGERED"}`
- `STOP_NIRYO_CONVEYOR` → calls stop service immediately. Returns `{"resource_state": "STOPPED"}`

Old reference: `nodes/conveyor1_node.py` and `conveyor2_node.py`.

C-VENDOR-NIRYO-6. `vendors/niryo/niryo_ir_adapter.py`

Purpose: reads IR sensor states. Used internally by conveyor adapter and by VS's autonomous sensor poll timer.

```python
class NiryoIRAdapter:
    # Subscribes to Niryo sensor topics (check old conveyor nodes for exact topic names)
    # Caches latest state per sensor_id
    def read_sensor(self, sensor_id: str) -> str:  # returns "FREE" or "OCCUPIED"
        return self._cache.get(sensor_id, "UNKNOWN")
```

Old reference: sensor status was published on `/c1s1/status`, `/c1s2/status`, etc. — check old `conveyor1_node.py`.

C-VENDOR-NIRYO-7. `vendors/niryo/robot2_niryo_vacuum_adapter.py`

Purpose: controls robot2's Niryo vacuum pump. Called from `robot2_adapter` as part of MOVE_PIECE sequences. Never called from any other adapter.

```python
class Robot2NiryoVacuumAdapter:
    # Service clients: /robot2/niryo_robot/tools/pull_air_vacuum_pump (ToolCommand)
    #                  /robot2/niryo_robot/tools/push_air_vacuum_pump (ToolCommand)
    def pick(self): ...    # calls pull service
    def release(self): ... # calls push service
```

Old reference: `robot2_node.py` lines where `self.vacuum_pull_client` and `self.vacuum_push_client` are called. Copy exactly.

7. `vendors/niryo/niryo_vendor_supervisor.py`

Purpose: SCADA-level supervisor for both Niryo robots, Niryo conveyors 1/2, IR sensors, local cameras, and robot2's Niryo vacuum.

Subscriptions:

- `/niryo_factory/command`

Publications:

- `/niryo_factory/ack`
- `/niryo_factory/status`

Internal resource map:

- `robot1_adapter`: moves robot1 only. Does not own Arduino vacuum.
- `robot2_adapter`: moves robot2 and calls `robot2_niryo_vacuum_adapter`.
- `niryo_conveyor_adapter`: controls conveyor1 and conveyor2 through Niryo APIs.
- `niryo_ir_adapter`: reads c1s1/c1s2/c2s1/c2s2.
- `local_vision_adapter`: local robot cameras for capture/verification.

Important behavior:

- Command for `resource_id=robot1` never calls Niryo vacuum unless a future real robot1 Niryo-vacuum configuration is explicitly registered.
- Command for `resource_id=robot2` may use internal Niryo vacuum and does not call `/arduino_vacuum_factory/*`.
- Status reports coarse results only: `PICK_DONE`, `PLACE_DONE`, `SENSOR_OCCUPIED`, `SENSOR_FREE`, `VISION_RESULT_READY`.

C-VENDOR-UFACTORY-1. `vendors/ufactory/ufactory_vendor_supervisor.py`

Purpose: extends `BaseVendorSupervisor`. Manages xArm1 and xArm2. Dispatches on `resource_id`.

`handle_task()`:
- `resource_id="xarm1"` → `xarm1_adapter.make_task_fn(cmd)`
- `resource_id="xarm2"` → `xarm2_adapter.make_task_fn(cmd)`
- Both adapters have their own TaskRunner, so xArm1 and xArm2 CAN execute concurrently at the hardware level. However, the FS serializes at the domain level (one pending command per domain). Future enhancement: if concurrent xArm1+xArm2 operation is needed, switch to per-resource VendorClient slots.

Forbidden inside this VS: no imports from `vendors.laser`, no HTTP/G-code calls, no global vision camera calls, no conveyor calls.

C-VENDOR-UFACTORY-2. `vendors/ufactory/xarm1_adapter.py`

Purpose: moves xArm1 between C1S2, laser_bed, and C2S1.

ROS2 interface (same as old `xarm1_node.py`):
- Service clients: `/xarm1/motion_ctrl` type `SetInt16`, `/xarm1/move_joint` type `MoveJoint`, `/xarm1/gripper_ctrl` type `Call`

Tasks handled:
- `INITIALIZE_DOMAIN` → enable motion, go home
- `MOVE_PIECE source=C1S2 target=C2S1` → approach_c1s2 → pick_c1s2 → [gripper close] → preapproach_c2s2 → approach_c2s2 → place_c2s1 → [gripper open]. Returns `{"resource_state": "PLACE_DONE"}`
- `MOVE_PIECE source=C1S2 target=LASER_BED` → approach_c1s2 → pick_c1s2 → [gripper close] → preapproach_laser → approach_laser → place_laser → [gripper open]. Returns `{"resource_state": "PLACE_DONE"}`
- `MOVE_PIECE source=LASER_BED target=C2S1` → approach_laser (pick height) → pick_laser → [gripper close] → preapproach_c2s2 → place_c2s1 → [gripper open]. Returns `{"resource_state": "PLACE_DONE"}`
- `MOVE_XARM_HOME` → home position. Returns `{"resource_state": "IDLE"}`

POSITIONS dict: copy ALL poses from old `xarm1_node.py`'s `self.positions` verbatim. Key names: `home`, `preapproach_c1s2`, `approach_c1s2`, `pick_c1s2`, `preapproach_laser`, `approach_laser`, `place_laser`, `preapproach_c2s2`, `approach_c2s2`, `place_c2s1`.

Old reference: `nodes/xarm1_node.py`. Task mapping: old `PICK_C1S2_RED` → `MOVE_PIECE source=C1S2 target=LASER_BED`. Old `PICK_C1S2_BLUE / PICK_C1S2_GREEN` → `MOVE_PIECE source=C1S2 target=C2S1`. Old `PICK_LASER_RED` → `MOVE_PIECE source=LASER_BED target=C2S1`.

C-VENDOR-UFACTORY-3. `vendors/ufactory/xarm2_adapter.py`

Purpose: moves xArm2 from initial stack slot to C1S1 (or C3 for secondary path).

ROS2 interface: same xarm_msgs services as xarm1, but namespace `/xarm2/`.

Tasks handled:
- `INITIALIZE_DOMAIN` → enable motion, go home
- `MOVE_PIECE source=INITIAL_STACK target=C1S1` → `parameters["pick_slot"]` contains slot_id (e.g., `"s2.4"`). Looks up pose for that slot from internal `SLOT_POSITIONS` dict. Sequence: approach_slot → pick → [gripper close] → move_to_c1s1 → place_c1s1 → [gripper open]. Returns `{"resource_state": "PLACE_DONE"}`
- `MOVE_XARM_HOME` → home. Returns `{"resource_state": "IDLE"}`

SLOT_POSITIONS: the old xarm2 used dynamic slot-based commands like `"pick s2.4 RED"`. The new adapter needs a mapping `slot_id → joint_angles`. Either compute from a grid formula or enumerate explicitly. Old reference: `nodes/xarm2_node.py` (if it exists) or equivalent in the old supervisor. Look at old xarm2 `self.positions` dict.

8. `vendors/ufactory/ufactory_vendor_supervisor.py`

Purpose: supervisor for UFactory xArm1 and xArm2 only.

Subscriptions:

- `/ufactory_factory/command`

Publications:

- `/ufactory_factory/ack`
- `/ufactory_factory/status`

Internal adapters:

- `xarm1_adapter`: C1S2 to C2S1/laser handoff movements.
- `xarm2_adapter`: initial stack to C1S1/C3 feeding movements.

Forbidden:

- No laser HTTP/G-code calls here.
- No global vision camera calls here.
- No green conveyor calls here.

C-VENDOR-LASER-1. `vendors/laser/laser_vendor_supervisor.py`

Purpose: extends `BaseVendorSupervisor`. Single resource `laser`. Delegates all hardware calls to `laser_adapter.py`.

`handle_task()` dispatch:
- `resource_id="laser"` → `laser_adapter.make_task_fn(cmd)`

C-VENDOR-LASER-2. `vendors/laser/laser_adapter.py`

Purpose: communicates with the laser machine via its native protocol (check old `laser_node.py` for the exact protocol — HTTP REST, serial, or vendor SDK).

Tasks:
- `INITIALIZE_DOMAIN` → check connectivity, confirm laser in safe idle state. Returns `{"resource_state": "IDLE"}`
- `PREPARE_JOB` → send job preparation command (if the laser needs a separate prepare step). Returns `{"resource_state": "PREPARING"}`
- `RUN_JOB` → `parameters["job_type"]` is `"RED_PROCESS"`. Sends the laser run command. Blocks (inside TaskRunner thread) until laser reports completion (poll or callback). Returns `{"resource_state": "FINISHED"}`
- `RESET` → sends reset/abort command. Returns `{"resource_state": "IDLE"}`

Forbidden in result payload: G-code contents, HTTP URLs, laser power settings, wavelength, calibration data. Allowed: `{"resource_state": "FINISHED", "code": "JOB_DONE"}`.

Old reference: `nodes/laser_node.py`. Copy protocol interaction code. The laser node's old topics (`/laser/command`, `/laser/status`) are replaced by the three-channel contract.

9. `vendors/laser/laser_vendor_supervisor.py`

Purpose: separate laser machine vendor.

Subscriptions:

- `/laser_factory/command`

Publications:

- `/laser_factory/ack`
- `/laser_factory/status`

Tasks:

- `INITIALIZE_DOMAIN`
- `PREPARE_JOB`
- `RUN_JOB`
- `RESET`

Status:

- `resource_id=laser`
- `resource_state=PREPARING|WORKING|FINISHED|ERROR`

Internal details such as G-code line contents and HTTP command URLs never cross the boundary.

C-VENDOR-GLOBALVISION-1. `vendors/globalvision/globalvision_vendor_supervisor.py`

Purpose: extends `BaseVendorSupervisor`. Manages the global stack camera. Owns `camera_adapter`, `slot_inventory`, and `calibrator`.

`handle_task()` dispatch:
- All tasks go to `camera_adapter.make_task_fn(cmd)` which uses `slot_inventory` for state.

C-VENDOR-GLOBALVISION-2. `vendors/globalvision/camera_adapter.py`

Purpose: captures images, runs slot detection, classifies color+shape per slot.

Tasks:
- `SCAN_STACK` → capture image(s), run full grid detection on all slots (using ROI config from `calibrator`). Returns result with full slot list.
- `LOCATE_NEXT_PIECE` → `parameters["color"]` is the requested color. Scans or uses cached scan. Returns `{"slot_id": "s2.4", "color": "RED", "shape": "CIRCLE", "confidence": "HIGH", "scan_id": "SCAN-0001"}`
- `GET_INVENTORY` → returns cached inventory from last scan without new capture.

Old reference: `nodes/globalvision_node.py` and `nodes/globalvision_calibrator.py`. The detection pipeline (OpenCV, ROI grid, color classification) is copied into `camera_adapter.py`. The calibrator result (ROI coordinates) is loaded at startup from `config/globalvision_rois.example.yaml`.

C-VENDOR-GLOBALVISION-3. `vendors/globalvision/slot_inventory.py`

Purpose: maintains in-memory slot state (occupied/color/shape per slot). Updated by camera_adapter after each scan. Used by camera_adapter for LOCATE_NEXT_PIECE without re-scanning.

```python
class SlotInventory:
    def __init__(self): self._slots: Dict[str, dict] = {}
    def update_from_scan(self, scan_results: List[dict]): ...
    def get_next_slot_for_color(self, color: str) -> Optional[dict]: ...
    def mark_slot_emptied(self, slot_id: str): ...
```

C-VENDOR-GLOBALVISION-4. `vendors/globalvision/calibrator.py`

Purpose: loads ROI grid configuration from YAML. Provides `get_roi(slot_id) -> Tuple[x,y,w,h]` for camera_adapter. Loaded once at startup. Not a ROS2 node.

Old reference: `nodes/globalvision_calibrator.py`.

10. `vendors/globalvision/globalvision_vendor_supervisor.py`

Purpose: separate global stack camera/inventory vendor.

Subscriptions:

- `/globalvision_factory/command`

Publications:

- `/globalvision_factory/ack`
- `/globalvision_factory/status`

Tasks:

- `SCAN_STACK`: scans all slots.
- `LOCATE_NEXT_PIECE`: returns the next slot matching a requested color/order constraint.
- `GET_INVENTORY`: returns latest normalized inventory.

Allowed status result:

- `slot_id`, `occupied`, `color`, `shape`, `confidence_class`, `scan_id`.

Forbidden status result:

- images, HSV masks, ROI pixel coordinates, ML model internals.

C-VENDOR-GC-1. `vendors/green_conveyors/green_conveyors_vendor_supervisor.py`

Purpose: extends `BaseVendorSupervisor`. Manages conveyors 3 and 4 via shared Arduino driver.

`handle_task()` dispatch:
- `resource_id="conveyor3"` → `shared_arduino_driver.make_task_fn(cmd, channel="A")`
- `resource_id="conveyor4"` → `shared_arduino_driver.make_task_fn(cmd, channel="B")`
Both share the same serial connection but different channel bytes.

C-VENDOR-GC-2. `vendors/green_conveyors/shared_arduino_driver.py`

Purpose: owns the serial connection to the Arduino that controls both green conveyors. Thread-safe — uses a lock when sending serial commands. Shared between conveyor3 and conveyor4 adapters.

Old reference: `nodes/green_conveyor_shared_driver_node.py` and `nodes/green_conveyor_boot_node.py`. The serial command format (channel bytes, speed bytes) is taken directly from those files.

Tasks:
- `INITIALIZE_DOMAIN` → send init byte sequence to Arduino, confirm response. Returns `{"resource_state": "STOPPED"}`
- `RUN_CONVEYOR` → `parameters["speed"]` optional (default = configured speed). Sends RUN command for specified channel. Returns `{"resource_state": "RUNNING"}`
- `STOP_CONVEYOR` → sends STOP command for channel. Returns `{"resource_state": "STOPPED"}`
- `SET_SPEED` → `parameters["speed"]`. Returns `{"resource_state": "RUNNING"}`
- `RESET` → sends RESET byte. Returns `{"resource_state": "STOPPED"}`

C-VENDOR-VACUUM-1. `vendors/arduino_vacuum/arduino_vacuum_vendor_supervisor.py`

Purpose: extends `BaseVendorSupervisor`. Single resource `arduino_vacuum`. Delegates to `arduino_vacuum_driver.py`.

`handle_task()` dispatch: only one resource, all tasks go to `arduino_vacuum_driver.make_task_fn(cmd)`.

C-VENDOR-VACUUM-2. `vendors/arduino_vacuum/arduino_vacuum_driver.py`

Purpose: owns the serial connection to the Arduino vacuum controller. Implements pick/release/off via serial byte commands.

Serial interface: same as old `vacuum_controller_node.py`. Port from `config/hardware_ports.yaml`. Commands: `b"p"` = pick, `b"r"` = release, `b"o"` = off.

```python
class ArduinoVacuumDriver:
    def __init__(self, port: str, baudrate: int = 9600): ...

    def make_task_fn(self, cmd: dict) -> Callable[[], dict]:
        task = cmd["task"]
        def fn():
            if task == "PICK":
                self._send(b"p")
                time.sleep(0.5)  # wait for vacuum to build
                return {"resource_state": "PICK_DONE"}
            elif task == "RELEASE":
                self._send(b"r")
                time.sleep(0.3)
                return {"resource_state": "RELEASE_DONE"}
            elif task == "OFF":
                self._send(b"o")
                return {"resource_state": "IDLE"}
        return fn

    def _send(self, byte: bytes):
        with self._lock:
            self._serial.write(byte)
```

State machine (implemented in VS, not driver):
- `IDLE → PICKING → PICK_DONE → IDLE`
- `IDLE → RELEASING → RELEASE_DONE → IDLE`
- `ANY → ERROR` on serial exception

Old reference: `nodes/vacuum_controller_node.py`. The old node exposed ROS2 services (`/vacuum SetBool`, `/vacuum_off Trigger`). The new driver is a plain Python class — no services. The serial interaction logic is identical.

C-VENDOR-BANTAM-1. `vendors/bantam/bantam_vendor_supervisor.py`

Purpose: extends `BaseVendorSupervisor`. Two resources: `bantam` and `bantam_door`.

`handle_task()` dispatch:
- `resource_id="bantam"` → `bantam_adapter.make_task_fn(cmd)`
- `resource_id="bantam_door"` → `door_adapter.make_task_fn(cmd)`

C-VENDOR-BANTAM-2. `vendors/bantam/bantam_adapter.py`

Purpose: controls Bantam CNC machine via its native interface.

Old reference: `nodes/bantam_node.py`. Copy the communication protocol (check that file for whether it uses serial, HTTP, or ROS2 interface). The Bantam's internal G-code, job parameters, and status codes stay inside this adapter.

Tasks:
- `INITIALIZE_DOMAIN` → check Bantam connectivity and door state
- `GET_READY` → prepare Bantam for the next job (open door if needed, reset position)
- `RUN_JOB` → `parameters["job_type"]` is `"BLUE_PROCESS"`. Executes job. Blocks until done. Returns `{"resource_state": "FINISHED", "code": "JOB_DONE"}`
- `RESET` → abort and reset

C-VENDOR-BANTAM-3. `vendors/bantam/door_adapter.py`

Purpose: controls the Bantam CNC door (servo or actuator).

Old reference: old `bantam_node.py` door control logic.

Tasks: `OPEN_DOOR` → returns `{"resource_state": "DOOR_OPEN"}`. `CLOSE_DOOR` → returns `{"resource_state": "DOOR_CLOSED"}`.

11. `vendors/green_conveyors/green_conveyors_vendor_supervisor.py`

See C-VENDOR-GC-1 above for full specification.

12. `vendors/arduino_vacuum/arduino_vacuum_vendor_supervisor.py`

See C-VENDOR-VACUUM-1 above for full specification.

13. `vendors/bantam/bantam_vendor_supervisor.py`

See C-VENDOR-BANTAM-1 above for full specification. Robot2 status is not subscribed directly. Factory Supervisor coordinates robot2 placement and Bantam readiness through their two vendor channels.

C-NODES-1. `nodes/dashboard_node.py`

Purpose: a thin ROS2 node that subscribes to `/factory/system_state` (published by the FS's `SystemStatePublisher`) and republishes the same JSON on `/dashboard/state` for any external dashboard UI or MES subscriber. Also subscribes to `/supervisor/set_optimized_order` to forward batch orders from the UI to the FS.

```python
class DashboardNode(Node):
    def __init__(self):
        super().__init__('dashboard_node')
        self.create_subscription(String, '/factory/system_state',
                                 self._on_system_state, 10)
        self.state_pub = self.create_publisher(String, '/dashboard/state', 10)
        # Optional: subscribe to piece color events for per-location display
        # These come from /factory/system_state pipeline field — no extra topics needed

    def _on_system_state(self, msg: String):
        # Republish verbatim
        self.state_pub.publish(msg)
```

If the existing dashboard UI expects the old `/dashboard/state` format (from old `build_dashboard_snapshot()`), add a translation layer inside `_on_system_state` that transforms the new `/factory/system_state` JSON into the old format. Document the field mapping explicitly.

Old format fields from old `supervisor.py` `build_dashboard_snapshot()` vs new `/factory/system_state` fields:
- Old `robots.robot1` → New `resources.robots.robot1`
- Old `sensors.c1s1` → New `resources.sensors.c1s1`
- Old `conveyor.conveyor1` → New `resources.conveyors.conveyor1`
- Old `pipeline` → New `pipeline` (same structure)
- Old `cycles` → New `cycles`

C-NODES-2. `factory/db_writer.py`

Purpose: synchronous PostgreSQL writer. Not a ROS2 node. Called from `piece_tracker.transfer_piece()` on every piece movement.

Database schema (see also Part G for full schema):

```python
class DBWriter:
    def __init__(self, dsn: str):
        # dsn = "postgresql://user:password@localhost:5432/shipyard_pnp"
        import psycopg2
        self._conn = psycopg2.connect(dsn)

    def insert_piece_transfer(self, piece: dict, from_loc: str, to_loc: str):
        sql = """
        INSERT INTO piece_transfers
            (piece_id, color, shape, from_location, to_location, transferred_at,
             piece_age_sec, history_json)
        VALUES (%s, %s, %s, %s, %s, NOW(),
                EXTRACT(EPOCH FROM NOW()) - %s, %s)
        """
        self._conn.cursor().execute(sql, (
            piece["id"], piece.get("color"), piece.get("shape"),
            from_loc, to_loc,
            piece["timestamp_created"],
            json.dumps(piece["history"]),
        ))
        self._conn.commit()

    def insert_cycle_complete(self, record: CycleRecord):
        sql = """
        INSERT INTO cycle_records
            (piece_id, color, shape, route, started_at, completed_at, cycle_time_sec)
        VALUES (%s, %s, %s, %s, to_timestamp(%s), to_timestamp(%s), %s)
        """
        ...
```

Old reference: `supervisor/db_writer.py`. Port the connection logic and the `insert_piece_transfer()` method. Rename DSN config to come from `config/hardware_ports.yaml` (which also holds DB connection string) or a separate `config/db.yaml`.

C-LAUNCH-1. Launch file specifications

`launch/pnp_full_system.launch.py` — launches all nodes for full production:
```python
def generate_launch_description():
    return LaunchDescription([
        # Factory layer (one process)
        Node(package='shipyard_pnp', executable='factory_supervisor', name='factory_supervisor'),
        Node(package='shipyard_pnp', executable='dashboard_node', name='dashboard_node'),
        # All seven vendor supervisors (separate processes)
        Node(package='shipyard_pnp', executable='niryo_vendor_supervisor'),
        Node(package='shipyard_pnp', executable='ufactory_vendor_supervisor'),
        Node(package='shipyard_pnp', executable='laser_vendor_supervisor'),
        Node(package='shipyard_pnp', executable='globalvision_vendor_supervisor'),
        Node(package='shipyard_pnp', executable='green_conveyors_vendor_supervisor'),
        Node(package='shipyard_pnp', executable='arduino_vacuum_vendor_supervisor'),
        Node(package='shipyard_pnp', executable='bantam_vendor_supervisor'),
    ])
```

`launch/pnp_sim_smoke.launch.py` — launches FS + all MOCK vendor supervisors (Phase 3 testing):
- Same structure but uses `mock_vendor_supervisor` executable with `domain_id` parameter.

`launch/vendor_niryo.launch.py` — launches ONLY niryo VS (for hardware testing in isolation):
```python
Node(package='shipyard_pnp', executable='niryo_vendor_supervisor',
     parameters=[{'config_file': 'config/hardware_ports.yaml'}])
```

Each vendor launch file follows the same single-node pattern. Used during Phase 5 one-domain-at-a-time hardware testing.

C-CONFIG-1. `config/hardware_ports.yaml` — full specification:

```yaml
niryo:
  robot1_namespace: /robot1
  robot2_namespace: /robot2
  conveyor1_id: 1        # Niryo conveyor bus ID
  conveyor2_id: 2
arduino_vacuum:
  port: /dev/ttyACM1
  baudrate: 9600
  open_wait_sec: 2.0
  read_wait_sec: 1.0
  reconnect_attempts: 8
green_conveyors:
  port: /dev/ttyACM0
  baudrate: 115200
laser:
  # Fill from old laser_node.py — HTTP endpoint or serial port
database:
  dsn: "postgresql://shipyard:password@localhost:5432/shipyard_pnp"
hmac:
  # Secrets stored in config/hmac_secrets.yaml (gitignored)
  secrets_file: config/hmac_secrets.yaml
```

C-CONFIG-2. `config/factory_layout.yaml` — production line positions and routing:

```yaml
locations:
  - id: initial_stack
    type: source
    vendor_domain: globalvision
  - id: conveyor1
    type: transit
    vendor_domain: niryo
    entry_sensor: c1s1
    exit_sensor: c1s2
  - id: laser_bed
    type: machine
    vendor_domain: laser
  - id: conveyor2
    type: transit
    vendor_domain: niryo
    entry_sensor: c2s1
    exit_sensor: c2s2
  - id: bantam_bed
    type: machine
    vendor_domain: bantam
  - id: c4_location
    type: handoff
    vendor_domain: niryo
    sensor: c4
  - id: c3_location
    type: handoff
    vendor_domain: niryo
    sensor: c3
  - id: final_red_stack
    type: sink
  - id: final_green_stack
    type: sink
  - id: final_blue_stack
    type: sink
  - id: robot1_scrap
    type: sink
  - id: robot2_scrap
    type: sink

color_routes:
  # CORRECTION: GREEN bypasses conveyor1, xarm1, conveyor2, robot2 entirely — direct to conveyor3
  RED:   ["initial_stack", "conveyor1", "laser_bed", "conveyor2", "c4_location", "final_red_stack"]
  BLUE:  ["initial_stack", "conveyor1", "conveyor2", "bantam_bed", "c4_location", "final_blue_stack"]
  GREEN: ["initial_stack", "c3", "final_green_stack"]
```

PART D — GREENFIELD BUILD SEQUENCE

Phase 1 — Package skeleton (Day 1, ~2 hours).

Actions:
- Create `shipyard_plug_and_plan/` directory tree matching Part B manifest.
- Create `package.xml` (ROS2 Humble, Python, depends: rclpy, std_msgs, threading).
- Create `setup.py` with entry_points for all executables (factory_supervisor, all seven VS nodes, dashboard_node, mock_vendor_supervisor).
- Create `setup.cfg`.
- Create empty `__init__.py` files for all packages.
- Create placeholder `config/` files with comments.
- Create empty test files.

Test: `colcon build --packages-select shipyard_pnp` must succeed (no imports to fail yet).
Old system state: untouched. No import of shipyard_core anywhere.

Phase 2 — Shared library (Day 1, ~3 hours).

Actions:
- Implement `shared/contracts.py` with all new state enums (RobotState, ConveyorState, etc.).
- Implement `shared/time_ids.py`: `make_command_id(domain_id, resource_id) -> str`, `make_nonce() -> str`, `iso_now() -> str`.
- Implement `shared/messages.py`: `build_command(...)`, `build_ack(...)`, `build_status(...)`, `sign_message(payload, secret) -> str`, `verify_message(payload, secret) -> bool`.
- Implement `shared/topic_acl.py`: `ACLChecker(policy_yaml_path)` with `check_publish(node_name, topic) -> bool` and `check_subscribe(node_name, topic) -> bool`. Used in tests only (not runtime-enforced until Phase 6).

Test: `pytest test/test_messages.py test/test_acl.py test/test_resource_routing.py`

All three must pass before Phase 3 starts. Do not proceed with VS or FS implementation until message schemas are locked.

Phase 3 — Mock vendor supervisors (Day 2, ~4 hours).

Actions:
- Implement `MockVendorSupervisor(BaseVendorSupervisor)` parametrized by `domain_id`.
- `handle_task()` in mock: accepts any command, waits `parameters.get("mock_delay_sec", 1.0)` seconds, then publishes COMPLETED status with `resource_state="IDLE"`.
- Implement `base_vendor_supervisor.py`, `internal_bus.py`, `task_runner.py` (these are needed by MockVendorSupervisor since it extends BaseVendorSupervisor).
- Add `mock_vendor_supervisor` to `setup.py` entry_points, parametrized: `ros2 run shipyard_pnp mock_vendor_supervisor --ros-args -p domain_id:=niryo`.
- Launch all seven mocks: `launch/pnp_sim_smoke.launch.py`.

Tests:
```bash
# Manual smoke test for each domain
ros2 topic pub --once /niryo_factory/command std_msgs/msg/String \
  "{data: '{\"schema\":\"shipyard.pnp.command.v1\",\"command_id\":\"CMD-niryo-robot1-...\",\"domain_id\":\"niryo\",\"resource_id\":\"robot1\",\"task\":\"GOTO_PICK_POSITION\",\"parameters\":{\"position\":\"C4\"}}'}"
ros2 topic echo /niryo_factory/ack     # expect accepted=true within 0.5s
ros2 topic echo /niryo_factory/status  # expect COMPLETED within 2s
```
Repeat for all 7 domains. Property reached: coordination topology is correct before any hardware.

Phase 4 — Factory Supervisor + state + planner (Days 3-4, ~8 hours).

This is the largest phase. Proceed in this sub-order:

4a — Data layer:
- Implement `factory/state_tracker.py`.
- Implement `factory/piece_tracker.py` with mock db_writer (no real DB yet).
- Implement `factory/cycle_tracker.py`.
- Implement `factory/vendor_client.py` including PendingCommand dataclass.
- Unit-test: `pytest test/test_piece_tracker.py test/test_vendor_client.py`.

4b — Factory Supervisor shell:
- Implement `factory/factory_supervisor.py` with full pub/sub setup, callback groups, `_state_lock`, and `send_command()`.
- Implement `factory/system_state_publisher.py`.
- Implement `nodes/dashboard_node.py`.
- Implement `watchdog()` timer.
- Test: launch FS + all mocks. Verify `/factory/system_state` publishes every 2s.

4c — Planner rules:
- Implement `planner/initialization_rules.py` first. Test: FS boots, all seven mock domains receive INITIALIZE_DOMAIN, all ACK+COMPLETED, FS transitions to RUNNING.
- Implement `planner/feeding_rules.py`. Test: manually send globalvision LOCATE_NEXT_PIECE status; verify feeding_rules triggers xarm2 MOVE_PIECE.
- Implement `planner/conveyor_rules.py`. Test: manually publish sensor OCCUPIED; verify conveyor RUN command.
- Implement `planner/processing_rules.py`. Test: verify RED path sends MOVE_PIECE to laser domain before C2S1.
- Implement `planner/classification_rules.py`. Test: verify CAPTURE_LOCAL_VISION sent to niryo/robot2, then routing based on mocked color result.
- Implement `planner/unloading_rules.py`. Test: verify four-step vacuum+arm sequence for robot1.
- Implement `planner/shutdown_rules.py`.

4d — Full logical cycle test (with all mocks, no hardware):
```bash
ros2 launch shipyard_pnp pnp_sim_smoke.launch.py
# Check logs: FS should run a complete piece from initial_stack to final_stack
# using mock delays. Check /factory/system_state for pipeline advancement.
```
Expected: one full cycle completes in ~15 seconds (7 mock domains × 1-2s delay each).

Old code reference during Phase 4: read `supervisor/rules/robot1_rules.py`, `robot2_rules.py`, `xarm1_rules.py`, `feeding_rules.py`, `conveyor1_rules.py`, `conveyor2_rules.py` to extract workflow semantics. These files are NOT imported — they are read as human reference to understand trigger conditions and sequencing. Map each old state-transition to the new planner rule trigger conditions described in Part C sections 12-18.

Phase 5 — Hardware adapters one domain at a time (Days 5-10, ~2 hours per domain).

Replace mocks in this order (safest-first ordering):

5.1 — `arduino_vacuum`:
- Implement `arduino_vacuum_driver.py`. Connect physical vacuum Arduino.
- Launch `vendor_arduino_vacuum.launch.py` alongside remaining 6 mocks.
- Test: send PICK / RELEASE commands, verify vacuum activates physically.
- Confirm: `/arduino_vacuum_factory/status` never contains serial bytes, port names, or voltage readings.

5.2 — `green_conveyors`:
- Implement `shared_arduino_driver.py` porting from `green_conveyor_shared_driver_node.py`.
- Test: RUN_CONVEYOR / STOP_CONVEYOR physical test.

5.3 — `globalvision`:
- Implement `camera_adapter.py`, `slot_inventory.py`, `calibrator.py`. Port from `globalvision_node.py` and `globalvision_calibrator.py`.
- Test: SCAN_STACK returns normalized slot list with no raw image data in STATUS.
- Test: LOCATE_NEXT_PIECE returns slot_id for a RED piece.

5.4 — `laser`:
- Implement `laser_adapter.py`. Port from `laser_node.py`.
- Test: INITIALIZE_DOMAIN, RUN_JOB with a safe low-power test job.

5.5 — `bantam`:
- Implement `bantam_adapter.py`, `door_adapter.py`. Port from `bantam_node.py`.
- Test: OPEN_DOOR, CLOSE_DOOR, GET_READY.

5.6 — `ufactory`:
- Implement `xarm1_adapter.py`, `xarm2_adapter.py`. Port positions from `xarm1_node.py` and `xarm2_node.py`.
- Test: INITIALIZE_DOMAIN (go home), then MOVE_PIECE on a single arm with a dummy piece.
- IMPORTANT: verify gripper open/close calls use the exact same service clients as old `xarm1_node.py`.

5.7 — `niryo` (largest, most complex, do last):
- Implement all adapters: `robot1_adapter.py`, `robot2_adapter.py`, `niryo_conveyor_adapter.py`, `niryo_ir_adapter.py`, `local_vision_adapter.py`, `robot2_niryo_vacuum_adapter.py`.
- Port joint positions verbatim from `robot1_node.py` and `robot2_node.py`.
- Test each resource independently:
  ```bash
  ros2 topic pub --once /niryo_factory/command ... resource_id=robot1 task=INITIALIZE_DOMAIN
  ros2 topic pub --once /niryo_factory/command ... resource_id=robot2 task=INITIALIZE_DOMAIN
  ros2 topic pub --once /niryo_factory/command ... resource_id=conveyor1 task=RUN_NIRYO_CONVEYOR
  ```
- Test CAPTURE_LOCAL_VISION: verify STATUS contains `color` and `shape` but no HSV data.
- Test GOTO_PICK_POSITION + LIFT_AND_PLACE + RETURN_HOME sequence manually.

Phase 6 — Full physical integration (Day 11).

- `ros2 launch shipyard_pnp pnp_full_system.launch.py`
- Load initial stack with 5 pieces (e.g., GREEN, GREEN, RED, BLUE, BLUE — same as old INITIAL_STACK_ORDER).
- Observe FS logs: should see BOOT → INITIALIZING → RUNNING.
- Monitor `/factory/system_state` (use `ros2 topic echo` or dashboard).
- Record rosbag: `ros2 bag record /niryo_factory/command /niryo_factory/ack /niryo_factory/status /ufactory_factory/command /ufactory_factory/ack /ufactory_factory/status /laser_factory/command /laser_factory/ack /laser_factory/status /globalvision_factory/command /globalvision_factory/ack /globalvision_factory/status /green_conveyors_factory/command /green_conveyors_factory/ack /green_conveyors_factory/status /arduino_vacuum_factory/command /arduino_vacuum_factory/ack /arduino_vacuum_factory/status /bantam_factory/command /bantam_factory/ack /bantam_factory/status /factory/system_state`
- Enable HMAC enforcement (set `hmac_enforce: true` in config).
- Run validation checklist from Part E.

Phase 7 — Documentation and compliance evidence.

- Save `ros2 topic list | grep '_factory/'` output.
- Save topic graph PNG: `ros2 run rqt_graph rqt_graph`.
- Save `topic_acl.yaml`, `vendor_registry.yaml`, message schema examples.
- Save test output from `pytest`.
- Save rosbag from Phase 6.
- Run proprietary confinement grep (Part E test 5).
- This constitutes the MOSA runtime-boundary evidence packet.

PART E — VALIDATION CHECKLIST

1. Topic count.

Expected: exactly 21 vendor coordination topics.

```bash
ros2 topic list | grep '_factory/' | sort
```

2. Resource ID routing.

Expected: robot1 and robot2 commands produce different command IDs and route to the same `niryo` topic but different `resource_id`.

```bash
python3 -m pytest shipyard_plug_and_plan/test/test_resource_routing.py
```

3. UFactory does not contain laser.

Expected: no import from `vendors.laser` inside `vendors.ufactory`.

```bash
grep -R "vendors.laser\\|laser_adapter\\|laser_factory" shipyard_plug_and_plan/shipyard_pnp/vendors/ufactory
```

The command should return no matches.

4. Robot vacuum split.

Expected:

- `niryo/robot2` tasks may call `robot2_niryo_vacuum_adapter`.
- `niryo/robot1` tasks do not call Arduino serial or robot2 vacuum.
- Arduino vacuum is commanded only through `/arduino_vacuum_factory/command`.

```bash
python3 -m pytest shipyard_plug_and_plan/test/test_proprietary_confinement.py
```

5. Global vision confinement.

Expected: `/globalvision_factory/status` may contain normalized slots but never raw frames/HSV/ROI pixels.

```bash
timeout 10s ros2 topic echo /globalvision_factory/status > /tmp/gv_status.txt
grep -Ei "raw_image|image|frame|hsv|mask|contour|roi_pixels|model" /tmp/gv_status.txt
```

The grep should return no matches.

6. Fault containment.

Kill one vendor and verify another keeps responding:

```bash
pkill -f globalvision_vendor_supervisor
ros2 topic pub --once /ufactory_factory/command std_msgs/msg/String "{data: '<valid command for ufactory/xarm1>'}"
```

Expected: UFactory ACK/status still works; Factory Supervisor marks only `globalvision` offline.

7. Greenfield no old imports.

Expected: the new package imports nothing from `shipyard_core`.

```bash
python3 -m pytest shipyard_plug_and_plan/test/test_greenfield_no_old_imports.py
grep -R "shipyard_core" shipyard_plug_and_plan/shipyard_pnp
```

The grep should return no matches except comments that explicitly say "reference only"; preferably no matches at all.

8. MOSA evidence.

Collect:

- `vendor_registry.yaml`
- `topic_acl.yaml`
- command/ACK/status schemas
- `ros2 topic list | grep '_factory/'`
- rosbag with all seven domains
- test logs proving resource routing, no old imports, no proprietary leakage, vendor-kill containment

PART F — COMPLETE PRODUCTION WORKFLOW DECISION TREE

NOTE ON ENCODER-PLANNER-DECODER: the paper introduces an E-P-D pipeline for its 11-robot testbed because it has AGVs doing variable routing through a large graph. This system has three fixed physical paths determined by color. The rules-based planner modules in Part C are the correct implementation — the E-P-D would add abstraction without adding value here. Do not implement E-P-D.

CRITICAL CORRECTION vs earlier draft: GREEN pieces do NOT go through conveyor1 → xarm1 → conveyor2 → robot2. GREEN pieces go directly to conveyor3 (green_conveyors domain) from xarm2. The routing decision happens at FEEDING TIME, not at classification time, because globalvision already knows the color before xarm2 picks. This means xarm2 places at different physical targets depending on color.

Three physical paths:
- RED:   xarm2→C1S1 → conveyor1 → xarm1→LASER_BED → laser → xarm1→C2S1 → conveyor2 → robot2 picks C2S2 → robot2 places C4 → robot1 picks C4 → final_red_stack
- BLUE:  xarm2→C1S1 → conveyor1 → xarm1→C2S1 → conveyor2 → robot2 picks C2S2 → robot2 places BANTAM → bantam → robot2 picks BANTAM → robot2 places C4 → robot1 picks C4 → final_blue_stack
- GREEN: xarm2→CONVEYOR3_ENTRY → conveyor3 → [exit position] → robot1 picks → final_green_stack

This also means:
- For GREEN pieces, xarm1, conveyor1, conveyor2, robot2, laser, bantam are NEVER used.
- The CAPTURE_LOCAL_VISION step for robot2 is only needed for RED and BLUE (to confirm color before placing at C4 — but since color was already known from globalvision, this may be used only as a verification step, not the primary routing decision).
- The `classification_rules.py` planner is simplified: it only handles RED→C4 and BLUE→BANTAM→C4. GREEN never reaches C2S2.
- The `feeding_rules.py` planner must read the piece color from globalvision result and set `target = C1S1` (RED/BLUE) or `target = CONVEYOR3_ENTRY` (GREEN).

Verify the exact conveyor3 entry position and robot1 pick position for GREEN pieces by reading old `robot1_rules.py` and `feeding_rules.py`.

F.1 — System boot (all colors):

```
FS: BOOT phase
  → send arduino_vacuum/arduino_vacuum  INITIALIZE_DOMAIN
  → send green_conveyors/conveyor3      INITIALIZE_DOMAIN
  → send globalvision/globalvision_camera INITIALIZE_DOMAIN
  → send ufactory/xarm1                 INITIALIZE_DOMAIN
  → send niryo/robot1                   INITIALIZE_DOMAIN
  → send laser/laser                    INITIALIZE_DOMAIN
  → send bantam/bantam                  INITIALIZE_DOMAIN
  [all 7 domains online] → planner_phase = RUNNING
```

F.2 — Feeding — color-aware routing decision at xarm2:

```
Trigger: initial_stack non-empty, xarm2 IDLE, ufactory not busy,
         AND (c1s1 FREE [for RED/BLUE] OR conveyor3_entry FREE [for GREEN])

FS → globalvision/globalvision_camera: LOCATE_NEXT_PIECE
     parameters={"color": pieces.peek_first_piece_color("initial_stack")}
  ← STATUS COMPLETED result={"slot_id": "s2.4", "color": "RED", "shape": "CIRCLE"}

FS: color = result["color"]
    pieces.assign_slot("s2.4")
    pieces.assign_color_shape("initial_stack", color, result["shape"])

    if color == "GREEN":
        target = "C3"   # old code name: PLACING_C3_DONE — entry of conveyor3 / green path
    else:  # RED or BLUE
        target = "C1S1"

FS → ufactory/xarm2: MOVE_PIECE source=INITIAL_STACK target=<target>
     parameters={"pick_slot": "s2.4"}
  ← STATUS COMPLETED resource_state=PLACE_DONE

if color == "GREEN":
    FS: pieces.transfer_piece("initial_stack", "c3")
        state.update_sensor("c3", OCCUPIED)
    → go to F.5 (GREEN path via conveyor3 → robot1 picks C3)
else:
    FS: pieces.transfer_piece("initial_stack", "conveyor1")
    → go to F.3 (RED) or F.4 (BLUE)
```

F.3 — Processing RED (via laser):

```
Trigger: conveyor1 non-empty AND piece color == RED, c1s2 FREE, xarm1 IDLE, ufactory not busy

FS → niryo/conveyor1: RUN_NIRYO_CONVEYOR parameters={"conveyor_id": "conveyor1"}
  ← STATUS COMPLETED resource_state=STOPPED reason=SENSOR_TRIGGERED
FS: state.update_sensor("c1s2", OCCUPIED)

FS → ufactory/xarm1: MOVE_PIECE source=C1S2 target=LASER_BED
  ← STATUS COMPLETED resource_state=PLACE_DONE
FS: pieces.transfer_piece("conveyor1", "laser_bed")
    state.update_sensor("c1s2", FREE)

FS → laser/laser: RUN_JOB parameters={"job_type": "RED_PROCESS"}
  ← STATUS COMPLETED resource_state=FINISHED

FS → ufactory/xarm1: MOVE_PIECE source=LASER_BED target=C2S1
  ← STATUS COMPLETED resource_state=PLACE_DONE
FS: pieces.transfer_piece("laser_bed", "conveyor2")
    → go to F.6 (robot2 pick from conveyor2, RED→C4)
```

F.4 — Processing BLUE (no laser, direct to conveyor2):

```
Trigger: conveyor1 non-empty AND piece color == BLUE, c1s2 FREE, xarm1 IDLE, ufactory not busy

FS → niryo/conveyor1: RUN_NIRYO_CONVEYOR parameters={"conveyor_id": "conveyor1"}
  ← STATUS COMPLETED resource_state=STOPPED
FS: state.update_sensor("c1s2", OCCUPIED)

FS → ufactory/xarm1: MOVE_PIECE source=C1S2 target=C2S1
  ← STATUS COMPLETED resource_state=PLACE_DONE
FS: pieces.transfer_piece("conveyor1", "conveyor2")
    state.update_sensor("c1s2", FREE)
    → go to F.6 (robot2 pick from conveyor2, BLUE→BANTAM→C4)
```

F.5 — GREEN path via conveyor3 → robot1 picks from C3:

In the old codebase, xarm2's place position for GREEN is called "C3" (states: `MOVING_TO_C3`, `PLACING_C3_DONE`), and robot1's pick position for GREEN is also called "C3" (states: `AT_CAPTURE_C3`, `GOING_TO_PICK_C3`, `PICKING_C3`, `PICKING_C3_DONE`). This is a shared location name — xarm2 places at the entry of conveyor3, the conveyor runs, and robot1 picks from the C3 exit zone (both labeled "C3" in the positions dict). Verify exact joint coordinates by reading old `robot1_node.py` and `xarm2_node.py` `self.positions` dicts.

```
Trigger: c3 OCCUPIED (conveyor3 non-empty — piece placed by xarm2)

FS → green_conveyors/conveyor3: RUN_CONVEYOR
  ← STATUS COMPLETED resource_state=STOPPED
     [green_conveyors VS stops when C3 sensor triggers at robot1 pick zone]
     [confirm stop logic from old green_conveyor_shared_driver_node.py]

[piece is now at C3 pick zone — robot1 pick position for GREEN]

Trigger: c3 OCCUPIED at robot1 pick zone, robot1 IDLE, niryo not busy, arduino_vacuum not busy

shape = pieces.get_shape("c3")  # already known from globalvision F.2
final_target = f"FINAL_GREEN_{shape}_STACK"  # e.g. FINAL_GREEN_CIRCLE_STACK

FS → niryo/robot1: GOTO_PICK_POSITION parameters={"position": "C3"}
  ← STATUS COMPLETED resource_state=AT_PICK_POSITION

FS → arduino_vacuum/arduino_vacuum: PICK
  ← STATUS COMPLETED resource_state=PICK_DONE

FS → niryo/robot1: LIFT_AND_PLACE parameters={"target": final_target}
  ← STATUS COMPLETED resource_state=AT_PLACE_POSITION

FS → arduino_vacuum/arduino_vacuum: RELEASE
  ← STATUS COMPLETED resource_state=RELEASE_DONE
FS: pieces.transfer_piece("c3", final_target.lower())
    state.update_sensor("c3", FREE)

FS → niryo/robot1: RETURN_HOME
  ← STATUS COMPLETED resource_state=IDLE
FS: cycles.complete_cycle(piece_id, "GREEN", shape, "GREEN_VIA_CONVEYOR3")
```

NOTE ON SHAPE-AWARE PLACEMENT: Robot1 has separate joint positions per color AND shape (e.g. PLACE_GREEN_FINAL_CIRCLE, PLACE_GREEN_FINAL_SQUARE). The shape is known from globalvision in step F.2. Pass shape in the LIFT_AND_PLACE parameters so the niryo VS can select the correct joint position. Verify the exact position names from old `robot1_node.py` `self.positions` dict and replicate them verbatim in `robot1_adapter.py`.

F.6 — Classification and unloading RED and BLUE (from conveyor2):

```
Trigger: conveyor2 non-empty, c2s2 FREE

FS → niryo/conveyor2: RUN_NIRYO_CONVEYOR parameters={"conveyor_id": "conveyor2"}
  ← STATUS COMPLETED resource_state=STOPPED reason=SENSOR_TRIGGERED
FS: state.update_sensor("c2s2", OCCUPIED)

color = pieces.peek_first_piece_color("conveyor2")
```

F.6a — RED path (color already known — vision is VERIFICATION only):

```
[Optional: FS → niryo/robot2: CAPTURE_LOCAL_VISION for confirmation]
[If skipped: trust globalvision color from F.2]

FS → niryo/robot2: MOVE_PIECE source=C2S2 target=C4
  ← STATUS COMPLETED resource_state=PLACE_DONE
FS: pieces.transfer_piece("conveyor2", "c4_location")
    state.update_sensor("c2s2", FREE)
    state.update_sensor("c4", OCCUPIED)
    → go to F.7 (robot1 unload from C4, RED)
```

F.6b — BLUE path (via Bantam):

```
FS → niryo/robot2: MOVE_PIECE source=C2S2 target=BANTAM_BED
  ← STATUS COMPLETED resource_state=PLACE_DONE
FS: pieces.transfer_piece("conveyor2", "bantam_bed")
    state.update_sensor("c2s2", FREE)

FS → bantam/bantam: RUN_JOB parameters={"job_type": "BLUE_PROCESS"}
  ← STATUS COMPLETED resource_state=FINISHED

FS → niryo/robot2: MOVE_PIECE source=BANTAM_BED target=C4
  ← STATUS COMPLETED resource_state=PLACE_DONE
FS: pieces.transfer_piece("bantam_bed", "c4_location")
    state.update_sensor("c4", OCCUPIED)
    → go to F.7 (robot1 unload from C4, BLUE)
```

F.6c — UNKNOWN color (scrap):

```
FS → niryo/robot2: MOVE_PIECE source=C2S2 target=SCRAP
  ← STATUS COMPLETED resource_state=PLACE_DONE
FS: pieces.transfer_piece("conveyor2", "robot2_scrap")
    state.update_sensor("c2s2", FREE)
```

F.7 — Unloading from C4 (RED or BLUE):

```
Trigger: c4 OCCUPIED, robot1 IDLE, niryo not busy, arduino_vacuum not busy

color = pieces.peek_first_piece_color("c4_location")
shape = pieces.get_shape("c4_location")  # from globalvision step F.2
# Robot1 has separate positions per color AND shape — e.g. PLACE_RED_FINAL_CIRCLE, PLACE_BLUE_FINAL_SQUARE
# Verify exact position names from old robot1_node.py self.positions dict
final_target = f"FINAL_{color}_{shape}_STACK"

FS → niryo/robot1: GOTO_PICK_POSITION parameters={"position": "C4"}
  ← STATUS COMPLETED resource_state=AT_PICK_POSITION

FS → arduino_vacuum/arduino_vacuum: PICK
  ← STATUS COMPLETED resource_state=PICK_DONE

FS → niryo/robot1: LIFT_AND_PLACE parameters={"target": final_target, "color": color, "shape": shape}
  ← STATUS COMPLETED resource_state=AT_PLACE_POSITION

FS → arduino_vacuum/arduino_vacuum: RELEASE
  ← STATUS COMPLETED resource_state=RELEASE_DONE
FS: pieces.transfer_piece("c4_location", final_target.lower())
    state.update_sensor("c4", FREE)

FS → niryo/robot1: RETURN_HOME
  ← STATUS COMPLETED resource_state=IDLE
FS: cycles.complete_cycle(piece_id, color, shape, route)
```

F.8 — Shutdown:

```
FS: planner_phase = SHUTTING_DOWN
→ send niryo/conveyor1:            STOP_NIRYO_CONVEYOR
→ send niryo/conveyor2:            STOP_NIRYO_CONVEYOR
→ send green_conveyors/conveyor3:  STOP_CONVEYOR
→ send green_conveyors/conveyor4:  STOP_CONVEYOR  [if used]
→ send arduino_vacuum/arduino_vacuum: OFF
→ send niryo/robot1:   RETURN_HOME  (if not IDLE)
→ send niryo/robot2:   RETURN_HOME  (if not IDLE)
→ send ufactory/xarm1: MOVE_XARM_HOME
→ send ufactory/xarm2: MOVE_XARM_HOME
[all completed] → planner_phase = STOPPED
```

F.9 — Planner rule impact of GREEN correction:

The GREEN correction changes these planner modules vs earlier draft:

`feeding_rules.py`: add color-based routing fork. After globalvision returns color, set `xarm2_target = "C3"` for GREEN, `"C1S1"` for RED/BLUE. The C3 position is where xarm2 places the piece onto the conveyor3 entry (old code: `PLACING_C3_DONE` state).

`conveyor_rules.py`: add `conveyor3` run rule triggered by `c3 OCCUPIED` (after xarm2 places GREEN piece there). The trigger for conveyor1/2 is unchanged.

`processing_rules.py`: gate RED and BLUE paths only. GREEN pieces NEVER trigger this module. Add precondition: `pieces.peek_first_piece_color("conveyor1") in ("RED", "BLUE")`.

`classification_rules.py`: handles only RED and BLUE arriving at C2S2. GREEN NEVER reaches C2S2. Remove any GREEN routing logic from this module.

`unloading_rules.py`: now has TWO separate pick-point triggers:
- Trigger A: `c4 OCCUPIED` → unload RED or BLUE from C4 (F.7). Final target is `FINAL_{color}_{shape}_STACK`.
- Trigger B: `c3 OCCUPIED` at robot1 pick zone → unload GREEN from C3 (F.5). Final target is `FINAL_GREEN_{shape}_STACK`.
- Robot1 has separate joint positions per color AND shape (CIRCLE vs SQUARE). Read all positions verbatim from old `robot1_node.py` `self.positions` and copy into `robot1_adapter.py`.

`factory_layout.yaml` `color_routes` corrected (already fixed in C-CONFIG-2 section):
```yaml
color_routes:
  RED:   ["initial_stack", "conveyor1", "laser_bed", "conveyor2", "c4_location", "final_red_stack"]
  BLUE:  ["initial_stack", "conveyor1", "conveyor2", "bantam_bed", "c4_location", "final_blue_stack"]
  GREEN: ["initial_stack", "c3", "final_green_stack"]
```

F.10 — Domain contention rules (niryo domain with multiple resources):

Since the FS has one VendorClient per domain (one pending command slot per domain), the following mutual exclusion rules apply:
- robot1 and robot2 CANNOT execute simultaneously — both are in niryo domain.
- conveyor1 and conveyor2 commands also compete with robot commands in the niryo domain.
- Implication: the planner evaluate_rules() checks `vendor_clients["niryo"].is_busy()` as a gate for ALL niryo rules. Only one runs at a time.
- GREEN path benefit: the GREEN path uses green_conveyors domain (not niryo) for the conveyor step, so GREEN conveyor3 CAN run concurrently with niryo robot operations. This is the main throughput advantage of the separate green_conveyors domain.
- This is a known throughput limitation for RED/BLUE. Can be addressed in future by per-resource VendorClient slots.

PART G — DATABASE SCHEMA

PostgreSQL schema for `shipyard_pnp` database. The DB is created once manually; `db_writer.py` only inserts rows.

```sql
-- Run once to create schema:

CREATE TABLE piece_transfers (
    id              SERIAL PRIMARY KEY,
    piece_id        VARCHAR(20) NOT NULL,
    color           VARCHAR(10),
    shape           VARCHAR(20),
    from_location   VARCHAR(40) NOT NULL,
    to_location     VARCHAR(40) NOT NULL,
    transferred_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    piece_age_sec   FLOAT,
    history_json    JSONB
);

CREATE INDEX idx_pt_piece_id   ON piece_transfers(piece_id);
CREATE INDEX idx_pt_transferred ON piece_transfers(transferred_at);

CREATE TABLE cycle_records (
    id              SERIAL PRIMARY KEY,
    piece_id        VARCHAR(20) NOT NULL,
    color           VARCHAR(10),
    shape           VARCHAR(20),
    route           VARCHAR(30),   -- e.g. "RED_VIA_LASER", "GREEN_DIRECT", "BLUE_VIA_BANTAM"
    started_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ NOT NULL,
    cycle_time_sec  FLOAT NOT NULL
);

CREATE INDEX idx_cr_completed ON cycle_records(completed_at);

CREATE TABLE coordination_log (
    id              SERIAL PRIMARY KEY,
    command_id      VARCHAR(80) NOT NULL,
    correlation_id  VARCHAR(60),
    domain_id       VARCHAR(30) NOT NULL,
    resource_id     VARCHAR(30) NOT NULL,
    task            VARCHAR(40) NOT NULL,
    task_state      VARCHAR(20),   -- COMPLETED, FAILED, TIMEOUT, etc.
    issued_at       TIMESTAMPTZ NOT NULL,
    ack_at          TIMESTAMPTZ,
    status_at       TIMESTAMPTZ,
    ack_latency_ms  FLOAT,
    total_latency_ms FLOAT,
    result_json     JSONB
);
-- Optional: insert into coordination_log from FS on every STATUS received.
-- Provides the T_coord measurement data from paper Section 6.3.

CREATE INDEX idx_cl_domain ON coordination_log(domain_id);
CREATE INDEX idx_cl_issued  ON coordination_log(issued_at);
```

`db_writer.py` methods:
- `insert_piece_transfer(piece, from_loc, to_loc)` → inserts into `piece_transfers`
- `insert_cycle_complete(record: CycleRecord)` → inserts into `cycle_records`
- `insert_coordination_event(command_id, domain_id, resource_id, task, task_state, issued_at, ack_at, status_at, result_json)` → inserts into `coordination_log`

Old reference: old `supervisor/db_writer.py` had `insert_piece_transfer()`. Port that method. Add `insert_cycle_complete()` and `insert_coordination_event()` as new methods. The DSN comes from `config/hardware_ports.yaml` under `database.dsn`.
