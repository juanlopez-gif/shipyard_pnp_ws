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
    xarm1_free = (
        fs.state.get_robot("xarm1") == RobotState.IDLE
        and not fs.vendor_clients["ufactory"].is_busy("xarm1")
    )
    if not xarm1_free:
        return

    # Two jobs can compete for xarm1's single arm at the same instant:
    # retrieving a finished piece off the laser bed, and handling the next
    # piece waiting at c1s2. Absolute rule when BOTH are ready: retrieve
    # wins (matches the validated simulator behavior). When only one is
    # ready, check whether the expected schedule wanted the other one --
    # give it up to MAP_GRACE_SEC to become ready before falling back.
    retrieve_ready = (
        fs.state.get_machine("laser") == MachineState.FINISHED
        and fs.state.get_sensor("c2s1") == SensorState.FREE
    )
    c1s2_ready = (
        fs.pieces.count("conveyor1") > 0
        and fs.state.get_sensor("c1s2") == SensorState.OCCUPIED
    )

    if not retrieve_ready and not c1s2_ready:
        return

    # If the expected schedule's pick is ALREADY physically ready, take it
    # immediately -- this is what resolves a wait: once the awaited option
    # becomes ready it must win outright, not get re-litigated against the
    # "both ready" absolute rule below.
    expected = fs._map_next("xarm1")
    wants_retrieve = expected is not None and expected["task"] == "LASER_TO_C2S1"
    wants_c1s2 = expected is not None and expected["task"] in ("C1S2_TO_LASER", "C1S2_TO_C2S1")

    if c1s2_ready and wants_c1s2:
        do_retrieve = False
    elif retrieve_ready and wants_retrieve:
        do_retrieve = True
    elif retrieve_ready and c1s2_ready:
        do_retrieve = True
    elif retrieve_ready:
        # If the map wants c1s2 handling next, give it up to MAP_GRACE_SEC
        # to actually show up, even if nothing's there yet -- waiting for a
        # piece that hasn't arrived is exactly the case this exists for (the
        # plain reactive rule already covers "already sitting there" on its
        # own). If it doesn't show up within the grace window, retrieve goes.
        if wants_c1s2 and fs._map_should_wait("xarm1"):
            return
        do_retrieve = True
    else:
        if wants_retrieve and fs._map_should_wait("xarm1"):
            return
        do_retrieve = False

    # ── Retrieve a finished piece from the laser bed ────────────────────────
    if do_retrieve:
        fs._map_note_dispatch("xarm1", "LASER_TO_C2S1")
        _send_xarm1_laser_to_c2(fs, fs._pending_laser_piece_id)
        return

    # ── Pick up the next piece waiting at c1s2 ──────────────────────────────
    piece_id = fs.pieces.peek_first_piece_id("conveyor1")
    color    = fs.pieces.peek_first_piece_color("conveyor1") or "UNKNOWN"
    if color == "RED":
        # Laser bed holds one piece at a time — RED can only go in once it's
        # back to IDLE (previous piece fully placed on the laser and cleared,
        # or laser never used). A RED piece waiting here does NOT block BLUE/
        # GREEN pieces at c1s2 from moving directly to c2s1 in the meantime.
        if fs.state.get_machine("laser") != MachineState.IDLE:
            return
        fs._map_note_dispatch("xarm1", "C1S2_TO_LASER")
        _send_xarm1_to_laser(fs, piece_id)
    else:
        # c2s1 must be empty for ANY color placed there — this direct move
        # competes for the same slot as the laser→c2s1 retrieval above.
        if fs.state.get_sensor("c2s1") != SensorState.FREE:
            return
        fs._map_note_dispatch("xarm1", "C1S2_TO_C2S1")
        _send_xarm1_direct_to_c2(fs, piece_id, color)


def _send_xarm1_direct_to_c2(fs, piece_id: str, color: str) -> None:
    fs.cycles.start_entity_cycle(
        "xarm1", "C1S2_TO_C2S1",
        piece_id=piece_id, color=color, route=color,
        metadata=fs._map_pop_dispatch_metadata("xarm1"),
    )
    fs.cycles.add_phase("xarm1", "MOVING_C1S2_TO_C2S1")

    fs._processing_state = "WAITING_XARM1_DIRECT"
    fs.register_pick_source("xarm1", "conveyor1")
    fs.register_place_target("xarm1", "conveyor2")
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
        metadata=fs._map_pop_dispatch_metadata("xarm1"),
    )
    fs.cycles.add_phase("xarm1", "MOVING_C1S2_TO_LASER")

    fs._processing_state = "WAITING_XARM1_TO_LASER"
    fs.register_pick_source("xarm1", "conveyor1")
    fs.register_place_target("xarm1", "laser_bed")
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

        if not fs.consume_place_done_flag("xarm1"):
            fs.pieces.transfer_via_gripper("xarm1_gripper", "conveyor1", "conveyor2")
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

        if not fs.consume_place_done_flag("xarm1"):
            fs.pieces.transfer_via_gripper("xarm1_gripper", "conveyor1", "laser_bed")
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
        # Unlike evaluate()'s Priority 1 (which checks xarm1_free before
        # dispatching), this callback used to call _send_xarm1_laser_to_c2
        # unconditionally whenever c2s1 was free -- if xarm1 was still busy
        # with an unrelated piece at that exact instant, send_command raised
        # ("VendorClient 'ufactory/xarm1' is busy"), after the entity cycle
        # had already been started, leaving a stray/duplicate cycle_event
        # once evaluate()'s next 0.5s tick retried it correctly. Guard on
        # xarm1_free here too; if busy, just leave laser=FINISHED and
        # _pending_laser_piece_id set -- evaluate()'s Priority 1 picks it up
        # on its own as soon as xarm1 frees up, no extra state needed.
        xarm1_free = (
            fs.state.get_robot("xarm1") == RobotState.IDLE
            and not fs.vendor_clients["ufactory"].is_busy("xarm1")
        )
        if fs.state.get_sensor("c2s1") != SensorState.FREE:
            fs.get_logger().info(
                f"[processing] laser done for {piece_id} — c2s1 occupied, waiting for conveyor2"
            )
            fs._processing_state = "LASER_DONE_WAITING_C2S1"
        elif xarm1_free:
            fs._map_note_dispatch("xarm1", "LASER_TO_C2S1")
            _send_xarm1_laser_to_c2(fs, piece_id)
        else:
            fs.get_logger().info(
                f"[processing] laser done for {piece_id} — xarm1 busy, evaluate() will retrieve it"
            )

    return on_complete


def _send_xarm1_laser_to_c2(fs, piece_id: str) -> None:
    fs.get_logger().info(f"[processing] xarm1 LASER_BED → C2S1: piece={piece_id}")
    fs.cycles.start_entity_cycle(
        "xarm1", "LASER_TO_C2S1",
        piece_id=piece_id, color="RED", route="RED",
        metadata=fs._map_pop_dispatch_metadata("xarm1"),
    )
    fs.cycles.add_phase("xarm1", "MOVING_LASER_TO_C2S1")

    fs._processing_state = "WAITING_XARM1_TO_C2S1"
    fs.register_pick_source("xarm1", "laser_bed")
    fs.register_place_target("xarm1", "conveyor2")
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

        if not fs.consume_place_done_flag("xarm1"):
            fs.pieces.transfer_via_gripper("xarm1_gripper", "laser_bed", "conveyor2")
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
