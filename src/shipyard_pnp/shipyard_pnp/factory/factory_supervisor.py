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
INITIAL_STACK_ORDER = [
    {"id": "piece-001", "color": "BLUE",  "shape": None},
    {"id": "piece-002", "color": "GREEN", "shape": None},
    {"id": "piece-003", "color": "GREEN", "shape": None},
    {"id": "piece-004", "color": "BLUE",  "shape": None},
    {"id": "piece-005", "color": "GREEN", "shape": None},
    {"id": "piece-006", "color": "RED",   "shape": None},
]


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
        # True from robot2 vision-complete until conveyor2 starts running.
        # Allows conveyor2 to start even while c2s2 physically still reads OCCUPIED.
        self._c2s2_committed: bool = False

        # Timestamps of the last C3/C4 deposit; robot1 waits until settle_sec has elapsed.
        self._c3_deposit_time: float = 0.0
        self._c4_deposit_time: float = 0.0
        self.c3_settle_sec: float = 10.0
        self.c4_settle_sec: float = 14.5
        self._optimized_order = list(INITIAL_STACK_ORDER)
        self._init_wait_logged_domains = set()
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
        )

        self.create_timer(0.5,  self.evaluate_rules,          callback_group=self.planner_cbg)
        self.create_timer(1.0,  self.watchdog,                 callback_group=self.watchdog_cbg)
        self.create_timer(2.0,  self._publish_system_state,    callback_group=self.dashboard_cbg)
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
        self.db.insert_operator_event("APPLY_ORDER", f"order={order}")
        self.db.update_production_run_optimized_order(
            order,
            getattr(self, "_optimizer_savings_s", 0.0),
        )

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
            self.db.update_production_run_finished(
                status="COMPLETED" if self.planner_phase == PlannerPhase.SHUTTING_DOWN else "ABORTED",
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
