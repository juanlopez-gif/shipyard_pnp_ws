"""Precomputed dynamic-map presets for live factory runs.

The dashboard uses this module only when the operator explicitly selects
``Load Map Dynamic`` and later confirms it. The normal ``Optimize Order`` path
continues to use the fixed SimPy optimizer and fixed expected schedule.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from shipyard_pnp.factory.expected_schedule import (
    build_schedule_from_state_changes,
    compute_expected_schedule,
)
from shipyard_pnp.nodes import dispatch_search2 as dynamic_dispatch


_COLOR_BY_CODE = {"B": "BLUE", "R": "RED", "G": "GREEN"}
_CODE_BY_COLOR = {v: k for k, v in _COLOR_BY_CODE.items()}
_DYNAMIC_MAP_DIR = Path(__file__).resolve().parents[2] / "config" / "dynamic_maps"

DYNAMIC_3B3R_ID = "dynamic_3b3r_brrbrb_v1"
DYNAMIC_3B3R_ORDER = ["BLUE", "RED", "RED", "BLUE", "RED", "BLUE"]
FIXED_3B3R_REFERENCE_ORDER = ["BLUE", "RED", "RED", "RED", "BLUE", "BLUE"]


def _ordered_decider(priority):
    def decide(ready_options, now=None, system=None):
        for option in priority:
            if option in ready_options:
                return option
        return "WAIT"

    return decide


def _schedule_makespan(schedule: dict) -> float:
    return round(
        max(
            c["t_start"] + c["dur"]
            for cycles in schedule.values()
            for c in cycles
        ),
        1,
    )


def _validate_3b3r(order: list[str]) -> None:
    counts = Counter(order)
    if counts != Counter({"BLUE": 3, "RED": 3}):
        raise ValueError(
            "Load Map Dynamic currently supports exactly 3 BLUE and 3 RED pieces"
        )


def _colors_from_code(order: str | list[str]) -> list[str]:
    if isinstance(order, list):
        return list(order)
    return [_COLOR_BY_CODE[ch] for ch in order]


def _map_filename_for_counts(counts: Counter) -> str:
    return (
        f"{counts.get('BLUE', 0)}b"
        f"{counts.get('RED', 0)}r"
        f"{counts.get('GREEN', 0)}g.json"
    )


def load_dynamic_map_result(current_order: list[str]) -> dict:
    """Load the precomputed dynamic map matching the current composition."""
    counts = Counter(current_order)
    map_path = _DYNAMIC_MAP_DIR / _map_filename_for_counts(counts)
    if not map_path.exists():
        if counts == Counter({"BLUE": 3, "RED": 3}):
            return load_dynamic_3b3r_result(current_order)
        raise ValueError(
            "No precomputed dynamic map for composition "
            f"{counts.get('BLUE', 0)}B/"
            f"{counts.get('RED', 0)}R/"
            f"{counts.get('GREEN', 0)}G"
        )

    with map_path.open() as f:
        data = json.load(f)

    expected_counts = Counter({
        "BLUE": data.get("composition", {}).get("BLUE", 0),
        "RED": data.get("composition", {}).get("RED", 0),
        "GREEN": data.get("composition", {}).get("GREEN", 0),
    })
    if counts != expected_counts:
        raise ValueError(
            f"Map {map_path.name} expects {dict(expected_counts)}, "
            f"but current stack is {dict(counts)}"
        )

    best_order = _colors_from_code(data["best_order"])
    reference_order = _colors_from_code(
        data.get("fixed_reference_order") or data.get("requested_order")
    )
    reference_time = round(float(data.get("fixed_reference_time_s", 0.0)), 1)
    best_time = round(float(data["best_time_s"]), 1)
    saving_s = round(reference_time - best_time, 1)
    saving_pct = round(100.0 * saving_s / reference_time, 2) if reference_time else 0.0
    stats = data.get("search_stats", {})

    return {
        "map_id": data["map_id"],
        "map_mode": "dynamic",
        "original_order": list(current_order),
        "reference_order": reference_order,
        "reference_time": reference_time,
        "best_order": best_order,
        "original_time": reference_time,
        "best_time": best_time,
        "saving_s": saving_s,
        "saving_pct": saving_pct,
        "method": data["map_id"],
        "permutations_evaluated": stats.get("permutations_searched", 0),
        "optimizer_runtime_s": stats.get("wall_time_s", 0.0),
        "expected_schedule": data["expected_schedule"],
    }


def load_dynamic_3b3r_result(current_order: list[str]) -> dict:
    """Return the dashboard optimizer-result payload for the 3B/3R map.

    Policy used by the dynamic simulator:
      * robot2: P2 before P1 before P3, so a finished Bantam piece can go to C4
        before another C2S2 classification when both are physically possible.
      * robot1: existing fixed fallback.
      * xarm1: C1 before LASER when both are physically possible.
    """
    _validate_3b3r(current_order)

    robot2_policy = _ordered_decider(("P2", "P1", "P3"))
    xarm1_policy = _ordered_decider(("C1", "LASER"))
    system = dynamic_dispatch.run_system(
        DYNAMIC_3B3R_ORDER,
        robot2_policy,
        dynamic_dispatch.fixed_priority_decide_r1,
        xarm1_policy,
    )
    dynamic_schedule = build_schedule_from_state_changes(system.state_changes)
    dynamic_time = dynamic_dispatch.makespan(system, 3, 3, 0)
    if dynamic_time is None:
        dynamic_time = _schedule_makespan(dynamic_schedule)
    dynamic_time = round(dynamic_time, 1)

    fixed_schedule = compute_expected_schedule(FIXED_3B3R_REFERENCE_ORDER)
    fixed_reference_time = _schedule_makespan(fixed_schedule)

    saving_s = round(fixed_reference_time - dynamic_time, 1)
    saving_pct = round(100.0 * saving_s / fixed_reference_time, 2)

    return {
        "map_id": DYNAMIC_3B3R_ID,
        "map_mode": "dynamic",
        "original_order": list(current_order),
        "reference_order": list(FIXED_3B3R_REFERENCE_ORDER),
        "reference_time": fixed_reference_time,
        "best_order": list(DYNAMIC_3B3R_ORDER),
        "original_time": fixed_reference_time,
        "best_time": dynamic_time,
        "saving_s": saving_s,
        "saving_pct": saving_pct,
        "method": DYNAMIC_3B3R_ID,
        "permutations_evaluated": 20,
        "optimizer_runtime_s": 0.0,
        "expected_schedule": dynamic_schedule,
    }
