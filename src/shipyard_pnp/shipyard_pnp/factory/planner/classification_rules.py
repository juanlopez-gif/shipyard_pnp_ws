"""
Classifies pieces at C2S2 and routes them with robot2.

Color → route:
  RED / GREEN  → C4 (robot1 unloads to final stack)
  BLUE         → BANTAM_BED if bantam is idle, else IBS (intermediate blue stack)
  UNKNOWN      → SCRAP

IBS drain: when bantam becomes idle and the intermediate stack has pieces,
evaluate() picks them up and feeds them to bantam.

c4 guard: only required before starting vision when the piece is known NOT to be
BLUE. BLUE pieces go to bantam/IBS and never need c4 free at pick time.

Concurrency model:
  _classification_state tracks robot2's OWN in-flight movement (classify+route
  for whichever piece it's currently handling) and must reflect that alone —
  it gets overwritten every time robot2 starts/finishes a step, regardless of
  what else is going on. Bantam's "job finished, piece waiting for pickup"
  signal is therefore tracked SEPARATELY via fs._pending_bantam_piece, which
  survives robot2 handling an unrelated piece (e.g. a RED/GREEN piece going
  straight to C4) while bantam is still holding a finished BLUE piece.
  Mixing the two into one variable previously caused bantam pickups to be
  silently dropped whenever robot2 was mid-cycle on another piece when the
  bantam job completed.

  States that mean robot2 is physically moving (block a new robot2 command):
    _ROBOT2_BUSY_STATES

Entity cycles:
  robot2 / CLASSIFY_C2S2_TO_C4       — vision + move to C4 + return home
  robot2 / CLASSIFY_C2S2_TO_BANTAM   — vision + move to bantam bed
  robot2 / CLASSIFY_C2S2_TO_IBS      — vision + move to IBS
  robot2 / CLASSIFY_C2S2_TO_SCRAP    — vision + move to scrap
  robot2 / IBS_TO_BANTAM             — pick from IBS, place on bantam bed
  robot2 / BANTAM_TO_C4              — pick from bantam, place on C4, return home
  bantam / PROCESS_BLUE              — bantam CNC job
"""

import threading
import time

from shipyard_pnp.shared.contracts import MachineState, RobotState, SensorState

# _classification_state values where robot2 is physically moving.
# evaluate() must not start a new robot2 command when in these states.
_ROBOT2_BUSY_STATES = frozenset({
    "WAITING_VISION",
    "WAITING_ROBOT2_TO_C4",
    "WAITING_ROBOT2_TO_BANTAM",
    "WAITING_ROBOT2_TO_IBS",
    "WAITING_ROBOT2_TO_SCRAP",
    "WAITING_ROBOT2_IBS_TO_BANTAM",
    "WAITING_ROBOT2_BANTAM_TO_C4",
    "WAITING_ROBOT2_HOME",
})


def evaluate(fs) -> None:
    if fs._classification_state in _ROBOT2_BUSY_STATES:
        return
    if fs.state.get_robot("robot2") != RobotState.IDLE:
        return
    if fs.vendor_clients["niryo"].is_busy("robot2"):
        return

    # Priority 1 / 2 tie: piece waiting at C2S2 (classify+route) vs a
    # finished bantam piece waiting to be moved to C4. Both need c4 free, so
    # they're mutually exclusive at any given instant. Absolute rule when
    # BOTH are truly ready: classify always wins (a piece at C2S2 blocks
    # conveyor2 and everything upstream, so it's worse to leave it there).
    # When only ONE is ready, check whether the expected schedule wanted the
    # other one instead -- if so, give it up to MAP_GRACE_SEC to become
    # ready before falling back to whichever is actually available. c4 free
    # is checked either way; this never lets classify skip its own color-
    # safety check (see note below) or lets bantam retrieval start without c4.
    classify_ready = (
        fs.pieces.count("conveyor2") > 0
        and fs.state.get_sensor("c2s2") == SensorState.OCCUPIED
        and fs.state.get_sensor("c4") == SensorState.FREE
    )
    bantam_ready = (
        fs._pending_bantam_piece is not None
        and fs.state.get_sensor("c2s2") != SensorState.OCCUPIED
        and fs.state.get_sensor("c4") == SensorState.FREE
    )

    if classify_ready or bantam_ready:
        do_classify = None
        if classify_ready and bantam_ready:
            do_classify = True
        elif classify_ready:
            # If the map wants bantam retrieval next, give it up to
            # MAP_GRACE_SEC to actually finish and become ready, even if
            # nothing is pending yet -- waiting for a piece that hasn't
            # arrived/finished yet is exactly the case this exists for (the
            # plain reactive rule already covers "already pending, just
            # blocked on c2s2/c4" on its own, no map needed). If it doesn't
            # show up within the grace window, classify goes.
            expected = fs._map_next("robot2")
            wants_bantam = expected is not None and expected["task"] == "BANTAM_TO_C4"
            if wants_bantam and fs._map_should_wait("robot2"):
                do_classify = None
            else:
                do_classify = True
        else:  # bantam_ready only
            expected = fs._map_next("robot2")
            wants_classify = expected is not None and expected["task"].startswith("CLASSIFY_C2S2")
            if wants_classify and fs._map_should_wait("robot2"):
                do_classify = None
            else:
                do_classify = False

        if do_classify:
            # c4 must be free before starting: robot2's own local vision is
            # the only authority on this piece's real color (it may disagree
            # with whatever an earlier stage guessed), and _send_robot2_to_c4()
            # never re-checks c4 once that result comes back. Gating on a
            # pre-known/hinted color here would let a piece through unsafely
            # if that hint turns out to be wrong.
            #
            # The real route (-> C4 / BANTAM / IBS / SCRAP) isn't known until
            # vision resolves, so the map can't be told "this dispatch was
            # CLASSIFY_C2S2_TO_X" yet -- only that a dispatch decision was
            # made now (_map_begin_dispatch just closes out wait-timer
            # bookkeeping). The actual match against what the map expected
            # happens later in _on_vision_complete, once X is known -- see
            # factory_supervisor._map_resolve_dispatch.
            wait_info = fs._map_begin_dispatch("robot2")
            piece_id = fs.pieces.peek_first_piece_id("conveyor2")
            # Start robot2 entity cycle — first phase is vision at C2S2.
            fs.cycles.start_entity_cycle(
                "robot2", "CLASSIFY_C2S2",
                piece_id=piece_id,
                metadata={"pick_position": "C2S2"},
            )
            fs.cycles.add_phase("robot2", "VISION_C2S2")
            fs._classification_state = "WAITING_VISION"
            fs.send_command(
                "niryo",
                "robot2",
                "CAPTURE_LOCAL_VISION",
                piece_id=piece_id,
                source="C2S2",
                parameters={"position": "C2S2"},
                on_complete=_on_vision_complete(fs, piece_id, wait_info),
            )
            return
        elif do_classify is False:
            fs._map_note_dispatch("robot2", "BANTAM_TO_C4")
            _send_robot2_bantam_to_c4(fs, fs._pending_bantam_piece)
            return
        # else: do_classify is None -- within the grace window, wait (fall
        # through to Priority 3, which never competes for c4).

    # Priority 3: IBS drain — only when bantam is fully idle.
    if (
        fs._classification_state == "IDLE"
        and fs.pieces.count("intermediate_blue_stack") > 0
        and fs.state.get_machine("bantam") == MachineState.IDLE
        and not fs.vendor_clients["bantam"].is_busy()
    ):
        piece_id = fs.pieces.peek_first_piece_id("intermediate_blue_stack")
        fs._map_note_dispatch("robot2", "IBS_TO_BANTAM")
        _send_robot2_ibs_to_bantam(fs, piece_id)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _decide_route(fs, color: str) -> str:
    if color in {"RED", "GREEN"}:
        return "C4"
    if color == "BLUE":
        if (
            fs.state.get_machine("bantam") == MachineState.IDLE
            and not fs.vendor_clients["bantam"].is_busy()
        ):
            return "BANTAM"
        return "IBS"
    return "SCRAP"


def _restore_classification_state(fs) -> None:
    # Always resolves to WAITING_BANTAM/IDLE based on bantam's real status,
    # regardless of fs._pending_bantam_piece — Priority 2 checks that flag
    # independently and fires as soon as this leaves _ROBOT2_BUSY_STATES.
    if (
        fs.vendor_clients["bantam"].is_busy()
        or fs.state.get_machine("bantam") == MachineState.PREPARING
    ):
        fs._classification_state = "WAITING_BANTAM"
    else:
        fs._classification_state = "IDLE"


# ── Vision ───────────────────────────────────────────────────────────────────

def _on_vision_complete(fs, piece_id: str, wait_info: dict):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"Robot2 local vision failed: {result}")
            _discard_and_insert(fs, "robot2", "vision_failed")
            _restore_classification_state(fs)
            return

        color = result.get("color", "UNKNOWN")
        shape = result.get("shape", "UNKNOWN")
        fs.pieces.assign_color_shape("conveyor2", color, shape)
        route = _decide_route(fs, color)

        fs.db.insert_vision_detection(
            "robot2_camera",
            piece_id=piece_id,
            detected_color=color,
            detected_shape=shape,
            success=True,
        )

        fs.get_logger().info(
            f"[classification] vision piece={piece_id} color={color} shape={shape} "
            f"route={route} — c2s2_committed=True"
        )

        # Only now is the real route known -- confirm it against the map
        # (or log an off-map "intruder" cycle without consuming the map's
        # still-pending expectation) with full knowledge, instead of the
        # pre-vision generic match this used to do.
        task_name = f"CLASSIFY_C2S2_TO_{route}"
        fs._map_resolve_dispatch("robot2", task_name, wait_info)
        fs.cycles.update_entity_cycle(
            "robot2", task_name=task_name, color=color, route=route,
            **fs._map_pop_dispatch_metadata("robot2"),
        )

        if route == "C4":
            fs.cycles.add_phase("robot2", "MOVING_C2S2_TO_C4")
            _send_robot2_to_c4(fs, piece_id, color)
        elif route == "BANTAM":
            fs.cycles.add_phase("robot2", "MOVING_C2S2_TO_BANTAM")
            _send_robot2_to_bantam(fs, piece_id)
        elif route == "IBS":
            fs.cycles.add_phase("robot2", "MOVING_C2S2_TO_IBS")
            _send_robot2_to_ibs(fs, piece_id)
        else:
            fs.cycles.add_phase("robot2", "MOVING_C2S2_TO_SCRAP")
            _send_robot2_to_scrap(fs, piece_id, color, shape)

    return on_complete


# ── C2S2 → C4 ──────────────────────────────────────────────────────────────

def _send_robot2_to_c4(fs, piece_id: str, color: str) -> None:
    fs._classification_state = "WAITING_ROBOT2_TO_C4"
    fs.register_pick_source("robot2", "conveyor2")
    fs.register_place_target("robot2", "c4_location")
    fs.send_command(
        "niryo",
        "robot2",
        "MOVE_PIECE",
        piece_id=piece_id,
        source="C2S2",
        target="C4",
        route=color,
        parameters={"source": "C2S2", "target": "C4"},
        on_complete=_on_robot2_to_c4_complete(fs),
    )


def _on_robot2_to_c4_complete(fs):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"Robot2 move to C4 failed: {result}")
            _discard_and_insert(fs, "robot2", "move_to_c4_failed")
            _restore_classification_state(fs)
            return

        if not fs.consume_place_done_flag("robot2"):
            fs.pieces.transfer_via_gripper("robot2_gripper", "conveyor2", "c4_location")
        fs.state.update_sensor("c4", SensorState.OCCUPIED)
        fs._c4_deposit_time = time.time()

        piece_id = fs.pieces.peek_first_piece_id("c4_location")
        try:
            fs.send_command(
                "green_conveyors", "conveyor4", "RUN_CONVEYOR",
                piece_id=piece_id, source="C4_ENTRY", target="C4",
            )
            _schedule_conveyor_stop(fs, "conveyor4", piece_id, None, fs.c4_settle_sec)
        except Exception as exc:
            fs.get_logger().error(f"Failed to start conveyor4: {exc}")

        fs.cycles.add_phase("robot2", "RETURNING_HOME")
        fs._classification_state = "WAITING_ROBOT2_HOME"
        fs.send_command(
            "niryo", "robot2", "RETURN_HOME",
            on_complete=_on_robot2_home_complete(fs),
        )

    return on_complete


# ── C2S2 → BANTAM ──────────────────────────────────────────────────────────

def _send_robot2_to_bantam(fs, piece_id: str) -> None:
    fs._classification_state = "WAITING_ROBOT2_TO_BANTAM"
    fs.register_pick_source("robot2", "conveyor2")
    fs.register_place_target("robot2", "bantam_bed")
    fs.send_command(
        "niryo",
        "robot2",
        "MOVE_PIECE",
        piece_id=piece_id,
        source="C2S2",
        target="BANTAM_BED",
        route="BLUE",
        parameters={"source": "C2S2", "target": "BANTAM_BED"},
        on_complete=_on_robot2_to_bantam_complete(fs, piece_id),
    )


def _on_robot2_to_bantam_complete(fs, piece_id: str):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"Robot2 move to Bantam failed: {result}")
            _discard_and_insert(fs, "robot2", "move_to_bantam_failed")
            _restore_classification_state(fs)
            return

        fs.get_logger().info(
            f"[classification] robot2 placed at bantam — piece={piece_id} "
            f"sending bantam RUN_JOB now"
        )
        if not fs.consume_place_done_flag("robot2"):
            fs.pieces.transfer_via_gripper("robot2_gripper", "conveyor2", "bantam_bed")
        fs.state.update_robot("robot2", RobotState.IDLE)
        fs.state.update_machine("bantam", MachineState.PREPARING)

        # Robot2 stays near bantam — cycle ends at place (no home command).
        _complete_and_insert(fs, "robot2")
        _send_bantam_job(fs, piece_id)

    return on_complete


# ── C2S2 → IBS (bantam busy) ───────────────────────────────────────────────

def _send_robot2_to_ibs(fs, piece_id: str) -> None:
    fs.get_logger().info(
        f"[classification] bantam busy — parking piece={piece_id} at IBS"
    )
    fs._classification_state = "WAITING_ROBOT2_TO_IBS"
    fs.register_pick_source("robot2", "conveyor2")
    fs.register_place_target("robot2", "intermediate_blue_stack")
    fs.send_command(
        "niryo",
        "robot2",
        "MOVE_PIECE",
        piece_id=piece_id,
        source="C2S2",
        target="IBS_BED",
        route="BLUE",
        parameters={"source": "C2S2", "target": "IBS_BED"},
        on_complete=_on_robot2_to_ibs_complete(fs, piece_id),
    )


def _on_robot2_to_ibs_complete(fs, piece_id: str):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"Robot2 move to IBS failed: {result}")
            _discard_and_insert(fs, "robot2", "move_to_ibs_failed")
            _restore_classification_state(fs)
            return

        if not fs.consume_place_done_flag("robot2"):
            fs.pieces.transfer_via_gripper("robot2_gripper", "conveyor2", "intermediate_blue_stack")
        fs.state.update_robot("robot2", RobotState.IDLE)
        fs.get_logger().info(
            f"[classification] piece={piece_id} parked at IBS "
            f"(total IBS={fs.pieces.count('intermediate_blue_stack')})"
        )
        # No home command — cycle ends at place.
        _complete_and_insert(fs, "robot2")
        _restore_classification_state(fs)

    return on_complete


# ── IBS → BANTAM (drain) ───────────────────────────────────────────────────

def _send_robot2_ibs_to_bantam(fs, piece_id: str) -> None:
    fs.get_logger().info(
        f"[classification] draining IBS → BANTAM: piece={piece_id} "
        f"(IBS remaining={fs.pieces.count('intermediate_blue_stack')})"
    )
    fs.cycles.start_entity_cycle(
        "robot2", "IBS_TO_BANTAM",
        piece_id=piece_id, color="BLUE", route="BLUE",
        metadata=fs._map_pop_dispatch_metadata("robot2"),
    )
    fs.cycles.add_phase("robot2", "MOVING_IBS_TO_BANTAM")

    fs._classification_state = "WAITING_ROBOT2_IBS_TO_BANTAM"
    fs.register_pick_source("robot2", "intermediate_blue_stack")
    fs.register_place_target("robot2", "bantam_bed")
    fs.send_command(
        "niryo",
        "robot2",
        "MOVE_PIECE",
        piece_id=piece_id,
        source="IBS_BED",
        target="BANTAM_BED",
        route="BLUE",
        parameters={"source": "IBS_BED", "target": "BANTAM_BED"},
        on_complete=_on_robot2_ibs_to_bantam_complete(fs, piece_id),
    )


def _on_robot2_ibs_to_bantam_complete(fs, piece_id: str):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"Robot2 IBS→bantam failed: {result}")
            _discard_and_insert(fs, "robot2", "ibs_to_bantam_failed")
            _restore_classification_state(fs)
            return

        fs.get_logger().info(
            f"[classification] robot2 IBS→bantam place done — piece={piece_id} "
            f"sending bantam RUN_JOB now"
        )
        if not fs.consume_place_done_flag("robot2"):
            fs.pieces.transfer_via_gripper("robot2_gripper", "intermediate_blue_stack", "bantam_bed")
        fs.state.update_robot("robot2", RobotState.IDLE)
        fs.state.update_machine("bantam", MachineState.PREPARING)

        _complete_and_insert(fs, "robot2")
        _send_bantam_job(fs, piece_id)

    return on_complete


# ── Bantam job ──────────────────────────────────────────────────────────────

def _send_bantam_job(fs, piece_id: str) -> None:
    fs.get_logger().info(f"[bantam] RUN_JOB sending piece={piece_id}")
    fs.cycles.start_entity_cycle(
        "bantam", "PROCESS_BLUE",
        piece_id=piece_id, color="BLUE", route="BLUE",
    )
    fs.cycles.add_phase("bantam", "PROCESSING")

    fs._classification_state = "WAITING_BANTAM"
    fs.send_command(
        "bantam",
        "bantam",
        "RUN_JOB",
        piece_id=piece_id,
        source="BANTAM_BED",
        target="BANTAM_BED",
        route="BLUE",
        parameters={"job_type": "BLUE_PROCESS"},
        on_complete=_on_bantam_complete(fs, piece_id),
    )


def _on_bantam_complete(fs, piece_id: str):
    def on_complete(task_state: str, result: dict) -> None:
        try:
            if task_state != "COMPLETED":
                fs.get_logger().error(
                    f"[classification] bantam RUN_JOB ended with {task_state}: {result}"
                )
                _discard_and_insert(fs, "bantam", "bantam_job_failed")
                _restore_classification_state(fs)
                return

            fs.state.update_machine("bantam", MachineState.FINISHED)
            _complete_and_insert(fs, "bantam")

            # fs._pending_bantam_piece alone drives Priority 2 — deliberately
            # NOT touching fs._classification_state here, since robot2 may
            # currently be mid-cycle on an unrelated piece (e.g. RED/GREEN
            # direct to C4); overwriting it would erase that tracking and
            # strand this piece unretrieved once robot2 finishes the other one.
            fs.get_logger().info(
                f"[classification] bantam COMPLETE piece={piece_id} "
                f"robot2={fs.state.get_robot('robot2').name} "
                f"robot2_busy={fs.vendor_clients['niryo'].is_busy('robot2')} "
                f"→ pending pickup"
            )
            fs._pending_bantam_piece = piece_id
        except Exception as exc:
            fs.get_logger().error(
                f"[classification] _on_bantam_complete raised: {exc}"
            )

    return on_complete


# ── BANTAM → C4 ────────────────────────────────────────────────────────────

def _send_robot2_bantam_to_c4(fs, piece_id: str) -> None:
    fs.get_logger().info(f"[classification] robot2 BANTAM→C4 piece={piece_id}")
    fs.cycles.start_entity_cycle(
        "robot2", "BANTAM_TO_C4",
        piece_id=piece_id, color="BLUE", route="BLUE",
        metadata=fs._map_pop_dispatch_metadata("robot2"),
    )
    fs.cycles.add_phase("robot2", "MOVING_BANTAM_TO_C4")

    fs._pending_bantam_piece = None
    fs._classification_state = "WAITING_ROBOT2_BANTAM_TO_C4"
    fs.register_pick_source("robot2", "bantam_bed")
    fs.register_place_target("robot2", "c4_location")
    fs.send_command(
        "niryo",
        "robot2",
        "MOVE_PIECE",
        piece_id=piece_id,
        source="BANTAM_BED",
        target="C4",
        route="BLUE",
        parameters={"source": "BANTAM_BED", "target": "C4"},
        on_complete=_on_robot2_bantam_to_c4_complete(fs),
    )


def _on_robot2_bantam_to_c4_complete(fs):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"Robot2 Bantam→C4 failed: {result}")
            _discard_and_insert(fs, "robot2", "bantam_to_c4_failed")
            fs._classification_state = "IDLE"
            return

        if not fs.consume_place_done_flag("robot2"):
            fs.pieces.transfer_via_gripper("robot2_gripper", "bantam_bed", "c4_location")
        fs.state.update_machine("bantam", MachineState.IDLE)
        fs.state.update_sensor("c4", SensorState.OCCUPIED)
        fs._c4_deposit_time = time.time()

        piece_id = fs.pieces.peek_first_piece_id("c4_location")
        try:
            fs.send_command(
                "green_conveyors", "conveyor4", "RUN_CONVEYOR",
                piece_id=piece_id, source="C4_ENTRY", target="C4",
            )
            _schedule_conveyor_stop(fs, "conveyor4", piece_id, None, fs.c4_settle_sec)
        except Exception as exc:
            fs.get_logger().error(f"Failed to start conveyor4 (bantam path): {exc}")

        fs.cycles.add_phase("robot2", "RETURNING_HOME")
        fs._classification_state = "WAITING_ROBOT2_HOME"
        fs.send_command(
            "niryo", "robot2", "RETURN_HOME",
            on_complete=_on_robot2_home_complete(fs),
        )

    return on_complete


# ── C2S2 → SCRAP ───────────────────────────────────────────────────────────

def _send_robot2_to_scrap(fs, piece_id: str, color: str, shape: str) -> None:
    fs.get_logger().warning(
        f"[classification] SCRAP piece={piece_id} color={color} shape={shape}"
    )
    fs._classification_state = "WAITING_ROBOT2_TO_SCRAP"
    fs.register_pick_source("robot2", "conveyor2")
    fs.register_place_target("robot2", "robot2_scrap")
    fs.send_command(
        "niryo",
        "robot2",
        "MOVE_PIECE",
        piece_id=piece_id,
        source="C2S2",
        target="SCRAP",
        route="SCRAP",
        parameters={"source": "C2S2", "target": "SCRAP"},
        on_complete=_on_robot2_to_scrap_complete(fs, piece_id, color, shape),
    )


def _on_robot2_to_scrap_complete(fs, piece_id: str, color: str, shape: str):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"Robot2 scrap move failed: {result}")
            _discard_and_insert(fs, "robot2", "move_to_scrap_failed")
            _restore_classification_state(fs)
            return

        if not fs.consume_place_done_flag("robot2"):
            fs.pieces.transfer_via_gripper("robot2_gripper", "conveyor2", "robot2_scrap")
        fs.state.update_robot("robot2", RobotState.IDLE)

        # Piece-level cycle ends here (scrap = completed, route=SCRAP).
        record = fs.cycles.complete_cycle(piece_id, color, shape, "SCRAP",
                                          final_location="robot2_scrap")
        if record is not None:
            fs.db.insert_cycle_complete(record)

        # Entity-level cycle also ends here (no home command for scrap).
        _complete_and_insert(fs, "robot2")
        _restore_classification_state(fs)

    return on_complete


# ── Shared home callback ────────────────────────────────────────────────────

def _on_robot2_home_complete(fs):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().warning(f"Robot2 return home ended with {task_state}")
        fs.state.update_robot("robot2", RobotState.IDLE)
        # Complete whichever robot2 cycle is active (C2S2→C4 or BANTAM→C4).
        _complete_and_insert(fs, "robot2")
        _restore_classification_state(fs)

    return on_complete


# ── Conveyor stop helper ────────────────────────────────────────────────────

def _schedule_conveyor_stop(fs, conveyor_id: str, piece_id, route, delay_sec: float) -> None:
    # green_conveyors is a single shared-Arduino domain (concurrent_resources=
    # False) -- conveyor3 and conveyor4 commands compete for the one pending
    # slot, so this stop can be rejected while the other conveyor's RUN/STOP
    # is still in flight. Retry with a short backoff instead of dropping the
    # stop silently (a swallowed stop leaves the conveyor running past its
    # intended point).
    def _stop(attempt=0):
        try:
            fs.send_command(
                "green_conveyors", conveyor_id, "STOP_CONVEYOR",
                piece_id=piece_id, route=route,
            )
        except Exception as exc:
            if attempt >= 10:
                fs.get_logger().error(
                    f"Auto-stop {conveyor_id} failed after {attempt} retries: {exc} — giving up"
                )
                return
            fs.get_logger().warning(
                f"Auto-stop {conveyor_id} failed (retry {attempt + 1}/10): {exc}"
            )
            t_retry = threading.Timer(0.5, _stop, args=(attempt + 1,))
            t_retry.daemon = True
            t_retry.start()
    t = threading.Timer(delay_sec, _stop)
    t.daemon = True
    t.start()


# ── DB helpers ───────────────────────────────────────────────────────────────

def _complete_and_insert(fs, entity: str) -> None:
    cycle = fs.cycles.complete_entity_cycle(entity)
    if cycle:
        fs.db.insert_entity_cycle(cycle)


def _discard_and_insert(fs, entity: str, reason: str) -> None:
    cycle = fs.cycles.discard_entity_cycle(entity, reason)
    if cycle:
        fs.db.insert_entity_cycle(cycle)
