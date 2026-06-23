import os
from typing import Optional, Tuple

import rclpy
import yaml
from rclpy.executors import SingleThreadedExecutor

from shipyard_pnp.vendors.common.base_vendor_supervisor import BaseVendorSupervisor
from shipyard_pnp.vendors.green_conveyors.shared_arduino_driver import (
    SharedGreenConveyorDriver,
)

_SUPPORTED_RESOURCES = {"conveyor3", "conveyor4"}
_SUPPORTED_TASKS = {
    "INITIALIZE_DOMAIN",
    "RUN_CONVEYOR",
    "STOP_CONVEYOR",
    "SET_SPEED",
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
        return data.get("green_conveyors", {}) or {}
    except Exception:
        return {}


class GreenConveyorsVendorSupervisor(BaseVendorSupervisor):
    """Vendor supervisor for the shared Arduino green conveyor domain."""

    def __init__(self):
        super().__init__("green_conveyors")
        defaults = _load_defaults()

        self.declare_parameter("port", defaults.get("port", "/dev/ttyACM0"))
        self.declare_parameter("baudrate", int(defaults.get("baudrate", 115200)))
        self.declare_parameter(
            "startup_wait_sec", float(defaults.get("startup_wait_sec", 2.0))
        )
        self.declare_parameter(
            "command_timeout_sec", float(defaults.get("command_timeout_sec", 2.0))
        )
        self.declare_parameter(
            "reconnect_attempts", int(defaults.get("reconnect_attempts", 5))
        )
        self.declare_parameter(
            "reconnect_delay_sec", float(defaults.get("reconnect_delay_sec", 1.0))
        )
        self.declare_parameter(
            "inter_command_delay_sec",
            float(defaults.get("inter_command_delay_sec", 0.3)),
        )
        self.declare_parameter(
            "conveyor3_speed", int(defaults.get("conveyor3_speed", 9000))
        )
        self.declare_parameter(
            "conveyor4_speed", int(defaults.get("conveyor4_speed", 9000))
        )
        self.declare_parameter(
            "conveyor3_direction", defaults.get("conveyor3_direction", "FWD")
        )
        self.declare_parameter(
            "conveyor4_direction", defaults.get("conveyor4_direction", "REV")
        )

        self.driver = SharedGreenConveyorDriver(
            port=self.get_parameter("port").value,
            baudrate=self.get_parameter("baudrate").value,
            startup_wait_sec=self.get_parameter("startup_wait_sec").value,
            command_timeout_sec=self.get_parameter("command_timeout_sec").value,
            reconnect_attempts=self.get_parameter("reconnect_attempts").value,
            reconnect_delay_sec=self.get_parameter("reconnect_delay_sec").value,
            inter_command_delay_sec=self.get_parameter("inter_command_delay_sec").value,
            conveyor3_speed=self.get_parameter("conveyor3_speed").value,
            conveyor4_speed=self.get_parameter("conveyor4_speed").value,
            conveyor3_direction=self.get_parameter("conveyor3_direction").value,
            conveyor4_direction=self.get_parameter("conveyor4_direction").value,
            logger=self.get_logger(),
        )

    def handle_task(self, cmd: dict) -> Tuple[bool, Optional[str]]:
        resource_id = cmd.get("resource_id")
        task = cmd.get("task")
        if resource_id not in _SUPPORTED_RESOURCES:
            return False, f"Unsupported resource_id: {resource_id}"
        if task not in _SUPPORTED_TASKS:
            return False, f"Unsupported task: {task}"
        if self.task_runner.is_running():
            return False, "green_conveyors busy"

        task_fn = self.driver.make_task_fn(cmd)
        self.task_runner.run(
            task_fn=task_fn,
            on_complete=lambda result: self._publish_completed(cmd, result),
            on_error=lambda exc: self._publish_failed(cmd, exc),
        )
        return True, None

    def _publish_completed(self, cmd: dict, result: dict) -> None:
        safe_result = dict(result)
        resource_state = safe_result.pop("resource_state", "STOPPED")
        self.publish_status(
            command_id=cmd["command_id"],
            resource_id=cmd.get("resource_id", ""),
            task=cmd.get("task", ""),
            task_state="COMPLETED",
            resource_state=resource_state,
            piece_id=cmd.get("piece_id"),
            source=cmd.get("source"),
            target=cmd.get("target"),
            route=cmd.get("route"),
            result=safe_result,
            correlation_id=cmd.get("correlation_id"),
        )

    def _publish_failed(self, cmd: dict, exc: Exception) -> None:
        self.get_logger().error(f"Green conveyor task failed: {exc}")
        self.publish_status(
            command_id=cmd["command_id"],
            resource_id=cmd.get("resource_id", ""),
            task=cmd.get("task", ""),
            task_state="FAILED",
            resource_state="ERROR",
            piece_id=cmd.get("piece_id"),
            source=cmd.get("source"),
            target=cmd.get("target"),
            route=cmd.get("route"),
            result={"code": "GREEN_CONVEYOR_COMMAND_FAILED", "reason": "hardware_error"},
            correlation_id=cmd.get("correlation_id"),
        )

    def destroy_node(self) -> None:
        self.driver.close(stop_first=True)
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    supervisor = GreenConveyorsVendorSupervisor()
    executor = SingleThreadedExecutor()
    executor.add_node(supervisor)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.remove_node(supervisor)
        supervisor.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
