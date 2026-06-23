import os
import threading
from typing import Optional, Tuple

import rclpy
import yaml
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor

from shipyard_pnp.shared.contracts import RobotState, TaskState
from shipyard_pnp.vendors.common.base_vendor_supervisor import BaseVendorSupervisor
from shipyard_pnp.vendors.common.task_runner import TaskRunner
from shipyard_pnp.vendors.ufactory.lite6_service_driver import Lite6ServiceDriver
from shipyard_pnp.vendors.ufactory.xarm1_adapter import XArm1Adapter
from shipyard_pnp.vendors.ufactory.xarm2_adapter import XArm2Adapter

_SUPPORTED_RESOURCES = {"xarm1", "xarm2"}
_SUPPORTED_TASKS = {
    "INITIALIZE_DOMAIN",
    "MOVE_PIECE",
    "MOVE_XARM_HOME",
    "MOVE_ROBOT",
    "RESET",
}


def _hardware_config_path() -> Optional[str]:
    source_candidate = os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "..",
            "..",
            "config",
            "hardware_ports.yaml",
        )
    )
    if os.path.isfile(source_candidate):
        return source_candidate
    try:
        from ament_index_python.packages import get_package_share_directory

        pkg = get_package_share_directory("shipyard_pnp")
        install_candidate = os.path.join(pkg, "config", "hardware_ports.yaml")
        if os.path.isfile(install_candidate):
            return install_candidate
    except Exception:
        pass
    return None


def _load_defaults() -> dict:
    path = _hardware_config_path()
    if path is None:
        return {}
    try:
        with open(path) as fh:
            data = yaml.safe_load(fh) or {}
        return data.get("ufactory", {}) or {}
    except Exception:
        return {}


class UFactoryVendorSupervisor(BaseVendorSupervisor):
    """Vendor supervisor for both UFACTORY Lite6 arms."""

    def __init__(self):
        super().__init__("ufactory")
        defaults = _load_defaults()
        self.service_cbg = ReentrantCallbackGroup()
        self._publish_lock = threading.Lock()

        self.declare_parameter("mode", defaults.get("mode", "dry_run"))
        self.declare_parameter("xarm1_namespace", defaults.get("xarm1_namespace", "/xarm1"))
        self.declare_parameter("xarm2_namespace", defaults.get("xarm2_namespace", "/xarm2"))
        self.declare_parameter(
            "service_wait_timeout_sec",
            float(defaults.get("service_wait_timeout_sec", 10.0)),
        )
        self.declare_parameter(
            "command_timeout_sec",
            float(defaults.get("command_timeout_sec", 35.0)),
        )
        self.declare_parameter("default_speed", float(defaults.get("default_speed", 30.0)))
        self.declare_parameter("default_acc", float(defaults.get("default_acc", 100.0)))
        self.declare_parameter(
            "settle_time_sec", float(defaults.get("settle_time_sec", 0.5))
        )
        self.declare_parameter(
            "gripper_delay_sec", float(defaults.get("gripper_delay_sec", 0.5))
        )

        dry_run = self._mode_is_dry_run(self.get_parameter("mode").value)
        shared = {
            "node": self,
            "dry_run": dry_run,
            "service_wait_timeout_sec": self.get_parameter(
                "service_wait_timeout_sec"
            ).value,
            "command_timeout_sec": self.get_parameter("command_timeout_sec").value,
            "default_speed": self.get_parameter("default_speed").value,
            "default_acc": self.get_parameter("default_acc").value,
            "settle_time_sec": self.get_parameter("settle_time_sec").value,
            "gripper_delay_sec": self.get_parameter("gripper_delay_sec").value,
            "callback_group": self.service_cbg,
        }
        self.adapters = {
            "xarm1": XArm1Adapter(
                Lite6ServiceDriver(
                    robot_id="xarm1",
                    namespace=self.get_parameter("xarm1_namespace").value,
                    **shared,
                )
            ),
            "xarm2": XArm2Adapter(
                Lite6ServiceDriver(
                    robot_id="xarm2",
                    namespace=self.get_parameter("xarm2_namespace").value,
                    **shared,
                )
            ),
        }
        self.resource_runners = {
            "xarm1": TaskRunner(),
            "xarm2": TaskRunner(),
        }
        self.get_logger().info(
            f"ufactory mode={'dry_run' if dry_run else 'hardware'} "
            f"xarm1={self.get_parameter('xarm1_namespace').value} "
            f"xarm2={self.get_parameter('xarm2_namespace').value}"
        )

    def handle_task(self, cmd: dict) -> Tuple[bool, Optional[str]]:
        resource_id = cmd.get("resource_id")
        task = cmd.get("task")
        if resource_id not in _SUPPORTED_RESOURCES:
            return False, f"Unsupported resource_id: {resource_id}"
        if task not in _SUPPORTED_TASKS:
            return False, f"Unsupported task: {task}"

        if task == "INITIALIZE_DOMAIN":
            if self.task_runner.is_running() or self._any_resource_running():
                return False, "ufactory busy"
            runner = self.task_runner
        else:
            if self.task_runner.is_running():
                return False, "ufactory initializing"
            runner = self.resource_runners[resource_id]
            if runner.is_running():
                return False, f"{resource_id} busy"

        self.get_logger().info(
            f"Accepted UFactory command {cmd.get('command_id')} "
            f"{resource_id}/{task}"
        )
        task_fn = self._make_task_fn(cmd)
        runner.run(
            task_fn=task_fn,
            on_complete=lambda result: self._publish_completed(cmd, result),
            on_error=lambda exc: self._publish_failed(cmd, exc),
        )
        return True, None

    def _any_resource_running(self) -> bool:
        return any(runner.is_running() for runner in self.resource_runners.values())

    def _make_task_fn(self, cmd: dict):
        task = cmd.get("task", "")
        resource_id = cmd.get("resource_id", "")
        params = cmd.get("parameters") or {}

        def status_cb(state: str, result: dict) -> None:
            self._publish_running(cmd, state, result)

        def fn() -> dict:
            if task == "INITIALIZE_DOMAIN":
                init = {}
                init["xarm1"] = self.adapters["xarm1"].initialize(
                    self._resource_status_cb(cmd, "xarm1")
                )
                init["xarm2"] = self.adapters["xarm2"].initialize(
                    self._resource_status_cb(cmd, "xarm2")
                )
                return {
                    "resource_state": RobotState.IDLE.value,
                    "code": "INITIALIZED",
                    "initialized": sorted(init.keys()),
                }

            adapter = self.adapters[resource_id]
            if task in {"MOVE_XARM_HOME", "MOVE_ROBOT"}:
                target = str(params.get("target", "HOME")).upper()
                if task == "MOVE_ROBOT" and target != "HOME":
                    raise ValueError(f"Unsupported MOVE_ROBOT target: {target}")
                return adapter.move_home(status_cb)

            if task == "MOVE_PIECE":
                if resource_id == "xarm1":
                    source = params.get("source") or cmd.get("source")
                    target = params.get("target") or cmd.get("target")
                    return adapter.move_piece(
                        source=source,
                        target=target,
                        route=cmd.get("route", ""),
                        status_cb=status_cb,
                    )

                pick_slot = params.get("pick_slot") or params.get("slot_id")
                target = params.get("target") or cmd.get("target")
                return adapter.move_piece(
                    pick_slot=pick_slot,
                    target=target,
                    route=cmd.get("route", ""),
                    status_cb=status_cb,
                )

            if task == "RESET":
                return adapter.reset(status_cb)

            raise ValueError(f"Unsupported ufactory task: {task}")

        return fn

    def _resource_status_cb(self, cmd: dict, resource_id: str):
        def cb(state: str, result: dict) -> None:
            self._publish_running(cmd, state, result, resource_id=resource_id)

        return cb

    def _publish_running(
        self,
        cmd: dict,
        resource_state: str,
        result: dict,
        resource_id: Optional[str] = None,
    ) -> None:
        with self._publish_lock:
            self.publish_status(
                command_id=cmd["command_id"],
                resource_id=resource_id or cmd.get("resource_id", ""),
                task=cmd.get("task", ""),
                task_state=TaskState.RUNNING.value,
                resource_state=resource_state,
                piece_id=cmd.get("piece_id"),
                source=cmd.get("source"),
                target=cmd.get("target"),
                route=cmd.get("route"),
                result=result,
                correlation_id=cmd.get("correlation_id"),
            )

    def _publish_completed(self, cmd: dict, result: dict) -> None:
        safe_result = dict(result)
        resource_state = safe_result.pop("resource_state", RobotState.IDLE.value)
        with self._publish_lock:
            self.publish_status(
                command_id=cmd["command_id"],
                resource_id=cmd.get("resource_id", ""),
                task=cmd.get("task", ""),
                task_state=TaskState.COMPLETED.value,
                resource_state=resource_state,
                piece_id=cmd.get("piece_id"),
                source=cmd.get("source"),
                target=cmd.get("target"),
                route=cmd.get("route"),
                result=safe_result,
                correlation_id=cmd.get("correlation_id"),
            )

    def _publish_failed(self, cmd: dict, exc: Exception) -> None:
        self.get_logger().error(f"UFactory task failed: {exc}")
        with self._publish_lock:
            self.publish_status(
                command_id=cmd["command_id"],
                resource_id=cmd.get("resource_id", ""),
                task=cmd.get("task", ""),
                task_state=TaskState.FAILED.value,
                resource_state=RobotState.ERROR.value,
                piece_id=cmd.get("piece_id"),
                source=cmd.get("source"),
                target=cmd.get("target"),
                route=cmd.get("route"),
                result={"code": "UFACTORY_COMMAND_FAILED", "reason": str(exc)},
                correlation_id=cmd.get("correlation_id"),
            )

    @staticmethod
    def _mode_is_dry_run(mode: str) -> bool:
        return str(mode or "dry_run").strip().lower() in {
            "dry_run",
            "dryrun",
            "dry-run",
            "sim",
            "simulation",
            "mock",
        }


def main(args=None):
    rclpy.init(args=args)
    supervisor = UFactoryVendorSupervisor()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(supervisor)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.remove_node(supervisor)
        supervisor.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
