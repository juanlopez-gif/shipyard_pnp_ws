import os
from typing import Optional, Tuple

import rclpy
import yaml
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor

from shipyard_pnp.shared.contracts import MachineState, TaskState
from shipyard_pnp.vendors.common.base_vendor_supervisor import BaseVendorSupervisor
from shipyard_pnp.vendors.laser.laser_adapter import LaserAdapter

_SUPPORTED_RESOURCES = {"laser"}
_SUPPORTED_TASKS = {
    "INITIALIZE_DOMAIN",
    "PREPARE_JOB",
    "RUN_JOB",
    "WORK",
    "RESET",
    "GET_READY_TO_WORK",
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
        return data.get("laser", {}) or {}
    except Exception:
        return {}


class LaserVendorSupervisor(BaseVendorSupervisor):
    """Vendor supervisor for the laser domain."""

    def __init__(self):
        super().__init__("laser")
        defaults = _load_defaults()

        self.declare_parameter("mode", defaults.get("mode", "dry_run"))
        self.declare_parameter("laser_ip", defaults.get("laser_ip", "192.168.0.173"))
        self.declare_parameter(
            "gcode_dir",
            defaults.get("gcode_dir", "/home/isecapstone/laser_gcode/"),
        )
        self.declare_parameter(
            "default_gcode", defaults.get("default_gcode", "happyface.gcode")
        )
        self.declare_parameter(
            "allowed_gcode_files",
            defaults.get("allowed_gcode_files", ["happyface.gcode"]),
        )
        self.declare_parameter(
            "blocked_gcode_fragments",
            defaults.get("blocked_gcode_fragments", ["S25"]),
        )
        self.declare_parameter(
            "wait_time_before_start_sec",
            float(defaults.get("wait_time_before_start_sec", 30.0)),
        )
        self.declare_parameter(
            "prepare_delay_sec", float(defaults.get("prepare_delay_sec", 0.2))
        )
        self.declare_parameter(
            "job_duration_sec", float(defaults.get("job_duration_sec", 2.0))
        )
        self.declare_parameter(
            "inter_command_delay_sec",
            float(defaults.get("inter_command_delay_sec", 1.0)),
        )
        self.declare_parameter(
            "http_timeout_sec", float(defaults.get("http_timeout_sec", 10.0))
        )
        self.declare_parameter(
            "fail_on_gcode_error", bool(defaults.get("fail_on_gcode_error", True))
        )

        self.adapter = LaserAdapter(
            mode=self.get_parameter("mode").value,
            laser_ip=self.get_parameter("laser_ip").value,
            gcode_dir=self.get_parameter("gcode_dir").value,
            default_gcode=self.get_parameter("default_gcode").value,
            allowed_gcode_files=self.get_parameter("allowed_gcode_files").value,
            blocked_gcode_fragments=self.get_parameter("blocked_gcode_fragments").value,
            wait_time_before_start_sec=self.get_parameter(
                "wait_time_before_start_sec"
            ).value,
            prepare_delay_sec=self.get_parameter("prepare_delay_sec").value,
            job_duration_sec=self.get_parameter("job_duration_sec").value,
            inter_command_delay_sec=self.get_parameter("inter_command_delay_sec").value,
            http_timeout_sec=self.get_parameter("http_timeout_sec").value,
            fail_on_gcode_error=self.get_parameter("fail_on_gcode_error").value,
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
            return False, "laser busy"

        task_fn = self.adapter.make_task_fn(cmd)
        self.task_runner.run(
            task_fn=lambda: self._run_with_running_status(cmd, task_fn),
            on_complete=lambda result: self._publish_completed(cmd, result),
            on_error=lambda exc: self._publish_failed(cmd, exc),
        )
        return True, None

    def _run_with_running_status(self, cmd: dict, task_fn) -> dict:
        running_state = self._running_state_for(cmd.get("task", ""))
        if running_state:
            self.publish_status(
                command_id=cmd["command_id"],
                resource_id=cmd.get("resource_id", ""),
                task=cmd.get("task", ""),
                task_state=TaskState.RUNNING.value,
                resource_state=running_state,
                piece_id=cmd.get("piece_id"),
                source=cmd.get("source"),
                target=cmd.get("target"),
                route=cmd.get("route"),
                result={"code": "STARTED"},
                correlation_id=cmd.get("correlation_id"),
            )
        return task_fn()

    @staticmethod
    def _running_state_for(task: str) -> Optional[str]:
        if task == "PREPARE_JOB":
            return MachineState.PREPARING.value
        if task in {"RUN_JOB", "WORK"}:
            return MachineState.WORKING.value
        return None

    def _publish_completed(self, cmd: dict, result: dict) -> None:
        safe_result = dict(result)
        resource_state = safe_result.pop("resource_state", MachineState.IDLE.value)
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
        self.get_logger().error(f"Laser task failed: {exc}")
        self.publish_status(
            command_id=cmd["command_id"],
            resource_id=cmd.get("resource_id", ""),
            task=cmd.get("task", ""),
            task_state=TaskState.FAILED.value,
            resource_state=MachineState.ERROR.value,
            piece_id=cmd.get("piece_id"),
            source=cmd.get("source"),
            target=cmd.get("target"),
            route=cmd.get("route"),
            result={"code": "LASER_COMMAND_FAILED", "reason": str(exc)},
            correlation_id=cmd.get("correlation_id"),
        )


def main(args=None):
    rclpy.init(args=args)
    supervisor = LaserVendorSupervisor()
    executor = SingleThreadedExecutor()
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
