"""
Coordinates robot1 and the Arduino vacuum for final unloading.

The arm and vacuum are separate vendor domains, so every pick/place is
serialized by the Factory Supervisor.
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
    if fs.state.get_sensor("c4") == SensorState.OCCUPIED:
        location = "c4_location"
        sensor_id = "c4"
        pick_position = "C4"
        elapsed = time.time() - fs._c4_deposit_time
        if elapsed < fs.c4_settle_sec:
            return None  # Wait for piece to reach pick position
    elif fs.state.get_sensor("c3") == SensorState.OCCUPIED:
        location = "c3_location"
        sensor_id = "c3"
        pick_position = "C3"
        elapsed = time.time() - fs._c3_deposit_time
        if elapsed < fs.c3_settle_sec:
            return None  # Wait for piece to reach pick position
    else:
        return None

    piece = fs.pieces.peek_first_piece(location)
    if piece is None:
        fs.state.update_sensor(sensor_id, SensorState.FREE)
        return None

    color = piece.get("color") or "UNKNOWN"
    shape = piece.get("shape") or "UNKNOWN"
    final_location, final_target = _final_destination(color, shape)
    return {
        "piece_id": piece["id"],
        "color": color,
        "shape": shape,
        "source_location": location,
        "sensor_id": sensor_id,
        "pick_position": pick_position,
        "final_location": final_location,
        "final_target": final_target,
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
            fs._unloading_state = "IDLE"
            return

        # Use robot1's local vision result to get the real shape/color.
        actual_color = result.get("color") or context["color"]
        actual_shape = result.get("shape") or context["shape"]
        confidence = result.get("confidence", "?")
        confidence_score = result.get("confidence_score", "?")
        fs.get_logger().info(
            f"[ML] piece={context['piece_id']} pos={context['pick_position']} "
            f"color={actual_color} shape={actual_shape} "
            f"conf={confidence} score={confidence_score}"
        )
        fs.pieces.assign_color_shape(context["source_location"], actual_color, actual_shape)

        final_location, final_target = _final_destination(actual_color, actual_shape)
        updated_context = dict(context)
        updated_context["color"] = actual_color
        updated_context["shape"] = actual_shape
        updated_context["final_location"] = final_location
        updated_context["final_target"] = final_target
        if actual_color in {"RED", "GREEN", "BLUE"}:
            updated_context["route"] = actual_color

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
            fs._unloading_state = "IDLE"
            return

        fs.state.update_vacuum("arduino_vacuum", VacuumState.PICK_DONE)
        # C3/C4 is physically free the moment the vacuum lifts the piece.
        # Freeing the sensor here lets xArm2 start the next GREEN piece immediately.
        fs.state.update_sensor(context["sensor_id"], SensorState.FREE)

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
            fs._unloading_state = "IDLE"
            return

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
            fs._unloading_state = "IDLE"
            return

        fs.pieces.transfer_piece(context["source_location"], context["final_location"])
        fs.state.update_vacuum("arduino_vacuum", VacuumState.RELEASE_DONE)

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
        record = fs.cycles.complete_cycle(
            context["piece_id"],
            context["color"],
            context["shape"],
            context["route"],
        )
        if record is not None:
            fs.db.insert_cycle_complete(record)
        fs._unloading_state = "IDLE"

    return on_complete
