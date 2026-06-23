"""
Manages all four conveyors.
- Conveyors 1 & 2: RUN_NIRYO_CONVEYOR to the niryo domain.
- Conveyors 3 & 4: RUN_CONVEYOR to the green_conveyors domain.

The VS stops the Niryo conveyors autonomously when the exit sensor trips; the
FS does NOT send a STOP command for those. It simply observes the STOPPED
status update that the niryo VS publishes autonomously via SENSOR_UPDATE.

Green conveyors 3 & 4 currently have no downstream sensor — the FS sends an
explicit STOP_CONVEYOR after the piece is picked by robot2 / xarm2 (handled
inside the classification / feeding rules that actually consume the piece).
"""

from shipyard_pnp.shared.contracts import ConveyorState, SensorState


def evaluate(fs) -> None:
    _conveyor1_rules(fs)
    _conveyor2_rules(fs)


def _conveyor1_rules(fs) -> None:
    if fs.vendor_clients["niryo"].is_busy("conveyor1"):
        return
    c1s1 = fs.state.get_sensor("c1s1")
    c1s2 = fs.state.get_sensor("c1s2")
    conv1 = fs.state.get_conveyor("conveyor1")
    if (
        c1s1 == SensorState.OCCUPIED
        and conv1 == ConveyorState.STOPPED
        and c1s2 == SensorState.FREE
    ):
        fs.send_command(
            "niryo", "conveyor1", "RUN_NIRYO_CONVEYOR",
            parameters={"conveyor_id": "conveyor1"},
            on_complete=_on_conveyor_done(fs, "conveyor1"),
        )


def _conveyor2_rules(fs) -> None:
    if fs.vendor_clients["niryo"].is_busy("conveyor2"):
        return
    c2s1 = fs.state.get_sensor("c2s1")
    c2s2 = fs.state.get_sensor("c2s2")
    conv2 = fs.state.get_conveyor("conveyor2")
    c2s2_clear = c2s2 == SensorState.FREE or fs._c2s2_committed
    if (
        c2s1 == SensorState.OCCUPIED
        and conv2 == ConveyorState.STOPPED
        and c2s2_clear
    ):
        fs.get_logger().info(
            f"[conveyor2] RUN c2s1={c2s1.name} c2s2={c2s2.name} "
            f"committed={fs._c2s2_committed}"
        )
        fs._c2s2_committed = False
        fs.send_command(
            "niryo", "conveyor2", "RUN_NIRYO_CONVEYOR",
            parameters={"conveyor_id": "conveyor2"},
            on_complete=_on_conveyor_done(fs, "conveyor2"),
        )


def _on_conveyor_done(fs, conveyor_id: str):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().error(
                f"RUN_NIRYO_CONVEYOR failed for '{conveyor_id}': {result}"
            )
            return
        fs.state.update_conveyor(conveyor_id, ConveyorState.STOPPED)
    return on_complete
