import json
import threading
import time
from typing import Optional

import rclpy
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from shipyard_pnp.factory import (
    cycle_tracker,
    db_writer,
    piece_tracker,
    state_tracker,
    system_state_publisher,
    vendor_client,
)
from shipyard_pnp.factory.planner import (
    classification_rules,
    conveyor_rules,
    feeding_rules,
    initialization_rules,
    processing_rules,
    shutdown_rules,
    unloading_rules,
)
from shipyard_pnp.shared.acl_guard import check_outbound as _acl_check_outbound
from shipyard_pnp.shared.contracts import (
    DOMAIN_ACK_TOPIC,
    DOMAIN_COMMAND_TOPIC,
    DOMAIN_IDS,
    DOMAIN_STATUS_TOPIC,
    ConveyorState,
    MachineState,
    PlannerPhase,
    RobotState,
    SensorState,
    TaskState,
    VacuumState,
    VisionState,
)

# Define aquí las piezas que el xArm2 debe coger del stack inicial.
# color/shape son opcionales: si se especifican, se usan como hint para globalvision.
# Si se omiten (None), globalvision los detecta automáticamente con visión.
INITIAL_STACK_ORDER = (
    [{"id": f"piece-{i:03d}", "color": "RED",   "shape": None} for i in range(1, 7)]
    + [{"id": f"piece-{i:03d}", "color": "BLUE",  "shape": None} for i in range(7, 13)]
    + [{"id": f"piece-{i:03d}", "color": "GREEN", "shape": None} for i in range(13, 19)]
)

# entity -> gripper location in piece_tracker.PIPELINE_LOCATIONS. Used by
# register_pick_source/_apply_resource_state to move a piece OUT of its
# source queue (EXPECTED) the instant the real robot reports PICK_DONE,
# instead of leaving it there until the whole pick+travel+place(+home)
# command finishes -- see register_pick_source below and
# piece_tracker.PieceTracker.transfer_via_gripper.
_GRIPPER_LOCATION = {
    "robot1": "robot1_gripper",
    "robot2": "robot2_gripper",
    "xarm1": "xarm1_gripper",
    "xarm2": "xarm2_gripper",
}


class FactorySupervisor(Node):
    """
    MES-level coordinator for the Plug-and-Plan architecture.

    Owns command correlation, coarse resource state, piece/cycle tracking, and
    planner dispatch. Vendor-internal details stay behind vendor supervisors.
    """

    def __init__(self):
        super().__init__("factory_supervisor")
        self.declare_parameter("boot_grace_sec", 2.0)

        self.ack_status_cbg = ReentrantCallbackGroup()
        self.planner_cbg = MutuallyExclusiveCallbackGroup()
        self.watchdog_cbg = MutuallyExclusiveCallbackGroup()
        self.dashboard_cbg = MutuallyExclusiveCallbackGroup()
        self.order_cbg = MutuallyExclusiveCallbackGroup()

        # RLock allows terminal STATUS callbacks to advance chained commands.
        self._state_lock = threading.RLock()

        self.state = state_tracker.StateTracker()
        self.db = db_writer.RealDBWriter(
            INITIAL_STACK_ORDER,
            config_snapshot={
                "c3_settle_sec":  self.c3_settle_sec if hasattr(self, "c3_settle_sec") else 10.0,
                "c4_settle_sec":  self.c4_settle_sec if hasattr(self, "c4_settle_sec") else 14.5,
                "boot_grace_sec": (
                    self.get_parameter("boot_grace_sec").get_parameter_value().double_value
                    if self.has_parameter("boot_grace_sec") else 2.0
                ),
            },
        )
        self.pieces = piece_tracker.PieceTracker(INITIAL_STACK_ORDER, self.db)
        self.cycles = cycle_tracker.CycleTracker()

        # slot_id -> {"color":..., "shape":...}, fed by the external vision
        # process (ml_node.py, runs on a separate computer) publishing on the
        # bare "stack_status" topic. Our own GlobalVision camera_adapter only
        # detects color/occupancy live (shape is intentionally not inferred
        # there) -- this map is the sole source of real shape for
        # initial_stack pieces (see feeding_rules.py::_on_locate_complete),
        # and also feeds the dashboard's initial-stack visualization
        # (get_stack_status_full -> /factory/system_state -> dashboard_node.py).
        self._stack_status: dict = {}

        # entity -> source location for a MOVE_PIECE-type command currently
        # in flight (pick+travel+place as ONE vendor command). Consumed in
        # _apply_resource_state the instant that entity's resource_state
        # reaches PICK_DONE. See register_pick_source.
        self._inflight_pick_source: dict = {}

        # entity -> target location for the same in-flight command,
        # consumed at PLACE_DONE (see register_place_target). Needed
        # because several vendor adapters (xarm1_adapter.py::_place_to_c2s1/
        # _place_to_laser, xarm2_adapter.py::_place_to_c1s1,
        # robot2_adapter.py's BANTAM/IBS/SCRAP placements) call move_home()
        # INSIDE the same command right after PLACE_DONE, so the command's
        # own on_complete/task_state==COMPLETED callback -- where the piece
        # used to get transferred to the target queue -- doesn't fire until
        # the robot is back home. Reacting to PLACE_DONE directly instead
        # (a real STATUS event, not a polled snapshot) fixes it regardless
        # of what a given adapter does after placing.
        self._inflight_place_target: dict = {}

        # entity -> True once the PLACE_DONE hook above has ALREADY done the
        # gripper->target transfer for the current dispatch. BUG FOUND
        # 2026-07-07 (real DB evidence, piece-001 GREEN got dragged through
        # conveyor1/laser_bed/conveyor2/c4_location behind piece-002 RED):
        # without this flag, the command's own on_complete callback still
        # unconditionally called transfer_via_gripper() too -- by the time
        # it fired (after the adapter's internal move_home), the gripper was
        # ALREADY empty (this hook emptied it minutes^Wseconds earlier), so
        # transfer_via_gripper's fallback kicked in and popped whatever
        # piece happened to be sitting at the head of source_loc NOW (an
        # unrelated piece waiting for a LATER dispatch) into target_loc.
        # consume_place_done_flag() lets on_complete skip its own transfer
        # entirely when this hook already handled it.
        self._place_done_via_hook: dict = {}

        self.vendor_clients = {}
        self._command_publishers = {}
        self._ack_subscriptions = []
        self._status_subscriptions = []

        self.planner_phase = PlannerPhase.BOOT
        self._init_started = False
        self._feeding_state = "IDLE"
        self._processing_state = "IDLE"
        self._classification_state = "IDLE"
        self._unloading_state = "IDLE"
        self._shutdown_state = "IDLE"
        self._shutdown_step = 0
        self._pending_laser_piece_id: Optional[str] = None
        self._pending_bantam_piece: Optional[str] = None
        self._last_state_log: float = 0.0

        # Timestamps of the last C3/C4 deposit; robot1 waits until settle_sec has elapsed.
        self._c3_deposit_time: float = 0.0
        self._c4_deposit_time: float = 0.0
        self.c3_settle_sec: float = 10.0
        self.c4_settle_sec: float = 14.5
        self._optimized_order = list(INITIAL_STACK_ORDER)
        self._init_wait_logged_domains = set()

        # Map-guided tie-breaking: physical readiness is checked exactly as
        # before and ALWAYS gates first (nothing here can make an entity act
        # before its normal preconditions are met). When TWO options are
        # simultaneously valid, or one option's map-predicted alternative
        # isn't ready yet, this schedule breaks the tie / grants a grace
        # period -- see FactorySupervisor._map_next/_map_should_wait/
        # _map_note_dispatch and their call sites in the planner rules.
        self.declare_parameter("map_guidance_enabled", True)
        self._map_guidance_enabled = bool(
            self.get_parameter("map_guidance_enabled").get_parameter_value().bool_value
        )
        self.MAP_GRACE_SEC = 10.0
        self._expected_schedule: dict = {}
        self._map_pointer: dict = {}
        self._map_wait_since: dict = {}
        self._map_last_wait_duration: dict = {}
        self._map_last_dispatch_info: dict = {}
        boot_grace_sec = (
            self.get_parameter("boot_grace_sec")
            .get_parameter_value()
            .double_value
        )
        self._boot_ready_at = time.time() + boot_grace_sec
        self._boot_wait_logged = False

        self._hmac_secrets = self._load_hmac_secrets()
        self._setup_vendor_clients()
        self._setup_pub_sub()

        self.sys_state_pub = system_state_publisher.SystemStatePublisher(
            self._sys_state_ros_pub,
            self.state,
            self.pieces,
            self.cycles,
            self.vendor_clients,
            initial_order=[
                e.get("color") if isinstance(e, dict) else e
                for e in INITIAL_STACK_ORDER
            ],
            get_planner_phase=lambda: self.planner_phase.value,
            get_stack_status=self.get_stack_status_full,
        )

        self.create_timer(0.5,  self.evaluate_rules,          callback_group=self.planner_cbg)
        self.create_timer(1.0,  self.watchdog,                 callback_group=self.watchdog_cbg)
        self.create_timer(0.5,  self._publish_system_state,    callback_group=self.dashboard_cbg)
        self.create_timer(5.0,  self._publish_run_id,          callback_group=self.dashboard_cbg)
        self.create_timer(10.0, self._sample_queue_depths,     callback_group=self.planner_cbg)

        self.get_logger().info(f"FactorySupervisor initialized  run_id={self.db.run_id}")

    # ------------------------------------------------------------------
    # ROS setup
    # ------------------------------------------------------------------

    def _load_hmac_secrets(self) -> dict:
        """Load per-domain HMAC secrets from config/hmac_secrets.yaml."""
        import yaml
        try:
            from ament_index_python.packages import get_package_share_directory
            cfg = get_package_share_directory("shipyard_pnp") + "/config/hmac_secrets.yaml"
        except Exception:
            cfg = ""
        if not cfg or not __import__("os").path.isfile(cfg):
            self.get_logger().warning(
                "hmac_secrets.yaml not found — commands will be sent unsigned"
            )
            return {}
        try:
            import yaml
            with open(cfg) as fh:
                data = yaml.safe_load(fh) or {}
            self.get_logger().info(
                f"HMAC secrets loaded for {len(data)} domains: {list(data.keys())}"
            )
            return data
        except Exception as exc:
            self.get_logger().warning(f"Failed to load hmac_secrets.yaml: {exc}")
            return {}

    def _setup_vendor_clients(self) -> None:
        for domain_id in DOMAIN_IDS:
            pub = self.create_publisher(String, DOMAIN_COMMAND_TOPIC[domain_id], 10)
            self._command_publishers[domain_id] = pub
            overrides = {}
            if domain_id == "laser":
                overrides["RUN_JOB"] = 300.0
            elif domain_id == "bantam":
                overrides["RUN_JOB"] = 600.0
            self.vendor_clients[domain_id] = vendor_client.VendorClient(
                domain_id=domain_id,
                publisher=pub,
                hmac_secret=self._hmac_secrets.get(domain_id, ""),
                status_timeout_overrides=overrides,
                concurrent_resources=(domain_id in {"ufactory", "niryo"}),
            )

    def _setup_pub_sub(self) -> None:
        for domain_id in DOMAIN_IDS:
            self._ack_subscriptions.append(
                self.create_subscription(
                    String,
                    DOMAIN_ACK_TOPIC[domain_id],
                    lambda msg, d=domain_id: self.on_ack(d, msg),
                    10,
                    callback_group=self.ack_status_cbg,
                )
            )
            self._status_subscriptions.append(
                self.create_subscription(
                    String,
                    DOMAIN_STATUS_TOPIC[domain_id],
                    lambda msg, d=domain_id: self.on_status(d, msg),
                    10,
                    callback_group=self.ack_status_cbg,
                )
            )

        from rclpy.qos import QoSProfile, DurabilityPolicy
        _latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self._run_id_pub = self.create_publisher(String, "/factory/run_id", _latched)
        self._sys_state_ros_pub = self.create_publisher(String, "/factory/system_state", 10)
        self._acl_event_pub = self.create_publisher(String, "/shipyard/acl_events", 10)
        self._order_sub = self.create_subscription(
            String,
            "/supervisor/set_optimized_order",
            self._on_optimized_order,
            10,
            callback_group=self.order_cbg,
        )
        self._stack_status_sub = self.create_subscription(
            String,
            "stack_status",
            self._on_stack_status,
            10,
            callback_group=self.ack_status_cbg,
        )

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def send_command(
        self,
        domain_id: str,
        resource_id: str,
        task: str,
        piece_id: Optional[str] = None,
        source: Optional[str] = None,
        target: Optional[str] = None,
        route: Optional[str] = None,
        parameters: Optional[dict] = None,
        correlation_id: Optional[str] = None,
        on_complete=None,
    ) -> str:
        with self._state_lock:
            vc = self.vendor_clients[domain_id]
            if vc.is_busy(resource_id):
                raise RuntimeError(
                    f"VendorClient '{domain_id}/{resource_id}' is busy; planner must wait"
                )
            command_id = vc.send_command(
                resource_id=resource_id,
                task=task,
                piece_id=piece_id,
                source=source,
                target=target,
                route=route,
                parameters=parameters,
                correlation_id=correlation_id,
                on_complete=on_complete,
            )
        self.db.insert_command(
            command_id=command_id,
            domain_id=domain_id,
            resource_id=resource_id,
            task_name=task,
            piece_id=piece_id,
            source=source,
            target=target,
            route=route,
            parameters=parameters,
            correlation_id=correlation_id,
        )
        return command_id

    def command_subscriber_count(self, domain_id: str) -> int:
        pub = self._command_publishers.get(domain_id)
        if pub is None:
            return 0
        return pub.get_subscription_count()

    # ------------------------------------------------------------------
    # Incoming vendor messages
    # ------------------------------------------------------------------

    def _publish_acl_event(
        self,
        command_id: str,
        sender_id: str,
        topic: str,
        reason: str,
        latency_us: float,
    ) -> None:
        event = {
            "event": "ACL_REJECTED",
            "command_id": command_id,
            "sender_id": sender_id,
            "topic": topic,
            "reason": reason,
            "latency_us": round(latency_us, 2),
            "timestamp_ns": time.time_ns(),
        }
        msg = String()
        msg.data = json.dumps(event)
        self._acl_event_pub.publish(msg)

    def on_ack(self, domain_id: str, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError as exc:
            self.get_logger().error(f"on_ack {domain_id}: invalid JSON: {exc}")
            return

        decision = _acl_check_outbound(
            sender_id=payload.get("sender_id", ""),
            topic=f"/{domain_id}_factory/ack",
            payload=payload,
        )
        if not decision.allowed:
            self.get_logger().error(
                f"AclGuard REJECTED ack sender='{payload.get('sender_id')}' "
                f"domain={domain_id} reason={decision.rejection_reason} "
                f"latency={decision.acl_latency_us:.1f}µs"
            )
            self._publish_acl_event(
                command_id=payload.get("command_id", ""),
                sender_id=payload.get("sender_id", ""),
                topic=f"/{domain_id}_factory/ack",
                reason=decision.rejection_reason,
                latency_us=decision.acl_latency_us,
            )
            return

        self.db.insert_ack(
            command_id=payload.get("command_id", ""),
            domain_id=domain_id,
            resource_id=payload.get("resource_id"),
            task_state=payload.get("task_state"),
            resource_state=payload.get("resource_state"),
            result=payload.get("result"),
        )
        try:
            with self._state_lock:
                vc = self.vendor_clients[domain_id]
                vc.domain_online = True
                vc.on_ack_received(payload)
                resource_state = payload.get("resource_state")
                if resource_state:
                    self._apply_resource_state(
                        payload.get("resource_id", ""), resource_state
                    )
        except Exception as exc:
            self.get_logger().error(f"on_ack {domain_id}: {exc}")

    def on_status(self, domain_id: str, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError as exc:
            self.get_logger().error(f"on_status {domain_id}: invalid JSON: {exc}")
            return

        decision = _acl_check_outbound(
            sender_id=payload.get("sender_id", ""),
            topic=f"/{domain_id}_factory/status",
            payload=payload,
        )
        if not decision.allowed:
            self.get_logger().error(
                f"AclGuard REJECTED status sender='{payload.get('sender_id')}' "
                f"domain={domain_id} reason={decision.rejection_reason} "
                f"latency={decision.acl_latency_us:.1f}µs"
            )
            self._publish_acl_event(
                command_id=payload.get("command_id", ""),
                sender_id=payload.get("sender_id", ""),
                topic=f"/{domain_id}_factory/status",
                reason=decision.rejection_reason,
                latency_us=decision.acl_latency_us,
            )
            return

        self.db.insert_status(
            domain_id=domain_id,
            resource_id=payload.get("resource_id"),
            topic=f"/{domain_id}_factory/status",
            resource_state=payload.get("resource_state"),
            task_state=payload.get("task_state"),
            code=(payload.get("result") or {}).get("code"),
            result=payload.get("result"),
            command_id=payload.get("command_id"),
        )
        trigger = False
        try:
            with self._state_lock:
                vc = self.vendor_clients[domain_id]
                vc.last_status_time = time.time()

                resource_id = payload.get("resource_id", "")
                resource_state = payload.get("resource_state")
                task = payload.get("task", "")
                task_state = payload.get("task_state", "")
                result = payload.get("result", {}) or {}

                if resource_state:
                    self._apply_resource_state(resource_id, resource_state)
                sensor_updated = self._apply_sensor_result(result)
                self._apply_vision_result(resource_id, task, result)

                if resource_id == "robot2" and result.get("code") in {
                    "PICKING_C2S2", "PICKING_C2S2_DONE",
                    "PLACING_BANTAM", "PLACING_BANTAM_DONE",
                    "PICKING_BANTAM", "PICKING_BANTAM_DONE",
                    "PICKING_IBS", "PICKING_IBS_DONE",
                    "PLACING_IBS", "PLACING_IBS_DONE",
                    "PLACING_C4", "PLACING_C4_DONE",
                    "PLACING_SCRAP", "RETURNING_HOME",
                }:
                    self.get_logger().info(f"[robot2] {result['code']}")

                if task == "INITIALIZE_DOMAIN" and task_state == TaskState.COMPLETED:
                    self._mark_domain_initialized(domain_id)

                vc.on_status_received(payload)
                terminal = task_state in {
                    TaskState.COMPLETED,
                    TaskState.FAILED,
                    TaskState.REJECTED,
                    TaskState.TIMEOUT,
                    TaskState.CANCELED,
                    "COMPLETED",
                    "FAILED",
                    "REJECTED",
                    "TIMEOUT",
                    "CANCELED",
                }
                # Trigger on terminal commands OR real sensor readings so that
                # a physical sensor change (c1s2, c2s1, c2s2...) immediately
                # re-evaluates the planner without waiting for the 0.5 s timer.
                trigger = terminal or sensor_updated
        except Exception as exc:
            self.get_logger().error(f"on_status {domain_id}: {exc}")
            return

        if trigger:
            self.evaluate_rules()

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def register_pick_source(self, entity: str, source_loc: str) -> None:
        """Call at the moment a MOVE_PIECE-type command (pick+travel+place
        handled as ONE vendor command, e.g. xarm1/xarm2/robot2) is
        dispatched for `entity`, naming the location the piece is
        currently sitting in. Once the real hardware reports PICK_DONE
        (see _apply_resource_state below), the piece leaves that queue
        right there -- otherwise EXPECTED keeps showing it at the source
        location until the whole command (including RETURNING_HOME)
        finishes, long after it's physically in the gripper. Not needed
        for robot1 (unloading_rules.py), which already gets an explicit
        on_complete callback for its separate vacuum PICK command."""
        self._inflight_pick_source[entity] = source_loc

    def register_place_target(self, entity: str, target_loc: str) -> None:
        """Call alongside register_pick_source, at the same MOVE_PIECE
        dispatch, naming where the piece is headed. Once the real hardware
        reports PLACE_DONE, the piece lands in that queue right there --
        see the comment on self._inflight_place_target in __init__ for why
        this can't wait for the command's own on_complete callback."""
        self._inflight_place_target[entity] = target_loc
        self._place_done_via_hook[entity] = False

    def consume_place_done_flag(self, entity: str) -> bool:
        """Call from a MOVE_PIECE on_complete callback INSTEAD of doing the
        gripper->target transfer unconditionally. Returns True if the
        PLACE_DONE hook already transferred the piece for this dispatch
        (nothing left to do -- see self._place_done_via_hook). Returns
        False if it never fired (e.g. a dropped STATUS message), in which
        case the caller should still fall back to
        pieces.transfer_via_gripper() itself."""
        return self._place_done_via_hook.pop(entity, False)

    def _apply_resource_state(self, resource_id: str, resource_state: str) -> None:
        if not resource_id or not resource_state:
            return
        # Determine resource type for DB logging
        _TYPE_MAP = {
            **{r: "robot"    for r in ["robot1","robot2","xarm1","xarm2"]},
            **{c: "conveyor" for c in ["conveyor1","conveyor2","conveyor3","conveyor4"]},
            **{s: "sensor"   for s in ["c1s1","c1s2","c2s1","c2s2","c3","c4"]},
            **{m: "machine"  for m in ["laser","bantam"]},
            **{v: "vision"   for v in ["vision_robot1","vision_robot2","globalvision_camera"]},
            "arduino_vacuum": "vacuum",
        }
        prev_state = None
        for category in (self.state.robots, self.state.conveyors, self.state.sensors,
                         self.state.machines, self.state.vision, self.state.vacuum):
            if resource_id in category:
                prev_state = category[resource_id].value
                break
        if not self.state.apply_resource_state(resource_id, resource_state):
            self.get_logger().debug(
                f"Ignoring resource_state for unknown resource '{resource_id}': "
                f"{resource_state}"
            )
            return
        rtype = _TYPE_MAP.get(resource_id, "unknown")
        self.db.insert_resource_state_change(resource_id, rtype, prev_state, resource_state)
        if resource_id == "robot1":
            unloading_rules.sync_robot1_vision_phase(
                self, prev_state or "", resource_state
            )

        # EXPECTED must leave the source location the instant the piece is
        # physically picked, not when the whole move (incl. RETURNING_HOME)
        # finishes -- see register_pick_source. Consumed once per dispatch.
        if resource_state == "PICK_DONE":
            gripper_loc = _GRIPPER_LOCATION.get(resource_id)
            source_loc = self._inflight_pick_source.pop(resource_id, None)
            if gripper_loc and source_loc:
                self.pieces.transfer_piece(source_loc, gripper_loc)

        # Symmetric to the PICK_DONE hook above -- several vendor adapters
        # call move_home() INSIDE the same command right after PLACE_DONE
        # (see comment on self._inflight_place_target in __init__), so
        # waiting for the command's own completion would show the piece
        # stuck in the gripper (nowhere) in EXPECTED until home. React to
        # the real PLACE_DONE event instead.
        if resource_state == "PLACE_DONE":
            gripper_loc = _GRIPPER_LOCATION.get(resource_id)
            target_loc = self._inflight_place_target.pop(resource_id, None)
            if gripper_loc and target_loc:
                if self.pieces.transfer_piece(gripper_loc, target_loc):
                    self._place_done_via_hook[resource_id] = True

    def _apply_sensor_result(self, result: dict) -> bool:
        sensor_id = result.get("sensor_id")
        sensor_state = result.get("state") or result.get("sensor_state")
        if not sensor_id or not sensor_state:
            return False
        try:
            self.state.update_sensor(sensor_id, SensorState(sensor_state))
            return True
        except ValueError:
            self.get_logger().warning(
                f"Unknown sensor state for {sensor_id}: {sensor_state}"
            )
            return False

    def _apply_vision_result(self, resource_id: str, task: str, result: dict) -> None:
        color = result.get("color")
        shape = result.get("shape")
        if not color or not shape:
            return

        location = None
        if task in {"LOCATE_NEXT_PIECE", "SCAN_STACK"}:
            location = "initial_stack"
        elif resource_id in {"robot2", "vision_robot2"}:
            location = "conveyor2"
        elif resource_id in {"robot1", "vision_robot1"}:
            location = "c4_location"

        if location:
            self.pieces.assign_color_shape(location, color, shape)

    def _mark_domain_initialized(self, domain_id: str) -> None:
        vc = self.vendor_clients[domain_id]
        vc.domain_online = True
        self.state.set_domain_online(domain_id, True)

        if domain_id == "niryo":
            self.state.update_robot("robot1", RobotState.IDLE)
            self.state.update_robot("robot2", RobotState.IDLE)
            self.state.update_conveyor("conveyor1", ConveyorState.STOPPED)
            self.state.update_conveyor("conveyor2", ConveyorState.STOPPED)
            self.state.update_vision("vision_robot1", VisionState.IDLE)
            self.state.update_vision("vision_robot2", VisionState.IDLE)
            for sensor_id in ("c1s1", "c1s2", "c2s1", "c2s2", "c3", "c4"):
                self.state.update_sensor(sensor_id, SensorState.FREE)
        elif domain_id == "ufactory":
            self.state.update_robot("xarm1", RobotState.IDLE)
            self.state.update_robot("xarm2", RobotState.IDLE)
        elif domain_id == "laser":
            self.state.update_machine("laser", MachineState.IDLE)
        elif domain_id == "bantam":
            self.state.update_machine("bantam", MachineState.IDLE)
        elif domain_id == "globalvision":
            self.state.update_vision("globalvision_camera", VisionState.IDLE)
        elif domain_id == "green_conveyors":
            self.state.update_conveyor("conveyor3", ConveyorState.STOPPED)
            self.state.update_conveyor("conveyor4", ConveyorState.STOPPED)
        elif domain_id == "arduino_vacuum":
            self.state.update_vacuum("arduino_vacuum", VacuumState.IDLE)

    # ------------------------------------------------------------------
    # Timers and planner
    # ------------------------------------------------------------------

    def evaluate_rules(self) -> None:
        with self._state_lock:
            if self.planner_phase == PlannerPhase.BOOT:
                if time.time() < self._boot_ready_at:
                    if not self._boot_wait_logged:
                        self._boot_wait_logged = True
                        self.get_logger().info("Waiting for vendor discovery before boot")
                    return
                try:
                    initialization_rules.evaluate(self)
                except Exception as exc:
                    self.get_logger().error(f"evaluate_rules [initialization]: {exc}")
            elif self.planner_phase == PlannerPhase.WAITING_FOR_ORDER:
                pass  # hold until dashboard sends optimized order
            elif self.planner_phase == PlannerPhase.RUNNING:
                for name, rule in (
                    ("feeding", feeding_rules),
                    ("conveyor", conveyor_rules),
                    ("processing", processing_rules),
                    ("classification", classification_rules),
                    ("unloading", unloading_rules),
                ):
                    try:
                        rule.evaluate(self)
                    except Exception as exc:
                        self.get_logger().error(f"evaluate_rules [{name}]: {exc}")
                now = time.time()
                if now - self._last_state_log >= 10.0:
                    self._last_state_log = now
                    self.get_logger().info(
                        f"[state] proc={self._processing_state} feed={self._feeding_state} "
                        f"class={self._classification_state} unload={self._unloading_state} | "
                        f"c1s1={self.state.get_sensor('c1s1').name} "
                        f"c1s2={self.state.get_sensor('c1s2').name} "
                        f"c2s1={self.state.get_sensor('c2s1').name} "
                        f"c2s2={self.state.get_sensor('c2s2').name} "
                        f"c4={self.state.get_sensor('c4').name} | "
                        f"xarm1={self.state.get_robot('xarm1').name} "
                        f"xarm2={self.state.get_robot('xarm2').name} "
                        f"robot1={self.state.get_robot('robot1').name} "
                        f"robot2={self.state.get_robot('robot2').name} | "
                        f"conv1={self.pieces.count('conveyor1')} "
                        f"laser={self.pieces.count('laser_bed')} "
                        f"conv2={self.pieces.count('conveyor2')}"
                    )
                if self.pieces.all_pieces_finished():
                    self.planner_phase = PlannerPhase.SHUTTING_DOWN
            elif self.planner_phase == PlannerPhase.SHUTTING_DOWN:
                try:
                    shutdown_rules.evaluate(self)
                except Exception as exc:
                    self.get_logger().error(f"evaluate_rules [shutdown]: {exc}")

    def watchdog(self) -> None:
        with self._state_lock:
            for vc in self.vendor_clients.values():
                vc.check_timeout()

    def _publish_system_state(self) -> None:
        with self._state_lock:
            self.sys_state_pub.publish()

    def _on_optimized_order(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
            order = payload.get("order", payload)
            if not isinstance(order, list) or not all(isinstance(p, str) for p in order):
                raise ValueError("expected JSON list or {'order': [...]} payload")
        except Exception as exc:
            self.get_logger().warning(f"Invalid optimized order ignored: {exc}")
            return

        with self._state_lock:
            self._optimized_order = list(order)
            if not self.pieces.reorder_initial_stack(order):
                self.get_logger().warning(
                    f"reorder_initial_stack failed (color mismatch?) — using original order"
                )
            if self.planner_phase == PlannerPhase.WAITING_FOR_ORDER:
                self.planner_phase = PlannerPhase.RUNNING
                self.get_logger().info(
                    f"Optimized order applied ({len(order)} pieces): {order} — production STARTING"
                )
            else:
                self.get_logger().info(
                    f"Optimized order updated ({len(order)} pieces): {order}"
                )

        if self._map_guidance_enabled:
            with self._state_lock:
                self._expected_schedule = {}
                self._map_pointer = {}
                self._map_wait_since = {}
            threading.Thread(
                target=self._build_expected_schedule_async,
                args=(list(order),), daemon=True,
            ).start()

        saving_s = payload.get("saving_s", 0.0)
        self.db.insert_operator_event("APPLY_ORDER", f"order={order}")
        self.db.update_production_run_optimized_order(order, saving_s)

        # Log optimizer result if the dashboard sent stats alongside the order.
        if "original_time_s" in payload:
            self.db.insert_optimizer_result(
                original_order        = payload.get("original_order", list(order)),
                best_order            = list(order),
                original_time_s       = payload["original_time_s"],
                best_time_s           = payload.get("best_time_s", payload["original_time_s"]),
                saving_s              = saving_s,
                saving_pct            = payload.get("saving_pct", 0.0),
                method                = payload.get("method", "unknown"),
                permutations_evaluated= payload.get("permutations_evaluated", 0),
                optimizer_runtime_s   = payload.get("optimizer_runtime_s", 0.0),
            )

    # ------------------------------------------------------------------
    # External vision shape enrichment (ml_node.py, runs off-repo)
    # ------------------------------------------------------------------

    def _on_stack_status(self, msg: String) -> None:
        """Parse {"s1.1": "GREEN_CIRCLE", "s1.2": "null", ...} into
        slot_id -> {"color", "shape"}.

        Color+slot SELECTION for initial_stack stays owned by our own live
        camera_adapter.py detection (unchanged) -- exactly like shipyard_core
        keeps that decision in GlobalVision's own live HSV pass and only
        overlays shape from this externally-published map (see
        feeding_rules.py::_on_locate_complete for that lookup). The full
        color+shape map is kept here too, only to drive the dashboard's
        initial-stack visualization (a live picture of the physical stack,
        not a control-flow input).
        """
        try:
            payload = json.loads(msg.data)
        except Exception as exc:
            self.get_logger().warning(f"Invalid stack_status payload ignored: {exc}")
            return
        if not isinstance(payload, dict):
            return

        slots = {}
        for slot_id, value in payload.items():
            if not isinstance(value, str) or value.upper() == "NULL":
                continue
            parts = value.split("_", 1)
            slots[slot_id] = {
                "color": parts[0].upper(),
                "shape": parts[1].upper() if len(parts) == 2 and parts[1] else "UNKNOWN",
            }

        with self._state_lock:
            self._stack_status = slots

    def get_stack_status_shape(self, slot_id: Optional[str]) -> Optional[str]:
        if not slot_id:
            return None
        with self._state_lock:
            entry = self._stack_status.get(slot_id)
        return entry.get("shape") if entry else None

    def get_stack_status_full(self) -> dict:
        with self._state_lock:
            return dict(self._stack_status)

    # ------------------------------------------------------------------
    # Map-guided tie-breaking (see comment in __init__)
    # ------------------------------------------------------------------

    def _build_expected_schedule_async(self, order: list) -> None:
        try:
            from shipyard_pnp.factory.expected_schedule import compute_expected_schedule
            sched = compute_expected_schedule(order)
            with self._state_lock:
                self._expected_schedule = sched
            self.get_logger().info(
                f"[map] expected schedule ready ({sum(len(v) for v in sched.values())} cycles)"
            )
        except Exception as exc:
            self.get_logger().warning(f"[map] failed to compute expected schedule: {exc}")
            with self._state_lock:
                self._expected_schedule = {}

    def _map_next(self, entity: str) -> Optional[dict]:
        """The next not-yet-fulfilled expected cycle for this entity, or
        None if there's no schedule (not confirmed yet, still computing,
        guidance disabled) or the entity has run past the end of it --
        callers must always treat None as "no opinion, use the plain
        physical rule", never as a reason to block."""
        if not self._map_guidance_enabled:
            return None
        cycles = self._expected_schedule.get(entity)
        if not cycles:
            return None
        idx = self._map_pointer.get(entity, 0)
        if idx >= len(cycles):
            return None
        return cycles[idx]

    def _map_should_wait(self, entity: str) -> bool:
        """True while this entity should keep waiting (up to MAP_GRACE_SEC)
        for its map-predicted option to become physically ready instead of
        taking a different option that's already ready. Starts the timer on
        first call for this "waiting episode". Clears itself the moment the
        grace period expires (the decision to stop waiting is made right
        here, regardless of whether the caller's fallback attempt actually
        succeeds this tick) so a stale timestamp can never leak into and
        cut short some later, unrelated waiting episode for this entity --
        records how long it waited so _map_note_dispatch can log/persist the
        outcome. _map_note_dispatch also clears the start time on an actual
        successful dispatch (whether that took any waiting or not)."""
        now = time.time()
        started = self._map_wait_since.get(entity)
        if started is None:
            self._map_wait_since[entity] = now
            return True
        if (now - started) < self.MAP_GRACE_SEC:
            return True
        self._map_wait_since.pop(entity, None)
        self._map_last_wait_duration[entity] = now - started
        return False

    def _map_begin_dispatch(self, entity: str) -> dict:
        """Call the instant a dispatch decision is made, even when the
        final outcome isn't knowable yet (robot2's classify commits to
        "go handle whatever's at C2S2" before vision reveals the real
        color/route). Closes out any pending wait-timer bookkeeping right
        away so it can never leak into a later, unrelated waiting episode
        for this entity. Returns the wait info to pass into
        _map_resolve_dispatch() once the real outcome is known."""
        started = self._map_wait_since.pop(entity, None)
        waited_before_this = (time.time() - started) if started is not None else None
        gave_up_after = self._map_last_wait_duration.pop(entity, None)
        return {"waited_before_this": waited_before_this, "gave_up_after": gave_up_after}

    def _map_resolve_dispatch(self, entity: str, actual_category: str, wait_info: dict) -> None:
        """Compare the FINAL, resolved actual_category against what the map
        expected, and advance the map pointer only on a genuine match.
        wait_info comes from _map_begin_dispatch(), called earlier at the
        moment the dispatch decision was made (may be well before this, if
        the real outcome took a vision call to resolve).

        If it doesn't match (a grace-period fallback, OR a genuinely
        unplanned outcome the map never predicted at all -- e.g. robot2's
        vision resolving to SCRAP when the map expected a normal route),
        the expected cycle stays pending and will be compared against again
        next time this entity is free. Per user decision: skipped/unplanned
        map entries are never dropped, only ever caught up on -- an
        "intruder" cycle must not silently consume the slot of whatever the
        map was actually still waiting for.

        Every outcome that involved waiting at all gets logged; a timeout
        fallback or an intruder cycle also gets persisted to alarm_event so
        it can be reviewed after the fact."""
        if not self._map_guidance_enabled:
            return
        expected = self._map_next(entity)
        if expected is None:
            return
        expected_task = expected["task"]
        expected_label = f"{expected_task} #{expected.get('cycle_number')}"
        matched = actual_category == expected_task
        waited_before_this = wait_info.get("waited_before_this")
        gave_up_after = wait_info.get("gave_up_after")

        if matched:
            self._map_pointer[entity] = self._map_pointer.get(entity, 0) + 1
            if waited_before_this:
                self.get_logger().info(
                    f"[map] {entity}: siguió el mapa ({expected_label}) "
                    f"tras esperar {waited_before_this:.1f}s"
                )
                self._map_last_dispatch_info[entity] = {
                    "map_outcome":      "followed",
                    "map_expected":     expected_label,
                    "map_wait_s":       round(waited_before_this, 2),
                }
        elif gave_up_after is not None:
            msg = (
                f"se esperaron {gave_up_after:.1f}s a {expected_label}, no llegó "
                f"a tiempo -> se hizo {actual_category} en su lugar (sigue pendiente)"
            )
            self.get_logger().warning(f"[map] {entity}: {msg}")
            self.db.insert_alarm(
                severity="warning",
                resource_id=entity,
                description=f"MAP GUIDANCE TIMEOUT [{entity}]: {msg}",
                context_snapshot={
                    "kind":            "map_guidance_timeout",
                    "entity":          entity,
                    "expected_task":   expected_task,
                    "expected_cycle":  expected.get("cycle_number"),
                    "actual_category": actual_category,
                    "waited_s":        round(gave_up_after, 2),
                    "grace_sec":       self.MAP_GRACE_SEC,
                },
            )
            self._map_last_dispatch_info[entity] = {
                "map_outcome":     "timeout",
                "map_expected":    expected_label,
                "map_wait_s":      round(gave_up_after, 2),
            }
        else:
            # Neither a match nor a grace-period fallback -- an outcome the
            # map had no opinion about waiting for at all (e.g. vision
            # revealed a route the map never predicted). Leave the pointer
            # untouched: the expected entry is still owed.
            msg = (
                f"ciclo no esperado ({actual_category}) -- el mapa seguía "
                f"esperando {expected_label}, se deja pendiente"
            )
            self.get_logger().warning(f"[map] {entity}: {msg}")
            self.db.insert_alarm(
                severity="warning",
                resource_id=entity,
                description=f"MAP GUIDANCE INTRUDER [{entity}]: {msg}",
                context_snapshot={
                    "kind":            "map_guidance_intruder",
                    "entity":          entity,
                    "expected_task":   expected_task,
                    "expected_cycle":  expected.get("cycle_number"),
                    "actual_category": actual_category,
                },
            )
            self._map_last_dispatch_info[entity] = {
                "map_outcome":     "intruder",
                "map_expected":    expected_label,
            }

    def _map_note_dispatch(self, entity: str, actual_category: str) -> None:
        """Convenience for call sites that already know their final,
        resolved actual_category at the moment of dispatch (everyone
        except robot2's classify, which only learns its real route after
        vision -- see _map_begin_dispatch/_map_resolve_dispatch)."""
        self._map_resolve_dispatch(entity, actual_category, self._map_begin_dispatch(entity))

    def _map_pop_dispatch_metadata(self, entity: str) -> dict:
        """Consume (return-and-clear) the map-guidance outcome recorded by
        the most recent _map_note_dispatch call for this entity, if any --
        callers merge this into the metadata of the cycle_event they're
        about to start, so a wait/timeout is visible on the specific
        piece/cycle it affected, not just in the ROS log and alarm_event."""
        return self._map_last_dispatch_info.pop(entity, {})

    # ------------------------------------------------------------------
    # DB support timers
    # ------------------------------------------------------------------

    def _publish_run_id(self) -> None:
        msg = String()
        msg.data = self.db.run_id
        self._run_id_pub.publish(msg)

    def _sample_queue_depths(self) -> None:
        with self._state_lock:
            samples = {loc: self.pieces.count(loc) for loc in (
                "initial_stack", "conveyor1", "laser_bed",
                "conveyor2", "c3_location", "c4_location",
            )}
        self.db.insert_queue_depth_sample(samples)

    def destroy_node(self) -> None:
        try:
            # shutdown_rules.py advances SHUTTING_DOWN -> STOPPED once the full
            # shutdown sequence finishes, so by the time destroy_node() runs
            # after a clean shutdown the phase is already STOPPED, not
            # SHUTTING_DOWN. Accept both — STOPPED is only ever set there.
            clean_shutdown = self.planner_phase in (
                PlannerPhase.SHUTTING_DOWN, PlannerPhase.STOPPED,
            )
            self.db.update_production_run_finished(
                status="COMPLETED" if clean_shutdown else "ABORTED",
            )
        except Exception:
            pass
        self.db.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = FactorySupervisor()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.remove_node(node)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
