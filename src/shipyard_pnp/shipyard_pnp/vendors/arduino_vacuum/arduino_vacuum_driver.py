import threading
import time
from typing import Callable, Optional


class ArduinoVacuumDriver:
    """
    Plain Python serial driver for the external Arduino vacuum controller.

    Firmware protocol:
      p -> PICK
      r -> RELEASE
      o -> OFF
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        open_wait_sec: float = 2.0,
        read_wait_sec: float = 1.0,
        reconnect_attempts: int = 8,
        reconnect_delay_sec: float = 1.0,
        pick_hold_sec: float = 0.5,
        release_hold_sec: float = 0.3,
        logger=None,
    ):
        self.port = port
        self.baudrate = int(baudrate)
        self.open_wait_sec = float(open_wait_sec)
        self.read_wait_sec = float(read_wait_sec)
        self.reconnect_attempts = int(reconnect_attempts)
        self.reconnect_delay_sec = float(reconnect_delay_sec)
        self.pick_hold_sec = float(pick_hold_sec)
        self.release_hold_sec = float(release_hold_sec)
        self._logger = logger
        self._serial = None
        self._serial_lock = threading.Lock()
        self._serial_module = None

    def make_task_fn(self, cmd: dict) -> Callable[[], dict]:
        task = cmd.get("task", "")

        def fn() -> dict:
            if task == "INITIALIZE_DOMAIN":
                self.connect()
                self._send_command(b"o", "OFF", "OFF")
                return {"resource_state": "IDLE", "code": "INITIALIZED"}
            if task == "PICK":
                self._send_command(b"p", "PICK", "PICK")
                time.sleep(self.pick_hold_sec)
                return {"resource_state": "PICK_DONE", "code": "OK"}
            if task == "RELEASE":
                self._send_command(b"r", "RELEASE", "RELEASE")
                time.sleep(self.release_hold_sec)
                return {"resource_state": "RELEASE_DONE", "code": "OK"}
            if task in {"OFF", "RESET"}:
                self._send_command(b"o", "OFF", "OFF")
                return {"resource_state": "IDLE", "code": "OK"}
            raise ValueError(f"Unsupported arduino_vacuum task: {task}")

        return fn

    def connect(self) -> None:
        last_error = None
        for attempt in range(1, self.reconnect_attempts + 1):
            try:
                with self._serial_lock:
                    if self._serial is not None and self._serial.is_open:
                        return
                    self._open_serial_locked()
                return
            except (OSError, RuntimeError, Exception) as exc:
                if not self._is_serial_error(exc):
                    raise
                last_error = exc
                self._warn(
                    f"Could not open Arduino vacuum serial link "
                    f"(attempt {attempt}/{self.reconnect_attempts}): {exc}"
                )
                if attempt < self.reconnect_attempts:
                    time.sleep(self.reconnect_delay_sec)
        raise RuntimeError(f"Arduino vacuum serial connection failed: {last_error}")

    def close(self, neutral: bool = True) -> None:
        should_neutralize = (
            neutral
            and self._serial is not None
            and getattr(self._serial, "is_open", False)
        )
        if should_neutralize:
            try:
                self._send_command(b"o", "OFF", "OFF")
            except Exception:
                pass
        with self._serial_lock:
            self._close_serial_locked()

    def _serial_lib(self):
        if self._serial_module is None:
            import serial  # noqa: PLC0415
            self._serial_module = serial
        return self._serial_module

    def _open_serial_locked(self):
        serial = self._serial_lib()
        self._close_serial_locked()
        self._info(
            f"Connecting to Arduino vacuum on {self.port} at {self.baudrate} baud"
        )
        ser = serial.Serial(self.port, self.baudrate, timeout=0.2)
        time.sleep(self.open_wait_sec)
        self._drain_serial_output(ser, "startup", self.read_wait_sec)
        self._serial = ser
        self._info("Arduino vacuum connected")
        return ser

    def _close_serial_locked(self) -> None:
        if self._serial is None:
            return
        try:
            if self._serial.is_open:
                self._serial.close()
        finally:
            self._serial = None

    def _send_command(self, payload: bytes, label: str, expected: str) -> None:
        last_error = None
        for attempt in range(1, self.reconnect_attempts + 1):
            try:
                with self._serial_lock:
                    if self._serial is None or not self._serial.is_open:
                        self._open_serial_locked()
                    ser = self._serial
                    self._drain_serial_output(ser, "stale", 0.05)
                    ser.write(payload)
                    ser.flush()
                    lines = self._drain_serial_output(
                        ser, label, self.read_wait_sec
                    )
                    if not self._contains_expected(lines, expected):
                        raise RuntimeError(
                            f"Unexpected Arduino response for {label}: {lines or '<none>'}"
                        )
                    return
            except Exception as exc:
                if not self._is_serial_error(exc) and not isinstance(exc, RuntimeError):
                    raise
                last_error = exc
                with self._serial_lock:
                    self._close_serial_locked()
                self._warn(
                    f"Serial command {label} failed "
                    f"(attempt {attempt}/{self.reconnect_attempts}): {exc}"
                )
                if attempt < self.reconnect_attempts:
                    time.sleep(self.reconnect_delay_sec)
        raise RuntimeError(f"Arduino vacuum command {label} failed: {last_error}")

    def _drain_serial_output(self, ser, context: str, duration_s: float) -> list:
        lines = []
        deadline = time.monotonic() + max(float(duration_s), 0.0)
        while time.monotonic() < deadline:
            while ser.in_waiting:
                line = ser.readline().decode(errors="replace").strip()
                if line:
                    lines.append(line)
            time.sleep(0.05)
        for line in lines:
            self._info(f"Arduino vacuum [{context}] << {line}")
        return lines

    @staticmethod
    def _contains_expected(lines: list, expected: str) -> bool:
        expected = expected.upper()
        return any(line.strip().upper() == expected for line in lines)

    def _is_serial_error(self, exc: Exception) -> bool:
        try:
            serial = self._serial_lib()
            return isinstance(exc, (serial.SerialException, OSError))
        except Exception:
            return isinstance(exc, OSError)

    def _info(self, msg: str) -> None:
        if self._logger is not None:
            self._logger.info(msg)

    def _warn(self, msg: str) -> None:
        if self._logger is not None:
            self._logger.warning(msg)
