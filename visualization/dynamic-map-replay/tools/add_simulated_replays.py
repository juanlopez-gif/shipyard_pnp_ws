#!/usr/bin/env python3
"""Append simulated counterparts for the browser replay catalog.

The physical replays come from MES events. This script builds the matching
SimPy replays for the same four presentation scenarios and stores them in the
same browser catalog with explicit source metadata.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import simpy


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
DEFAULT_CATALOG = ROOT / "data" / "runs.js"
DEFAULT_SAMPLE = ROOT / "data" / "sample_run.js"
SIM_RUN_PREFIX = "simulated_"

sys.path.insert(0, str(REPO_ROOT / "src" / "shipyard_pnp"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_replay_from_run import build_replay  # noqa: E402
from shipyard_pnp.factory import expected_schedule as schedule  # noqa: E402
from shipyard_pnp.factory.dynamic_schedule import (  # noqa: E402
    DYNAMIC_3B3R_ID,
    DYNAMIC_3B3R_ORDER,
    _ordered_decider,
)
from shipyard_pnp.nodes import dispatch_search2 as dynamic_dispatch  # noqa: E402
from shipyard_pnp.nodes.shipyard_sim import (  # noqa: E402
    System,
    bantam_machine_process,
    conveyor1_control,
    conveyor1_process,
    conveyor2_control,
    conveyor2_process,
    robot1_process,
    robot2_process,
    xarm1_process,
    xarm2_process,
)


COLOR_BY_CODE = {"B": "BLUE", "R": "RED", "G": "GREEN"}
MAP_DIR = REPO_ROOT / "src" / "shipyard_pnp" / "config" / "dynamic_maps"


def load_catalog(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    prefix = "window.ShipyardRunCatalog = "
    suffix = ";\nwindow.ShipyardRuns = window.ShipyardRunCatalog.runs;"
    try:
        start = text.index(prefix) + len(prefix)
        end = text.index(suffix, start)
    except ValueError as exc:
        raise SystemExit(f"Could not parse catalog JS file: {path}") from exc
    return json.loads(text[start:end])


def write_catalog(path: Path, catalog: dict[str, Any]) -> None:
    path.write_text(
        "window.ShipyardRunCatalog = "
        + json.dumps(catalog, indent=2, ensure_ascii=True)
        + ";\nwindow.ShipyardRuns = window.ShipyardRunCatalog.runs;\n",
        encoding="utf-8",
    )


def colors_from_code(order: str | list[str]) -> list[str]:
    if isinstance(order, list):
        return list(order)
    return [COLOR_BY_CODE[ch.upper()] for ch in order if ch.upper() in COLOR_BY_CODE]


def composition_key(order: list[str]) -> str:
    counts = {color: order.count(color) for color in ("BLUE", "RED", "GREEN")}
    return f"{counts['BLUE']}b{counts['RED']}r{counts['GREEN']}g"


def piece_rows(original_order: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "piece_id": f"piece-{index:03d}",
            "color": color,
            "shape": "CIRCLE",
            "initial_position": index,
        }
        for index, color in enumerate(original_order, start=1)
    ]


def sim_piece_lookup(original_order: list[str], applied_order: list[str]) -> dict[str, str]:
    by_color: dict[str, list[str]] = defaultdict(list)
    for piece in piece_rows(original_order):
        by_color[piece["color"]].append(piece["piece_id"])

    lookup = {}
    for index, color in enumerate(applied_order, start=1):
        if not by_color[color]:
            raise SystemExit(f"Applied order asks for unavailable {color} piece")
        lookup[f"P{index:02d}"] = by_color[color].pop(0)
    return lookup


def run_fixed_state_changes(order: list[str]) -> list[dict[str, Any]]:
    env = simpy.Environment()
    system = System(env, list(order))
    env.process(bantam_machine_process(env, system))
    env.process(xarm2_process(env, system))
    env.process(conveyor1_process(env, system))
    env.process(conveyor1_control(env, system))
    env.process(conveyor2_process(env, system))
    env.process(conveyor2_control(env, system))
    env.process(xarm1_process(env, system))
    env.process(robot2_process(env, system))
    env.process(robot1_process(env, system))
    with contextlib.redirect_stdout(io.StringIO()):
        env.run(until=2500)
    return system.state_changes


def load_dynamic_map_for_order(order: list[str]) -> dict[str, Any]:
    path = MAP_DIR / f"{composition_key(order)}.json"
    if not path.exists():
        raise SystemExit(f"No dynamic map JSON found for {composition_key(order)}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data


def run_dynamic_state_changes(base_run: dict[str, Any]) -> list[dict[str, Any]]:
    map_id = (base_run.get("runConfig") or {}).get("map_id") or (base_run.get("meta") or {}).get("mapId")
    if map_id == DYNAMIC_3B3R_ID:
        robot2_policy = _ordered_decider(("P2", "P1", "P3"))
        xarm1_policy = _ordered_decider(("C1", "LASER"))
        system = dynamic_dispatch.run_system(
            DYNAMIC_3B3R_ORDER,
            robot2_policy,
            dynamic_dispatch.fixed_priority_decide_r1,
            xarm1_policy,
        )
        return system.state_changes

    data = load_dynamic_map_for_order(base_run["optimizedOrder"])
    decision_path = [tuple(item) for item in data["decision_path"]]
    best_order = colors_from_code(data["best_order"])
    system, need_decision = dynamic_dispatch.run_with_path_tagged(best_order, decision_path)
    if need_decision is not None:
        raise SystemExit(f"Dynamic map {data['map_id']} did not fully determine the simulated run")
    return system.state_changes


def grouped_cycles(state_changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entity_stream: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for change in sorted(state_changes, key=lambda item: item["time"]):
        entity_stream[change["entity"]].append(change)

    groups = []
    for entity in schedule.SCHEDULE_ENTITIES:
        markers = schedule.SCHEDULE_CYCLE_START[entity]
        hard_ends = schedule.SCHEDULE_HARD_END.get(entity, ())
        current = None
        for change in entity_stream[entity]:
            new_piece = change["piece"] is not None and (
                current is None or current["piece"] != change["piece"]
            )
            if change["state"] in markers or current is None or new_piece:
                if current is not None:
                    groups.append(current)
                current = {
                    "entity": entity,
                    "piece": change["piece"],
                    "color": change["color"],
                    "events": [change],
                }
            else:
                current["events"].append(change)
            if current is not None and change["state"] in hard_ends:
                groups.append(current)
                current = None
        if current is not None:
            groups.append(current)

    task_counts: dict[tuple[str, str], int] = defaultdict(int)
    cycles = []
    for group in sorted(groups, key=lambda item: item["events"][0]["time"]):
        entity = group["entity"]
        if group["events"][0]["state"] not in schedule.SCHEDULE_CYCLE_START[entity]:
            continue
        states = {event["state"] for event in group["events"]}
        task = schedule.infer_task(entity, states, group["color"])
        counter_key = "CLASSIFY_C2S2" if entity == "robot2" and task.startswith("CLASSIFY_C2S2_TO_") else task
        task_counts[(entity, counter_key)] += 1
        t_start = group["events"][0]["time"]
        t_end = group["events"][-1]["time"]
        cycles.append(
            {
                "entity": entity,
                "piece": group["piece"],
                "color": group["color"],
                "events": group["events"],
                "task_name": task,
                "cycle_number": task_counts[(entity, counter_key)],
                "t": round(t_start, 3),
                "duration": round(max(t_end - t_start, 0.1), 3),
            }
        )
    return cycles


def transfer_endpoints(task_name: str, color: str | None) -> tuple[str, str, str] | None:
    color_key = (color or "").upper()
    final_location = {
        "BLUE": "final_blue_circle",
        "GREEN": "final_green_circle",
        "RED": "final_red_circle",
    }.get(color_key, "robot1_scrap")
    endpoints = {
        "FEED_TO_C1S1": ("PLACE_C1S1", "initial_stack", "conveyor1"),
        "FEED_GREEN_TO_C3": ("PLACE_C3", "initial_stack", "c3_location"),
        "C1S2_TO_C2S1": ("PLACE_C2S1", "conveyor1", "conveyor2"),
        "C1S2_TO_LASER": ("PLACE_LASER_BED", "conveyor1", "laser_bed"),
        "LASER_TO_C2S1": ("PLACE_C2S1", "laser_bed", "conveyor2"),
        "CLASSIFY_C2S2_TO_BANTAM": ("PLACE_BANTAM", "conveyor2", "bantam_bed"),
        "CLASSIFY_C2S2_TO_IBS": ("PLACE_IBS", "conveyor2", "intermediate_blue_stack"),
        "CLASSIFY_C2S2_TO_C4": ("PLACE_C4", "conveyor2", "c4_location"),
        "IBS_TO_BANTAM": ("PLACE_BANTAM", "intermediate_blue_stack", "bantam_bed"),
        "BANTAM_TO_C4": ("PLACE_C4", "bantam_bed", "c4_location"),
        "UNLOAD_C3": ("PLACE_FINAL_GREEN", "c3_location", final_location),
        "UNLOAD_C4": (f"PLACE_FINAL_{color_key}", "c4_location", final_location),
    }
    return endpoints.get(task_name)


def transfer_time_for_cycle(cycle: dict[str, Any], place_state: str) -> float:
    events = cycle["events"]
    for index, event in enumerate(events):
        if event["state"] != place_state:
            continue
        if index + 1 < len(events):
            return round(events[index + 1]["time"], 3)
        return round(event["time"], 3)
    return round(cycle["t"] + cycle["duration"] * 0.78, 3)


def raw_from_state_changes(
    base_run: dict[str, Any],
    state_changes: list[dict[str, Any]],
    source_label: str,
) -> dict[str, Any]:
    original_order = list(base_run["originalOrder"])
    applied_order = list(base_run["optimizedOrder"] or base_run["originalOrder"])
    piece_lookup = sim_piece_lookup(original_order, applied_order)
    cycles = grouped_cycles(state_changes)

    raw_cycles = []
    transfers = []
    for index, cycle in enumerate(cycles, start=1):
        piece_id = piece_lookup.get(cycle["piece"], cycle["piece"])
        raw_cycles.append(
            {
                "t": cycle["t"],
                "id": 700000 + index,
                "color": cycle["color"],
                "entity": cycle["entity"],
                "duration": cycle["duration"],
                "metadata": {
                    "source": "simpy_expected_schedule",
                    "source_run_id": base_run["id"],
                },
                "piece_id": piece_id,
                "task_name": cycle["task_name"],
                "cycle_number": cycle["cycle_number"],
                "is_discarded": False,
                "discarded_reason": None,
            }
        )
        endpoint = transfer_endpoints(cycle["task_name"], cycle["color"])
        if endpoint and piece_id:
            place_state, raw_from, raw_to = endpoint
            transfers.append(
                {
                    "t": transfer_time_for_cycle(cycle, place_state),
                    "id": 800000 + len(transfers) + 1,
                    "piece_id": piece_id,
                    "from_loc": raw_from,
                    "to_loc": raw_to,
                    "moved_by": cycle["entity"],
                    "piece_age_s": None,
                    "history_json": [],
                }
            )

    config = dict(base_run.get("runConfig") or {})
    meta = base_run.get("meta") or {}
    config["map_mode"] = meta.get("mapMode") or meta.get("mode") or config.get("map_mode") or "fixed"
    if meta.get("mapId"):
        config["map_id"] = meta["mapId"]
    config["source_type"] = "simulation"
    config["physical_run_id"] = base_run["id"]

    return {
        "run": {
            "run_id": f"{SIM_RUN_PREFIX}{base_run['id']}",
            "status": "SIMULATED",
            "started_at": "SimPy timeline t=0",
            "finished_at": source_label,
            "total_pieces": base_run.get("totalPieces") or len(original_order),
            "pieces_completed": base_run.get("totalPieces") or len(original_order),
            "original_order": original_order,
            "optimized_order": applied_order,
            "config_snapshot": config,
        },
        "pieces": piece_rows(original_order),
        "cycles": raw_cycles,
        "transfers": sorted(transfers, key=lambda item: (item["t"], item["id"])),
        "resource_changes": [],
        "operator_events": [],
    }


def simulated_replay_for(base_run: dict[str, Any]) -> dict[str, Any]:
    meta = base_run.get("meta") or {}
    mode = meta.get("mode") or meta.get("mapMode") or "fixed"
    state_changes = run_dynamic_state_changes(base_run) if mode == "dynamic" else run_fixed_state_changes(base_run["optimizedOrder"])
    raw = raw_from_state_changes(base_run, state_changes, "Calibrated SimPy expected schedule")
    replay = build_replay(raw)
    sim_time = replay["duration"]
    real_time = float(base_run.get("duration") or 0.0)
    base_title = meta.get("title") or base_run.get("label") or base_run["id"]
    source_note = "dynamic-map SimPy replay" if mode == "dynamic" else "fixed-priority SimPy replay"

    replay["label"] = f"{base_title} - Simulation"
    replay["sourceRefs"] = [
        f"Simulation source: {source_note}.",
        f"Physical counterpart: {base_run['id']} ({real_time:.3f} s real).",
    ]
    replay["notes"] = [
        "This replay is simulated from the calibrated SimPy expected schedule.",
        "The 2D motion is reconstructed from simulated task timings and physical handoff points.",
    ]
    replay["meta"] = {
        **meta,
        "key": f"{meta.get('key', base_run['id'])}_simulation",
        "title": replay["label"],
        "summary": (
            f"{base_title}: {sim_time:.1f} s simulated; "
            f"physical counterpart {base_run['id']} is {real_time:.3f} s real."
        ),
        "runId": replay["id"],
        "physicalRunId": base_run["id"],
        "sourceType": "simulation",
        "sourceLabel": "Simulation",
        "sourceDescription": "Calibrated SimPy expected schedule.",
        "simulatedTotalS": round(sim_time, 1),
        "realCounterpartS": round(real_time, 3),
    }
    return replay


def annotate_real_run(run: dict[str, Any]) -> dict[str, Any]:
    meta = dict(run.get("meta") or {})
    meta.setdefault("sourceType", "real")
    meta.setdefault("sourceLabel", "Real cell")
    meta.setdefault("sourceDescription", "Physical MES production run from the cell.")
    meta.setdefault("physicalRunId", run["id"])
    run["meta"] = meta
    return run


def add_simulated_replays(catalog: dict[str, Any]) -> dict[str, Any]:
    physical_runs = [
        annotate_real_run(run)
        for run in catalog["runs"]
        if not str(run.get("id", "")).startswith(SIM_RUN_PREFIX)
        and (run.get("meta") or {}).get("sourceType") != "simulation"
    ]
    simulated_runs = [simulated_replay_for(run) for run in physical_runs]
    catalog["generatedAt"] = datetime.now().isoformat(timespec="seconds")
    catalog["runs"] = physical_runs + simulated_runs
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--sample-output", type=Path, default=DEFAULT_SAMPLE)
    args = parser.parse_args()

    catalog = add_simulated_replays(load_catalog(args.catalog))
    write_catalog(args.catalog, catalog)
    default_run = next(
        (run for run in catalog["runs"] if run["id"] == catalog.get("defaultRunId")),
        catalog["runs"][0],
    )
    args.sample_output.write_text(
        "window.ShipyardSampleRun = "
        + json.dumps(default_run, indent=2, ensure_ascii=True)
        + ";\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.catalog} with {len(catalog['runs'])} runs.")
    print("Added simulated counterparts:")
    for run in catalog["runs"]:
        if (run.get("meta") or {}).get("sourceType") == "simulation":
            print(f"  {run['id']}: {run['duration']:.1f} s")


if __name__ == "__main__":
    main()
