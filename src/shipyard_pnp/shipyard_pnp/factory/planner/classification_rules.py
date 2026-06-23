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
  _classification_state tracks the bantam pipeline state. Robot2's concurrent
  sub-movements (classify+route while bantam runs) are tracked via the hardware
  state (is_busy / get_robot). Both can advance independently.

  States that mean robot2 is physically moving (block a new robot2 command):
    _ROBOT2_BUSY_STATES

  States compatible with robot2 being idle (bantam running, waiting for result):
    "WAITING_BANTAM", "BANTAM_DONE_WAITING_PICKUP"
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

# State set by _on_bantam_complete to signal "bantam done, send robot2 to bantam→c4
# as soon as robot2 is free". NOT in _ROBOT2_BUSY_STATES — evaluate() must be able
# to enter and dispatch robot2 from this state.
_STATE_BANTAM_DONE = "BANTAM_DONE_WAITING_PICKUP"


def evaluate(fs) -> None:
    if fs._classification_state in _ROBOT2_BUSY_STATES:
        return
    if fs.state.get_robot("robot2") != RobotState.IDLE:
        return
    if fs.vendor_clients["niryo"].is_busy("robot2"):
        return

    # Priority 1: bantam finished — pick processed piece bantam → c4.
    # _on_bantam_complete always sets this state; evaluate() dispatches robot2
    # here as soon as robot2 is free AND c4 is free.
    # Without the c4 guard, robot2 deposits on top of a piece that robot1 is still
    # transporting, and robot1's vacuum_pick FREE-s the sensor for the wrong piece.
    if (
        fs._classification_state == _STATE_BANTAM_DONE
        and fs._pending_bantam_piece is not None
    ):
        if fs.state.get_sensor("c4") != SensorState.FREE:
            return  # c4 busy — wait for robot1 to clear before depositing from bantam
        _send_robot2_bantam_to_c4(fs, fs._pending_bantam_piece)
        return

    # Priority 2: piece waiting at C2S2 — classify and route.
    # Runs even while WAITING_BANTAM (robot2 is free during bantam processing).
    if (
        fs.pieces.count("conveyor2") > 0
        and fs.state.get_sensor("c2s2") == SensorState.OCCUPIED
    ):
        # BLUE goes to bantam/IBS — does NOT need c4 free at pick time.
        # RED/GREEN and unknown pieces go to c4 — require it free before picking.
        known_color = fs.pieces.peek_first_piece_color("conveyor2")
        c4_needed = known_color != "BLUE"
        if c4_needed and fs.state.get_sensor("c4") != SensorState.FREE:
            # c4 occupied and piece might go there — wait
            pass
        else:
            piece_id = fs.pieces.peek_first_piece_id("conveyor2")
            fs._classification_state = "WAITING_VISION"
            fs.send_command(
                "niryo",
                "robot2",
                "CAPTURE_LOCAL_VISION",
                piece_id=piece_id,
                source="C2S2",
                parameters={"position": "C2S2"},
                on_complete=_on_vision_complete(fs, piece_id),
            )
            return

    # Priority 3: IBS drain — only when bantam is fully idle (not running a job).
    # c4 state does not matter here: piece goes bantam→c4 AFTER bantam finishes.
    if (
        fs._classification_state == "IDLE"
        and fs.pieces.count("intermediate_blue_stack") > 0
        and fs.state.get_machine("bantam") == MachineState.IDLE
        and not fs.vendor_clients["bantam"].is_busy()
    ):
        piece_id = fs.pieces.peek_first_piece_id("intermediate_blue_stack")
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
        return "IBS"  # bantam busy — park in intermediate blue stack
    return "SCRAP"


def _restore_classification_state(fs) -> None:
    """
    After robot2 finishes a sub-move, restore _classification_state to the
    correct background state:
      - BANTAM_DONE_WAITING_PICKUP  → keep it; evaluate() handles the pickup
      - bantam job still running    → WAITING_BANTAM
      - otherwise                   → IDLE
    """
    if fs._classification_state == _STATE_BANTAM_DONE:
        return  # evaluate() will dispatch BANTAM→C4 when robot2 is free
    if (
        fs.vendor_clients["bantam"].is_busy()
        or fs.state.get_machine("bantam") == MachineState.PREPARING
    ):
        fs._classification_state = "WAITING_BANTAM"
    else:
        fs._classification_state = "IDLE"


# ── Vision ───────────────────────────────────────────────────────────────────

def _on_vision_complete(fs, piece_id: str):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(f"Robot2 local vision failed: {result}")
            _restore_classification_state(fs)
            return

        color = result.get("color", "UNKNOWN")
        shape = result.get("shape", "UNKNOWN")
        fs.pieces.assign_color_shape("conveyor2", color, shape)
        # Robot2 is committed to picking from C2S2 — conveyor2 can start without
        # waiting for the physical c2s2 sensor to go FREE.
        fs._c2s2_committed = True
        route = _decide_route(fs, color)
        fs.get_logger().info(
            f"[classification] vision piece={piece_id} color={color} shape={shape} "
            f"route={route} — c2s2_committed=True"
        )
        if route == "C4":
            _send_robot2_to_c4(fs, piece_id, color)
        elif route == "BANTAM":
            _send_robot2_to_bantam(fs, piece_id)
        elif route == "IBS":
            _send_robot2_to_ibs(fs, piece_id)
        else:
            _send_robot2_to_scrap(fs, piece_id, color, shape)

    return on_complete


# ── C2S2 → C4 ──────────────────────────────────────────────────────────────

def _send_robot2_to_c4(fs, piece_id: str, color: str) -> None:
    fs._classification_state = "WAITING_ROBOT2_TO_C4"
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
            _restore_classification_state(fs)
            return

        fs.pieces.transfer_piece("conveyor2", "c4_location")
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

        fs._classification_state = "WAITING_ROBOT2_HOME"
        fs.send_command(
            "niryo", "robot2", "RETURN_HOME",
            on_complete=_on_robot2_home_complete(fs),
        )

    return on_complete


# ── C2S2 → BANTAM ──────────────────────────────────────────────────────────

def _send_robot2_to_bantam(fs, piece_id: str) -> None:
    fs._classification_state = "WAITING_ROBOT2_TO_BANTAM"
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
            _restore_classification_state(fs)
            return

        fs.get_logger().info(
            f"[classification] robot2 HOME after bantam place — piece={piece_id} "
            f"sending bantam RUN_JOB now"
        )
        fs.pieces.transfer_piece("conveyor2", "bantam_bed")
        fs.state.update_robot("robot2", RobotState.IDLE)
        fs.state.update_machine("bantam", MachineState.PREPARING)
        _send_bantam_job(fs, piece_id)

    return on_complete


# ── C2S2 → IBS (bantam busy) ───────────────────────────────────────────────

def _send_robot2_to_ibs(fs, piece_id: str) -> None:
    fs.get_logger().info(
        f"[classification] bantam busy — parking piece={piece_id} at IBS"
    )
    fs._classification_state = "WAITING_ROBOT2_TO_IBS"
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
            _restore_classification_state(fs)
            return

        fs.pieces.transfer_piece("conveyor2", "intermediate_blue_stack")
        fs.state.update_robot("robot2", RobotState.IDLE)
        fs.get_logger().info(
            f"[classification] piece={piece_id} parked at IBS "
            f"(total IBS={fs.pieces.count('intermediate_blue_stack')})"
        )
        _restore_classification_state(fs)

    return on_complete


# ── IBS → BANTAM (drain) ───────────────────────────────────────────────────

def _send_robot2_ibs_to_bantam(fs, piece_id: str) -> None:
    fs.get_logger().info(
        f"[classification] draining IBS → BANTAM: piece={piece_id} "
        f"(IBS remaining={fs.pieces.count('intermediate_blue_stack')})"
    )
    fs._classification_state = "WAITING_ROBOT2_IBS_TO_BANTAM"
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
            _restore_classification_state(fs)
            return

        fs.get_logger().info(
            f"[classification] robot2 HOME after IBS→bantam place — piece={piece_id} "
            f"sending bantam RUN_JOB now"
        )
        fs.pieces.transfer_piece("intermediate_blue_stack", "bantam_bed")
        fs.state.update_robot("robot2", RobotState.IDLE)
        fs.state.update_machine("bantam", MachineState.PREPARING)
        _send_bantam_job(fs, piece_id)

    return on_complete


# ── Bantam job ──────────────────────────────────────────────────────────────

def _send_bantam_job(fs, piece_id: str) -> None:
    fs.get_logger().info(f"[bantam] RUN_JOB sending piece={piece_id}")
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
                fs._classification_state = "IDLE"
                return

            fs.state.update_machine("bantam", MachineState.FINISHED)
            fs.get_logger().info(
                f"[classification] bantam COMPLETE piece={piece_id} "
                f"robot2={fs.state.get_robot('robot2').name} "
                f"robot2_busy={fs.vendor_clients['niryo'].is_busy('robot2')} "
                f"→ signalling {_STATE_BANTAM_DONE}"
            )
            # Always defer to evaluate() — avoids any race between this callback
            # and concurrent robot2 moves. evaluate() dispatches BANTAM→C4 as
            # soon as robot2 is idle (within 0.5 s of this callback).
            fs._pending_bantam_piece = piece_id
            fs._classification_state = _STATE_BANTAM_DONE
        except Exception as exc:
            fs.get_logger().error(
                f"[classification] _on_bantam_complete raised: {exc}"
            )

    return on_complete


# ── BANTAM → C4 ────────────────────────────────────────────────────────────

def _send_robot2_bantam_to_c4(fs, piece_id: str) -> None:
    fs.get_logger().info(f"[classification] robot2 BANTAM→C4 piece={piece_id}")
    fs._pending_bantam_piece = None
    fs._classification_state = "WAITING_ROBOT2_BANTAM_TO_C4"
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
            fs._classification_state = "IDLE"
            return

        fs.pieces.transfer_piece("bantam_bed", "c4_location")
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
            _restore_classification_state(fs)
            return

        fs.pieces.transfer_piece("conveyor2", "robot2_scrap")
        fs.state.update_robot("robot2", RobotState.IDLE)
        record = fs.cycles.complete_cycle(piece_id, color, shape, "SCRAP")
        if record is not None:
            fs.db.insert_cycle_complete(record)
        _restore_classification_state(fs)

    return on_complete


# ── Shared home callback ────────────────────────────────────────────────────

def _on_robot2_home_complete(fs):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().warning(f"Robot2 return home ended with {task_state}")
        fs.state.update_robot("robot2", RobotState.IDLE)
        _restore_classification_state(fs)

    return on_complete


# ── Conveyor stop helper ────────────────────────────────────────────────────

def _schedule_conveyor_stop(fs, conveyor_id: str, piece_id: str, route, delay_sec: float) -> None:
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
