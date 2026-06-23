from typing import Dict, List, Optional

from shipyard_pnp.vendors.globalvision.calibrator import SLOT_NAMES


class SlotInventory:
    """In-memory normalized inventory for the global stack."""

    def __init__(self):
        self._slots: Dict[str, dict] = {
            slot_id: {
                "slot_id": slot_id,
                "occupied": False,
                "color": "NONE",
                "shape": "UNKNOWN",
                "confidence_class": "LOW",
                "scan_id": None,
            }
            for slot_id in SLOT_NAMES
        }
        self.last_scan_id = None

    def update_from_scan(self, scan_id: str, scan_results: List[dict]) -> None:
        self.last_scan_id = scan_id
        for item in scan_results:
            slot_id = item.get("slot_id")
            if slot_id not in self._slots:
                continue
            normalized = {
                "slot_id": slot_id,
                "occupied": bool(item.get("occupied", False)),
                "color": item.get("color", "NONE"),
                "shape": "UNKNOWN",
                "confidence_class": item.get("confidence_class", "LOW"),
                "scan_id": scan_id,
            }
            self._slots[slot_id] = normalized

    def get_next_slot_for_color(self, color: Optional[str] = None) -> Optional[dict]:
        requested = str(color or "").strip().upper()
        for slot_id in SLOT_NAMES:
            slot = self._slots[slot_id]
            if not slot.get("occupied"):
                continue
            if requested and requested not in {"ANY", "UNKNOWN", "NONE"}:
                if slot.get("color") != requested:
                    continue
            return dict(slot)
        return None

    def mark_slot_emptied(self, slot_id: str) -> None:
        if slot_id not in self._slots:
            return
        self._slots[slot_id] = {
            "slot_id": slot_id,
            "occupied": False,
            "color": "NONE",
            "shape": "UNKNOWN",
            "confidence_class": "LOW",
            "scan_id": self.last_scan_id,
        }

    def snapshot(self) -> List[dict]:
        return [dict(self._slots[slot_id]) for slot_id in SLOT_NAMES]
