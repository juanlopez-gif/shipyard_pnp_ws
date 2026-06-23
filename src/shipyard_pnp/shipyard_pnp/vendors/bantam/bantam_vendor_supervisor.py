import os
from typing import Optional, Tuple

import rclpy
import yaml
from rclpy.executors import MultiThreadedExecutor

from shipyard_pnp.shared.contracts import MachineState
from shipyard_pnp.vendors.bantam.bantam_adapter import BantamAdapter
from shipyard_pnp.vendors.bantam.door_adapter import DoorAdapter
from shipyard_pnp.vendors.common.base_vendor_supervisor import BaseVendorSupervisor

_RESOURCE_ID = "bantam"

_SUPPORTED_TASKS = {
    "INITIALIZE_DOMAIN",
    "RUN_JOB",
    "GET_READY",
    "OPEN_DOOR",
    "CLOSE_DOOR",
    "RESET",
}


def _hardware_config_path() -> Optional[str]:
    source_candidate = os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "..", "..", "config", "hardware_ports.yaml",
        )
    )
    if os.path.isfile(source_candidate):
        return source_candidate
    try:
        from ament_index_python.packages import get_package_share_directory
        pkg = get_package_share_directory("shipyard_pnp")
        candidate = os.path.join(pkg, "config", "hardware_ports.yaml")
        if os.path.isfile(candidate):
            return candidate
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
        return data.get("bantam", {}) or {}
    except Exception:
        return {}


class BantamVendorSupervisor(BaseVendorSupervisor):
    """
    Vendor supervisor for the Bantam CNC machine.

    Machining is currently SIMULATED (sleep). The door is REAL — it is
    controlled via /door/cmd and tracked via /door/status.

    See bantam_adapter.py module docstring for the serial CNC integration guide.
    """

    def __init__(self):
        super().__init__("bantam")
        defaults = _load_defaults()

        self.declare_parameter(
            "processing_time_sec",
            float(defaults.get("processing_time_sec", 25.0)),
        )
        self.declare_parameter(
            "settle_sec",
            float(defaults.get("settle_sec", 1.5)),
        )
        self.declare_parameter(
            "door_timeout_sec",
            float(defaults.get("door_timeout_sec", 12.0)),
        )
        self.declare_parameter(
            "door_cooldown_sec",
            float(defaults.get("door_cooldown_sec", 2.0)),
        )
        self.declare_parameter(
            "door_zmq_address",
            str(defaults.get("door_zmq_address", "tcp://192.168.0.171:5555")),
        )

        self.door = DoorAdapter(
            node=self,
            zmq_address=self.get_parameter("door_zmq_address").value,
            cooldown_sec=self.get_parameter("door_cooldown_sec").value,
            timeout_sec=self.get_parameter("door_timeout_sec").value,
        )

        self.bantam = BantamAdapter(
            door=self.door,
            processing_time_sec=self.get_parameter("processing_time_sec").value,
            settle_sec=self.get_parameter("settle_sec").value,
            door_timeout_sec=self.get_parameter("door_timeout_sec").value,
        )

        self.get_logger().info(
            f"bantam_vendor_supervisor ready  "
            f"(machining=SIMULATED {self.get_parameter('processing_time_sec').value}s, "
            f"door=REAL)"
        )

    # ── command dispatch ──────────────────────────────────────────────────

    def handle_task(self, cmd: dict) -> Tuple[bool, Optional[str]]:
        resource_id = cmd.get("resource_id", "")
        task        = cmd.get("task", "")

        if resource_id != _RESOURCE_ID:
            return False, f"Unsupported resource_id: {resource_id}"
        if task not in _SUPPORTED_TASKS:
            return False, f"Unsupported task: {task}"
        if task != "INITIALIZE_DOMAIN" and self.task_runner.is_running():
            return False, "bantam busy"

        if task == "INITIALIZE_DOMAIN":
            self.task_runner.run(
                task_fn=lambda: self.bantam.initialize(
                    status_cb=self._status_cb(cmd)
                ),
                on_complete=lambda r: self._publish_completed(cmd, r),
                on_error=lambda e: self._publish_failed(cmd, e),
            )

        elif task == "RUN_JOB":
            job_type = (cmd.get("parameters") or {}).get("job_type", "BLUE_PROCESS")
            self.task_runner.run(
                task_fn=lambda: self.bantam.run_job(
                    job_type=job_type,
                    status_cb=self._status_cb(cmd),
                ),
                on_complete=lambda r: self._publish_completed(cmd, r),
                on_error=lambda e: self._publish_failed(cmd, e),
            )

        elif task in {"GET_READY", "RESET"}:
            self.task_runner.run(
                task_fn=lambda: self.bantam.reset(
                    status_cb=self._status_cb(cmd)
                ),
                on_complete=lambda r: self._publish_completed(cmd, r),
                on_error=lambda e: self._publish_failed(cmd, e),
            )

        elif task == "OPEN_DOOR":
            self.task_runner.run(
                task_fn=lambda: self._open_door_task(cmd),
                on_complete=lambda r: self._publish_completed(cmd, r),
                on_error=lambda e: self._publish_failed(cmd, e),
            )

        elif task == "CLOSE_DOOR":
            self.task_runner.run(
                task_fn=lambda: self._close_door_task(cmd),
                on_complete=lambda r: self._publish_completed(cmd, r),
                on_error=lambda e: self._publish_failed(cmd, e),
            )

        return True, None

    # ── task helpers ──────────────────────────────────────────────────────

    def _open_door_task(self, cmd: dict) -> dict:
        self.door.open("OPEN_DOOR command")
        self.door.wait_for_open()
        return {"resource_state": MachineState.IDLE.value, "code": "DOOR_OPEN"}

    def _close_door_task(self, cmd: dict) -> dict:
        self.door.close("CLOSE_DOOR command")
        self.door.wait_for_closed()
        return {"resource_state": MachineState.IDLE.value, "code": "DOOR_CLOSED"}

    # ── status callbacks ──────────────────────────────────────────────────

    def _status_cb(self, cmd: dict):
        """Returns a callback that publishes intermediate RUNNING status messages."""
        _LOG_CODES = {
            "CLOSING_DOOR":          "[bantam] → CLOSING DOOR (starting machining)",
            "MACHINING_SIMULATED":   "[bantam] → WORKING (machining started)",
            "OPENING_DOOR_AFTER_JOB":"[bantam] → FINISHED (opening door for pickup)",
            "JOB_COMPLETE":          "[bantam] → JOB COMPLETE (door open, piece ready)",
        }
        def cb(resource_state: str, result: dict) -> None:
            code = result.get("code", "")
            msg = _LOG_CODES.get(code)
            if msg:
                piece_id = cmd.get("piece_id", "?")
                self.get_logger().info(f"{msg}  piece={piece_id}")
            self.publish_status(
                command_id=cmd["command_id"],
                resource_id=_RESOURCE_ID,
                task=cmd.get("task", ""),
                task_state="RUNNING",
                resource_state=resource_state,
                piece_id=cmd.get("piece_id"),
                source=cmd.get("source"),
                target=cmd.get("target"),
                route=cmd.get("route"),
                result=result,
                correlation_id=cmd.get("correlation_id"),
            )
        return cb

    def _publish_completed(self, cmd: dict, result: dict) -> None:
        safe_result    = dict(result)
        resource_state = safe_result.pop("resource_state", MachineState.IDLE.value)
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
        self.get_logger().error(f"Bantam task failed: {exc}")
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
            result={"code": "BANTAM_TASK_FAILED", "reason": str(exc)},
            correlation_id=cmd.get("correlation_id"),
        )


def main(args=None):
    rclpy.init(args=args)
    supervisor = BantamVendorSupervisor()
    executor = MultiThreadedExecutor(num_threads=2)
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
