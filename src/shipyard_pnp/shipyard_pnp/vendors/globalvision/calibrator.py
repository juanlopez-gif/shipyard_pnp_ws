import json
import os
from typing import Dict, List, Optional

import yaml

SLOT_NAMES = [f"s{col}.{row}" for col in range(1, 4) for row in range(1, 7)]
NORM_W = 64
NORM_H = 64
PROCESS_W = 640
PROCESS_H = 480


def default_config_path() -> str:
    source_candidate = os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "..",
            "..",
            "config",
            "globalvision_rois.yaml",
        )
    )
    if os.path.isfile(source_candidate):
        return source_candidate
    try:
        from ament_index_python.packages import get_package_share_directory
        pkg = get_package_share_directory("shipyard_pnp")
        install_candidate = os.path.join(pkg, "config", "globalvision_rois.yaml")
        if os.path.isfile(install_candidate):
            return install_candidate
    except Exception:
        pass
    return os.path.expanduser("~/camera_globalvision_rois.json")


def load_rois(config_file: Optional[str] = None) -> Dict[str, List[List[int]]]:
    path = config_file or default_config_path()
    if not path or not os.path.isfile(path):
        return build_default_rois()

    try:
        with open(path) as fh:
            if path.endswith(".json"):
                data = json.load(fh)
            else:
                data = yaml.safe_load(fh) or {}
    except Exception:
        return build_default_rois()

    slots = data.get("slots") if isinstance(data, dict) else None
    if not isinstance(slots, dict):
        return build_default_rois()

    rois = {}
    for slot_id, corners in slots.items():
        parsed = _parse_corners(corners)
        if parsed is not None:
            rois[slot_id] = parsed

    defaults = build_default_rois()
    for slot_id in SLOT_NAMES:
        rois.setdefault(slot_id, defaults[slot_id])
    return {slot_id: rois[slot_id] for slot_id in SLOT_NAMES}


def build_default_rois(fw: int = PROCESS_W, fh: int = PROCESS_H) -> Dict[str, List[List[int]]]:
    rois = {}
    for idx, name in enumerate(SLOT_NAMES):
        col = idx // 6
        row = idx % 6
        rois[name] = _default_corners(col, row, fw, fh)
    return rois


def _default_corners(col: int, row: int, fw: int, fh: int) -> List[List[int]]:
    n_cols, n_rows = 3, 6
    mx, my = 40, 30
    sw = (fw - 2 * mx) // n_cols
    sh = (fh - 2 * my) // n_rows
    pad = 5
    x0 = mx + col * sw + pad
    y0 = my + row * sh + pad
    x1 = x0 + sw - 2 * pad
    y1 = y0 + sh - 2 * pad
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _parse_corners(corners) -> Optional[List[List[int]]]:
    if not isinstance(corners, list) or len(corners) != 4:
        return None
    parsed = []
    for point in corners:
        if not isinstance(point, list) or len(point) != 2:
            return None
        parsed.append([int(point[0]), int(point[1])])
    return parsed
