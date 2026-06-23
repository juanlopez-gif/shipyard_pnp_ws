import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class CycleRecord:
    piece_id: str
    color: str
    shape: str
    route: str
    started_at: float
    completed_at: float
    cycle_time_sec: float


class CycleTracker:
    """
    Records per-piece production cycle timing.
    Not thread-safe — protected by FactorySupervisor._state_lock.
    """

    def __init__(self):
        self._in_progress: Dict[str, float] = {}   # piece_id → started_at
        self._completed: List[CycleRecord] = []

    def start_cycle(self, piece_id: str) -> None:
        self._in_progress[piece_id] = time.time()

    def complete_cycle(
        self, piece_id: str, color: str, shape: str, route: str
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
        )
        self._completed.append(record)
        return record

    def get_throughput_last_n(self, n: int) -> float:
        """Returns pieces/hour based on the last n completed cycles."""
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
                "piece_id": r.piece_id,
                "color": r.color,
                "shape": r.shape,
                "route": r.route,
                "cycle_time_sec": round(r.cycle_time_sec, 3),
            }
            for r in self._completed[-5:]
        ]
        avg_cycle = (
            sum(r.cycle_time_sec for r in self._completed) / len(self._completed)
            if self._completed
            else 0.0
        )
        return {
            "completed_count": len(self._completed),
            "in_progress_count": len(self._in_progress),
            "avg_cycle_time_sec": round(avg_cycle, 3),
            "throughput_per_hour": round(self.get_throughput_last_n(20), 2),
            "last_completed_piece_id": (
                self._completed[-1].piece_id if self._completed else None
            ),
            "last_five_cycles": last_five,
        }
