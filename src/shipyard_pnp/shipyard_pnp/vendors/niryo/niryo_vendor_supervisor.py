import os
import threading
from typing import Optional, Tuple

import rclpy
import yaml
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor

from shipyard_pnp.shared.contracts import (
    ConveyorState,
    RobotState,
    SensorState,
    TaskState,
    VacuumState,
    VisionState,
)
from shipyard_pnp.vendors.common.base_vendor_supervisor import BaseVendorSupervisor
from shipyard_pnp.vendors.common.task_runner import TaskRunner
from shipyard_pnp.vendors.niryo.local_vision_adapter import LocalVisionAdapter
from shipyard_pnp.vendors.niryo.niryo_conveyor_adapter import NiryoConveyorAdapter
from shipyard_pnp.vendors.niryo.niryo_ir_adapter import NiryoIRAdapter
from shipyard_pnp.vendors.niryo.niryo_service_driver import NiryoServiceDriver
from shipyard_pnp.vendors.niryo.robot1_adapter import Robot1Adapter
from shipyard_pnp.vendors.niryo.robot2_adapter import Robot2Adapter
from shipyard_pnp.vendors.niryo.robot2_niryo_vacuum_adapter import (
    Robot2NiryoVacuumAdapter,
)

_SUPPORTED_RESOURCES = {
    "robot1",
    "robot2",
    "conveyor1",
    "conveyor2",
    "vision_robot1",
    "vision_robot2",
    "robot2_niryo_vacuum",
    "c1s1",
    "c1s2",
    "c2s1",
    "c2s2",
}

# Maps each resource_id to the TaskRunner key that serialises its execution.
# robot2 / vision_robot2 / robot2_niryo_vacuum share one runner because the
# robot2 adapter orchestrates vision and vacuum internally.
_RESOURCE_TO_RUNNER = {
    "robot1": "robot1",
    "robot2": "robot2",
    "vision_robot1": "robot1",
    "vision_robot2": "robot2",
    "robot2_niryo_vacuum": "robot2",
    "conveyor1": "conveyor1",
    "conveyor2": "conveyor2",
    "c1s1": None,   # sensor reads are fast/synchronous; no TaskRunner needed
    "c1s2": None,
    "c2s1": None,
    "c2s2": None,
}

_SUPPORTED_TASKS = {
    "INITIALIZE_DOMAIN",
    "MOVE_ROBOT",
    "MOVE_PIECE",
    "CAPTURE_LOCAL_VISION",
    "CLASSIFY_AND_PICK",
    "RUN_NIRYO_CONVEYOR",
    "STOP_NIRYO_CONVEYOR",
    "READ_IR_SENSOR",
    "SENSOR_UPDATE",
    "GOTO_PICK_POSITION",
    "LIFT_AND_PLACE",
    "RETURN_HOME",
    "RESET",
    "PICK",
    "RELEASE",
    "OFF",
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
        return data.get("niryo", {}) or {}
    except Exception:
        return {}


class NiryoVendorSupervisor(BaseVendorSupervisor):
    """Vendor supervisor for both Niryo Ned2 robots, local vision, IR and conveyors."""

    def __init__(self):
        super().__init__("niryo")
        defaults = _load_defaults()
        self.service_cbg = ReentrantCallbackGroup()
        self._publish_lock = threading.Lock()
        self._sensor_poll_lock = threading.Lock()
        self._sensor_poll_error_logged = False

        self.declare_parameter("mode", defaults.get("mode", "dry_run"))
        self.declare_parameter("robot1_namespace", defaults.get("robot1_namespace", "/robot1"))
        self.declare_parameter("robot1_ip", defaults.get("robot1_ip", ""))
        self.declare_parameter("robot2_namespace", defaults.get("robot2_namespace", "/robot2"))
        self.declare_parameter("robot2_ip", defaults.get("robot2_ip", ""))
        self.declare_parameter(
            "service_wait_timeout_sec",
            float(defaults.get("service_wait_timeout_sec", 10.0)),
        )
        self.declare_parameter(
            "command_timeout_sec",
            float(defaults.get("command_timeout_sec", 45.0)),
        )
        self.declare_parameter("settle_time_sec", float(defaults.get("settle_time_sec", 0.2)))
        self.declare_parameter("vacuum_delay_sec", float(defaults.get("vacuum_delay_sec", 0.5)))
        self.declare_parameter(
            "sensor_poll_interval_sec",
            float(defaults.get("sensor_poll_interval_sec", 0.2)),
        )
        self.declare_parameter(
            "conveyor_run_timeout_sec",
            float(defaults.get("conveyor_run_timeout_sec", 30.0)),
        )
        self.declare_parameter(
            "vision_default_color",
            defaults.get("vision_default_color", "RED"),
        )
        self.declare_parameter(
            "vision_capture_timeout_sec",
            float(defaults.get("vision_capture_timeout_sec", 8.0)),
        )
        self.declare_parameter(
            "vision_target_captures",
            int(defaults.get("vision_target_captures", 15)),
        )
        self.declare_parameter(
            "vision_detection_threshold",
            float(defaults.get("vision_detection_threshold", 0.03)),
        )

        dry_run = self._mode_is_dry_run(self.get_parameter("mode").value)
        shared_driver_args = {
            "node": self,
            "dry_run": dry_run,
            "service_wait_timeout_sec": self.get_parameter(
                "service_wait_timeout_sec"
            ).value,
            "command_timeout_sec": self.get_parameter("command_timeout_sec").value,
            "settle_time_sec": self.get_parameter("settle_time_sec").value,
            "vacuum_delay_sec": self.get_parameter("vacuum_delay_sec").value,
            "callback_group": self.service_cbg,
        }
        self.robot1_driver = NiryoServiceDriver(
            robot_id="robot1",
            namespace=self.get_parameter("robot1_namespace").value,
            vacuum_tool_id=int(defaults.get("robot1_vacuum_tool_id", 31)),
            **shared_driver_args,
        )
        self.robot2_driver = NiryoServiceDriver(
            robot_id="robot2",
            namespace=self.get_parameter("robot2_namespace").value,
            vacuum_tool_id=int(defaults.get("robot2_vacuum_tool_id", 31)),
            **shared_driver_args,
        )

        self.robot1 = Robot1Adapter(self.robot1_driver)
        self.robot2 = Robot2Adapter(self.robot2_driver)
        self.robot2_vacuum = Robot2NiryoVacuumAdapter(self.robot2_driver)
        self.vision_robot1 = LocalVisionAdapter(
            node=self,
            robot_id=1,
            camera_topic=str(
                defaults.get(
                    "vision_robot1_topic",
                    f"{self.get_parameter('robot1_namespace').value}/niryo_robot_vision/compressed_video_stream",
                )
            ),
            dry_run=dry_run,
            default_color=self.get_parameter("vision_default_color").value,
            detection_threshold=self.get_parameter("vision_detection_threshold").value,
            target_captures=self.get_parameter("vision_target_captures").value,
            capture_timeout_sec=self.get_parameter("vision_capture_timeout_sec").value,
            callback_group=self.service_cbg,
        )
        self.vision_robot2 = LocalVisionAdapter(
            node=self,
            robot_id=2,
            camera_topic=str(
                defaults.get(
                    "vision_robot2_topic",
                    f"{self.get_parameter('robot2_namespace').value}/niryo_robot_vision/compressed_video_stream",
                )
            ),
            dry_run=dry_run,
            default_color=self.get_parameter("vision_default_color").value,
            detection_threshold=self.get_parameter("vision_detection_threshold").value,
            target_captures=self.get_parameter("vision_target_captures").value,
            capture_timeout_sec=self.get_parameter("vision_capture_timeout_sec").value,
            callback_group=self.service_cbg,
        )

        self.conveyors = self._build_conveyors(defaults)
        self.ir_sensors = self._build_ir_sensors()

        # Per-resource TaskRunners — allows robot1, robot2, conveyor1, conveyor2
        # to execute hardware tasks concurrently inside this VS.
        self._runners: dict[str, TaskRunner] = {
            "robot1": TaskRunner(),
            "robot2": TaskRunner(),
            "conveyor1": TaskRunner(),
            "conveyor2": TaskRunner(),
        }

        self._sensor_timer = None
        poll_interval = self.get_parameter("sensor_poll_interval_sec").value
        if not dry_run and poll_interval > 0.0:
            self._sensor_timer = self.create_timer(
                poll_interval,
                self._poll_sensors_once,
                callback_group=self.service_cbg,
            )

        self.get_logger().info(
            f"niryo mode={'dry_run' if dry_run else 'hardware'} "
            f"robot1={self.get_parameter('robot1_namespace').value} "
            f"({self.get_parameter('robot1_ip').value}) "
            f"robot2={self.get_parameter('robot2_namespace').value} "
            f"({self.get_parameter('robot2_ip').value})"
        )

    def handle_task(self, cmd: dict) -> Tuple[bool, Optional[str]]:
        resource_id = cmd.get("resource_id")
        task = cmd.get("task")

        if resource_id not in _SUPPORTED_RESOURCES:
            return False, f"Unsupported resource_id: {resource_id}"
        if task not in _SUPPORTED_TASKS:
            return False, f"Unsupported task: {task}"

        runner_key = _RESOURCE_TO_RUNNER.get(resource_id)

        # Sensor reads are fast and synchronous — no TaskRunner needed.
        if runner_key is None:
            try:
                result = self._make_task_fn(cmd)()
                self._publish_completed(cmd, result)
            except Exception as exc:
                self._publish_failed(cmd, exc)
            return True, None

        runner = self._runners[runner_key]
        if runner.is_running():
            return False, f"{resource_id} busy"

        self.get_logger().info(
            f"Accepted Niryo command {cmd.get('command_id')} {resource_id}/{task}"
        )
        runner.run(
            task_fn=self._make_task_fn(cmd),
            on_complete=lambda result: self._publish_completed(cmd, result),
            on_error=lambda exc: self._publish_failed(cmd, exc),
        )
        return True, None

    def _build_conveyors(self, defaults: dict) -> dict:
        run_timeout = self.get_parameter("conveyor_run_timeout_sec").value
        poll_interval = self.get_parameter("sensor_poll_interval_sec").value
        cfg1 = defaults.get("conveyor1", {}) or {}
        cfg2 = defaults.get("conveyor2", {}) or {}
        return {
            "conveyor1": NiryoConveyorAdapter(
                resource_id="conveyor1",
                driver=self.robot1_driver,
                hardware_id=int(cfg1.get("hardware_id", defaults.get("conveyor1_hardware_id", 9))),
                speed=int(cfg1.get("speed", defaults.get("conveyor_speed", 100))),
                direction=int(cfg1.get("direction", defaults.get("conveyor_direction", 1))),
                sensors=cfg1.get(
                    "sensors",
                    {
                        "c1s1": {"pin": "DI5", "active_low": True},
                        "c1s2": {"pin": "DI1", "active_low": True},
                    },
                ),
                exit_sensor_id=str(cfg1.get("exit_sensor_id", "c1s2")),
                poll_interval_sec=poll_interval,
                run_timeout_sec=run_timeout,
                dry_run_duration_sec=float(defaults.get("dry_run_conveyor_duration_sec", 1.0)),
            ),
            "conveyor2": NiryoConveyorAdapter(
                resource_id="conveyor2",
                driver=self.robot2_driver,
                hardware_id=int(cfg2.get("hardware_id", defaults.get("conveyor2_hardware_id", 9))),
                speed=int(cfg2.get("speed", defaults.get("conveyor_speed", 100))),
                direction=int(cfg2.get("direction", defaults.get("conveyor_direction", 1))),
                sensors=cfg2.get(
                    "sensors",
                    {
                        "c2s1": {"pin": "DI5", "active_low": True},
                        "c2s2": {"pin": "DI1", "active_low": True},
                    },
                ),
                exit_sensor_id=str(cfg2.get("exit_sensor_id", "c2s2")),
                poll_interval_sec=poll_interval,
                run_timeout_sec=run_timeout,
                dry_run_duration_sec=float(defaults.get("dry_run_conveyor_duration_sec", 1.0)),
            ),
        }

    def _build_ir_sensors(self) -> dict:
        sensors = {}
        for conveyor in self.conveyors.values():
            for sensor_id, cfg in conveyor.sensors.items():
                sensors[sensor_id] = NiryoIRAdapter(
                    sensor_id=sensor_id,
                    driver=conveyor.driver,
                    pin=cfg["pin"],
                    active_low=cfg.get("active_low", True),
                )
        return sensors

    def _make_task_fn(self, cmd: dict):
        task = cmd.get("task", "")
        resource_id = cmd.get("resource_id", "")
        params = cmd.get("parameters") or {}

        def status_cb(state: str, result: dict) -> None:
            self._publish_running(cmd, state, result)

        def fn() -> dict:
            if task == "INITIALIZE_DOMAIN":
                return self._initialize_domain(cmd)

            if task in {"MOVE_ROBOT", "RETURN_HOME"}:
                target = str(params.get("target", "HOME")).upper()
                if target != "HOME":
                    raise ValueError(f"Unsupported Niryo MOVE_ROBOT target: {target}")
                return self._robot_adapter(resource_id).move_home(status_cb)

            if task == "RESET":
                if resource_id in {"robot1", "robot2"}:
                    return self._robot_adapter(resource_id).reset(status_cb)
                if resource_id in {"conveyor1", "conveyor2"}:
                    return self.conveyors[resource_id].stop(status_cb)
                if resource_id == "robot2_niryo_vacuum":
                    return self.robot2_vacuum.off(
                        self._resource_status_cb(cmd, "robot2_niryo_vacuum")
                    )
                return {"resource_state": VisionState.IDLE.value, "code": "RESET"}

            if task == "GOTO_PICK_POSITION":
                if resource_id != "robot1":
                    raise ValueError("GOTO_PICK_POSITION is only supported by robot1")
                position = params.get("position") or cmd.get("source")
                return self.robot1.goto_pick_position(position, status_cb)

            if task == "LIFT_AND_PLACE":
                if resource_id != "robot1":
                    raise ValueError("LIFT_AND_PLACE is only supported by robot1")
                target = params.get("target") or cmd.get("target")
                return self.robot1.lift_and_place(target, status_cb)

            if task == "CAPTURE_LOCAL_VISION":
                if resource_id == "robot2":
                    return self.robot2.capture_local_vision(
                        self.vision_robot2,
                        status_cb=status_cb,
                        vision_status_cb=self._resource_status_cb(cmd, "vision_robot2"),
                    )
                raise ValueError("CAPTURE_LOCAL_VISION is only supported by robot2")

            if task == "CLASSIFY_AND_PICK":
                if resource_id != "robot1":
                    raise ValueError("CLASSIFY_AND_PICK is only supported by robot1")
                position = params.get("position") or cmd.get("source", "C3")
                return self.robot1.classify_and_goto_pick(
                    position=position,
                    vision_adapter=self.vision_robot1,
                    status_cb=status_cb,
                    vision_status_cb=self._resource_status_cb(cmd, "vision_robot1"),
                )

            if task == "MOVE_PIECE":
                if resource_id != "robot2":
                    raise ValueError("Niryo MOVE_PIECE is only supported by robot2")
                source = params.get("source") or cmd.get("source")
                target = params.get("target") or cmd.get("target")
                return self.robot2.move_piece(source, target, status_cb)

            if task == "RUN_NIRYO_CONVEYOR":
                conveyor_id = params.get("conveyor_id") or resource_id
                return self.conveyors[conveyor_id].run_until_exit_sensor(
                    status_cb=status_cb,
                    sensor_cb=self._publish_auto_sensor,
                )

            if task == "STOP_NIRYO_CONVEYOR":
                conveyor_id = params.get("conveyor_id") or resource_id
                return self.conveyors[conveyor_id].stop(status_cb)

            if task == "READ_IR_SENSOR":
                sensor_id = params.get("sensor_id") or resource_id
                return self._read_ir_sensor(sensor_id)

            if task == "SENSOR_UPDATE":
                sensor_id = params.get("sensor_id") or resource_id
                state = params.get("state") or SensorState.UNKNOWN.value
                return {
                    "resource_state": state,
                    "code": "SENSOR_UPDATE",
                    "sensor_id": sensor_id,
                    "state": state,
                }

            if resource_id == "robot2_niryo_vacuum":
                vacuum_cb = self._resource_status_cb(cmd, "robot2_niryo_vacuum")
                if task == "PICK":
                    return self.robot2_vacuum.pick(vacuum_cb)
                if task == "RELEASE":
                    return self.robot2_vacuum.release(vacuum_cb)
                if task == "OFF":
                    return self.robot2_vacuum.off(vacuum_cb)

            raise ValueError(f"Unsupported Niryo task: {task}")

        return fn

    def _initialize_domain(self, cmd: dict) -> dict:
        init = {}
        init["robot1"] = self.robot1.initialize(self._resource_status_cb(cmd, "robot1"))
        init["robot2"] = self.robot2.initialize(self._resource_status_cb(cmd, "robot2"))
        init["vision_robot1"] = self.vision_robot1.initialize(
            self._resource_status_cb(cmd, "vision_robot1")
        )
        init["vision_robot2"] = self.vision_robot2.initialize(
            self._resource_status_cb(cmd, "vision_robot2")
        )
        for conveyor_id, conveyor in self.conveyors.items():
            init[conveyor_id] = conveyor.initialize(
                self._resource_status_cb(cmd, conveyor_id),
                sensor_cb=self._publish_auto_sensor,
            )
        return {
            "resource_state": RobotState.IDLE.value,
            "code": "INITIALIZED",
            "initialized": sorted(init.keys()),
        }

    def _robot_adapter(self, resource_id: str):
        if resource_id == "robot1":
            return self.robot1
        if resource_id == "robot2":
            return self.robot2
        raise ValueError(f"Unsupported robot resource: {resource_id}")

    def _read_ir_sensor(self, sensor_id: str) -> dict:
        if sensor_id not in self.ir_sensors:
            raise ValueError(f"Unsupported IR sensor: {sensor_id}")
        result = self.ir_sensors[sensor_id].read()
        return {
            "resource_state": result["state"],
            "code": "SENSOR_READ",
            **result,
        }

    def _poll_sensors_once(self) -> None:
        if not self._sensor_poll_lock.acquire(blocking=False):
            return
        try:
            for conveyor in self.conveyors.values():
                updates = conveyor.poll_sensors(self._publish_auto_sensor)
                for u in updates:
                    self.get_logger().debug(
                        f"[sensor-raw] {u['sensor_id']} pin={u.get('pin')} "
                        f"raw={u.get('raw')} active_low={u.get('active_low')} "
                        f"→ {u['state']}"
                    )
            self._sensor_poll_error_logged = False
        except Exception as exc:
            if not self._sensor_poll_error_logged:
                self._sensor_poll_error_logged = True
                self.get_logger().warning(f"Niryo sensor polling paused: {exc}")
        finally:
            self._sensor_poll_lock.release()

    def _publish_auto_sensor(self, sensor_id: str, state: str) -> None:
        self.get_logger().info(f"[sensor] {sensor_id} → {state}")
        with self._publish_lock:
            self.publish_status(
                command_id="AUTO",
                resource_id=sensor_id,
                task="SENSOR_UPDATE",
                task_state=TaskState.COMPLETED.value,
                resource_state=state,
                result={
                    "code": "SENSOR_UPDATE",
                    "sensor_id": sensor_id,
                    "state": state,
                },
            )

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
        resource_state = safe_result.pop(
            "resource_state",
            self._default_resource_state(cmd.get("resource_id", "")),
        )
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
        self.get_logger().error(f"Niryo task failed: {exc}")
        with self._publish_lock:
            self.publish_status(
                command_id=cmd["command_id"],
                resource_id=cmd.get("resource_id", ""),
                task=cmd.get("task", ""),
                task_state=TaskState.FAILED.value,
                resource_state=self._error_resource_state(cmd.get("resource_id", "")),
                piece_id=cmd.get("piece_id"),
                source=cmd.get("source"),
                target=cmd.get("target"),
                route=cmd.get("route"),
                result={"code": "NIRYO_COMMAND_FAILED", "reason": str(exc)},
                correlation_id=cmd.get("correlation_id"),
            )

    @staticmethod
    def _default_resource_state(resource_id: str) -> str:
        if resource_id in {"conveyor1", "conveyor2"}:
            return ConveyorState.STOPPED.value
        if resource_id.startswith("vision_"):
            return VisionState.IDLE.value
        if resource_id in {"c1s1", "c1s2", "c2s1", "c2s2"}:
            return SensorState.UNKNOWN.value
        if resource_id == "robot2_niryo_vacuum":
            return VacuumState.IDLE.value
        return RobotState.IDLE.value

    @staticmethod
    def _error_resource_state(resource_id: str) -> str:
        if resource_id in {"conveyor1", "conveyor2"}:
            return ConveyorState.ERROR.value
        if resource_id.startswith("vision_"):
            return VisionState.ERROR.value
        if resource_id in {"c1s1", "c1s2", "c2s1", "c2s2"}:
            return SensorState.ERROR.value
        if resource_id == "robot2_niryo_vacuum":
            return VacuumState.ERROR.value
        return RobotState.ERROR.value

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
    supervisor = NiryoVendorSupervisor()
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
