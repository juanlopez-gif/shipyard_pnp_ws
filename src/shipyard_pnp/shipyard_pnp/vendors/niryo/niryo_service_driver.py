import threading
import time

from rclpy.action import ActionClient


class NiryoServiceError(RuntimeError):
    pass


class NiryoServiceDriver:
    """Thin wrapper around the Niryo Ned2 ROS2 hardware API."""

    def __init__(
        self,
        node,
        robot_id: str,
        namespace: str,
        dry_run: bool = True,
        service_wait_timeout_sec: float = 10.0,
        command_timeout_sec: float = 45.0,
        settle_time_sec: float = 0.2,
        vacuum_delay_sec: float = 0.5,
        vacuum_tool_id: int = 31,
        callback_group=None,
    ):
        self.node = node
        self.robot_id = robot_id
        self.namespace = namespace.rstrip("/") or f"/{robot_id}"
        if not self.namespace.startswith("/"):
            self.namespace = f"/{self.namespace}"
        self.dry_run = bool(dry_run)
        self.service_wait_timeout_sec = float(service_wait_timeout_sec)
        self.command_timeout_sec = float(command_timeout_sec)
        self.settle_time_sec = float(settle_time_sec)
        self.vacuum_delay_sec = float(vacuum_delay_sec)
        self.vacuum_tool_id = int(vacuum_tool_id)
        self.callback_group = callback_group

        self._types = None
        self._robot_ready = False
        self._conveyor_ready = False
        self._setup_lock = threading.Lock()
        self._robot_call_lock = threading.Lock()
        self._conveyor_call_lock = threading.Lock()

        self.robot_move_client = None
        self.vacuum_pull_client = None
        self.vacuum_push_client = None
        self.conveyor_client = None
        self.ir_client = None

    def initialize_robot(self, use_vacuum: bool = True) -> None:
        if self.dry_run:
            self._info("dry-run initialize robot API")
            return
        self._ensure_robot_ready(use_vacuum=use_vacuum)

    def move_joints(self, joints, description: str) -> None:
        if self.dry_run:
            self._info(f"dry-run move: {description}")
            time.sleep(min(self.settle_time_sec, 0.2))
            return

        self._ensure_robot_ready(use_vacuum=False)
        types = self._load_types()
        goal = types["RobotMove"].Goal()
        goal.cmd.cmd_type = types["ArmMoveCommand"].JOINTS
        goal.cmd.joints = list(joints)
        goal.cmd.tcp_version = types["ArmMoveCommand"].DH_CONVENTION

        with self._robot_call_lock:
            handle = self._wait_action_goal(
                self.robot_move_client.send_goal_async(goal),
                f"move:{description}",
                timeout=10.0,
            )
            result = self._wait_action_result(
                handle.get_result_async(),
                f"move:{description}",
                timeout=self.command_timeout_sec,
            )

        status = getattr(result, "status", 1)
        message = getattr(result, "message", "")
        if int(status) == 0:
            raise NiryoServiceError(
                f"{self.robot_id} move failed {description}: {message or status}"
            )
        time.sleep(self.settle_time_sec)

    def vacuum(self, mode: str) -> None:
        mode = str(mode or "").strip().lower()
        if mode not in {"pull", "push", "neutral"}:
            raise NiryoServiceError(f"{self.robot_id} invalid vacuum mode: {mode}")

        if self.dry_run:
            self._info(f"dry-run vacuum {mode}")
            time.sleep(min(self.vacuum_delay_sec, 0.2))
            return

        self._ensure_robot_ready(use_vacuum=True)
        req = self._request("ToolCommand")
        req.id = self.vacuum_tool_id
        req.speed = 0
        if mode == "pull":
            req.position = 0
            req.max_torque = 1000
            req.hold_torque = 800
            client = self.vacuum_pull_client
        elif mode == "push":
            req.position = 1900
            req.max_torque = -1000
            req.hold_torque = 0
            client = self.vacuum_push_client
        else:
            req.position = 1000
            req.max_torque = -1000
            req.hold_torque = 0
            client = self.vacuum_push_client

        with self._robot_call_lock:
            self._call_required(client, req, f"vacuum:{mode}", timeout=8.0)
        time.sleep(self.vacuum_delay_sec)

    def initialize_conveyor(self) -> None:
        if self.dry_run:
            self._info("dry-run initialize conveyor API")
            return
        self._ensure_conveyor_ready()

    def control_conveyor(
        self,
        hardware_id: int,
        control_on: bool,
        speed: int,
        direction: int,
    ) -> None:
        if self.dry_run:
            state = "RUN" if control_on else "STOP"
            self._info(
                f"dry-run conveyor {state} id={hardware_id} speed={speed} direction={direction}"
            )
            time.sleep(min(self.settle_time_sec, 0.2))
            return

        self._ensure_conveyor_ready()
        req = self._request("ControlConveyor")
        req.id = int(hardware_id)
        req.control_on = bool(control_on)
        req.speed = int(speed)
        req.direction = int(direction)
        with self._conveyor_call_lock:
            self._call_required(
                self.conveyor_client,
                req,
                f"control_conveyor:{hardware_id}:{control_on}",
                timeout=8.0,
            )

    def read_digital_io(self, pin_name: str) -> bool:
        if self.dry_run:
            return True

        self._ensure_conveyor_ready()
        req = self._request("GetDigitalIO")
        req.name = str(pin_name)
        with self._conveyor_call_lock:
            result = self._call_required(
                self.ir_client,
                req,
                f"get_digital_io:{pin_name}",
                timeout=5.0,
            )
        return bool(getattr(result, "value", False))

    def _ensure_robot_ready(self, use_vacuum: bool) -> None:
        if self._robot_ready:
            return
        with self._setup_lock:
            if self._robot_ready:
                return
            types = self._load_types()
            # Create clients only once — recreating them on every retry resets
            # DDS discovery, making wait_for_server always start from scratch.
            if self.robot_move_client is None:
                self.robot_move_client = ActionClient(
                    self.node,
                    types["RobotMove"],
                    f"{self.namespace}/niryo_robot_arm_commander/robot_action",
                    callback_group=self.callback_group,
                )
            if self.vacuum_pull_client is None:
                self.vacuum_pull_client = self.node.create_client(
                    types["ToolCommand"],
                    f"{self.namespace}/niryo_robot/tools/pull_air_vacuum_pump",
                    callback_group=self.callback_group,
                )
            if self.vacuum_push_client is None:
                self.vacuum_push_client = self.node.create_client(
                    types["ToolCommand"],
                    f"{self.namespace}/niryo_robot/tools/push_air_vacuum_pump",
                    callback_group=self.callback_group,
                )

            if not self.robot_move_client.wait_for_server(
                timeout_sec=self.service_wait_timeout_sec
            ):
                raise NiryoServiceError(
                    f"{self.robot_id} action unavailable: "
                    f"{self.namespace}/niryo_robot_arm_commander/robot_action"
                )

            if use_vacuum:
                for client in (self.vacuum_pull_client, self.vacuum_push_client):
                    if not client.wait_for_service(
                        timeout_sec=self.service_wait_timeout_sec
                    ):
                        raise NiryoServiceError(
                            f"{self.robot_id} required service unavailable: {client.srv_name}"
                        )
            self._robot_ready = True
            self._info(f"robot services ready under {self.namespace}")

    def _ensure_conveyor_ready(self) -> None:
        if self._conveyor_ready:
            return
        with self._setup_lock:
            if self._conveyor_ready:
                return
            types = self._load_types()
            if self.conveyor_client is None:
                self.conveyor_client = self.node.create_client(
                    types["ControlConveyor"],
                    f"{self.namespace}/niryo_robot/conveyor/control_conveyor",
                    callback_group=self.callback_group,
                )
            if self.ir_client is None:
                self.ir_client = self.node.create_client(
                    types["GetDigitalIO"],
                    f"{self.namespace}/niryo_robot_rpi/get_digital_io",
                    callback_group=self.callback_group,
                )
            for client in (self.conveyor_client, self.ir_client):
                if not client.wait_for_service(timeout_sec=self.service_wait_timeout_sec):
                    raise NiryoServiceError(
                        f"{self.robot_id} required service unavailable: {client.srv_name}"
                    )
            self._conveyor_ready = True
            self._info(f"conveyor services ready under {self.namespace}")

    def _load_types(self) -> dict:
        if self._types is None:
            try:
                from niryo_ned_ros2_interfaces.action import RobotMove
                from niryo_ned_ros2_interfaces.msg import ArmMoveCommand
                from niryo_ned_ros2_interfaces.srv import (
                    ControlConveyor,
                    GetDigitalIO,
                    ToolCommand,
                )
            except Exception as exc:
                raise NiryoServiceError(
                    "niryo_ned_ros2_interfaces is required for Niryo hardware mode"
                ) from exc
            self._types = {
                "ArmMoveCommand": ArmMoveCommand,
                "ControlConveyor": ControlConveyor,
                "GetDigitalIO": GetDigitalIO,
                "RobotMove": RobotMove,
                "ToolCommand": ToolCommand,
            }
        return self._types

    def _request(self, srv_name: str):
        return self._load_types()[srv_name].Request()

    def _call_required(self, client, request, label: str, timeout: float):
        if client is None:
            raise NiryoServiceError(f"{self.robot_id} client not created for {label}")
        event = threading.Event()
        box = {"result": None, "error": None}
        future = client.call_async(request)

        def _done(done_future):
            try:
                box["result"] = done_future.result()
            except Exception as exc:
                box["error"] = exc
            finally:
                event.set()

        future.add_done_callback(_done)
        if not event.wait(timeout):
            raise NiryoServiceError(f"{self.robot_id} service timeout: {label}")
        if box["error"] is not None:
            raise NiryoServiceError(
                f"{self.robot_id} service error {label}: {box['error']}"
            )
        return box["result"]

    def _wait_action_goal(self, future, label: str, timeout: float):
        event = threading.Event()
        box = {"handle": None, "error": None}

        def _done(done_future):
            try:
                box["handle"] = done_future.result()
            except Exception as exc:
                box["error"] = exc
            finally:
                event.set()

        future.add_done_callback(_done)
        if not event.wait(timeout):
            raise NiryoServiceError(f"{self.robot_id} action goal timeout: {label}")
        if box["error"] is not None:
            raise NiryoServiceError(
                f"{self.robot_id} action goal error {label}: {box['error']}"
            )
        handle = box["handle"]
        if handle is None or not getattr(handle, "accepted", False):
            raise NiryoServiceError(f"{self.robot_id} action rejected: {label}")
        return handle

    def _wait_action_result(self, future, label: str, timeout: float):
        event = threading.Event()
        box = {"result": None, "error": None}

        def _done(done_future):
            try:
                box["result"] = done_future.result().result
            except Exception as exc:
                box["error"] = exc
            finally:
                event.set()

        future.add_done_callback(_done)
        if not event.wait(timeout):
            raise NiryoServiceError(f"{self.robot_id} action result timeout: {label}")
        if box["error"] is not None:
            raise NiryoServiceError(
                f"{self.robot_id} action result error {label}: {box['error']}"
            )
        return box["result"]

    def _info(self, msg: str) -> None:
        self.node.get_logger().info(f"[{self.robot_id}] {msg}")
