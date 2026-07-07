"""
Twin Bridge Node — translates P&P status topics into the topics expected
by the MuJoCo digital twin (mujoco_pkg / twin_node_5).

Subscribes (read-only, never writes to any P&P topic):
  /ufactory_factory/status
  /niryo_factory/status
  /arduino_vacuum_factory/status
  /bantam_factory/status
  /laser_factory/status
  /green_conveyors_factory/status

Publishes (digital twin topics):
  /xarm1/vacuum_state          std_msgs/String  "ON" | "OFF"
  /xarm2/vacuum_state          std_msgs/String  "ON" | "OFF"
  /robot1/vacuum_state         std_msgs/String  "ON" | "OFF"
  /robot2/vacuum_state         std_msgs/String  "ON" | "OFF"
  /factory/conveyor_1/status   std_msgs/String  "RUNNING" | "STOPPED"
  /factory/conveyor_2/status   std_msgs/String  "RUNNING" | "STOPPED"
  /factory/conveyor_small/status std_msgs/String "RUNNING" | "STOPPED"
  /bantam/door_state           std_msgs/String  "OPEN" | "MOVING_TO_OPEN" |
                                                "CLOSED" | "MOVING_TO_CLOSED"
  /laser/status                std_msgs/String  "IDLE" | "FINISHED" | "WORKING"
"""

import json

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

# ── vacuum state mappings ────────────────────────────────────────────────────
# Only react to the exact transition states where vacuum physically changes.
# Intermediate movement states (GOING_TO_POSITION, RETURNING_HOME, etc.) are
# emitted both before AND after picking, so reacting to them would incorrectly
# release the part mid-transit.

# xArm: PICKING = arm is at pick pos, vacuum_on() is about to fire
#        PLACE_DONE = vacuum_off() has fired, piece is released
_XARM_ON_STATES  = {"PICKING"}
_XARM_OFF_STATES = {"PLACE_DONE"}

# arduino_vacuum: PICK_DONE = arduino acked the PICK command (piece held)
#                 RELEASE_DONE = arduino acked the RELEASE command
_ARDUINO_ON_STATES  = {"PICK_DONE"}
_ARDUINO_OFF_STATES = {"RELEASE_DONE"}

# robot2 Niryo vacuum:
# - robot2_adapter (normal production) uses RobotState → PICK_DONE / PLACE_DONE
# - robot2_niryo_vacuum_adapter (explicit cmds) uses VacuumState → PICK_DONE / RELEASE_DONE
_NIRYO_VAC_ON_STATES  = {"PICK_DONE"}
_NIRYO_VAC_OFF_STATES = {"PLACE_DONE", "RELEASE_DONE"}

# ── bantam door: inferred from intermediate status codes ─────────────────────

_BANTAM_CODE_TO_DOOR = {
    "CLOSING_DOOR":           "MOVING_TO_CLOSED",
    "MACHINING_SIMULATED":    "CLOSED",
    "OPENING_DOOR_AFTER_JOB": "MOVING_TO_OPEN",
    "JOB_COMPLETE":           "OPEN",
}


class TwinBridgeNode(Node):
    def __init__(self):
        super().__init__("twin_bridge_node")

        # ── publishers ───────────────────────────────────────────────────────
        qos = 10
        self._pub = {
            "xarm1_vac":    self.create_publisher(String, "/xarm1/vacuum_state",           qos),
            "xarm2_vac":    self.create_publisher(String, "/xarm2/vacuum_state",           qos),
            "robot1_vac":   self.create_publisher(String, "/robot1/vacuum_state",          qos),
            "robot2_vac":   self.create_publisher(String, "/robot2/vacuum_state",          qos),
            "conv1":        self.create_publisher(String, "/factory/conveyor_1/status",    qos),
            "conv2":        self.create_publisher(String, "/factory/conveyor_2/status",    qos),
            "conv_small":   self.create_publisher(String, "/factory/conveyor_small/status",qos),
            "bantam_door":  self.create_publisher(String, "/bantam/door_state",            qos),
            "laser":        self.create_publisher(String, "/laser/status",                 qos),
        }

        # ── subscribers ──────────────────────────────────────────────────────
        self.create_subscription(String, "/ufactory_factory/status",
                                 self._on_ufactory,       qos)
        self.create_subscription(String, "/niryo_factory/status",
                                 self._on_niryo,          qos)
        self.create_subscription(String, "/arduino_vacuum_factory/status",
                                 self._on_arduino_vacuum, qos)
        self.create_subscription(String, "/bantam_factory/status",
                                 self._on_bantam,         qos)
        self.create_subscription(String, "/laser_factory/status",
                                 self._on_laser,          qos)
        self.create_subscription(String, "/green_conveyors_factory/status",
                                 self._on_green_conveyors, qos)

        self.get_logger().info("twin_bridge_node ready — bridging P&P → MuJoCo digital twin")

    # ── ufactory → xArm vacuum ───────────────────────────────────────────────

    def _on_ufactory(self, msg: String) -> None:
        data = _parse(msg)
        if data is None:
            return
        rid   = data.get("resource_id", "")
        state = data.get("resource_state", "")

        if rid == "xarm1":
            if state in _XARM_ON_STATES:
                self._pub["xarm1_vac"].publish(_str("ON"))
            elif state in _XARM_OFF_STATES:
                self._pub["xarm1_vac"].publish(_str("OFF"))

        elif rid == "xarm2":
            if state in _XARM_ON_STATES:
                self._pub["xarm2_vac"].publish(_str("ON"))
            elif state in _XARM_OFF_STATES:
                self._pub["xarm2_vac"].publish(_str("OFF"))

    # ── niryo → conveyors + robot2 vacuum ────────────────────────────────────

    def _on_niryo(self, msg: String) -> None:
        data = _parse(msg)
        if data is None:
            return
        rid   = data.get("resource_id", "")
        state = data.get("resource_state", "")

        if rid == "conveyor1":
            if state == "RUNNING":
                self._pub["conv1"].publish(_str("RUNNING"))
            elif state == "STOPPED":
                self._pub["conv1"].publish(_str("STOPPED"))

        elif rid == "conveyor2":
            if state == "RUNNING":
                self._pub["conv2"].publish(_str("RUNNING"))
            elif state == "STOPPED":
                self._pub["conv2"].publish(_str("STOPPED"))

        elif rid == "robot2":
            # robot2_adapter drives vacuum internally via driver.vacuum("pull"/"push").
            # Status arrives as resource_id="robot2", NOT "robot2_niryo_vacuum".
            # PICK_DONE: arm is at pick pos and vacuum("pull") has already fired.
            # PLACE_DONE: vacuum("push") has already fired, piece released.
            if state in _NIRYO_VAC_ON_STATES:
                self._pub["robot2_vac"].publish(_str("ON"))
            elif state in _NIRYO_VAC_OFF_STATES:
                self._pub["robot2_vac"].publish(_str("OFF"))

        elif rid == "robot2_niryo_vacuum":
            # Only used for explicit PICK/RELEASE/OFF commands (e.g. safety reset).
            if state in _NIRYO_VAC_ON_STATES:
                self._pub["robot2_vac"].publish(_str("ON"))
            elif state in _NIRYO_VAC_OFF_STATES:
                self._pub["robot2_vac"].publish(_str("OFF"))

    # ── arduino_vacuum → robot1 vacuum ───────────────────────────────────────

    def _on_arduino_vacuum(self, msg: String) -> None:
        data = _parse(msg)
        if data is None:
            return
        state = data.get("resource_state", "")
        if state in _ARDUINO_ON_STATES:
            self._pub["robot1_vac"].publish(_str("ON"))
        elif state in _ARDUINO_OFF_STATES:
            self._pub["robot1_vac"].publish(_str("OFF"))

    # ── bantam → door state ───────────────────────────────────────────────────

    def _on_bantam(self, msg: String) -> None:
        data = _parse(msg)
        if data is None:
            return
        task       = data.get("task", "")
        task_state = data.get("task_state", "")
        result     = data.get("result") or {}
        code       = result.get("code", "")

        # Intermediate codes from bantam_adapter status_cb
        door_val = _BANTAM_CODE_TO_DOOR.get(code)
        if door_val:
            self._pub["bantam_door"].publish(_str(door_val))
            return

        # Terminal states from explicit OPEN_DOOR / CLOSE_DOOR tasks
        if task_state == "COMPLETED":
            if task == "OPEN_DOOR":
                self._pub["bantam_door"].publish(_str("OPEN"))
            elif task == "CLOSE_DOOR":
                self._pub["bantam_door"].publish(_str("CLOSED"))
            elif task == "INITIALIZE_DOMAIN":
                # Bantam initialises with door open
                self._pub["bantam_door"].publish(_str("OPEN"))

    # ── laser → laser status ─────────────────────────────────────────────────

    def _on_laser(self, msg: String) -> None:
        data = _parse(msg)
        if data is None:
            return
        state = data.get("resource_state", "")

        # MachineState.WORKING → engraving; IDLE / FINISHED → home position
        if state == "WORKING":
            self._pub["laser"].publish(_str("WORKING"))
        elif state == "IDLE":
            self._pub["laser"].publish(_str("IDLE"))
        elif state == "FINISHED":
            self._pub["laser"].publish(_str("FINISHED"))

    # ── green_conveyors → conveyor_small ─────────────────────────────────────

    def _on_green_conveyors(self, msg: String) -> None:
        data = _parse(msg)
        if data is None:
            return
        rid   = data.get("resource_id", "")
        state = data.get("resource_state", "")

        # conveyor3 and conveyor4 both map to the small conveyor animation
        if rid in {"conveyor3", "conveyor4"}:
            if state == "RUNNING":
                self._pub["conv_small"].publish(_str("RUNNING"))
            elif state == "STOPPED":
                self._pub["conv_small"].publish(_str("STOPPED"))


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse(msg: String):
    try:
        return json.loads(msg.data)
    except Exception:
        return None


def _str(value: str) -> String:
    m = String()
    m.data = value
    return m


# ── entry point ──────────────────────────────────────────────────────────────

def main(args=None):
    rclpy.init(args=args)
    node = TwinBridgeNode()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.remove_node(node)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
