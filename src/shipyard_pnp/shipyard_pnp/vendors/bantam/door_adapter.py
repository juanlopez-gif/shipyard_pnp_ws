"""
DoorAdapter — controls the Bantam door via ZMQ to the Raspberry Pi.

Sends "open" / "close" / "status" to tcp://<pi_host>:<pi_port>
and reads the plain-text response.
"""

import threading
import time
from typing import Optional


class DoorState:
    OPEN             = "OPEN"
    CLOSED           = "CLOSED"
    MOVING_TO_OPEN   = "MOVING_TO_OPEN"
    MOVING_TO_CLOSED = "MOVING_TO_CLOSED"
    UNKNOWN          = "UNKNOWN"


class DoorAdapter:
    def __init__(
        self,
        node,
        zmq_address:  str   = "tcp://192.168.0.171:5555",
        cooldown_sec: float = 2.0,
        timeout_sec:  float = 12.0,
        poll_interval_sec: float = 1.0,
    ):
        self._node         = node
        self._address      = zmq_address
        self._cooldown     = cooldown_sec
        self._timeout      = timeout_sec
        self._poll_interval = poll_interval_sec

        self._state_lock   = threading.Lock()   # protects _state, _last_cmd
        self._zmq_lock     = threading.Lock()   # serialises all ZMQ send/recv
        self._state        = DoorState.UNKNOWN
        self._last_cmd: Optional[str] = None
        self._last_cmd_at: float      = 0.0

        import zmq
        self._ctx  = zmq.Context()
        self._sock = self._ctx.socket(zmq.REQ)
        self._sock.connect(zmq_address)
        node.get_logger().info(f"DoorAdapter connected to {zmq_address}")

        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    # ── public ────────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    def open(self, reason: str = "") -> None:
        self._send_cmd("open", reason)

    def close(self, reason: str = "") -> None:
        self._send_cmd("close", reason)

    def wait_for_open(self, timeout: Optional[float] = None) -> bool:
        return self._wait_for(DoorState.OPEN, timeout)

    def wait_for_closed(self, timeout: Optional[float] = None) -> bool:
        return self._wait_for(DoorState.CLOSED, timeout)

    # ── private ───────────────────────────────────────────────────────────

    def _send_cmd(self, cmd: str, reason: str) -> None:
        now = time.monotonic()
        with self._state_lock:
            if self._last_cmd == cmd and (now - self._last_cmd_at) < self._cooldown:
                self._node.get_logger().info(
                    f"Door '{cmd}' suppressed — cooldown ({reason})"
                )
                return
            self._last_cmd    = cmd
            self._last_cmd_at = now
            moving = DoorState.MOVING_TO_OPEN if cmd == "open" else DoorState.MOVING_TO_CLOSED
            self._state = moving

        try:
            with self._zmq_lock:
                self._sock.send_string(cmd)
                resp = self._sock.recv_string()
            self._node.get_logger().info(f"Door → {cmd}  ({reason})  resp={resp!r}")
            with self._state_lock:
                self._state = _infer_state(resp)
        except Exception as exc:
            self._node.get_logger().error(f"Door cmd '{cmd}' failed: {exc}")

    def _poll_loop(self) -> None:
        while True:
            time.sleep(self._poll_interval)
            try:
                with self._zmq_lock:
                    self._sock.send_string("status")
                    resp = self._sock.recv_string()
                with self._state_lock:
                    self._state = _infer_state(resp)
            except Exception as exc:
                self._node.get_logger().debug(f"Door poll error: {exc}")

    def _wait_for(self, target: str, timeout: Optional[float]) -> bool:
        deadline = time.monotonic() + (timeout if timeout is not None else self._timeout)
        while time.monotonic() < deadline:
            with self._state_lock:
                if self._state == target:
                    return True
            time.sleep(0.2)
        with self._state_lock:
            return self._state == target


def _infer_state(raw: str) -> str:
    text = (raw or "").strip().lower()
    if any(w in text for w in ("opening", "closing", "moving", "busy")):
        return DoorState.MOVING_TO_OPEN if "open" in text else DoorState.MOVING_TO_CLOSED
    if "closed" in text:
        return DoorState.CLOSED
    if "open" in text:
        return DoorState.OPEN
    return DoorState.UNKNOWN
