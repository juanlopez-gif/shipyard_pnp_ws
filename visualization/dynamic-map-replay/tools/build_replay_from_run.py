#!/usr/bin/env python3
"""Build the browser replay data from an exported real Shipyard PnP run."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = Path("/tmp/shipyard_replay_20260710_190550_RBRBRB.json")
DEFAULT_OUTPUT = ROOT / "data" / "sample_run.js"

HANDOFF_S = 2.0
CONVEYOR_TRAVEL_S = {
    "conveyor1": 8.0,
    "conveyor2": 8.0,
    "conveyor3": 7.0,
    "conveyor4": 5.0,
}

PHASE_BREAKS = (0.18, 0.36, 0.68, 0.86, 0.96)

SLOTS = {position: f"s{((position - 1) // 6) + 1}.{((position - 1) % 6) + 1}" for position in range(1, 19)}

CONVEYOR_ANCHORS = {
    "conveyor1": {"to": "conveyor1_entry", "from": "conveyor1_exit"},
    "conveyor2": {"to": "conveyor2_entry", "from": "conveyor2_exit"},
    "conveyor3": {"to": "conveyor3_entry", "from": "conveyor3_exit"},
    "conveyor4": {"to": "conveyor4_entry", "from": "conveyor4_exit"},
}

HANDOFF_CONVEYORS = {
    "c3_location": "conveyor3",
    "c4_location": "conveyor4",
}

FINAL_ALIASES = {
    "final_blue_circle": "final_blue_stack",
    "final_red_circle": "final_red_stack",
    "final_green_circle": "final_green_stack",
}

HOLD_SOURCE_LOCATIONS = {
    "initial_stack",
    "laser_bed",
    "bantam_bed",
    "c3_location",
    "c4_location",
    "intermediate_blue_stack",
}

ENTITY_LABELS = {
    "xarm1": "xArm1",
    "xarm2": "xArm2",
    "robot1": "Niryo 1",
    "robot2": "Niryo 2",
    "laser": "LASER",
    "bantam": "BANTAM CNC",
}

LOCATION_LABELS = {
    "initial_stack": "Initial Stack",
    "conveyor1_entry": "Conveyor 1 entry",
    "conveyor1_exit": "Conveyor 1 exit",
    "conveyor2_entry": "Conveyor 2 entry",
    "conveyor2_exit": "Conveyor 2 exit",
    "conveyor3_entry": "Conveyor 3 entry",
    "conveyor3_exit": "Conveyor 3 exit",
    "c3_location": "Conveyor 3 sensor",
    "conveyor4_entry": "Conveyor 4 entry",
    "conveyor4_exit": "Conveyor 4 exit",
    "c4_location": "Conveyor 4 sensor",
    "laser_bed": "Laser engraver",
    "bantam_bed": "Bantam CNC",
    "intermediate_blue_stack": "Blue Buffer",
    "final_red_stack": "red output",
    "final_blue_stack": "blue output",
    "final_green_stack": "green output",
    "xarm1_gripper": "xArm1 gripper",
    "xarm2_gripper": "xArm2 gripper",
    "robot1_gripper": "Niryo 1 gripper",
    "robot2_gripper": "Niryo 2 gripper",
}

TASK_LABELS = {
    "FEED_TO_C1S1": "release part to Conveyor 1",
    "FEED_GREEN_TO_C3": "release green part to Conveyor 3",
    "C1S2_TO_C2S1": "transfer from Conveyor 1 to Conveyor 2",
    "C1S2_TO_LASER": "load the laser engraver",
    "LASER_TO_C2S1": "move laser output to Conveyor 2",
    "CLASSIFY_C2S2_TO_BANTAM": "route blue part to CNC",
    "CLASSIFY_C2S2_TO_IBS": "route blue part to Blue Buffer",
    "CLASSIFY_C2S2_TO_C4": "route part to Conveyor 4",
    "IBS_TO_BANTAM": "feed CNC from blue buffer",
    "BANTAM_TO_C4": "clear CNC output to Conveyor 4",
    "PROCESS_RED": "engrave red part",
    "PROCESS_BLUE": "machine blue part",
    "UNLOAD_C4": "unload Conveyor 4",
    "UNLOAD_C3": "unload Conveyor 3",
}

DEFAULT_RESOURCES = {
    "robot1": "IDLE",
    "robot2": "IDLE",
    "xarm1": "IDLE",
    "xarm2": "IDLE",
    "laser": "IDLE",
    "bantam": "IDLE",
    "bantam_door": "CLOSED",
    "conveyor1": "STOPPED",
    "conveyor2": "STOPPED",
    "conveyor3": "STOPPED",
    "conveyor4": "STOPPED",
    "c3": "CLEAR",
    "c4": "CLEAR",
    "initial_stack": "READY",
    "intermediate_blue_stack": "EMPTY",
    "final_red_stack": "EMPTY",
    "final_blue_stack": "EMPTY",
    "final_green_stack": "EMPTY",
    "robot1_scrap": "EMPTY",
}


def clean_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def slot_for_position(position: int | None) -> str:
    return SLOTS.get(int(position or 1), "s1.1")


def shift_time(value: float, offset: float) -> float:
    return round(max(0.0, float(value) - offset), 3)


def normalize_location(location: str | None, role: str) -> str | None:
    if not location:
        return None
    if location in CONVEYOR_ANCHORS:
        return CONVEYOR_ANCHORS[location][role]
    if location in HANDOFF_CONVEYORS:
        conveyor = HANDOFF_CONVEYORS[location]
        return CONVEYOR_ANCHORS[conveyor][role]
    return FINAL_ALIASES.get(location, location)


def add_keyframe(keyframes: dict[str, list[dict]], piece_id: str, time_s: float, location: str | None, slot: str | None = None) -> None:
    if not piece_id or not location:
        return
    entry = {"time": round(max(0.0, time_s), 3), "location": location}
    if slot:
        entry["slot"] = slot
    keyframes[piece_id].append(entry)


def last_keyframe(keyframes: dict[str, list[dict]], piece_id: str) -> dict | None:
    frames = keyframes.get(piece_id) or []
    return frames[-1] if frames else None


def add_source_hold(
    keyframes: dict[str, list[dict]],
    piece_slots: dict[str, str],
    conveyor_exit_clear: dict[str, float],
    piece_id: str,
    raw_from: str | None,
    from_anchor: str | None,
    transfer_time: float,
) -> None:
    if not raw_from or not from_anchor:
        return

    last = last_keyframe(keyframes, piece_id)
    last_time = float(last["time"]) if last else 0.0
    handoff_start = max(last_time, transfer_time - HANDOFF_S)

    if raw_from in CONVEYOR_ANCHORS:
        entry_anchor = CONVEYOR_ANCHORS[raw_from]["to"]
        exit_anchor = CONVEYOR_ANCHORS[raw_from]["from"]
        if last and last["location"] == entry_anchor:
            travel_s = CONVEYOR_TRAVEL_S.get(raw_from, 8.0)
            travel_start = max(last_time, conveyor_exit_clear.get(raw_from, 0.0))
            if travel_start > last_time + 0.001:
                add_keyframe(keyframes, piece_id, travel_start, entry_anchor)
            travel_end = min(handoff_start, travel_start + travel_s)
            add_keyframe(keyframes, piece_id, travel_end, exit_anchor)
        add_keyframe(keyframes, piece_id, handoff_start, exit_anchor)
        conveyor_exit_clear[raw_from] = transfer_time
        return

    if raw_from in HANDOFF_CONVEYORS:
        conveyor = HANDOFF_CONVEYORS[raw_from]
        entry_anchor = CONVEYOR_ANCHORS[conveyor]["to"]
        exit_anchor = CONVEYOR_ANCHORS[conveyor]["from"]
        if last and last["location"] == entry_anchor:
            travel_s = CONVEYOR_TRAVEL_S.get(conveyor, 6.0)
            travel_start = max(last_time, conveyor_exit_clear.get(conveyor, 0.0))
            if travel_start > last_time + 0.001:
                add_keyframe(keyframes, piece_id, travel_start, entry_anchor)
            travel_end = min(handoff_start, travel_start + travel_s)
            add_keyframe(keyframes, piece_id, travel_end, exit_anchor)
        add_keyframe(keyframes, piece_id, handoff_start, exit_anchor)
        conveyor_exit_clear[conveyor] = transfer_time
        return

    if raw_from == "initial_stack":
        add_keyframe(keyframes, piece_id, handoff_start, "initial_stack", piece_slots.get(piece_id))
        return

    if raw_from in HOLD_SOURCE_LOCATIONS:
        add_keyframe(keyframes, piece_id, handoff_start, from_anchor)


def sort_keyframes(keyframes: dict[str, list[dict]]) -> dict[str, list[dict]]:
    sorted_keyframes = {}
    for piece_id, frames in keyframes.items():
        frames = sorted(frames, key=lambda item: (item["time"], item["location"]))
        collapsed: list[dict] = []
        for frame in frames:
            if collapsed and abs(collapsed[-1]["time"] - frame["time"]) < 0.001:
                collapsed[-1] = frame
            else:
                collapsed.append(frame)
        sorted_keyframes[piece_id] = collapsed
    return sorted_keyframes


def state_at(keyframes: list[dict], time_s: float) -> dict:
    current = keyframes[0]
    for frame in keyframes[1:]:
        if frame["time"] <= time_s:
            current = frame
        else:
            break
    return current


def build_piece_keyframes(raw: dict, cycles: list[dict], offset: float) -> tuple[list[dict], dict[str, list[dict]]]:
    pieces = []
    piece_slots = {}
    keyframes: dict[str, list[dict]] = defaultdict(list)
    conveyor_exit_clear = {name: 0.0 for name in CONVEYOR_ANCHORS}

    for piece in sorted(raw["pieces"], key=lambda item: item.get("initial_position") or 0):
        piece_id = piece["piece_id"]
        slot = slot_for_position(piece.get("initial_position"))
        piece_slots[piece_id] = slot
        pieces.append(
            {
                "id": piece_id,
                "color": piece.get("color") or "UNKNOWN",
                "shape": piece.get("shape") or "CIRCLE",
                "slot": slot,
                "initialPosition": piece.get("initial_position"),
            }
        )
        add_keyframe(keyframes, piece_id, 0.0, "initial_stack", slot)

    for transfer in sorted(raw["transfers"], key=lambda item: item["t"]):
        piece_id = transfer["piece_id"]
        transfer_time = shift_time(transfer["t"], offset)
        raw_from = transfer.get("from_loc")
        raw_to = transfer.get("to_loc")
        from_anchor = normalize_location(raw_from, "from")
        to_anchor = normalize_location(raw_to, "to")
        add_source_hold(keyframes, piece_slots, conveyor_exit_clear, piece_id, raw_from, from_anchor, transfer_time)
        add_keyframe(keyframes, piece_id, transfer_time, to_anchor)

    return pieces, sort_keyframes(keyframes)


def final_location_for_color(color: str | None) -> str:
    color = (color or "").upper()
    if color == "BLUE":
        return "final_blue_stack"
    if color == "GREEN":
        return "final_green_stack"
    if color == "RED":
        return "final_red_stack"
    return "robot1_scrap"


def action_sentence(cycle: dict, action: dict | None = None) -> str:
    actor = ENTITY_LABELS.get(cycle["entity"], cycle["entity"])
    piece = short_piece(cycle.get("piece_id"))
    color = (cycle.get("color") or "part").lower()
    task = cycle["task_name"]
    source = location_label(action.get("from")) if action and action.get("from") else ""
    target = location_label(action.get("to")) if action and action.get("to") else ""

    if task == "FEED_TO_C1S1":
        return f"{actor} picks {piece} from the Initial Stack and places it at Conveyor 1 entry."
    if task == "FEED_GREEN_TO_C3":
        return f"{actor} sends green {piece} from the Initial Stack to Conveyor 3."
    if task == "C1S2_TO_C2S1":
        return f"{actor} moves {piece} from Conveyor 1 exit to Conveyor 2 entry."
    if task == "C1S2_TO_LASER":
        return f"{actor} loads red {piece} into the laser engraver."
    if task == "LASER_TO_C2S1":
        return f"{actor} moves engraved {piece} from the laser to Conveyor 2 entry."
    if task == "CLASSIFY_C2S2_TO_BANTAM":
        return f"{actor} routes blue {piece} from Conveyor 2 exit to the CNC."
    if task == "CLASSIFY_C2S2_TO_IBS":
        return f"{actor} moves blue {piece} from Conveyor 2 exit to the Blue Buffer."
    if task == "CLASSIFY_C2S2_TO_C4":
        return f"{actor} places {piece} from Conveyor 2 exit onto Conveyor 4."
    if task == "IBS_TO_BANTAM":
        return f"{actor} moves {piece} from the blue buffer into the CNC."
    if task == "BANTAM_TO_C4":
        return f"{actor} clears machined {piece} from the CNC to Conveyor 4."
    if task == "PROCESS_RED":
        return f"The laser engraver processes red {piece}."
    if task == "PROCESS_BLUE":
        return f"The CNC machines blue {piece}."
    if task == "UNLOAD_C4":
        return f"{actor} unloads {piece} from Conveyor 4 into the output area."
    if task == "UNLOAD_C3":
        return f"{actor} unloads green {piece} from Conveyor 3 into the output area."
    if source and target:
        return f"{actor} moves {color} {piece} from {source} to {target}."
    return f"{actor} starts the next operation for {piece}."


def selected_action_for_cycle(cycle: dict) -> dict:
    task = cycle["task_name"]
    color = cycle.get("color")
    piece_id = cycle.get("piece_id")
    action_id = clean_id(f"{cycle['entity']}_{task}_{piece_id}_{cycle.get('cycle_number')}")

    endpoints = {
        "FEED_TO_C1S1": ("initial_stack", "conveyor1_entry"),
        "FEED_GREEN_TO_C3": ("initial_stack", "conveyor3_entry"),
        "C1S2_TO_C2S1": ("conveyor1_exit", "conveyor2_entry"),
        "C1S2_TO_LASER": ("conveyor1_exit", "laser_bed"),
        "LASER_TO_C2S1": ("laser_bed", "conveyor2_entry"),
        "CLASSIFY_C2S2_TO_BANTAM": ("conveyor2_exit", "bantam_bed"),
        "CLASSIFY_C2S2_TO_IBS": ("conveyor2_exit", "intermediate_blue_stack"),
        "CLASSIFY_C2S2_TO_C4": ("conveyor2_exit", "conveyor4_entry"),
        "IBS_TO_BANTAM": ("intermediate_blue_stack", "bantam_bed"),
        "BANTAM_TO_C4": ("bantam_bed", "conveyor4_entry"),
        "UNLOAD_C3": ("conveyor3_exit", final_location_for_color(color)),
        "UNLOAD_C4": ("conveyor4_exit", final_location_for_color(color)),
    }
    work_at = {
        "PROCESS_RED": "laser_bed",
        "PROCESS_BLUE": "bantam_bed",
    }

    if task in work_at:
        action = {"id": action_id, "type": "work", "at": work_at[task]}
        action["pieceId"] = piece_id
        action["color"] = color
        action["taskName"] = task
        action["label"] = action_sentence(cycle, action)
        return action
    if task in endpoints:
        source, target = endpoints[task]
        action = {"id": action_id, "from": source, "to": target}
        action["pieceId"] = piece_id
        action["color"] = color
        action["taskName"] = task
        action["label"] = action_sentence(cycle, action)
        return action
    action = {"id": action_id, "type": "wait", "at": cycle["entity"]}
    action["pieceId"] = piece_id
    action["color"] = color
    action["taskName"] = task
    action["label"] = action_sentence(cycle, action)
    return action


def candidate_action(entity: str, task_name: str, piece_id: str, color: str | None, suffix: str) -> dict:
    pseudo_cycle = {
        "entity": entity,
        "task_name": task_name,
        "piece_id": piece_id,
        "color": color,
        "cycle_number": suffix,
    }
    return selected_action_for_cycle(pseudo_cycle)


def location_label(location: str | None) -> str:
    return LOCATION_LABELS.get(location or "", location or "resource")


def short_piece(piece_id: str | None) -> str:
    return (piece_id or "").replace("piece-", "P")


def activity_detail_for_cycle(cycle: dict, time_s: float) -> str:
    action = selected_action_for_cycle(cycle)
    piece = short_piece(cycle.get("piece_id"))
    task = cycle["task_name"]

    if action.get("type") == "work":
        return f"Processing {piece}"

    if not action.get("from") or not action.get("to"):
        return f"{TASK_LABELS.get(task, task)} {piece}".strip()

    source = location_label(action["from"])
    target = location_label(action["to"])
    progress = 0 if cycle["duration"] <= 0 else (time_s - cycle["time"]) / cycle["duration"]

    if progress < 0.18:
        return f"Moving to {source}"
    if progress < 0.36:
        return f"Picking {piece} at {source}"
    if progress < 0.68:
        return f"Moving {piece} to {target}"
    if progress < 0.86:
        return f"Placing {piece} at {target}"
    return "Moving home"


def physical_flow_for_cycle(cycle: dict, selected: dict) -> dict:
    actor = ENTITY_LABELS.get(cycle["entity"], cycle["entity"])
    piece = short_piece(cycle.get("piece_id"))
    color = (cycle.get("color") or "part").lower()
    task = cycle["task_name"]
    action = selected.get("label") or action_sentence(cycle, selected)

    flows = {
        "FEED_TO_C1S1": {
            "condition": "Conveyor 1 entry is available and the Initial Stack still contains parts.",
            "decision": f"{actor} can release the next {color} part into the line.",
            "highlightResources": ["initial_stack", "conveyor1", "conveyor1_entry"],
        },
        "FEED_GREEN_TO_C3": {
            "condition": "A green part is available and Conveyor 3 entry is clear.",
            "decision": f"{actor} can send the part through the bypass conveyor.",
            "highlightResources": ["initial_stack", "conveyor3", "conveyor3_entry"],
        },
        "C1S2_TO_C2S1": {
            "condition": f"{piece} is detected at Conveyor 1 exit and Conveyor 2 entry is available.",
            "decision": f"{actor} can transfer the part to the next conveyor.",
            "highlightResources": ["conveyor1", "conveyor1_exit", "conveyor2", "conveyor2_entry"],
        },
        "C1S2_TO_LASER": {
            "condition": f"Red {piece} is detected at Conveyor 1 exit and the laser engraver is available.",
            "decision": f"{actor} routes the red part to laser processing.",
            "highlightResources": ["conveyor1", "conveyor1_exit", "laser_bed"],
        },
        "LASER_TO_C2S1": {
            "condition": f"The laser has finished {piece} and Conveyor 2 entry is available.",
            "decision": f"{actor} can return the engraved part to the main line.",
            "highlightResources": ["laser_bed", "conveyor2", "conveyor2_entry"],
        },
        "CLASSIFY_C2S2_TO_BANTAM": {
            "condition": f"Blue {piece} is detected at Conveyor 2 exit and the CNC path is available.",
            "decision": f"{actor} routes the blue part toward machining.",
            "highlightResources": ["conveyor2", "conveyor2_exit", "bantam_bed", "intermediate_blue_stack"],
        },
        "CLASSIFY_C2S2_TO_IBS": {
            "condition": f"Blue {piece} is detected at Conveyor 2 exit and the Blue Buffer is available.",
            "decision": f"{actor} stores the blue part while the CNC path is busy.",
            "highlightResources": ["conveyor2", "conveyor2_exit", "intermediate_blue_stack"],
        },
        "CLASSIFY_C2S2_TO_C4": {
            "condition": f"{piece} is detected at Conveyor 2 exit and Conveyor 4 entry is available.",
            "decision": f"{actor} can send the part directly toward the output side.",
            "highlightResources": ["conveyor2", "conveyor2_exit", "conveyor4", "conveyor4_entry"],
        },
        "IBS_TO_BANTAM": {
            "condition": f"The blue buffer is holding {piece} and the CNC is available.",
            "decision": f"{actor} can load the buffered part into the CNC.",
            "highlightResources": ["intermediate_blue_stack", "bantam_bed"],
        },
        "BANTAM_TO_C4": {
            "condition": f"The CNC has finished {piece} and Conveyor 4 entry is available.",
            "decision": f"{actor} clears the CNC output so the machining path can continue.",
            "highlightResources": ["bantam_bed", "conveyor4", "conveyor4_entry"],
        },
        "PROCESS_RED": {
            "condition": f"Red {piece} is inside the laser engraver.",
            "decision": "The laser engraver starts the required red-part operation.",
            "highlightResources": ["laser_bed"],
        },
        "PROCESS_BLUE": {
            "condition": f"Blue {piece} is inside the CNC.",
            "decision": "The CNC starts the required blue-part operation.",
            "highlightResources": ["bantam_bed"],
        },
        "UNLOAD_C4": {
            "condition": f"{piece} is waiting at Conveyor 4 exit and an output position is available.",
            "decision": f"{actor} can unload the finished part.",
            "highlightResources": ["conveyor4", "conveyor4_exit"],
        },
        "UNLOAD_C3": {
            "condition": f"Green {piece} is waiting at Conveyor 3 exit and an output position is available.",
            "decision": f"{actor} can unload the bypassed part.",
            "highlightResources": ["conveyor3", "conveyor3_exit"],
        },
    }

    flow = flows.get(
        task,
        {
            "condition": f"A physical condition is ready for {piece}.",
            "decision": f"{actor} can start the next operation.",
            "highlightResources": [cycle["entity"]],
        },
    )
    flow = dict(flow)
    flow["action"] = action
    flow["summary"] = f"{flow['condition']} {flow['decision']}"
    return flow


def piece_at_location(
    piece_states: list[dict],
    pieces_by_id: dict[str, dict],
    location: str,
    exclude_piece_id: str | None = None,
) -> dict | None:
    for state in sorted(piece_states, key=lambda item: item["id"]):
        if state["location"] != location or state["id"] == exclude_piece_id:
            continue
        piece = pieces_by_id.get(state["id"], {})
        return {
            "id": state["id"],
            "color": piece.get("color"),
            "shape": piece.get("shape"),
            "location": state["location"],
        }
    return None


def completed_before(cycles: list[dict], piece_id: str, task_name: str, time_s: float) -> bool:
    return any(
        cycle["piece_id"] == piece_id
        and cycle["task_name"] == task_name
        and cycle["end"] <= time_s
        for cycle in cycles
    )


def robot2_classify_task_for_waiting_piece(waiting_piece: dict, selected_task: str) -> str | None:
    color = (waiting_piece.get("color") or "").upper()
    if color == "BLUE":
        if selected_task == "BANTAM_TO_C4":
            return "CLASSIFY_C2S2_TO_IBS"
        return "CLASSIFY_C2S2_TO_BANTAM"
    if color in {"RED", "GREEN"}:
        return "CLASSIFY_C2S2_TO_C4"
    return None


def dynamic_decision_override(
    cycle: dict,
    selected: dict,
    flow: dict,
    piece_states: list[dict],
    pieces_by_id: dict[str, dict],
    cycles: list[dict],
    map_mode: str,
) -> dict | None:
    if map_mode != "dynamic":
        return None

    entity = cycle["entity"]
    task = cycle["task_name"]

    if entity == "robot2" and task == "BANTAM_TO_C4":
        waiting_piece = piece_at_location(piece_states, pieces_by_id, "conveyor2_exit", cycle.get("piece_id"))
        alternate_task = robot2_classify_task_for_waiting_piece(waiting_piece or {}, task) if waiting_piece else None
        if alternate_task:
            alternate = candidate_action(
                "robot2",
                alternate_task,
                waiting_piece["id"],
                waiting_piece.get("color"),
                f"candidate_{cycle.get('cycle_number')}",
            )
            selected_piece = short_piece(cycle.get("piece_id"))
            waiting_short = short_piece(waiting_piece["id"])
            waiting_color = (waiting_piece.get("color") or "part").lower()
            target_label = location_label(alternate.get("to"))
            return {
                "title": "Niryo 2",
                "summary": (
                    f"The CNC output is ready and Conveyor 4 can receive it. "
                    f"The competing physical choice is to route {waiting_short} from Conveyor 2 exit to {target_label}."
                ),
                "flow": {
                    "condition": (
                        f"The CNC output contains {selected_piece}, Conveyor 4 entry is available, "
                        f"and Conveyor 2 exit has {waiting_color} {waiting_short} waiting."
                    ),
                    "decision": "Niryo 2 follows the dynamic-map priority and clears the CNC output first.",
                    "action": selected["label"],
                },
                "conditions": [
                    f"CNC output contains {selected_piece}.",
                    "Conveyor 4 entry is available.",
                    f"Conveyor 2 exit has {waiting_color} {waiting_short} waiting.",
                    f"{target_label} is available.",
                ],
                "highlightResources": [
                    "bantam_bed",
                    "conveyor4",
                    "conveyor4_entry",
                    "conveyor2",
                    "conveyor2_exit",
                    alternate.get("to"),
                ],
                "feasibleActions": [selected, alternate],
                "selectedReason": "The map selects BANTAM_TO_C4 before classifying the waiting Conveyor 2 piece.",
            }

    if entity == "xarm1" and task in {"C1S2_TO_C2S1", "C1S2_TO_LASER"}:
        laser_piece = piece_at_location(piece_states, pieces_by_id, "laser_bed", cycle.get("piece_id"))
        if not laser_piece or not completed_before(cycles, laser_piece["id"], "PROCESS_RED", cycle["time"]):
            return None
        alternate = candidate_action(
            "xarm1",
            "LASER_TO_C2S1",
            laser_piece["id"],
            laser_piece.get("color"),
            f"candidate_{cycle.get('cycle_number')}",
        )
        selected_piece = short_piece(cycle.get("piece_id"))
        laser_short = short_piece(laser_piece["id"])
        return {
            "title": "xArm1",
            "summary": (
                f"Conveyor 1 exit has {selected_piece} and Conveyor 2 entry is free. "
                f"The competing physical choice is to retrieve completed {laser_short} from the laser."
            ),
            "flow": {
                "condition": f"Conveyor 1 exit contains {selected_piece}, Conveyor 2 entry is available, and the laser has completed {laser_short}.",
                "decision": "xArm1 follows the dynamic-map priority and feeds the Conveyor 1 part first.",
                "action": selected["label"],
            },
            "conditions": [
                f"Conveyor 1 exit contains {selected_piece}.",
                "Conveyor 2 entry is available.",
                f"Laser output contains completed {laser_short}.",
            ],
            "highlightResources": ["conveyor1", "conveyor1_exit", "conveyor2", "conveyor2_entry", "laser_bed"],
            "feasibleActions": [selected, alternate],
            "selectedReason": "The map selects the Conveyor 1 pickup before retrieving the completed laser output.",
        }

    return None


def decision_for_cycle(
    cycle: dict,
    map_id: str,
    map_mode: str,
    piece_states: list[dict],
    pieces_by_id: dict[str, dict],
    cycles: list[dict],
) -> dict:
    selected = selected_action_for_cycle(cycle)
    actor = ENTITY_LABELS.get(cycle["entity"], cycle["entity"])
    selected_id = selected["id"]
    flow = physical_flow_for_cycle(cycle, selected)

    decision = {
        "title": actor,
        "actor": cycle["entity"],
        "focus": cycle["entity"],
        "state": "Active",
        "summary": flow["summary"],
        "flow": {
            "condition": flow["condition"],
            "decision": flow["decision"],
            "action": flow["action"],
        },
        "conditions": [flow["condition"]],
        "highlightResources": flow["highlightResources"],
        "feasibleActions": [selected],
        "selected": selected_id,
        "selectedReason": flow["decision"],
        "start": round(cycle["time"], 3),
        "end": round(cycle["end"], 3),
        "displayEnd": round(min(cycle["end"], cycle["time"] + 10.0), 3),
    }
    override = dynamic_decision_override(cycle, selected, flow, piece_states, pieces_by_id, cycles, map_mode)
    if override:
        decision.update(override)
        decision["selected"] = selected_id
        decision["start"] = round(cycle["time"], 3)
        decision["end"] = round(cycle["end"], 3)
        decision["displayEnd"] = round(min(cycle["end"], cycle["time"] + 10.0), 3)
    return decision


def build_cycle_rows(raw: dict, offset: float) -> list[dict]:
    cycles = []
    for cycle in raw["cycles"]:
        start = shift_time(cycle["t"], offset)
        duration = round(float(cycle["duration"]), 3)
        cycles.append(
            {
                "id": cycle["id"],
                "entity": cycle["entity"],
                "task_name": cycle["task_name"],
                "piece_id": cycle["piece_id"],
                "color": cycle.get("color"),
                "cycle_number": cycle.get("cycle_number"),
                "time": start,
                "duration": duration,
                "end": round(start + duration, 3),
                "metadata": cycle.get("metadata") or {},
            }
        )
    return sorted(cycles, key=lambda item: (item["time"], item["id"]))


def conveyor_intervals_from_keyframes(piece_keyframes: dict[str, list[dict]]) -> list[dict]:
    intervals = []
    transitions = {
        ("conveyor1_entry", "conveyor1_exit"): "conveyor1",
        ("conveyor2_entry", "conveyor2_exit"): "conveyor2",
        ("conveyor3_entry", "conveyor3_exit"): "conveyor3",
        ("conveyor4_entry", "conveyor4_exit"): "conveyor4",
    }
    for piece_id, frames in piece_keyframes.items():
        for start, end in zip(frames, frames[1:]):
            conveyor = transitions.get((start["location"], end["location"]))
            if conveyor and end["time"] > start["time"]:
                intervals.append({"conveyor": conveyor, "piece": piece_id, "start": start["time"], "end": end["time"]})
    return intervals


def conveyor_block_intervals_from_keyframes(piece_keyframes: dict[str, list[dict]]) -> list[dict]:
    intervals = []
    entries = {
        "conveyor1_entry": "conveyor1",
        "conveyor2_entry": "conveyor2",
        "conveyor3_entry": "conveyor3",
        "conveyor4_entry": "conveyor4",
    }
    for piece_id, frames in piece_keyframes.items():
        for start, end in zip(frames, frames[1:]):
            conveyor = entries.get(start["location"])
            if conveyor and end["location"] == start["location"] and end["time"] - start["time"] > 0.2:
                intervals.append({"conveyor": conveyor, "piece": piece_id, "start": start["time"], "end": end["time"]})
    return intervals


def resources_and_details_at(
    time_s: float,
    cycles: list[dict],
    piece_keyframes: dict[str, list[dict]],
    conveyor_intervals: list[dict],
    block_intervals: list[dict],
) -> tuple[dict, dict]:
    resources = dict(DEFAULT_RESOURCES)
    details = {key: value for key, value in DEFAULT_RESOURCES.items()}

    for block in block_intervals:
        if block["start"] <= time_s < block["end"]:
            conveyor = block["conveyor"]
            resources[conveyor] = "BLOCKED"
            details[conveyor] = f"{short_piece(block['piece'])} waiting at entry"

    for interval in conveyor_intervals:
        if interval["start"] <= time_s < interval["end"]:
            conveyor = interval["conveyor"]
            if resources[conveyor] != "BLOCKED":
                resources[conveyor] = "RUNNING"
                details[conveyor] = f"{short_piece(interval['piece'])} moving entry to exit"

    for cycle in cycles:
        if cycle["time"] <= time_s < cycle["end"]:
            resources[cycle["entity"]] = "WORKING" if cycle["entity"] in {"laser", "bantam"} else "MOVING"
            details[cycle["entity"]] = activity_detail_for_cycle(cycle, time_s)

    piece_locations = {piece_id: state_at(frames, time_s)["location"] for piece_id, frames in piece_keyframes.items()}
    locations = list(piece_locations.values())
    resources["initial_stack"] = "READY" if "initial_stack" in locations else "EMPTY"
    resources["c3"] = "OCCUPIED" if any(loc in {"conveyor3_entry", "conveyor3_exit", "c3_location"} for loc in locations) else "CLEAR"
    resources["c4"] = "OCCUPIED" if any(loc in {"conveyor4_entry", "conveyor4_exit", "c4_location"} for loc in locations) else "CLEAR"
    resources["intermediate_blue_stack"] = "HOLDING" if "intermediate_blue_stack" in locations else "EMPTY"
    resources["final_red_stack"] = "HOLDING" if "final_red_stack" in locations else "EMPTY"
    resources["final_blue_stack"] = "HOLDING" if "final_blue_stack" in locations else "EMPTY"
    resources["final_green_stack"] = "HOLDING" if "final_green_stack" in locations else "EMPTY"
    initial_pieces = [short_piece(piece_id) for piece_id, loc in piece_locations.items() if loc == "initial_stack"]
    c3_pieces = [short_piece(piece_id) for piece_id, loc in piece_locations.items() if loc in {"conveyor3_entry", "conveyor3_exit", "c3_location"}]
    c4_pieces = [short_piece(piece_id) for piece_id, loc in piece_locations.items() if loc in {"conveyor4_entry", "conveyor4_exit", "c4_location"}]
    ibs_pieces = [short_piece(piece_id) for piece_id, loc in piece_locations.items() if loc == "intermediate_blue_stack"]
    final_red = [short_piece(piece_id) for piece_id, loc in piece_locations.items() if loc == "final_red_stack"]
    final_blue = [short_piece(piece_id) for piece_id, loc in piece_locations.items() if loc == "final_blue_stack"]
    final_green = [short_piece(piece_id) for piece_id, loc in piece_locations.items() if loc == "final_green_stack"]

    details["initial_stack"] = f"{len(initial_pieces)} / 18 parts" if initial_pieces else "0 / 18 parts"
    details["c3"] = ", ".join(c3_pieces) if c3_pieces else "Clear"
    details["c4"] = ", ".join(c4_pieces) if c4_pieces else "Clear"
    details["intermediate_blue_stack"] = ", ".join(ibs_pieces) if ibs_pieces else "Empty"
    details["final_red_stack"] = f"{len(final_red)} red complete" if final_red else "Empty"
    details["final_blue_stack"] = f"{len(final_blue)} blue complete" if final_blue else "Empty"
    details["final_green_stack"] = f"{len(final_green)} green complete" if final_green else "Empty"
    return resources, details


def active_cycle_at(time_s: float, cycles: list[dict]) -> dict | None:
    active = [cycle for cycle in cycles if cycle["time"] <= time_s < cycle["end"]]
    if not active:
        return None
    return sorted(active, key=lambda item: (item["time"], item["id"]))[-1]


def active_cycles_at(time_s: float, cycles: list[dict]) -> list[dict]:
    return sorted(
        (cycle for cycle in cycles if cycle["time"] <= time_s < cycle["end"]),
        key=lambda item: (item["time"], item["id"]),
    )


def frame_pieces_at(time_s: float, pieces: list[dict], piece_keyframes: dict[str, list[dict]]) -> list[dict]:
    states = []
    for piece in pieces:
        frame = state_at(piece_keyframes[piece["id"]], time_s)
        state = {"id": piece["id"], "location": frame["location"]}
        if frame.get("slot"):
            state["slot"] = frame["slot"]
        states.append(state)
    return states


def physical_conditions_at(
    resources: dict,
    details: dict,
    piece_states: list[dict],
    active_decisions: list[dict],
) -> list[dict]:
    conditions: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(label: str, value: str, state: str = "AVAILABLE") -> None:
        key = (label, value)
        if key in seen:
            return
        seen.add(key)
        conditions.append({"label": label, "value": value, "state": state})

    pieces_by_location: dict[str, list[str]] = defaultdict(list)
    for piece in piece_states:
        pieces_by_location[piece["location"]].append(short_piece(piece["id"]))

    focus_locations = set()
    for decision in active_decisions:
        focus_locations.update(decision.get("highlightResources") or [])
        for action in decision.get("feasibleActions") or []:
            for key in ("at", "from", "to"):
                if action.get(key):
                    focus_locations.add(action[key])

    initial_count = len(pieces_by_location.get("initial_stack", []))
    add("Initial Stack", f"{initial_count} / 18 parts waiting", "READY" if initial_count else "EMPTY")

    sensor_locations = [
        ("conveyor1_entry", "Conveyor 1 entry sensor"),
        ("conveyor1_exit", "Conveyor 1 exit sensor"),
        ("conveyor2_entry", "Conveyor 2 entry sensor"),
        ("conveyor2_exit", "Conveyor 2 exit sensor"),
        ("conveyor3_entry", "Conveyor 3 entry"),
        ("conveyor3_exit", "Conveyor 3 exit"),
        ("conveyor4_entry", "Conveyor 4 entry"),
        ("conveyor4_exit", "Conveyor 4 exit"),
    ]
    for location, label in sensor_locations:
        pieces = pieces_by_location.get(location, [])
        if pieces:
            add(label, f"Occupied by {', '.join(pieces)}", "OCCUPIED")
        elif location in focus_locations:
            add(label, "Available", "AVAILABLE")

    for resource, label in [
        ("conveyor1", "Conveyor 1"),
        ("conveyor2", "Conveyor 2"),
        ("conveyor3", "Conveyor 3"),
        ("conveyor4", "Conveyor 4"),
    ]:
        if resources.get(resource) in {"RUNNING", "BLOCKED"}:
            add(label, details.get(resource, resources[resource]), resources[resource])

    for location, label, resource in [
        ("laser_bed", "Laser engraver", "laser"),
        ("bantam_bed", "Bantam CNC", "bantam"),
        ("intermediate_blue_stack", "Blue buffer", "intermediate_blue_stack"),
    ]:
        pieces = pieces_by_location.get(location, [])
        if resources.get(resource) in {"WORKING", "HOLDING"}:
            add(label, details.get(resource, resources[resource]), resources[resource])
        elif pieces:
            add(label, f"Contains {', '.join(pieces)}", "OCCUPIED")
        elif location in focus_locations:
            add(label, "Available", "AVAILABLE")

    for resource, label in [
        ("xarm2", "xArm2"),
        ("xarm1", "xArm1"),
        ("robot2", "Niryo 2"),
        ("robot1", "Niryo 1"),
    ]:
        if resources.get(resource) not in {"IDLE", None}:
            add(label, details.get(resource, resources[resource]), resources[resource])

    return conditions[:8]


def build_frames(
    run: dict,
    pieces: list[dict],
    cycles: list[dict],
    piece_keyframes: dict[str, list[dict]],
    duration: float,
) -> list[dict]:
    config = run.get("config_snapshot") or {}
    map_id = config.get("map_id", "unknown")
    map_mode = config.get("map_mode", "unknown")
    conveyor_intervals = conveyor_intervals_from_keyframes(piece_keyframes)
    block_intervals = conveyor_block_intervals_from_keyframes(piece_keyframes)
    pieces_by_id = {piece["id"]: piece for piece in pieces}

    event_times = {0.0, round(duration, 3)}
    for cycle in cycles:
        event_times.add(cycle["time"])
        event_times.add(cycle["end"])
        for phase_break in PHASE_BREAKS:
            event_times.add(round(cycle["time"] + cycle["duration"] * phase_break, 3))
    for frames in piece_keyframes.values():
        for frame in frames:
            event_times.add(frame["time"])
    for interval in conveyor_intervals:
        event_times.add(interval["start"])
        event_times.add(interval["end"])
    for interval in block_intervals:
        event_times.add(interval["start"])
        event_times.add(interval["end"])

    frames = []
    for time_s in sorted(time for time in event_times if 0 <= time <= duration):
        active_cycles = active_cycles_at(time_s, cycles)
        cycle = active_cycles[-1] if active_cycles else None
        if cycle:
            label = ENTITY_LABELS.get(cycle["entity"], cycle["entity"])
            task = TASK_LABELS.get(cycle["task_name"], cycle["task_name"])
            phase = f"{label}: {task}"
            summary = action_sentence(cycle, selected_action_for_cycle(cycle))
        else:
            phase = "Physical state update"
            summary = "The cell is waiting for the next physical condition."

        resources, resource_details = resources_and_details_at(
            time_s,
            cycles,
            piece_keyframes,
            conveyor_intervals,
            block_intervals,
        )
        piece_states = frame_pieces_at(time_s, pieces, piece_keyframes)
        visible_decisions = [
            decision_for_cycle(cycle, map_id, map_mode, piece_states, pieces_by_id, cycles)
            for cycle in active_cycles
            if cycle["time"] <= time_s < min(cycle["end"], cycle["time"] + 10.0)
        ]

        frames.append(
            {
                "time": round(time_s, 3),
                "phase": phase,
                "summary": summary,
                "resources": resources,
                "resourceDetails": resource_details,
                "pieces": piece_states,
                "physicalConditions": physical_conditions_at(resources, resource_details, piece_states, visible_decisions),
                "activeDecisions": visible_decisions,
                "decision": visible_decisions[-1] if visible_decisions else None,
            }
        )

    return frames


def build_replay(raw: dict) -> dict:
    offset = min(cycle["t"] for cycle in raw["cycles"])
    cycles = build_cycle_rows(raw, offset)
    pieces, piece_keyframes = build_piece_keyframes(raw, cycles, offset)
    duration = round(max(max(cycle["end"] for cycle in cycles), max(frame[-1]["time"] for frame in piece_keyframes.values())), 3)
    run = raw["run"]
    config = run.get("config_snapshot") or {}
    frames = build_frames(run, pieces, cycles, piece_keyframes, duration)

    return {
        "id": run["run_id"],
        "label": "Shipyard PnP cell flow",
        "status": run.get("status"),
        "startedAt": run.get("started_at"),
        "finishedAt": run.get("finished_at"),
        "totalPieces": run.get("total_pieces"),
        "piecesCompleted": run.get("pieces_completed"),
        "originalOrder": run.get("original_order"),
        "optimizedOrder": run.get("optimized_order"),
        "runConfig": config,
        "duration": duration,
        "sourceRefs": [],
        "notes": [
            "Conveyors show visible travel from entry to exit.",
            "A part waits at conveyor entry while the exit zone is occupied.",
            "Decision explanations stay visible only while they are physically relevant.",
        ],
        "pieces": pieces,
        "pieceKeyframes": piece_keyframes,
        "cycles": cycles,
        "frames": frames,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    with args.input.open() as handle:
        raw = json.load(handle)

    replay = build_replay(raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "window.ShipyardSampleRun = "
        + json.dumps(replay, indent=2, sort_keys=False)
        + ";\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output} from {replay['id']} ({len(replay['cycles'])} cycles, {len(replay['frames'])} frames).")


if __name__ == "__main__":
    main()
