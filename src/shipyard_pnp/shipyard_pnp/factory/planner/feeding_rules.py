"""
Feeds pieces from the global stack into the production route.

RED/BLUE enter conveyor1 at C1S1. GREEN bypasses conveyor1 and is placed at
C3 for robot1 unloading, matching the corrected color_routes layout.
"""

import threading
import time

from shipyard_pnp.shared.contracts import RobotState, SensorState


def evaluate(fs) -> None:
    if fs._feeding_state != "IDLE":
        return
    if fs.pieces.count("initial_stack") <= 0:
        return
    if fs.state.get_robot("xarm2") != RobotState.IDLE:
        return
    if fs.state.get_sensor("c1s1") != SensorState.FREE:
        return
    if fs.vendor_clients["globalvision"].is_busy():
        return
    if fs.vendor_clients["ufactory"].is_busy("xarm2"):
        return

    # If next piece is GREEN and C3 is already occupied, wait.
    requested_color = fs.pieces.peek_first_piece_color("initial_stack")
    if requested_color == "GREEN" and fs.state.get_sensor("c3") != SensorState.FREE:
        return

    piece_id = fs.pieces.peek_first_piece_id("initial_stack")
    color    = requested_color or "UNKNOWN"
    params   = {}
    if requested_color:
        params["color"] = requested_color

    # Start entity cycle for xarm2 — first phase is waiting for globalvision.
    task_name = "FEED_GREEN_TO_C3" if color == "GREEN" else "FEED_TO_C1S1"
    fs.cycles.start_entity_cycle(
        "xarm2", task_name,
        piece_id=piece_id,
        color=color,
        metadata={"expected_color": color},
    )
    fs.cycles.add_phase("xarm2", "WAITING_GLOBALVISION")

    fs._feeding_state = "WAITING_VISION"
    fs.send_command(
        "globalvision",
        "globalvision_camera",
        "LOCATE_NEXT_PIECE",
        piece_id=piece_id,
        source="INITIAL_STACK",
        parameters=params,
        on_complete=_on_locate_complete(fs, piece_id),
    )


def _on_locate_complete(fs, piece_id: str):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"LOCATE_NEXT_PIECE failed: {result}")
            _discard_and_insert(fs, "xarm2", "globalvision_failed")
            fs._feeding_state = "IDLE"
            return

        slot_id = result.get("slot_id")
        color   = result.get("color")
        shape   = result.get("shape")

        if not slot_id:
            fs.get_logger().warning(f"LOCATE_NEXT_PIECE returned no slot: {result}")
            _discard_and_insert(fs, "xarm2", "globalvision_no_slot")
            fs._feeding_state = "IDLE"
            return

        if slot_id:
            fs.pieces.assign_slot(slot_id)
        if color and shape:
            fs.pieces.assign_color_shape("initial_stack", color, shape)

        # Update cycle with vision-confirmed color and final task name.
        confirmed_task = "FEED_GREEN_TO_C3" if color == "GREEN" else "FEED_TO_C1S1"
        fs.cycles.update_entity_cycle("xarm2", color=color, task_name=confirmed_task)

        # After vision confirms GREEN, re-check C3 occupancy.
        if color == "GREEN" and fs.state.get_sensor("c3") != SensorState.FREE:
            fs.get_logger().warning("C3 still occupied after vision; aborting GREEN feed")
            _discard_and_insert(fs, "xarm2", "c3_occupied_after_vision")
            fs._feeding_state = "IDLE"
            return

        if color == "GREEN":
            fs.cycles.add_phase("xarm2", "MOVING_TO_C3")
            _send_xarm2_to_c3(fs, piece_id, slot_id)
        else:
            fs.cycles.add_phase("xarm2", "MOVING_TO_C1S1")
            _send_xarm2_to_c1(fs, piece_id, slot_id)

    return on_complete


def _send_xarm2_to_c1(fs, piece_id: str, slot_id: str) -> None:
    fs._feeding_state = "WAITING_XARM2_PICK"
    fs.send_command(
        "ufactory",
        "xarm2",
        "MOVE_PIECE",
        piece_id=piece_id,
        source="INITIAL_STACK",
        target="C1S1",
        parameters={"pick_slot": slot_id, "target": "C1S1"},
        on_complete=_on_xarm2_to_c1_complete(fs, piece_id),
    )


def _send_xarm2_to_c3(fs, piece_id: str, slot_id: str) -> None:
    fs._feeding_state = "WAITING_XARM2_GREEN"
    fs.send_command(
        "ufactory",
        "xarm2",
        "MOVE_PIECE",
        piece_id=piece_id,
        source="INITIAL_STACK",
        target="C3",
        route="GREEN",
        parameters={"pick_slot": slot_id, "target": "C3"},
        on_complete=_on_xarm2_to_c3_complete(fs, piece_id),
    )


def _on_xarm2_to_c1_complete(fs, piece_id: str):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"xArm2 feed to C1S1 failed: {result}")
            _discard_and_insert(fs, "xarm2", "move_to_c1s1_failed")
            fs._feeding_state = "IDLE"
            return

        fs.pieces.transfer_piece("initial_stack", "conveyor1")
        fs.cycles.start_cycle(piece_id)  # piece-level cycle starts here

        _complete_and_insert(fs, "xarm2")

        fs.state.update_robot("xarm2", RobotState.IDLE)
        fs._feeding_state = "IDLE"

    return on_complete


def _on_xarm2_to_c3_complete(fs, piece_id: str):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"xArm2 feed to C3 failed: {result}")
            _discard_and_insert(fs, "xarm2", "move_to_c3_failed")
            fs._feeding_state = "IDLE"
            return

        fs.pieces.transfer_piece("initial_stack", "c3_location")
        fs.cycles.start_cycle(piece_id)  # piece-level cycle starts here
        fs.state.update_sensor("c3", SensorState.OCCUPIED)
        fs._c3_deposit_time = time.time()

        # Home command is part of the GREEN feed cycle.
        fs.cycles.add_phase("xarm2", "RETURNING_HOME")

        # Start conveyor and schedule auto-stop.
        try:
            fs.send_command(
                "green_conveyors",
                "conveyor3",
                "RUN_CONVEYOR",
                piece_id=piece_id,
                source="C3_ENTRY",
                target="C3",
                route="GREEN",
            )
            _schedule_conveyor_stop(fs, "conveyor3", piece_id, "GREEN", fs.c3_settle_sec)
        except Exception as exc:
            fs.get_logger().error(f"Failed to start conveyor3: {exc}")

        fs._feeding_state = "WAITING_XARM2_HOME"
        fs.send_command(
            "ufactory",
            "xarm2",
            "MOVE_XARM_HOME",
            on_complete=_on_xarm2_c3_home_complete(fs),
        )

    return on_complete


def _on_xarm2_c3_home_complete(fs):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().warning(f"xArm2 return home after C3 ended with {task_state}")
            # Complete rather than discard — the piece was already placed successfully.
        _complete_and_insert(fs, "xarm2")
        fs.state.update_robot("xarm2", RobotState.IDLE)
        fs._feeding_state = "IDLE"

    return on_complete


def _schedule_conveyor_stop(fs, conveyor_id: str, piece_id: str, route: str, delay_sec: float) -> None:
    def _stop():
        try:
            fs.send_command(
                "green_conveyors", conveyor_id, "STOP_CONVEYOR",
                piece_id=piece_id, route=route,
            )
        except Exception as exc:
            fs.get_logger().warning(f"Auto-stop {conveyor_id} failed: {exc}")
    t = threading.Timer(delay_sec, _stop)
    t.daemon = True
    t.start()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _complete_and_insert(fs, entity: str) -> None:
    cycle = fs.cycles.complete_entity_cycle(entity)
    if cycle:
        fs.db.insert_entity_cycle(cycle)


def _discard_and_insert(fs, entity: str, reason: str) -> None:
    cycle = fs.cycles.discard_entity_cycle(entity, reason)
    if cycle:
        fs.db.insert_entity_cycle(cycle)
