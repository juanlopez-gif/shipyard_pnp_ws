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
    params = {}
    if requested_color:
        params["color"] = requested_color

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
            fs._feeding_state = "IDLE"
            return

        slot_id = result.get("slot_id")
        color = result.get("color")
        shape = result.get("shape")
        if not slot_id:
            fs.get_logger().warning(f"LOCATE_NEXT_PIECE returned no slot: {result}")
            fs._feeding_state = "IDLE"
            return
        if slot_id:
            fs.pieces.assign_slot(slot_id)
        if color and shape:
            fs.pieces.assign_color_shape("initial_stack", color, shape)

        # After vision confirms GREEN, re-check C3 occupancy.
        if color == "GREEN" and fs.state.get_sensor("c3") != SensorState.FREE:
            fs.get_logger().warning("C3 still occupied after vision; aborting GREEN feed")
            fs._feeding_state = "IDLE"
            return

        if color == "GREEN":
            _send_xarm2_to_c3(fs, piece_id, slot_id)
        else:
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
            fs._feeding_state = "IDLE"
            return

        fs.pieces.transfer_piece("initial_stack", "conveyor1")
        fs.cycles.start_cycle(piece_id)
        fs.state.update_robot("xarm2", RobotState.IDLE)
        # c1s1=OCCUPIED is NOT set here — the real IR sensor already fired it.
        # Setting it here races against the conveyor (which may have already
        # moved the piece and caused c1s1=FREE from hardware) and leaves a
        # phantom OCCUPIED state that blocks all future feeding.
        fs._feeding_state = "IDLE"

    return on_complete


def _on_xarm2_to_c3_complete(fs, piece_id: str):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"xArm2 feed to C3 failed: {result}")
            fs._feeding_state = "IDLE"
            return

        fs.pieces.transfer_piece("initial_stack", "c3_location")
        fs.cycles.start_cycle(piece_id)
        fs.state.update_sensor("c3", SensorState.OCCUPIED)
        fs._c3_deposit_time = time.time()

        # Piece is now placed — start conveyor immediately and stop after settle time.
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

        # Send xArm2 home as a follow-up; feeding stays blocked until home done.
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
