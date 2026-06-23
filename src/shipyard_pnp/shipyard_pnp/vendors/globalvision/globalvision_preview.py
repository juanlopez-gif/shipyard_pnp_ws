import rclpy
from rclpy.node import Node

from shipyard_pnp.vendors.globalvision.camera_adapter import GlobalVisionCameraAdapter
from shipyard_pnp.vendors.globalvision.calibrator import SLOT_NAMES
from shipyard_pnp.vendors.globalvision.slot_inventory import SlotInventory

COLOR_BGR = {
    "RED": (0, 0, 255),
    "GREEN": (0, 200, 0),
    "BLUE": (255, 80, 0),
    "NONE": (110, 110, 110),
}


class GlobalVisionPreview(Node):
    """Local OpenCV preview window for GlobalVision ROIs and color detection."""

    def __init__(self):
        super().__init__("globalvision_preview")
        self.declare_parameter("camera_index", 0)
        self.declare_parameter("camera_device", "")
        self.declare_parameter("config_file", "")
        self.declare_parameter("color_threshold_pct", 5.0)

        self.adapter = GlobalVisionCameraAdapter(
            inventory=SlotInventory(),
            camera_index=self.get_parameter("camera_index").value,
            camera_device=self.get_parameter("camera_device").value,
            config_file=self.get_parameter("config_file").value,
            color_threshold_pct=self.get_parameter("color_threshold_pct").value,
            logger=self.get_logger(),
        )
        self.cv2, self.np = self.adapter._cv()
        self.window_name = "GlobalVision Preview  [Q/ESC cerrar]"
        self.cv2.namedWindow(self.window_name, self.cv2.WINDOW_NORMAL)
        self.cv2.resizeWindow(self.window_name, 960, 720)
        self.timer = self.create_timer(0.033, self._tick)
        self.get_logger().info("GlobalVision preview window ready")

    def _tick(self) -> None:
        try:
            frame = self.adapter._capture_frame()
        except Exception as exc:
            self.get_logger().error(f"Preview capture failed: {exc}")
            return

        detections = {}
        for slot_id in SLOT_NAMES:
            try:
                color, pct = self.adapter._detect_color(
                    frame, self.adapter._rois[slot_id]
                )
            except Exception:
                color, pct = "NONE", 0.0
            detections[slot_id] = (color, pct)

        display = self._draw_overlay(frame, detections)
        self.cv2.imshow(self.window_name, display)
        key = self.cv2.waitKey(1) & 0xFF
        if key in (27, ord("q"), ord("Q")):
            self.get_logger().info("Closing GlobalVision preview")
            self.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()

    def _draw_overlay(self, frame, detections: dict):
        img = frame.copy()
        counts = {"RED": 0, "GREEN": 0, "BLUE": 0, "NONE": 0}

        for slot_id in SLOT_NAMES:
            corners = self.adapter._rois.get(slot_id)
            if not corners:
                continue
            color, pct = detections.get(slot_id, ("NONE", 0.0))
            counts[color] = counts.get(color, 0) + 1
            pts = self.np.array(corners, dtype=self.np.int32)
            line_color = COLOR_BGR.get(color, COLOR_BGR["NONE"])
            thickness = 2 if color != "NONE" else 1
            self.cv2.polylines(img, [pts], True, line_color, thickness)

            tx = int(pts[:, 0].min())
            ty = max(int(pts[:, 1].min()) - 3, 12)
            self.cv2.putText(
                img,
                slot_id,
                (tx, ty),
                self.cv2.FONT_HERSHEY_SIMPLEX,
                0.38,
                (255, 255, 255),
                1,
                self.cv2.LINE_AA,
            )

            if color != "NONE":
                cx = int(pts[:, 0].mean())
                cy = int(pts[:, 1].mean())
                self.cv2.putText(
                    img,
                    f"{color[0]}{pct:.0f}",
                    (cx - 14, cy + 5),
                    self.cv2.FONT_HERSHEY_SIMPLEX,
                    0.38,
                    line_color,
                    1,
                    self.cv2.LINE_AA,
                )

        panel = [
            f"RED: {counts.get('RED', 0)}",
            f"GREEN: {counts.get('GREEN', 0)}",
            f"BLUE: {counts.get('BLUE', 0)}",
            f"NONE: {counts.get('NONE', 0)}",
            "Shape: disabled",
        ]
        y = 22
        for line in panel:
            self.cv2.putText(
                img,
                line,
                (12, y),
                self.cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 255),
                1,
                self.cv2.LINE_AA,
            )
            y += 24
        return img

    def destroy_node(self):
        self.adapter.close()
        self.cv2.destroyAllWindows()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = GlobalVisionPreview()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
