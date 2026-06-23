import threading
import time
from typing import Optional


class Lite6ServiceError(RuntimeError):
    pass


class Lite6ServiceDriver:
    """Thin wrapper around the UFACTORY Lite6 ROS2 service API."""

    def __init__(
        self,
        node,
        robot_id: str,
        namespace: str,
        dry_run: bool = True,
        service_wait_timeout_sec: float = 10.0,
        command_timeout_sec: float = 35.0,
        default_speed: float = 30.0,
        default_acc: float = 100.0,
        settle_time_sec: float = 0.5,
        gripper_delay_sec: float = 0.5,
        callback_group=None,
    ):
        self.node = node
        self.robot_id = robot_id
        self.namespace = namespace.rstrip("/") or f"/{robot_id}"
        self.dry_run = bool(dry_run)
        self.service_wait_timeout_sec = float(service_wait_timeout_sec)
        self.command_timeout_sec = float(command_timeout_sec)
        self.default_speed = float(default_speed)
        self.default_acc = float(default_acc)
        self.settle_time_sec = float(settle_time_sec)
        self.gripper_delay_sec = float(gripper_delay_sec)
        self.callback_group = callback_group

        self._clients_ready = False
        self._setup_lock = threading.Lock()
        self._call_lock = threading.Lock()

        self.clean_error_client = None
        self.motion_enable_client = None
        self.set_mode_client = None
        self.set_state_client = None
        self.move_joint_client = None
        self.open_gripper_client = None
        self.close_gripper_client = None

        self._srv_types = None

    def initialize_motion(self) -> None:
        if self.dry_run:
            self._info("dry-run initialize motion")
            return
        self._ensure_clients_ready()
        self._call_optional(self.clean_error_client, self._request("Call"), "clean_error")
        self._call_optional(
            self.motion_enable_client,
            self._request("SetInt16ById", id=8, data=1),
            "motion_enable",
        )
        self._call_optional(
            self.set_mode_client,
            self._request("SetInt16", data=0),
            "set_mode",
        )
        self._call_required(
            self.set_state_client,
            self._request("SetInt16", data=0),
            "set_state",
            timeout=5.0,
        )

    def move_joint(
        self,
        angles,
        description: str,
        speed: Optional[float] = None,
        acc: Optional[float] = None,
    ) -> None:
        speed = self.default_speed if speed is None else float(speed)
        acc = self.default_acc if acc is None else float(acc)
        if self.dry_run:
            self._info(f"dry-run move: {description}")
            time.sleep(min(self.settle_time_sec, 0.2))
            return

        self._ensure_clients_ready()
        self._call_required(
            self.set_state_client,
            self._request("SetInt16", data=0),
            "set_state",
            timeout=5.0,
        )

        req = self._request("MoveJoint")
        req.angles = list(angles)
        req.speed = speed
        req.acc = acc
        req.mvtime = 0.0
        req.wait = True
        req.timeout = 30.0
        self._call_required(
            self.move_joint_client,
            req,
            f"move_joint:{description}",
            timeout=self.command_timeout_sec,
        )
        time.sleep(self.settle_time_sec)

    def vacuum_on(self) -> None:
        if self.dry_run:
            self._info("dry-run gripper open / vacuum on")
            time.sleep(min(self.gripper_delay_sec, 0.2))
            return
        self._ensure_clients_ready()
        self._call_required(
            self.open_gripper_client,
            self._request("Call"),
            "open_lite6_gripper",
            timeout=5.0,
        )
        time.sleep(self.gripper_delay_sec)

    def vacuum_off(self) -> None:
        if self.dry_run:
            self._info("dry-run gripper close / vacuum off")
            time.sleep(min(self.gripper_delay_sec, 0.2))
            return
        self._ensure_clients_ready()
        self._call_required(
            self.close_gripper_client,
            self._request("Call"),
            "close_lite6_gripper",
            timeout=5.0,
        )
        time.sleep(self.gripper_delay_sec)

    def _ensure_clients_ready(self) -> None:
        if self._clients_ready:
            return
        with self._setup_lock:
            if self._clients_ready:
                return
            srv = self._load_srv_types()
            self.clean_error_client = self.node.create_client(
                srv["Call"],
                f"{self.namespace}/clean_error",
                callback_group=self.callback_group,
            )
            self.motion_enable_client = self.node.create_client(
                srv["SetInt16ById"],
                f"{self.namespace}/motion_enable",
                callback_group=self.callback_group,
            )
            self.set_mode_client = self.node.create_client(
                srv["SetInt16"],
                f"{self.namespace}/set_mode",
                callback_group=self.callback_group,
            )
            self.set_state_client = self.node.create_client(
                srv["SetInt16"],
                f"{self.namespace}/set_state",
                callback_group=self.callback_group,
            )
            self.move_joint_client = self.node.create_client(
                srv["MoveJoint"],
                f"{self.namespace}/set_servo_angle",
                callback_group=self.callback_group,
            )
            self.open_gripper_client = self.node.create_client(
                srv["Call"],
                f"{self.namespace}/open_lite6_gripper",
                callback_group=self.callback_group,
            )
            self.close_gripper_client = self.node.create_client(
                srv["Call"],
                f"{self.namespace}/close_lite6_gripper",
                callback_group=self.callback_group,
            )

            required = [
                self.set_state_client,
                self.move_joint_client,
                self.open_gripper_client,
                self.close_gripper_client,
            ]
            for client in required:
                if not client.wait_for_service(timeout_sec=self.service_wait_timeout_sec):
                    raise Lite6ServiceError(
                        f"{self.robot_id} required service unavailable: {client.srv_name}"
                    )

            optional = [
                self.clean_error_client,
                self.motion_enable_client,
                self.set_mode_client,
            ]
            for client in optional:
                if not client.wait_for_service(timeout_sec=0.2):
                    self._warn(
                        f"{self.robot_id} optional service unavailable: {client.srv_name}"
                    )

            self._clients_ready = True
            self._info(f"services ready under {self.namespace}")

    def _load_srv_types(self) -> dict:
        if self._srv_types is None:
            try:
                from xarm_msgs.srv import Call, MoveJoint, SetInt16, SetInt16ById
            except Exception as exc:
                raise Lite6ServiceError(
                    "xarm_msgs is required for UFactory hardware mode"
                ) from exc
            self._srv_types = {
                "Call": Call,
                "MoveJoint": MoveJoint,
                "SetInt16": SetInt16,
                "SetInt16ById": SetInt16ById,
            }
        return self._srv_types

    def _request(self, srv_name: str, **values):
        srv = self._load_srv_types()[srv_name]
        req = srv.Request()
        for key, value in values.items():
            setattr(req, key, value)
        return req

    def _call_optional(self, client, request, label: str) -> None:
        if client is None or not client.service_is_ready():
            return
        try:
            self._call_required(client, request, label, timeout=5.0)
        except Lite6ServiceError as exc:
            self._warn(str(exc))

    def _call_required(self, client, request, label: str, timeout: float) -> None:
        if client is None:
            raise Lite6ServiceError(f"{self.robot_id} client not created for {label}")
        with self._call_lock:
            event = threading.Event()
            result_box = {"result": None, "error": None}

            future = client.call_async(request)

            def _done(done_future):
                try:
                    result_box["result"] = done_future.result()
                except Exception as exc:
                    result_box["error"] = exc
                finally:
                    event.set()

            future.add_done_callback(_done)
            if not event.wait(timeout):
                raise Lite6ServiceError(f"{self.robot_id} service timeout: {label}")

            if result_box["error"] is not None:
                raise Lite6ServiceError(
                    f"{self.robot_id} service error {label}: {result_box['error']}"
                )

            result = result_box["result"]
            ret = getattr(result, "ret", 0)
            if ret != 0:
                raise Lite6ServiceError(f"{self.robot_id} service failed {label}: ret={ret}")

    def _info(self, msg: str) -> None:
        self.node.get_logger().info(f"[{self.robot_id}] {msg}")

    def _warn(self, msg: str) -> None:
        self.node.get_logger().warning(f"[{self.robot_id}] {msg}")
