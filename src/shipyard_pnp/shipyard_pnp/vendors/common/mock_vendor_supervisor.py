"""
Mock vendor supervisor for smoke tests and simulation.

Extends BaseVendorSupervisor so the full three-channel wiring is exercised.
Every task is immediately accepted (ACK = true) and then publishes COMPLETED
status after `sim_delay_sec` (default 0.05 s), making integration tests fast
without needing real hardware.

Launch via: ros2 run shipyard_pnp mock_vendor_supervisor --ros-args -p domain_id:=niryo
Or programmatically: MockVendorSupervisor("niryo")
"""

import threading
import time
from typing import Optional, Tuple

import rclpy
from rclpy.executors import SingleThreadedExecutor

from shipyard_pnp.vendors.common.base_vendor_supervisor import BaseVendorSupervisor

_TASK_RESULT_STATE = {
    "INITIALIZE_DOMAIN": "IDLE",
    "MOVE_PIECE": "PLACE_DONE",
    "MOVE_ROBOT": "IDLE",
    "CAPTURE_LOCAL_VISION": "IDLE",
    "RUN_NIRYO_CONVEYOR": "STOPPED",
    "STOP_NIRYO_CONVEYOR": "STOPPED",
    "READ_IR_SENSOR": "FREE",
    "SENSOR_UPDATE": "FREE",
    "GOTO_PICK_POSITION": "AT_PICK_POSITION",
    "LIFT_AND_PLACE": "AT_PLACE_POSITION",
    "RETURN_HOME": "IDLE",
    "MOVE_XARM_HOME": "IDLE",
    "PREPARE_JOB": "PREPARING",
    "RUN_JOB": "FINISHED",
    "RESET": "IDLE",
    "SCAN_STACK": "IDLE",
    "LOCATE_NEXT_PIECE": "IDLE",
    "GET_INVENTORY": "IDLE",
    "RUN_CONVEYOR": "RUNNING",
    "STOP_CONVEYOR": "STOPPED",
    "SET_SPEED": "RUNNING",
    "PICK": "PICK_DONE",
    "RELEASE": "RELEASE_DONE",
    "OFF": "IDLE",
    "GET_READY": "IDLE",
    "OPEN_DOOR": "IDLE",
    "CLOSE_DOOR": "IDLE",
}

_TASK_RESULT_PAYLOAD = {
    "CAPTURE_LOCAL_VISION": {
        "code": "VISION_RESULT_READY",
        "color": "RED",
        "shape": "CIRCLE",
        "confidence": "HIGH",
    },
    "LOCATE_NEXT_PIECE": {
        "code": "SLOT_FOUND",
        "slot_id": "s1.1",
        "color": "RED",
        "shape": "CIRCLE",
        "confidence": "HIGH",
        "scan_id": "SCAN-0001",
    },
    "SCAN_STACK": {
        "code": "INVENTORY_READY",
        "scan_id": "SCAN-0001",
        "slots": [{"slot_id": "s1.1", "occupied": True, "color": "RED", "shape": "CIRCLE"}],
    },
    "RUN_JOB": {"code": "JOB_DONE"},
    "PICK": {"code": "OK"},
    "RELEASE": {"code": "OK"},
}


class MockVendorSupervisor(BaseVendorSupervisor):
    def __init__(self, domain_id: str, sim_delay_sec: float = 0.05):
        super().__init__(domain_id)
        self._sim_delay = sim_delay_sec

    def handle_task(self, cmd: dict) -> Tuple[bool, Optional[str]]:
        task = cmd.get("task", "UNKNOWN")
        resource_state = _TASK_RESULT_STATE.get(task, "IDLE")
        result = dict(_TASK_RESULT_PAYLOAD.get(task, {"code": "OK"}))

        def _publish_after_delay():
            time.sleep(self._sim_delay)
            self.publish_status(
                command_id=cmd["command_id"],
                resource_id=cmd.get("resource_id", ""),
                task=task,
                task_state="COMPLETED",
                resource_state=resource_state,
                piece_id=cmd.get("piece_id"),
                source=cmd.get("source"),
                target=cmd.get("target"),
                route=cmd.get("route"),
                result=result,
                correlation_id=cmd.get("correlation_id"),
            )

        t = threading.Thread(target=_publish_after_delay, daemon=True)
        t.start()
        return True, None


def main(args=None):
    rclpy.init(args=args)
    node = rclpy.create_node("_mock_param_reader")
    node.declare_parameter("domain_id", "niryo")
    node.declare_parameter("sim_delay_sec", 0.05)
    domain_id = node.get_parameter("domain_id").get_parameter_value().string_value
    sim_delay = node.get_parameter("sim_delay_sec").get_parameter_value().double_value
    node.destroy_node()

    supervisor = MockVendorSupervisor(domain_id=domain_id, sim_delay_sec=sim_delay)
    executor = SingleThreadedExecutor()
    executor.add_node(supervisor)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        supervisor.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
