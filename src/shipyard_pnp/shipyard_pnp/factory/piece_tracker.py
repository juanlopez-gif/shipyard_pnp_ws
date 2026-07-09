import time
import uuid
from collections import deque
from typing import Any, Deque, Dict, List, Optional

PIPELINE_LOCATIONS = [
    "initial_stack",
    "xarm2_gripper",
    "c3_location",
    "conveyor1",
    "xarm1_gripper",
    "laser_bed",
    "conveyor2",
    "robot2_gripper",
    "c4_location",
    "bantam_bed",
    "intermediate_blue_stack",
    "robot1_gripper",
    "final_red_stack",
    "final_blue_stack",
    "final_green_stack",
    "final_red_circle",
    "final_blue_circle",
    "final_green_circle",
    "robot1_scrap",
    "robot2_scrap",
]

_FINAL_LOCATIONS = {
    "final_red_stack",
    "final_blue_stack",
    "final_green_stack",
    "final_red_circle",
    "final_blue_circle",
    "final_green_circle",
    "robot1_scrap",
    "robot2_scrap",
}

_INTERMEDIATE_LOCATIONS = frozenset(PIPELINE_LOCATIONS) - {"initial_stack"} - _FINAL_LOCATIONS


class PieceTracker:
    """
    Owns all pipeline queues — the single source of truth for piece locations.
    Calls db_writer on every transfer.
    Not thread-safe — protected by FactorySupervisor._state_lock.
    """

    def __init__(self, initial_stack_order: List[str], db_writer: Any):
        self._db = db_writer
        self._queues: Dict[str, Deque[dict]] = {loc: deque() for loc in PIPELINE_LOCATIONS}
        self._all_pieces: Dict[str, dict] = {}

        now = time.time()
        for entry in initial_stack_order:
            if isinstance(entry, dict):
                piece_id = entry["id"]
                color    = entry.get("color")
                shape    = entry.get("shape")
            else:
                piece_id = entry
                color    = None
                shape    = None
            piece = {
                "id": piece_id,
                "color": color,
                "shape": shape,
                "slot_id": None,
                "timestamp_created": now,
                "current_location": "initial_stack",
                "history": [
                    {"location": "initial_stack", "timestamp": now,
                     "color": color, "shape": shape}
                ],
            }
            self._queues["initial_stack"].append(piece)
            self._all_pieces[piece_id] = piece

    # ------------------------------------------------------------------
    # Order control
    # ------------------------------------------------------------------

    def reorder_initial_stack(self, color_order: list) -> bool:
        """Reorder the initial_stack deque to match the given color sequence.

        color_order must be a list of color strings the same length as the
        current initial_stack queue (e.g. ["BLUE","GREEN","RED","BLUE"]).
        Returns True on success, False if lengths or colors don't match.
        """
        from collections import Counter
        from collections import deque as _deque
        q = self._queues["initial_stack"]
        if len(q) != len(color_order):
            return False
        by_color: dict = {}
        for piece in q:
            c = (piece.get("color") or "").upper()
            by_color.setdefault(c, []).append(piece)
        if Counter(p.get("color","").upper() for p in q) != Counter(c.upper() for c in color_order):
            return False
        new_order = []
        indices: dict = {}
        for color in color_order:
            c = color.upper()
            idx = indices.get(c, 0)
            new_order.append(by_color[c][idx])
            indices[c] = idx + 1
        self._queues["initial_stack"] = _deque(new_order)
        return True

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    def transfer_via_gripper(self, gripper_loc: str, source_loc: str, target_loc: str) -> bool:
        """Complete a move whose pick may already have been fast-forwarded
        into `gripper_loc` by FactorySupervisor._apply_resource_state (the
        PICK_DONE hook, see register_pick_source) -- so EXPECTED shows the
        piece leaving `source_loc` at pick time instead of only at the end
        of the whole move. Falls back to a direct source_loc->target_loc
        transfer if that early hook never fired (e.g. the vendor never
        reported PICK_DONE), so behavior never regresses below the old
        single-step transfer."""
        if self._queues.get(gripper_loc):
            return self.transfer_piece(gripper_loc, target_loc)
        return self.transfer_piece(source_loc, target_loc)

    def transfer_piece(self, from_loc: str, to_loc: str) -> bool:
        if from_loc not in self._queues or to_loc not in self._queues:
            return False
        q = self._queues[from_loc]
        if not q:
            return False
        piece = q.popleft()
        piece["current_location"] = to_loc
        piece["history"].append(
            {
                "location": to_loc,
                "timestamp": time.time(),
                "color": piece.get("color"),
                "shape": piece.get("shape"),
            }
        )
        self._queues[to_loc].append(piece)
        self._db.insert_piece_transfer(piece, from_loc, to_loc)
        return True

    # ------------------------------------------------------------------
    # Attribute assignment
    # ------------------------------------------------------------------

    def assign_slot(self, slot_id: str) -> None:
        """Called when globalvision returns slot_id for the next initial_stack piece."""
        q = self._queues["initial_stack"]
        if q:
            q[0]["slot_id"] = slot_id

    def assign_color_shape(self, location: str, color: str, shape: str) -> None:
        """Called when local or global vision returns color+shape for the first piece at location."""
        q = self._queues.get(location)
        if q:
            q[0]["color"] = color
            q[0]["shape"] = shape

    def register_intruder(self, location: str, at_front: bool = False) -> str:
        """2026-07-08: a sensor reading OCCUPIED with nothing tracked at
        `location` (an intruder -- e.g. a piece placed at C2S2 by hand,
        never fed through the normal pipeline) used to mean the planner
        rule gating on count()>0 simply never fired, leaving it stuck
        there forever with no vision, no routing, no way out except a
        human physically removing it. Only call this when count(location)
        is already 0 (i.e. the planner decided to act on the sensor alone,
        see classification_rules.py) -- appends a synthetic piece, which
        becomes index 0 automatically since the queue was empty, so every
        existing assumption (peek_first_piece*, assign_color_shape,
        transfer_piece/transfer_via_gripper, downstream unload routing)
        keeps working completely unmodified from here on. The piece gets
        vision-inspected and routed to a real final location like any
        other -- it fully leaves the system instead of staying a phantom
        the sensor remembers but nothing ever resolves.

        at_front=True is for the OTHER case: count(location) > 0 (a real
        piece IS tracked there) but vision proves the physical object
        actually at the pickup point is not that piece (color mismatch --
        it cut in line ahead of the tracked one, e.g. placed by hand
        directly at the pickup point while the real piece is still
        further back). appendleft() puts the intruder at index 0 without
        disturbing the real piece behind it, so scrapping the intruder
        via the normal transfer_piece/transfer_via_gripper pop only
        consumes the intruder -- the real piece keeps its own identity,
        shifts back to index 0 once the intruder is gone, and gets
        correctly re-inspected on the next cycle instead of being
        silently overwritten and scrapped under the wrong color."""
        piece_id = f"intruder-{uuid.uuid4().hex[:8]}"
        now = time.time()
        piece = {
            "id": piece_id,
            "color": None,
            "shape": None,
            "slot_id": None,
            "timestamp_created": now,
            "current_location": location,
            "history": [{"location": location, "timestamp": now, "color": None, "shape": None}],
        }
        if at_front:
            self._queues[location].appendleft(piece)
        else:
            self._queues[location].append(piece)
        self._all_pieces[piece_id] = piece
        return piece_id

    # ------------------------------------------------------------------
    # Read-only accessors
    # ------------------------------------------------------------------

    def peek_first_piece(self, location: str) -> Optional[dict]:
        q = self._queues.get(location)
        return q[0] if q else None

    def peek_first_piece_color(self, location: str) -> Optional[str]:
        p = self.peek_first_piece(location)
        return p["color"] if p else None

    def peek_first_piece_shape(self, location: str) -> Optional[str]:
        p = self.peek_first_piece(location)
        return p["shape"] if p else None

    def peek_first_piece_id(self, location: str) -> Optional[str]:
        p = self.peek_first_piece(location)
        return p["id"] if p else None

    def count(self, location: str) -> int:
        return len(self._queues.get(location, []))

    def total_pieces_in_system(self) -> int:
        return sum(len(q) for q in self._queues.values())

    def all_pieces_finished(self) -> bool:
        """True when initial_stack is empty AND every intermediate location is empty."""
        if self._queues["initial_stack"]:
            return False
        return all(
            len(self._queues[loc]) == 0 for loc in _INTERMEDIATE_LOCATIONS
        )

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        # 2026-07-08: "queues" here is what gets published as pipeline.queues
        # on /factory/system_state -- the ONLY source both dashboard_node.py
        # and the external ml_node.py use to know "what piece is EXPECTED at
        # this location" (see CLAUDE.md). An intruder registered via
        # register_intruder() lives in self._queues (needed unmodified for
        # peek_first_piece*/transfer_piece/assign_color_shape/count() --
        # count() in particular is what classify_ready/bantam_ready gate on)
        # but was never actually planned/fed -- it must never be reported as
        # "expected". Confirmed live: without this filter, the moment vision
        # assigns the intruder its own detected color, EXPECTED and Reality
        # trivially match each other (the intruder's color mirrors itself),
        # which silently defeated the exact mismatch alarm this session
        # already fixed once for the untracked case. Filtering it out of the
        # exposed queues here restores the correct signal: EXPECTED stays
        # empty/null for that location for as long as only an intruder (no
        # real tracked piece) occupies it.
        queues = {}
        for loc, q in self._queues.items():
            visible = [p for p in q if not p["id"].startswith("intruder-")]
            if visible:
                queues[loc] = [
                    {
                        "id": p["id"],
                        "color": p.get("color"),
                        "shape": p.get("shape"),
                        "slot_id": p.get("slot_id"),
                    }
                    for p in visible
                ]
        return {
            "total_in_system": self.total_pieces_in_system(),
            "all_finished": self.all_pieces_finished(),
            "queues": queues,
        }
