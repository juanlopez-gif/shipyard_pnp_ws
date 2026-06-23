"""
Graceful system shutdown.
Called when planner_phase == SHUTTING_DOWN.

Shutdown sequence (serialised — each step waits for COMPLETED):
  1. STOP_NIRYO_CONVEYOR → conveyor1
  2. STOP_NIRYO_CONVEYOR → conveyor2
  3. STOP_CONVEYOR       → green_conveyors/conveyor3
  4. STOP_CONVEYOR       → green_conveyors/conveyor4
  5. CLOSE_DOOR          → bantam/bantam
  6. OFF                 → arduino_vacuum/arduino_vacuum
  7. RETURN_HOME         → niryo/robot1  (if not already IDLE)
  8. RETURN_HOME         → niryo/robot2  (if not already IDLE)
  9. MOVE_XARM_HOME      → ufactory/xarm1
 10. MOVE_XARM_HOME      → ufactory/xarm2
 11. → planner_phase = STOPPED
"""

from shipyard_pnp.shared.contracts import PlannerPhase, RobotState

_STEPS = [
    ("niryo",           "conveyor1",      "STOP_NIRYO_CONVEYOR", {}),
    ("niryo",           "conveyor2",      "STOP_NIRYO_CONVEYOR", {}),
    ("green_conveyors", "conveyor3",      "STOP_CONVEYOR",       {}),
    ("green_conveyors", "conveyor4",      "STOP_CONVEYOR",       {}),
    ("bantam",          "bantam",         "CLOSE_DOOR",          {}),
    ("arduino_vacuum",  "arduino_vacuum", "OFF",                 {}),
    ("niryo",           "robot1",         "RETURN_HOME",         {}),
    ("niryo",           "robot2",         "RETURN_HOME",         {}),
    ("ufactory",        "xarm1",          "MOVE_XARM_HOME",      {}),
    ("ufactory",        "xarm2",          "MOVE_XARM_HOME",      {}),
]


def evaluate(fs) -> None:
    if fs._shutdown_state == "DONE":
        return
    if fs._shutdown_state == "IN_PROGRESS":
        return  # waiting for a step's callback
    # First evaluate() call in SHUTTING_DOWN starts the chain
    if fs._shutdown_state == "IDLE":
        fs._shutdown_state = "IN_PROGRESS"
        fs._shutdown_step = 0
        _execute_step(fs)


def _execute_step(fs) -> None:
    step = fs._shutdown_step
    if step >= len(_STEPS):
        fs._shutdown_state = "DONE"
        fs.planner_phase = PlannerPhase.STOPPED
        fs.get_logger().info("Shutdown complete")
        return

    domain_id, resource_id, task, params = _STEPS[step]

    # Skip RETURN_HOME for robots already IDLE
    if task == "RETURN_HOME":
        state = fs.state.get_robot(resource_id)
        if state == RobotState.IDLE:
            fs._shutdown_step += 1
            _execute_step(fs)
            return

    vc = fs.vendor_clients[domain_id]
    if vc.is_busy():
        # Previous step in same domain still pending; wait for next evaluate() tick
        fs._shutdown_state = "IDLE"
        return

    fs.send_command(
        domain_id, resource_id, task,
        parameters=params,
        on_complete=_make_step_callback(fs, step, domain_id, resource_id, task),
    )


def _make_step_callback(fs, step: int, domain_id: str, resource_id: str, task: str):
    def on_complete(task_state: str, result: dict) -> None:
        if task_state != "COMPLETED":
            fs.get_logger().warning(
                f"Shutdown step {step} ({domain_id}/{resource_id} {task}) "
                f"ended with {task_state}: {result} — continuing anyway"
            )
        fs._shutdown_step = step + 1
        _execute_step(fs)
    return on_complete
