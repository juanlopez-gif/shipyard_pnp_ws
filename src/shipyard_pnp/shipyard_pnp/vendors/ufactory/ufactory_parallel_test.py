import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

_TERMINAL = {"COMPLETED", "FAILED", "REJECTED", "TIMEOUT", "CANCELED"}


class UFactoryParallelTest(Node):
    def __init__(self):
        super().__init__("ufactory_parallel_test")
        self.declare_parameter("delay_between_commands_sec", 0.1)
        self.declare_parameter("timeout_sec", 180.0)

        self.pub = self.create_publisher(String, "/ufactory_factory/command", 10)
        self.create_subscription(String, "/ufactory_factory/ack", self._on_ack, 10)
        self.create_subscription(String, "/ufactory_factory/status", self._on_status, 10)
        self.done = {}
        self.started = False
        self.sent_at = None
        self.timer = self.create_timer(0.2, self._tick)

    def _tick(self) -> None:
        if not self.started:
            if self.pub.get_subscription_count() < 1:
                return
            self.started = True
            self.sent_at = time.monotonic()
            self._send_pair()
            return

        timeout = self.get_parameter("timeout_sec").value
        if time.monotonic() - self.sent_at > timeout:
            self.get_logger().error("Parallel test timeout")
            rclpy.shutdown()
            return
        if self.done.get("CMD-parallel-test-xarm1") and self.done.get("CMD-parallel-test-xarm2"):
            self.get_logger().info("Parallel test finished")
            rclpy.shutdown()

    def _send_pair(self) -> None:
        self.get_logger().info("Sending xarm2 s3.1 -> C3")
        self._publish({
            "schema": "shipyard.pnp.command.v1",
            "command_id": "CMD-parallel-test-xarm2",
            "domain_id": "ufactory",
            "resource_id": "xarm2",
            "task": "MOVE_PIECE",
            "piece_id": "P-parallel-test-xarm2",
            "source": "INITIAL_STACK",
            "target": "C3",
            "route": "GREEN",
            "parameters": {"pick_slot": "s3.1", "target": "C3"},
            "issued_at": "2026-06-19T00:00:00Z",
            "nonce": "test-xarm2",
            "auth": "",
        })

        delay = float(self.get_parameter("delay_between_commands_sec").value)
        if delay > 0:
            time.sleep(delay)

        self.get_logger().info("Sending xarm1 C1S2 -> C2S1")
        self._publish({
            "schema": "shipyard.pnp.command.v1",
            "command_id": "CMD-parallel-test-xarm1",
            "domain_id": "ufactory",
            "resource_id": "xarm1",
            "task": "MOVE_PIECE",
            "piece_id": "P-parallel-test-xarm1",
            "source": "C1S2",
            "target": "C2S1",
            "route": "TEST",
            "parameters": {"source": "C1S2", "target": "C2S1"},
            "issued_at": "2026-06-19T00:00:01Z",
            "nonce": "test-xarm1",
            "auth": "",
        })

    def _publish(self, payload: dict) -> None:
        msg = String()
        msg.data = json.dumps(payload)
        self.pub.publish(msg)

    def _on_ack(self, msg: String) -> None:
        payload = json.loads(msg.data)
        self.get_logger().info(
            f"ACK {payload.get('command_id')} accepted={payload.get('accepted')} "
            f"reason={payload.get('reason')}"
        )

    def _on_status(self, msg: String) -> None:
        payload = json.loads(msg.data)
        command_id = payload.get("command_id")
        task_state = payload.get("task_state")
        resource_id = payload.get("resource_id")
        result = payload.get("result", {}) or {}
        code = result.get("code", "")
        self.get_logger().info(
            f"STATUS {command_id} {resource_id} {task_state} "
            f"{payload.get('resource_state')} {code}"
        )
        if task_state in _TERMINAL:
            self.done[command_id] = task_state


def main(args=None):
    rclpy.init(args=args)
    node = UFactoryParallelTest()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
