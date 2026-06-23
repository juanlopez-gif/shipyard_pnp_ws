import glob
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from shipyard_pnp.vendors.globalvision.calibrator import (
    NORM_H,
    NORM_W,
    PROCESS_H,
    PROCESS_W,
    SLOT_NAMES,
    load_rois,
)
from shipyard_pnp.vendors.globalvision.slot_inventory import SlotInventory

COLOR_THRESHOLD_PCT = 5.0
COLOR_BGR = {
    "RED": (0, 0, 255),
    "GREEN": (0, 200, 0),
    "BLUE": (255, 80, 0),
    "NONE": (110, 110, 110),
}


class GlobalVisionCameraAdapter:
    """
    Camera adapter for the global initial-stack camera.

    Only color and occupancy are detected. Shape is intentionally not inferred.
    """

    def __init__(
        self,
        inventory: SlotInventory,
        camera_index: int = 0,
        camera_device: str = "",
        config_file: Optional[str] = None,
        color_threshold_pct: float = COLOR_THRESHOLD_PCT,
        logger=None,
    ):
        self.inventory = inventory
        self.camera_index = int(camera_index)
        self.camera_device = str(camera_device or "").strip()
        self.config_file = config_file
        self.color_threshold_pct = float(color_threshold_pct)
        self._logger = logger
        self._cap = None
        self._scan_seq = 0
        self._rois = load_rois(config_file)
        self._cv2 = None
        self._np = None
        self._camera_lock = threading.RLock()

    def make_task_fn(self, cmd: dict) -> Callable[[], dict]:
        task = cmd.get("task", "")
        params = cmd.get("parameters") or {}

        def fn() -> dict:
            if task == "INITIALIZE_DOMAIN":
                self.initialize()
                return {"resource_state": "IDLE", "code": "INITIALIZED"}
            if task == "SCAN_STACK":
                scan_id, slots = self.scan_stack()
                return {
                    "resource_state": "IDLE",
                    "code": "INVENTORY_READY",
                    "scan_id": scan_id,
                    "slots": slots,
                }
            if task == "LOCATE_NEXT_PIECE":
                color = params.get("color")
                scan_id, slot = self.locate_next_piece(color=color)
                if slot is None:
                    return {
                        "resource_state": "IDLE",
                        "code": "NOT_FOUND",
                        "scan_id": scan_id,
                    }
                return {
                    "resource_state": "IDLE",
                    "code": "SLOT_FOUND",
                    "slot_id": slot["slot_id"],
                    "color": slot["color"],
                    "shape": "UNKNOWN",
                    "confidence": slot["confidence_class"],
                    "confidence_class": slot["confidence_class"],
                    "scan_id": scan_id,
                }
            if task == "GET_INVENTORY":
                if self.inventory.last_scan_id is None:
                    scan_id, slots = self.scan_stack()
                else:
                    scan_id = self.inventory.last_scan_id
                    slots = self.inventory.snapshot()
                return {
                    "resource_state": "IDLE",
                    "code": "INVENTORY_READY",
                    "scan_id": scan_id,
                    "slots": slots,
                }
            raise ValueError(f"Unsupported globalvision task: {task}")

        return fn

    def initialize(self) -> None:
        self._open_camera()

    def scan_stack(self) -> Tuple[str, List[dict]]:
        with self._camera_lock:
            frame = self._capture_frame()
            self._scan_seq += 1
            scan_id = f"SCAN-{self._scan_seq:04d}"
            slots = []
            for slot_id in SLOT_NAMES:
                color, pct = self._detect_color(frame, self._rois[slot_id])
                occupied = color != "NONE"
                slots.append(
                    {
                        "slot_id": slot_id,
                        "occupied": occupied,
                        "color": color if occupied else "NONE",
                        "shape": "UNKNOWN",
                        "confidence_class": self._confidence_class(pct),
                        "scan_id": scan_id,
                    }
                )
        self.inventory.update_from_scan(scan_id, slots)
        return scan_id, slots

    def locate_next_piece(self, color: Optional[str] = None) -> Tuple[str, Optional[dict]]:
        scan_id, _ = self.scan_stack()
        return scan_id, self.inventory.get_next_slot_for_color(color)

    def close(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            finally:
                self._cap = None

    def _open_camera(self):
        if self._cap is not None and self._cap.isOpened():
            return self._cap
        cv2, _ = self._cv()
        source = self.camera_device or self.camera_index
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            raise RuntimeError(
                f"GlobalVision camera {source!r} unavailable; "
                f"available devices: {self._available_video_devices() or 'none'}"
            )
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc("M", "J", "P", "G"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, PROCESS_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, PROCESS_H)
        ret, _frame = cap.read()
        if not ret:
            cap.release()
            raise RuntimeError(f"GlobalVision camera {self.camera_index} did not return frames")
        self._cap = cap
        self._info(f"GlobalVision camera {source!r} opened")
        return self._cap

    def _capture_frame(self):
        with self._camera_lock:
            cv2, _ = self._cv()
            cap = self._open_camera()
            frame = None
            for _ in range(3):
                ret, candidate = cap.read()
                if ret and candidate is not None:
                    frame = candidate
                    break
                time.sleep(0.05)
            if frame is None:
                raise RuntimeError("GlobalVision camera frame capture failed")
            if frame.shape[1] != PROCESS_W or frame.shape[0] != PROCESS_H:
                frame = cv2.resize(frame, (PROCESS_W, PROCESS_H), interpolation=cv2.INTER_AREA)
            return frame

    def build_preview_image(self):
        with self._camera_lock:
            frame = self._capture_frame()
            detections = {}
            for slot_id in SLOT_NAMES:
                try:
                    detections[slot_id] = self._detect_color(frame, self._rois[slot_id])
                except Exception:
                    detections[slot_id] = ("NONE", 0.0)
            return self._draw_preview_overlay(frame, detections)

    def _detect_color(self, frame_bgr, corners: List[List[int]]) -> Tuple[str, float]:
        cv2, np = self._cv()
        src = np.float32(corners)
        dst = np.float32([[0, 0], [NORM_W, 0], [NORM_W, NORM_H], [0, NORM_H]])
        transform = cv2.getPerspectiveTransform(src, dst)
        warped = cv2.warpPerspective(frame_bgr, transform, (NORM_W, NORM_H))
        hsv = cv2.cvtColor(warped, cv2.COLOR_BGR2HSV)

        ranges = self._color_ranges(np)
        counts: Dict[str, int] = {}
        for name, hsv_ranges in ranges.items():
            total = 0
            for lo, hi in hsv_ranges:
                total += cv2.countNonZero(cv2.inRange(hsv, lo, hi))
            counts[name] = total

        best = max(counts, key=counts.get)
        pct = (counts[best] / float(NORM_W * NORM_H)) * 100.0
        if pct < self.color_threshold_pct:
            return "NONE", 0.0
        return best, pct

    @staticmethod
    def _confidence_class(pct: float) -> str:
        if pct >= 20.0:
            return "HIGH"
        if pct >= 10.0:
            return "MEDIUM"
        return "LOW"

    def _cv(self):
        if self._cv2 is None or self._np is None:
            import cv2  # noqa: PLC0415
            import numpy as np  # noqa: PLC0415
            self._cv2 = cv2
            self._np = np
        return self._cv2, self._np

    @staticmethod
    def _color_ranges(np):
        return {
            "RED": [
                (np.array([0, 80, 60]), np.array([12, 255, 255])),
                (np.array([155, 60, 60]), np.array([180, 255, 255])),
            ],
            "GREEN": [
                (np.array([35, 40, 40]), np.array([90, 255, 255])),
            ],
            "BLUE": [
                (np.array([95, 70, 50]), np.array([130, 255, 255])),
            ],
        }

    def _info(self, msg: str) -> None:
        if self._logger is not None:
            self._logger.info(msg)

    @staticmethod
    def _available_video_devices() -> str:
        return ", ".join(sorted(glob.glob("/dev/video*")))

    def _draw_preview_overlay(self, frame, detections: dict):
        cv2, np = self._cv()
        img = frame.copy()
        counts = {"RED": 0, "GREEN": 0, "BLUE": 0, "NONE": 0}

        for slot_id in SLOT_NAMES:
            corners = self._rois.get(slot_id)
            if not corners:
                continue
            color, pct = detections.get(slot_id, ("NONE", 0.0))
            counts[color] = counts.get(color, 0) + 1
            pts = np.array(corners, dtype=np.int32)
            line_color = COLOR_BGR.get(color, COLOR_BGR["NONE"])
            thickness = 2 if color != "NONE" else 1
            cv2.polylines(img, [pts], True, line_color, thickness)

            tx = int(pts[:, 0].min())
            ty = max(int(pts[:, 1].min()) - 3, 12)
            cv2.putText(
                img,
                slot_id,
                (tx, ty),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

            if color != "NONE":
                cx = int(pts[:, 0].mean())
                cy = int(pts[:, 1].mean())
                cv2.putText(
                    img,
                    f"{color[0]}{pct:.0f}",
                    (cx - 14, cy + 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.38,
                    line_color,
                    1,
                    cv2.LINE_AA,
                )

        y = 22
        for line in (
            f"RED: {counts.get('RED', 0)}",
            f"GREEN: {counts.get('GREEN', 0)}",
            f"BLUE: {counts.get('BLUE', 0)}",
            f"NONE: {counts.get('NONE', 0)}",
            "Shape: disabled",
        ):
            cv2.putText(
                img,
                line,
                (12, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 255),
                1,
                cv2.LINE_AA,
            )
            y += 24
        return img
