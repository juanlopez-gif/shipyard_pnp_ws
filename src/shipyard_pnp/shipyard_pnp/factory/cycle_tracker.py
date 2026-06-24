import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ── Entity-level data classes ─────────────────────────────────────────────────

@dataclass
class Phase:
    name:  str
    start: float
    end:   Optional[float] = None

    @property
    def duration_s(self) -> Optional[float]:
        if self.end is None:
            return None
        return round(self.end - self.start, 4)

    def to_dict(self) -> dict:
        return {
            "phase":      self.name,
            "start":      self.start,
            "end":        self.end,
            "duration_s": self.duration_s,
        }


@dataclass
class EntityCycle:
    entity:           str
    task_name:        str
    cycle_number:     int
    started_at:       float
    piece_id:         Optional[str]   = None
    color:            Optional[str]   = None
    route:            Optional[str]   = None
    metadata:         dict            = field(default_factory=dict)
    phases:           List[Phase]     = field(default_factory=list)
    completed_at:     Optional[float] = None
    is_discarded:     bool            = False
    discarded_reason: Optional[str]   = None

    @property
    def total_duration_s(self) -> Optional[float]:
        if self.completed_at is None:
            return None
        return round(self.completed_at - self.started_at, 3)

    def phases_as_list(self) -> list:
        return [p.to_dict() for p in self.phases]


# ── Backward-compatible piece-level record ─────────────────────────────────────

@dataclass
class CycleRecord:
    piece_id:       str
    color:          str
    shape:          str
    route:          str
    started_at:     float
    completed_at:   float
    cycle_time_sec: float
    final_location: Optional[str] = None


# ── CycleTracker ──────────────────────────────────────────────────────────────

class CycleTracker:
    """
    Two tracking layers:

    1. Entity-level cycles (robot/machine with phases, task_name, discard logic).
       One active cycle per entity at a time. Written to cycle_event via
       db.insert_entity_cycle() when complete or discarded.

    2. Piece-level cycles (total production time per piece, start/complete).
       Backward-compatible. Written to piece_outcome via db.insert_cycle_complete().

    Not thread-safe — protected by FactorySupervisor._state_lock.
    """

    def __init__(self):
        # Entity-level
        self._active_entity:    Dict[str, EntityCycle]        = {}
        self._cycle_counts:     Dict[str, Dict[str, int]]     = {}  # entity → task → n
        self._completed_entity: List[EntityCycle]             = []
        self._discarded_entity: List[EntityCycle]             = []

        # Piece-level (backward compat)
        self._in_progress: Dict[str, float] = {}  # piece_id → started_at
        self._completed:   List[CycleRecord] = []

    # ── Entity-level API ──────────────────────────────────────────────────────

    def start_entity_cycle(
        self,
        entity:    str,
        task_name: str,
        piece_id:  Optional[str]  = None,
        color:     Optional[str]  = None,
        route:     Optional[str]  = None,
        metadata:  Optional[dict] = None,
    ) -> None:
        """Begin a new entity cycle. Discards any previously active cycle first."""
        if entity in self._active_entity:
            self.discard_entity_cycle(entity, "interrupted_by_new_cycle")

        counts = self._cycle_counts.setdefault(entity, {})
        counts[task_name] = counts.get(task_name, 0) + 1

        self._active_entity[entity] = EntityCycle(
            entity=entity,
            task_name=task_name,
            cycle_number=counts[task_name],
            started_at=time.time(),
            piece_id=piece_id,
            color=color,
            route=route,
            metadata=metadata or {},
        )

    def add_phase(self, entity: str, phase_name: str) -> None:
        """Close the current open phase and open a new one."""
        cycle = self._active_entity.get(entity)
        if cycle is None:
            return
        now = time.time()
        if cycle.phases:
            cycle.phases[-1].end = now
        cycle.phases.append(Phase(name=phase_name, start=now))

    def update_entity_cycle(self, entity: str, **kwargs) -> None:
        """Update fields on the active cycle (task_name, color, route, piece_id).
        Unknown kwargs go into metadata."""
        cycle = self._active_entity.get(entity)
        if cycle is None:
            return
        for k, v in kwargs.items():
            if hasattr(cycle, k):
                setattr(cycle, k, v)
            else:
                cycle.metadata[k] = v

    def complete_entity_cycle(
        self,
        entity: str,
        color:  Optional[str] = None,
        route:  Optional[str] = None,
    ) -> Optional[EntityCycle]:
        """Close the last phase, mark the cycle complete, return it."""
        cycle = self._active_entity.pop(entity, None)
        if cycle is None:
            return None
        now = time.time()
        if cycle.phases:
            cycle.phases[-1].end = now
        cycle.completed_at = now
        if color is not None:
            cycle.color = color
        if route is not None:
            cycle.route = route
        self._completed_entity.append(cycle)
        return cycle

    def discard_entity_cycle(self, entity: str, reason: str) -> Optional[EntityCycle]:
        """Mark the active cycle as discarded and return it."""
        cycle = self._active_entity.pop(entity, None)
        if cycle is None:
            return None
        now = time.time()
        if cycle.phases:
            cycle.phases[-1].end = now
        cycle.completed_at = now
        cycle.is_discarded = True
        cycle.discarded_reason = reason
        self._discarded_entity.append(cycle)
        return cycle

    # ── Piece-level API (backward compat) ─────────────────────────────────────

    def start_cycle(self, piece_id: str) -> None:
        self._in_progress[piece_id] = time.time()

    def complete_cycle(
        self,
        piece_id: str,
        color:    str,
        shape:    str,
        route:    str,
        final_location: Optional[str] = None,
    ) -> Optional[CycleRecord]:
        started_at = self._in_progress.pop(piece_id, None)
        if started_at is None:
            return None
        completed_at = time.time()
        record = CycleRecord(
            piece_id=piece_id,
            color=color,
            shape=shape,
            route=route,
            started_at=started_at,
            completed_at=completed_at,
            cycle_time_sec=completed_at - started_at,
            final_location=final_location,
        )
        self._completed.append(record)
        return record

    # ── Queries / Dashboard ───────────────────────────────────────────────────

    def get_throughput_last_n(self, n: int) -> float:
        if len(self._completed) < 2:
            return 0.0
        subset = self._completed[-n:]
        if len(subset) < 2:
            return 0.0
        elapsed = subset[-1].completed_at - subset[0].started_at
        if elapsed <= 0:
            return 0.0
        return len(subset) / elapsed * 3600.0

    def snapshot(self) -> dict:
        last_five = [
            {
                "piece_id":       r.piece_id,
                "color":          r.color,
                "shape":          r.shape,
                "route":          r.route,
                "cycle_time_sec": round(r.cycle_time_sec, 3),
            }
            for r in self._completed[-5:]
        ]
        avg_cycle = (
            sum(r.cycle_time_sec for r in self._completed) / len(self._completed)
            if self._completed else 0.0
        )
        active_entities = {
            entity: {
                "task_name":     c.task_name,
                "piece_id":      c.piece_id,
                "current_phase": c.phases[-1].name if c.phases else None,
                "elapsed_s":     round(time.time() - c.started_at, 1),
            }
            for entity, c in self._active_entity.items()
        }
        return {
            "completed_count":          len(self._completed),
            "in_progress_count":        len(self._in_progress),
            "avg_cycle_time_sec":       round(avg_cycle, 3),
            "throughput_per_hour":      round(self.get_throughput_last_n(20), 2),
            "last_completed_piece_id":  (
                self._completed[-1].piece_id if self._completed else None
            ),
            "last_five_cycles":         last_five,
            "active_entity_cycles":     active_entities,
            "entity_cycles_completed":  len(self._completed_entity),
            "entity_cycles_discarded":  len(self._discarded_entity),
        }
