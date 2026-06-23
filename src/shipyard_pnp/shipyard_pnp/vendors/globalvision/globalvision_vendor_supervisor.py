import os
from typing import Optional, Tuple

import rclpy
import yaml
from rclpy.executors import SingleThreadedExecutor

from shipyard_pnp.vendors.common.base_vendor_supervisor import BaseVendorSupervisor
from shipyard_pnp.vendors.globalvision.calibrator import default_config_path
from shipyard_pnp.vendors.globalvision.camera_adapter import GlobalVisionCameraAdapter
from shipyard_pnp.vendors.globalvision.slot_inventory import SlotInventory

_RESOURCE_ID = "globalvision_camera"
_SUPPORTED_TASKS = {
    "INITIALIZE_DOMAIN",
    "SCAN_STACK",
    "LOCATE_NEXT_PIECE",
    "GET_INVENTORY",
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
        return data.get("globalvision", {}) or {}
    except Exception:
        return {}


class GlobalVisionVendorSupervisor(BaseVendorSupervisor):
    """Vendor supervisor for global stack camera and slot inventory."""

    def __init__(self):
        super().__init__("globalvision")
        defaults = _load_defaults()

        self.declare_parameter("camera_index", int(defaults.get("camera_index", 0)))
        self.declare_parameter("camera_device", defaults.get("camera_device", ""))
        self.declare_parameter(
            "config_file", defaults.get("config_file", default_config_path())
        )
        self.declare_parameter(
            "color_threshold_pct", float(defaults.get("color_threshold_pct", 5.0))
        )
        self.declare_parameter("show_window", bool(defaults.get("show_window", False)))

        self.inventory = SlotInventory()
        self.camera = GlobalVisionCameraAdapter(
            inventory=self.inventory,
            camera_index=self.get_parameter("camera_index").value,
            camera_device=self.get_parameter("camera_device").value,
            config_file=self.get_parameter("config_file").value,
            color_threshold_pct=self.get_parameter("color_threshold_pct").value,
            logger=self.get_logger(),
        )
        self._show_window = bool(self.get_parameter("show_window").value)
        self._preview_window = "GlobalVision Vendor Preview  [Q/ESC cerrar ventana]"
        self._preview_error_logged = False
        if self._show_window:
            self._cv2, _ = self.camera._cv()
            self._cv2.namedWindow(self._preview_window, self._cv2.WINDOW_NORMAL)
            self._cv2.resizeWindow(self._preview_window, 960, 720)
            self._preview_timer = self.create_timer(0.05, self._preview_tick)
            self.get_logger().info("GlobalVision preview window enabled")

    def handle_task(self, cmd: dict) -> Tuple[bool, Optional[str]]:
        resource_id = cmd.get("resource_id")
        task = cmd.get("task")
        if resource_id != _RESOURCE_ID:
            return False, f"Unsupported resource_id: {resource_id}"
        if task not in _SUPPORTED_TASKS:
            return False, f"Unsupported task: {task}"
        if self.task_runner.is_running():
            return False, "globalvision busy"

        if task == "RESET":
            task_fn = self._make_reset_task_fn()
        else:
            task_fn = self.camera.make_task_fn(cmd)
        self.task_runner.run(
            task_fn=task_fn,
            on_complete=lambda result: self._publish_completed(cmd, result),
            on_error=lambda exc: self._publish_failed(cmd, exc),
        )
        return True, None

    def _make_reset_task_fn(self):
        def fn() -> dict:
            self.inventory = SlotInventory()
            self.camera.inventory = self.inventory
            return {"resource_state": "IDLE", "code": "RESET_DONE"}

        return fn

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
        self.get_logger().error(f"GlobalVision task failed: {exc}")
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
            result={"code": "GLOBALVISION_COMMAND_FAILED", "reason": "camera_error"},
            correlation_id=cmd.get("correlation_id"),
        )

    def _preview_tick(self) -> None:
        if not self._show_window:
            return
        try:
            img = self.camera.build_preview_image()
            self._cv2.imshow(self._preview_window, img)
            key = self._cv2.waitKey(1) & 0xFF
            if key in (27, ord("q"), ord("Q")):
                self._show_window = False
                self._cv2.destroyWindow(self._preview_window)
                self.get_logger().info("GlobalVision preview window closed")
        except Exception as exc:
            if not self._preview_error_logged:
                self._preview_error_logged = True
                self.get_logger().error(f"GlobalVision preview failed: {exc}")

    def destroy_node(self) -> None:
        self.camera.close()
        if getattr(self, "_show_window", False):
            try:
                self._cv2.destroyWindow(self._preview_window)
            except Exception:
                pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    supervisor = GlobalVisionVendorSupervisor()
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
