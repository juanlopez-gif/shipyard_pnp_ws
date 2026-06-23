"""
LocalVisionAdapter — YOLO-based color+shape detection for the Niryo camera.

Model search order (first hit wins):
  1. SHIPYARD_ML_MODEL_PATH environment variable
  2. <workspace_root>/models/best.pt   (recommended — put your model here)
  3. <workspace_root>/models/*.pt      (any .pt in that directory)

Workspace root is resolved by walking up from this file until a directory
that contains a 'models/' subdirectory is found, OR the environment variable
COLCON_PREFIX_PATH / a sentinel file is present.

The adapter exposes exactly the same public interface as before:
  initialize(status_cb) → dict
  capture(status_cb)    → dict  (returns color, shape, confidence)

HSV is NOT used. The YOLO model is the single source of truth.
"""

import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy

from shipyard_pnp.shared.contracts import VisionState

_VALID_COLORS = {"RED", "GREEN", "BLUE"}
_VALID_SHAPES = {"CIRCLE", "SQUARE", "TRIANGLE", "HEXAGON"}
_CONFIDENCE_THRESHOLDS = {"HIGH": 0.70, "MEDIUM": 0.45, "LOW": 0.0}


def _find_model_path() -> Optional[Path]:
    env = os.environ.get("SHIPYARD_ML_MODEL_PATH")
    if env:
        p = Path(env)
        if p.is_file():
            return p

    # Walk up from this file to find a workspace root with a 'models/' dir
    here = Path(__file__).resolve()
    for parent in [here] + list(here.parents):
        candidate = parent / "models"
        if candidate.is_dir():
            best = candidate / "best.pt"
            if best.is_file():
                return best
            pts = sorted(candidate.glob("*.pt"))
            if pts:
                return pts[0]

    return None


def _classify_confidence(score: float) -> str:
    if score >= _CONFIDENCE_THRESHOLDS["HIGH"]:
        return "HIGH"
    if score >= _CONFIDENCE_THRESHOLDS["MEDIUM"]:
        return "MEDIUM"
    return "LOW"


def _split_label(label: str):
    """'blue_square' → ('BLUE', 'SQUARE').  'red' → ('RED', 'UNKNOWN')."""
    cleaned = str(label).strip().replace("-", "_").replace(" ", "_")
    parts = [p for p in cleaned.split("_") if p]
    color = parts[0].upper() if parts else "UNKNOWN"
    shape = "_".join(p.upper() for p in parts[1:]) if len(parts) >= 2 else "UNKNOWN"
    return color, shape


class LocalVisionAdapter:
    """YOLO-based local vision for the Niryo camera. No HSV."""

    def __init__(
        self,
        node,
        robot_id: int,
        camera_topic: str,
        dry_run: bool = True,
        default_color: str = "RED",
        default_shape: str = "CIRCLE",
        capture_timeout_sec: float = 8.0,
        ml_inference_count: int = 3,      # frames to infer and vote over
        callback_group=None,
        # Legacy params accepted but ignored (removed from active use)
        roi_size: int = 72,
        detection_threshold: float = 0.03,
        target_captures: int = 15,
    ):
        self.node = node
        self.robot_id = int(robot_id)
        self.camera_topic = camera_topic
        self.dry_run = bool(dry_run)
        self.default_color = str(default_color).upper()
        self.default_shape = str(default_shape).upper()
        self.capture_timeout_sec = float(capture_timeout_sec)
        self.ml_inference_count = max(1, int(ml_inference_count))
        self.callback_group = callback_group

        self.latest_image = None
        self._image_lock = threading.Lock()
        self._subscription = None

        # Lazily loaded — avoids import errors when ultralytics isn't installed
        self._model = None
        self._model_lock = threading.Lock()
        self._model_path: Optional[Path] = None

        if not self.dry_run:
            self._setup_subscription()
            self._model_path = _find_model_path()
            if self._model_path is None:
                node.get_logger().error(
                    "LocalVisionAdapter: no ML model found. "
                    "Put your YOLO model at <workspace>/models/best.pt "
                    "or set SHIPYARD_ML_MODEL_PATH."
                )
            else:
                node.get_logger().info(
                    f"LocalVisionAdapter: model path = {self._model_path}"
                )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def initialize(self, status_cb: Optional[Callable] = None) -> dict:
        self._status(status_cb, VisionState.IDLE.value, "INITIALIZED")
        return {"resource_state": VisionState.IDLE.value, "code": "INITIALIZED"}

    def capture(self, status_cb: Optional[Callable] = None) -> dict:
        if self.dry_run:
            self._status(status_cb, VisionState.PROCESSING.value, "DRY_RUN_CAPTURE")
            time.sleep(0.1)
            self._status(status_cb, VisionState.RESULT_READY.value, "RESULT_READY")
            return {
                "color": self.default_color,
                "shape": self.default_shape,
                "confidence": "HIGH",
            }

        if self._model_path is None:
            raise RuntimeError(
                "No YOLO model available. "
                "Set SHIPYARD_ML_MODEL_PATH or place best.pt in <workspace>/models/"
            )

        self._status(status_cb, VisionState.PROCESSING.value, "WAITING_FRAME")
        frame = self._wait_for_frame(timeout=self.capture_timeout_sec)
        if frame is None:
            raise TimeoutError(
                f"No camera frame received within {self.capture_timeout_sec}s "
                f"on topic {self.camera_topic}"
            )

        self._status(status_cb, VisionState.PROCESSING.value, "RUNNING_ML")
        model = self._get_model()

        votes_color: list[str] = []
        votes_shape: list[str] = []
        best_confidence = 0.0

        for _ in range(self.ml_inference_count):
            current = self._latest_frame_copy()
            if current is None:
                current = frame
            color, shape, conf = self._infer(model, current)
            votes_color.append(color)
            votes_shape.append(shape)
            if conf > best_confidence:
                best_confidence = conf

        final_color = _majority(votes_color, fallback="UNKNOWN")
        final_shape = _majority(votes_shape, fallback="UNKNOWN")
        confidence_class = _classify_confidence(best_confidence)

        self.node.get_logger().info(
            f"Vision R{self.robot_id}: {final_color}/{final_shape} "
            f"conf={best_confidence:.2f} ({confidence_class})"
        )

        self._status(status_cb, VisionState.RESULT_READY.value, "RESULT_READY")
        return {
            "color": final_color,
            "shape": final_shape,
            "confidence": confidence_class,
            "confidence_score": round(best_confidence, 4),
        }

    # ------------------------------------------------------------------
    # ROS2 camera subscription
    # ------------------------------------------------------------------

    def _setup_subscription(self) -> None:
        try:
            from sensor_msgs.msg import CompressedImage
        except Exception as exc:
            raise RuntimeError(
                "sensor_msgs is required for Niryo local vision hardware mode"
            ) from exc
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self._subscription = self.node.create_subscription(
            CompressedImage,
            self.camera_topic,
            self._image_callback,
            qos,
            callback_group=self.callback_group,
        )

    def _image_callback(self, msg) -> None:
        try:
            import cv2
            import numpy as np
        except ImportError:
            return
        arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is not None:
            with self._image_lock:
                self.latest_image = frame

    def _latest_frame_copy(self):
        with self._image_lock:
            return None if self.latest_image is None else self.latest_image.copy()

    def _wait_for_frame(self, timeout: float):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = self._latest_frame_copy()
            if frame is not None:
                return frame
            time.sleep(0.05)
        return None

    # ------------------------------------------------------------------
    # YOLO inference
    # ------------------------------------------------------------------

    def _get_model(self):
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                raise RuntimeError(
                    "ultralytics is required for ML vision. "
                    "Install with: pip install ultralytics"
                ) from exc
            self._model = YOLO(str(self._model_path))
            return self._model

    def _infer(self, model, frame) -> tuple[str, str, float]:
        """Run one inference pass. Returns (color, shape, confidence_score)."""
        results = model.predict(source=frame, verbose=False)
        if not results:
            return "UNKNOWN", "UNKNOWN", 0.0

        first = results[0]
        names = getattr(first, "names", {}) or {}

        # Classification model (probs)
        probs = getattr(first, "probs", None)
        if probs is not None and getattr(probs, "top1", None) is not None:
            label = _lookup_name(names, int(probs.top1))
            conf = float(probs.top1conf)
            color, shape = _split_label(label)
            return color, shape, conf

        # Detection model (boxes)
        boxes = getattr(first, "boxes", None)
        if boxes is not None and len(boxes) > 0:
            confs = [float(c) for c in boxes.conf.tolist()]
            ids = [int(i) for i in boxes.cls.tolist()]
            best = max(range(len(confs)), key=lambda i: confs[i])
            label = _lookup_name(names, ids[best])
            color, shape = _split_label(label)
            return color, shape, confs[best]

        return "UNKNOWN", "UNKNOWN", 0.0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _status(cb: Optional[Callable], resource_state: str, code: str, **kw) -> None:
        if cb:
            cb(resource_state, {"code": code, **kw})


def _majority(votes: list[str], fallback: str = "UNKNOWN") -> str:
    if not votes:
        return fallback
    from collections import Counter
    return Counter(votes).most_common(1)[0][0]


def _lookup_name(names, index: int) -> str:
    if isinstance(names, dict):
        return str(names.get(index, index))
    if isinstance(names, (list, tuple)) and 0 <= index < len(names):
        return str(names[index])
    return str(index)
