"""
Processes pieces after conveyor1.

RED pieces are routed through the laser bed before conveyor2. BLUE and
UNKNOWN pieces go directly to conveyor2. GREEN normally bypasses this module.

Entity cycles:
  xarm1 / C1S2_TO_C2S1       — direct move (BLUE/GREEN/UNKNOWN)
  xarm1 / C1S2_TO_LASER       — RED: pick from C1S2 and place on laser bed
  laser / PROCESS_RED          — laser job
  xarm1 / LASER_TO_C2S1       — pick from laser bed and place on conveyor2
"""

from shipyard_pnp.shared.contracts import MachineState, RobotState, SensorState


def evaluate(fs) -> None:
    # Laser finished but c2s1 was occupied — poll until conveyor2 frees it.
    if fs._processing_state == "LASER_DONE_WAITING_C2S1":
        if (
            fs.state.get_sensor("c2s1") == SensorState.FREE
            and not fs.vendor_clients["ufactory"].is_busy("xarm1")
        ):
            _send_xarm1_laser_to_c2(fs, fs._pending_laser_piece_id)
        return

    if fs._processing_state != "IDLE":
        return
    if fs.pieces.count("conveyor1") <= 0:
        return
    if fs.state.get_sensor("c1s2") != SensorState.OCCUPIED:
        return
    if fs.state.get_robot("xarm1") != RobotState.IDLE:
        return
    if fs.vendor_clients["ufactory"].is_busy("xarm1"):
        return

    piece_id = fs.pieces.peek_first_piece_id("conveyor1")
    color    = fs.pieces.peek_first_piece_color("conveyor1") or "UNKNOWN"
    if color == "RED":
        # c2s1 is checked only for the laser→c2s1 move, not for c1s2→laser.
        _send_xarm1_to_laser(fs, piece_id)
    else:
        if fs.state.get_sensor("c2s1") != SensorState.FREE:
            return
        _send_xarm1_direct_to_c2(fs, piece_id, color)


def _send_xarm1_direct_to_c2(fs, piece_id: str, color: str) -> None:
    fs.cycles.start_entity_cycle(
        "xarm1", "C1S2_TO_C2S1",
        piece_id=piece_id, color=color, route=color,
    )
    fs.cycles.add_phase("xarm1", "MOVING_C1S2_TO_C2S1")

    fs._processing_state = "WAITING_XARM1_DIRECT"
    fs.send_command(
        "ufactory",
        "xarm1",
        "MOVE_PIECE",
        piece_id=piece_id,
        source="C1S2",
        target="C2S1",
        route=color,
        parameters={"source": "C1S2", "target": "C2S1"},
        on_complete=_on_xarm1_direct_complete(fs),
    )


def _send_xarm1_to_laser(fs, piece_id: str) -> None:
    fs.get_logger().info(f"[processing] xarm1 → LASER_BED: piece={piece_id}")
    fs.cycles.start_entity_cycle(
        "xarm1", "C1S2_TO_LASER",
        piece_id=piece_id, color="RED", route="RED",
    )
    fs.cycles.add_phase("xarm1", "MOVING_C1S2_TO_LASER")

    fs._processing_state = "WAITING_XARM1_TO_LASER"
    fs.send_command(
        "ufactory",
        "xarm1",
        "MOVE_PIECE",
        piece_id=piece_id,
        source="C1S2",
        target="LASER_BED",
        route="RED",
        parameters={"source": "C1S2", "target": "LASER_BED"},
        on_complete=_on_xarm1_to_laser_complete(fs, piece_id),
    )


def _on_xarm1_direct_complete(fs):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"xArm1 direct move failed: {result}")
            _discard_and_insert(fs, "xarm1", "direct_move_failed")
            fs._processing_state = "IDLE"
            return

        fs.pieces.transfer_piece("conveyor1", "conveyor2")
        fs.state.update_robot("xarm1", RobotState.IDLE)
        _complete_and_insert(fs, "xarm1")
        fs._processing_state = "IDLE"

    return on_complete


def _on_xarm1_to_laser_complete(fs, piece_id: str):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"xArm1 move to laser failed: {result}")
            _discard_and_insert(fs, "xarm1", "move_to_laser_failed")
            fs._processing_state = "IDLE"
            return

        fs.pieces.transfer_piece("conveyor1", "laser_bed")
        fs.state.update_robot("xarm1", RobotState.IDLE)
        fs.state.update_machine("laser", MachineState.PREPARING)
        _complete_and_insert(fs, "xarm1")
        _send_laser_job(fs, piece_id)

    return on_complete


def _send_laser_job(fs, piece_id: str) -> None:
    fs.cycles.start_entity_cycle(
        "laser", "PROCESS_RED",
        piece_id=piece_id, color="RED", route="RED",
    )
    fs.cycles.add_phase("laser", "PROCESSING")

    fs._processing_state = "WAITING_LASER"
    fs.send_command(
        "laser",
        "laser",
        "RUN_JOB",
        piece_id=piece_id,
        source="LASER_BED",
        target="LASER_BED",
        route="RED",
        parameters={"job_type": "RED_PROCESS"},
        on_complete=_on_laser_complete(fs, piece_id),
    )


def _on_laser_complete(fs, piece_id: str):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"Laser job failed: {result}")
            _discard_and_insert(fs, "laser", "laser_job_failed")
            fs._processing_state = "IDLE"
            return

        fs.state.update_machine("laser", MachineState.FINISHED)
        _complete_and_insert(fs, "laser")

        fs._pending_laser_piece_id = piece_id
        if fs.state.get_sensor("c2s1") == SensorState.FREE:
            _send_xarm1_laser_to_c2(fs, piece_id)
        else:
            fs.get_logger().info(
                f"[processing] laser done for {piece_id} — c2s1 occupied, waiting for conveyor2"
            )
            fs._processing_state = "LASER_DONE_WAITING_C2S1"

    return on_complete


def _send_xarm1_laser_to_c2(fs, piece_id: str) -> None:
    fs.get_logger().info(f"[processing] xarm1 LASER_BED → C2S1: piece={piece_id}")
    fs.cycles.start_entity_cycle(
        "xarm1", "LASER_TO_C2S1",
        piece_id=piece_id, color="RED", route="RED",
    )
    fs.cycles.add_phase("xarm1", "MOVING_LASER_TO_C2S1")

    fs._processing_state = "WAITING_XARM1_TO_C2S1"
    fs.send_command(
        "ufactory",
        "xarm1",
        "MOVE_PIECE",
        piece_id=piece_id,
        source="LASER_BED",
        target="C2S1",
        route="RED",
        parameters={"source": "LASER_BED", "target": "C2S1"},
        on_complete=_on_xarm1_laser_to_c2_complete(fs),
    )


def _on_xarm1_laser_to_c2_complete(fs):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"xArm1 laser unload failed: {result}")
            _discard_and_insert(fs, "xarm1", "laser_unload_failed")
            fs._processing_state = "IDLE"
            return

        fs.pieces.transfer_piece("laser_bed", "conveyor2")
        fs.state.update_robot("xarm1", RobotState.IDLE)
        fs.state.update_machine("laser", MachineState.IDLE)
        _complete_and_insert(fs, "xarm1")
        fs._processing_state = "IDLE"

    return on_complete


# ── Helpers ──────────────────────────────────────────────────────────────────

def _complete_and_insert(fs, entity: str) -> None:
    cycle = fs.cycles.complete_entity_cycle(entity)
    if cycle:
        fs.db.insert_entity_cycle(cycle)


def _discard_and_insert(fs, entity: str, reason: str) -> None:
    cycle = fs.cycles.discard_entity_cycle(entity, reason)
    if cycle:
        fs.db.insert_entity_cycle(cycle)
