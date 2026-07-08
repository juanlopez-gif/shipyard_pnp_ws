"""
Coordinates robot1 and the Arduino vacuum for final unloading.

The arm and vacuum are separate vendor domains, so every pick/place is
serialized by the Factory Supervisor.

Entity cycles:
  robot1 / UNLOAD_C4  — classify+pick from C4, vacuum, lift+place, release, home
  robot1 / UNLOAD_C3  — classify+pick from C3, vacuum, lift+place, release, home
  Phases: VISION_C3/C4 → MOVING_C3/C4_TO_FINAL_* →
          VACUUM_PICK → LIFT_AND_PLACE → VACUUM_RELEASE → RETURNING_HOME
"""

import time

from shipyard_pnp.shared.contracts import RobotState, SensorState, VacuumState


def evaluate(fs) -> None:
    if fs._unloading_state != "IDLE":
        return
    if fs.state.get_robot("robot1") != RobotState.IDLE:
        return
    if fs.vendor_clients["niryo"].is_busy("robot1"):
        return
    if fs.vendor_clients["arduino_vacuum"].is_busy():
        return

    context = _next_pick_context(fs)
    if context is None:
        return

    # Start robot1 entity cycle — task name includes the source position.
    task_name = f"UNLOAD_{context['pick_position']}"  # UNLOAD_C4 or UNLOAD_C3
    metadata = {
        "pick_position":  context["pick_position"],
        "expected_color": context["color"],
        "expected_shape": context["shape"],
        "expected_final_target": context["final_target"],
    }
    metadata.update(fs._map_pop_dispatch_metadata("robot1"))
    fs.cycles.start_entity_cycle(
        "robot1", task_name,
        piece_id=context["piece_id"],
        metadata=metadata,
    )
    fs.cycles.add_phase("robot1", f"VISION_{context['pick_position']}")

    fs._unloading_state = "WAITING_CLASSIFY_PICK"
    fs.send_command(
        "niryo",
        "robot1",
        "CLASSIFY_AND_PICK",
        piece_id=context["piece_id"],
        source=context["pick_position"],
        target=context["final_target"],
        route=context["route"],
        parameters={"position": context["pick_position"]},
        on_complete=_on_classify_pick_complete(fs, context),
    )


def _next_pick_context(fs) -> dict:
    # Whichever of C3/C4 finished settling FIRST wins -- matches the SimPy
    # model (system.c4_finish_time <= system.c3_finish_time), which is the
    # validated reference behavior. This replaces the old unconditional
    # "C4 always wins" if/elif, which picked C4 even when C3 had been
    # ready and waiting longer, and caused a confirmed C3/C4 unload-order
    # mismatch against the simulator.
    c4_occupied = fs.state.get_sensor("c4") == SensorState.OCCUPIED
    c3_occupied = fs.state.get_sensor("c3") == SensorState.OCCUPIED
    now = time.time()

    c4_ready_at = fs._c4_deposit_time + fs.c4_settle_sec if c4_occupied else None
    c3_ready_at = fs._c3_deposit_time + fs.c3_settle_sec if c3_occupied else None
    c4_ready = c4_occupied and now >= c4_ready_at
    c3_ready = c3_occupied and now >= c3_ready_at

    if not c4_ready and not c3_ready:
        return None

    # If the expected schedule's pick is ALREADY physically ready, take it
    # immediately -- no reason to consult the settle-time tie rule at all,
    # and critically this is what resolves a wait: once the awaited option
    # becomes ready, it must win outright, not get re-litigated against
    # whichever one merely settled earliest.
    expected = fs._map_next("robot1")
    wants_c3 = expected is not None and expected["task"] == "UNLOAD_C3"
    wants_c4 = expected is not None and expected["task"] == "UNLOAD_C4"

    if c3_ready and wants_c3:
        go_c4 = False
    elif c4_ready and wants_c4:
        go_c4 = True
    elif c4_ready and c3_ready:
        # Both ready, map has no opinion (or none confirmed yet) -- fall
        # back to the plain settle-time tie rule.
        go_c4 = c4_ready_at <= c3_ready_at
    elif c4_ready:
        # Only c4 ready. If the map wants c3 next, give it up to
        # MAP_GRACE_SEC to actually show up and become ready before falling
        # back to c4 -- deliberately not conditioned on c3 already having a
        # piece on it: waiting for a piece that hasn't even arrived yet is
        # exactly the case this exists for (the plain reactive rule already
        # covers "something is already sitting there settling" on its own,
        # no map needed). Physical readiness is still the only thing that
        # can ever trigger an action; this can only delay, never skip, a
        # precondition check -- if c3 never shows up within the grace
        # window, c4 goes.
        if wants_c3 and fs._map_should_wait("robot1"):
            return None
        go_c4 = True
    else:
        if wants_c4 and fs._map_should_wait("robot1"):
            return None
        go_c4 = False

    if go_c4:
        location      = "c4_location"
        sensor_id     = "c4"
        pick_position = "C4"
    else:
        location      = "c3_location"
        sensor_id     = "c3"
        pick_position = "C3"

    piece = fs.pieces.peek_first_piece(location)
    if piece is None:
        fs.state.update_sensor(sensor_id, SensorState.FREE)
        return None

    fs._map_note_dispatch("robot1", "UNLOAD_C4" if go_c4 else "UNLOAD_C3")

    color = piece.get("color") or "UNKNOWN"
    shape = piece.get("shape") or "UNKNOWN"
    final_location, final_target = _final_destination(color, shape)
    return {
        "piece_id":        piece["id"],
        "color":           color,
        "shape":           shape,
        "source_location": location,
        "sensor_id":       sensor_id,
        "pick_position":   pick_position,
        "final_location":  final_location,
        "final_target":    final_target,
        "route": color if color in {"RED", "GREEN", "BLUE"} else "SCRAP",
    }


def _final_destination(color: str, shape: str = "UNKNOWN") -> tuple:
    is_circle = shape == "CIRCLE"
    if color == "RED":
        if is_circle:
            return "final_red_circle", "FINAL_RED_CIRCLE"
        return "final_red_stack", "FINAL_RED_STACK"
    if color == "GREEN":
        if is_circle:
            return "final_green_circle", "FINAL_GREEN_CIRCLE"
        return "final_green_stack", "FINAL_GREEN_STACK"
    if color == "BLUE":
        if is_circle:
            return "final_blue_circle", "FINAL_BLUE_CIRCLE"
        return "final_blue_stack", "FINAL_BLUE_STACK"
    return "robot1_scrap", "SCRAP"


def _on_classify_pick_complete(fs, context: dict):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"Robot1 classify and pick failed: {result}")
            _discard_and_insert(fs, "robot1", "classify_pick_failed")
            fs._unloading_state = "IDLE"
            return

        # Use robot1's local vision result to update color/shape.
        actual_color  = result.get("color")  or context["color"]
        actual_shape  = result.get("shape")  or context["shape"]
        confidence    = result.get("confidence",       "?")
        confidence_score = result.get("confidence_score", "?")
        fs.get_logger().info(
            f"[ML] piece={context['piece_id']} pos={context['pick_position']} "
            f"color={actual_color} shape={actual_shape} "
            f"conf={confidence} score={confidence_score}"
        )
        fs.pieces.assign_color_shape(context["source_location"], actual_color, actual_shape)

        final_location, final_target = _final_destination(actual_color, actual_shape)
        updated_context = dict(context)
        updated_context["color"]          = actual_color
        updated_context["shape"]          = actual_shape
        updated_context["final_location"] = final_location
        updated_context["final_target"]   = final_target
        if actual_color in {"RED", "GREEN", "BLUE"}:
            updated_context["route"] = actual_color

        fs.db.insert_vision_detection(
            "robot1_camera",
            piece_id=context["piece_id"],
            detected_color=actual_color,
            detected_shape=actual_shape,
            success=True,
        )

        # Update entity cycle with confirmed color/route from vision.
        fs.cycles.update_entity_cycle(
            "robot1",
            color=actual_color,
            route=updated_context["route"],
            final_target=final_target,
        )
        _sync_robot1_moving_phase_target(fs, updated_context)
        fs.cycles.add_phase("robot1", "VACUUM_PICK")

        fs._unloading_state = "WAITING_VACUUM_PICK"
        fs.send_command(
            "arduino_vacuum",
            "arduino_vacuum",
            "PICK",
            piece_id=updated_context["piece_id"],
            source=updated_context["pick_position"],
            target=updated_context["final_target"],
            route=updated_context["route"],
            on_complete=_on_vacuum_pick_complete(fs, updated_context),
        )

    return on_complete


def _on_vacuum_pick_complete(fs, context: dict):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"Vacuum pick failed: {result}")
            _discard_and_insert(fs, "robot1", "vacuum_pick_failed")
            fs._unloading_state = "IDLE"
            return

        fs.state.update_vacuum("arduino_vacuum", VacuumState.PICK_DONE)
        fs.state.update_sensor(context["sensor_id"], SensorState.FREE)
        # Vacuum PICK just completed -- the piece is physically off
        # C3/C4 now (into the gripper), even though LIFT_AND_PLACE +
        # RELEASE + RETURN_HOME are still ahead. Move it out of EXPECTED
        # here instead of waiting for _on_vacuum_release_complete below.
        fs.pieces.transfer_piece(context["source_location"], "robot1_gripper")
        fs.cycles.add_phase("robot1", "LIFT_AND_PLACE")

        fs._unloading_state = "WAITING_LIFT_PLACE"
        fs.send_command(
            "niryo",
            "robot1",
            "LIFT_AND_PLACE",
            piece_id=context["piece_id"],
            source=context["pick_position"],
            target=context["final_target"],
            route=context["route"],
            parameters={"target": context["final_target"]},
            on_complete=_on_lift_place_complete(fs, context),
        )

    return on_complete


def _on_lift_place_complete(fs, context: dict):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"Robot1 lift/place failed: {result}")
            _discard_and_insert(fs, "robot1", "lift_place_failed")
            fs._unloading_state = "IDLE"
            return

        fs.cycles.add_phase("robot1", "VACUUM_RELEASE")
        fs._unloading_state = "WAITING_VACUUM_RELEASE"
        fs.send_command(
            "arduino_vacuum",
            "arduino_vacuum",
            "RELEASE",
            piece_id=context["piece_id"],
            source=context["pick_position"],
            target=context["final_target"],
            route=context["route"],
            on_complete=_on_vacuum_release_complete(fs, context),
        )

    return on_complete


def _on_vacuum_release_complete(fs, context: dict):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"Vacuum release failed: {result}")
            _discard_and_insert(fs, "robot1", "vacuum_release_failed")
            fs._unloading_state = "IDLE"
            return

        fs.pieces.transfer_via_gripper("robot1_gripper", context["source_location"], context["final_location"])
        fs.state.update_vacuum("arduino_vacuum", VacuumState.RELEASE_DONE)
        fs.cycles.add_phase("robot1", "RETURNING_HOME")

        fs._unloading_state = "WAITING_HOME"
        fs.send_command(
            "niryo",
            "robot1",
            "RETURN_HOME",
            piece_id=context["piece_id"],
            route=context["route"],
            on_complete=_on_return_home_complete(fs, context),
        )

    return on_complete


def _on_return_home_complete(fs, context: dict):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().warning(f"Robot1 return home ended with {task_state}: {result}")

        fs.state.update_robot("robot1", RobotState.IDLE)

        # Piece-level cycle complete.
        record = fs.cycles.complete_cycle(
            context["piece_id"],
            context["color"],
            context["shape"],
            context["route"],
            final_location=context["final_location"],
        )
        if record is not None:
            fs.db.insert_cycle_complete(record)

        # Entity-level cycle complete.
        cycle = fs.cycles.complete_entity_cycle(
            "robot1",
            color=context["color"],
            route=context["route"],
        )
        if cycle is not None:
            cycle.metadata["final_location"] = context["final_location"]
            cycle.metadata["final_target"]   = context["final_target"]
            fs.db.insert_entity_cycle(cycle)

        fs._unloading_state = "IDLE"

    return on_complete


# ── DB helpers ───────────────────────────────────────────────────────────────

def sync_robot1_vision_phase(fs, previous_state: str, current_state: str) -> None:
    """Mirror robot1's internal vision state in cycle_event phases."""
    if previous_state == current_state:
        return

    cycle = fs.cycles.get_active_entity_cycle("robot1")
    if cycle is None or not cycle.task_name.startswith("UNLOAD_"):
        return

    pick_position = cycle.metadata.get("pick_position")
    if pick_position not in {"C3", "C4"}:
        return

    current_phase = cycle.phases[-1].name if cycle.phases else None
    vision_phase = f"VISION_{pick_position}"

    if current_state == RobotState.WAITING_FOR_VISION.value:
        if current_phase != vision_phase:
            fs.cycles.add_phase("robot1", vision_phase)
        return

    if previous_state == RobotState.WAITING_FOR_VISION.value:
        if current_phase == vision_phase:
            target = (
                cycle.metadata.get("final_target")
                or cycle.metadata.get("expected_final_target")
                or "FINAL"
            )
            fs.cycles.add_phase("robot1", f"MOVING_{pick_position}_TO_{target}")


def _sync_robot1_moving_phase_target(fs, context: dict) -> None:
    cycle = fs.cycles.get_active_entity_cycle("robot1")
    if cycle is None:
        return

    pick_position = cycle.metadata.get("pick_position")
    current_phase = cycle.phases[-1].name if cycle.phases else ""
    prefix = f"MOVING_{pick_position}_TO_"
    if pick_position in {"C3", "C4"} and current_phase.startswith(prefix):
        fs.cycles.rename_active_phase(
            "robot1",
            f"MOVING_{pick_position}_TO_{context['final_target']}",
        )


def _discard_and_insert(fs, entity: str, reason: str) -> None:
    cycle = fs.cycles.discard_entity_cycle(entity, reason)
    if cycle:
        fs.db.insert_entity_cycle(cycle)
