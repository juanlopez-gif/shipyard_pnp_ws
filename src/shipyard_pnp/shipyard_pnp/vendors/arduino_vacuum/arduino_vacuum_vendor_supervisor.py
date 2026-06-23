import os
from typing import Optional, Tuple

import rclpy
import yaml
from rclpy.executors import SingleThreadedExecutor

from shipyard_pnp.vendors.arduino_vacuum.arduino_vacuum_driver import (
    ArduinoVacuumDriver,
)
from shipyard_pnp.vendors.common.base_vendor_supervisor import BaseVendorSupervisor

_RESOURCE_ID = "arduino_vacuum"
_SUPPORTED_TASKS = {
    "INITIALIZE_DOMAIN",
    "PICK",
    "RELEASE",
    "OFF",
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
        return data.get("arduino_vacuum", {}) or {}
    except Exception:
        return {}


class ArduinoVacuumVendorSupervisor(BaseVendorSupervisor):
    """Vendor supervisor for the external Arduino vacuum domain."""

    def __init__(self):
        super().__init__("arduino_vacuum")
        defaults = _load_defaults()

        self.declare_parameter("port", defaults.get("port", "/dev/ttyACM1"))
        self.declare_parameter("baudrate", int(defaults.get("baudrate", 9600)))
        self.declare_parameter(
            "open_wait_sec", float(defaults.get("open_wait_sec", 2.0))
        )
        self.declare_parameter(
            "read_wait_sec", float(defaults.get("read_wait_sec", 1.0))
        )
        self.declare_parameter(
            "reconnect_attempts", int(defaults.get("reconnect_attempts", 8))
        )
        self.declare_parameter(
            "reconnect_delay_sec", float(defaults.get("reconnect_delay_sec", 1.0))
        )
        self.declare_parameter(
            "pick_hold_sec", float(defaults.get("pick_hold_sec", 0.5))
        )
        self.declare_parameter(
            "release_hold_sec", float(defaults.get("release_hold_sec", 0.3))
        )

        self.driver = ArduinoVacuumDriver(
            port=self.get_parameter("port").value,
            baudrate=self.get_parameter("baudrate").value,
            open_wait_sec=self.get_parameter("open_wait_sec").value,
            read_wait_sec=self.get_parameter("read_wait_sec").value,
            reconnect_attempts=self.get_parameter("reconnect_attempts").value,
            reconnect_delay_sec=self.get_parameter("reconnect_delay_sec").value,
            pick_hold_sec=self.get_parameter("pick_hold_sec").value,
            release_hold_sec=self.get_parameter("release_hold_sec").value,
            logger=self.get_logger(),
        )

    def handle_task(self, cmd: dict) -> Tuple[bool, Optional[str]]:
        resource_id = cmd.get("resource_id")
        task = cmd.get("task")
        if resource_id != _RESOURCE_ID:
            return False, f"Unsupported resource_id: {resource_id}"
        if task not in _SUPPORTED_TASKS:
            return False, f"Unsupported task: {task}"
        if self.task_runner.is_running():
            return False, "arduino_vacuum busy"

        task_fn = self.driver.make_task_fn(cmd)
        self.task_runner.run(
            task_fn=task_fn,
            on_complete=lambda result: self._publish_completed(cmd, result),
            on_error=lambda exc: self._publish_failed(cmd, exc),
        )
        return True, None

    def _publish_completed(self, cmd: dict, result: dict) -> None:
        safe_result = dict(result)
        resource_state = safe_result.pop("resource_state", "IDLE")
        self.publish_status(
            command_id=cmd["command_id"],
            resource_id=_RESOURCE_ID,
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
        self.get_logger().error(f"Arduino vacuum task failed: {exc}")
        self.publish_status(
            command_id=cmd["command_id"],
            resource_id=_RESOURCE_ID,
            task=cmd.get("task", ""),
            task_state="FAILED",
            resource_state="ERROR",
            piece_id=cmd.get("piece_id"),
            source=cmd.get("source"),
            target=cmd.get("target"),
            route=cmd.get("route"),
            result={"code": "VACUUM_COMMAND_FAILED", "reason": "hardware_error"},
            correlation_id=cmd.get("correlation_id"),
        )

    def destroy_node(self) -> None:
        self.driver.close(neutral=True)
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    supervisor = ArduinoVacuumVendorSupervisor()
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
