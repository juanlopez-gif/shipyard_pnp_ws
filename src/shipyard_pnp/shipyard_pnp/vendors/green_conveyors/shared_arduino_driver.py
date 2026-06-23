import threading
import time
from typing import Callable, Optional

_CHANNEL_BY_RESOURCE = {
    "conveyor3": "B",
    "conveyor4": "A",
}

class SharedGreenConveyorDriver:
    """
    Serial driver for the shared Arduino that owns green conveyors 3 and 4.

    Firmware protocol:
      A:START / A:STOP / A:FWD / A:REV / A:SPEED:<n>
      B:START / B:STOP / B:FWD / B:REV / B:SPEED:<n>
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        startup_wait_sec: float = 2.0,
        command_timeout_sec: float = 2.0,
        reconnect_attempts: int = 5,
        reconnect_delay_sec: float = 1.0,
        inter_command_delay_sec: float = 0.3,
        conveyor3_speed: int = 9000,
        conveyor4_speed: int = 9000,
        conveyor3_direction: str = "FWD",
        conveyor4_direction: str = "REV",
        logger=None,
    ):
        self.port = port
        self.baudrate = int(baudrate)
        self.startup_wait_sec = float(startup_wait_sec)
        self.command_timeout_sec = float(command_timeout_sec)
        self.reconnect_attempts = int(reconnect_attempts)
        self.reconnect_delay_sec = float(reconnect_delay_sec)
        self.inter_command_delay_sec = float(inter_command_delay_sec)
        self.default_speed = {
            "A": int(conveyor4_speed),
            "B": int(conveyor3_speed),
        }
        self.default_direction = {
            "A": self._normalize_direction(conveyor4_direction),
            "B": self._normalize_direction(conveyor3_direction),
        }
        self._logger = logger
        self._serial = None
        self._serial_lock = threading.Lock()
        self._serial_module = None

    def make_task_fn(self, cmd: dict) -> Callable[[], dict]:
        task = cmd.get("task", "")
        resource_id = cmd.get("resource_id", "")
        channel = _CHANNEL_BY_RESOURCE.get(resource_id)
        params = cmd.get("parameters") or {}

        def fn() -> dict:
            if task == "INITIALIZE_DOMAIN":
                self.initialize_domain()
                return {"resource_state": "STOPPED", "code": "INITIALIZED"}
            if channel is None:
                raise ValueError(f"Unsupported green conveyor resource: {resource_id}")
            if task == "RUN_CONVEYOR":
                speed = int(params.get("speed", self.default_speed[channel]))
                direction = self._normalize_direction(
                    params.get("direction", self.default_direction[channel])
                )
                self.configure_channel(channel, speed, direction)
                self._sleep_between_commands()
                self.send_channel_command(channel, "START")
                return {"resource_state": "RUNNING", "code": "OK"}
            if task == "STOP_CONVEYOR":
                self.send_channel_command(channel, "STOP")
                return {"resource_state": "STOPPED", "code": "OK"}
            if task == "SET_SPEED":
                speed = int(params["speed"])
                self.send_channel_command(channel, f"SPEED:{speed}")
                return {"resource_state": "RUNNING", "code": "OK"}
            if task == "RESET":
                self.send_channel_command(channel, "STOP")
                return {"resource_state": "STOPPED", "code": "OK"}
            raise ValueError(f"Unsupported green_conveyors task: {task}")

        return fn

    def initialize_domain(self) -> None:
        self.connect()
        for channel in ("A", "B"):
            self.send_channel_command(channel, "STOP")
            self._sleep_between_commands()
            self.configure_channel(
                channel,
                self.default_speed[channel],
                self.default_direction[channel],
            )

    def configure_channel(self, channel: str, speed: int, direction: str) -> None:
        if speed <= 0:
            raise ValueError(f"Invalid conveyor speed: {speed}")
        direction = self._normalize_direction(direction)
        self.send_channel_command(channel, f"SPEED:{speed}")
        self._sleep_between_commands()
        self.send_channel_command(channel, direction)

    def send_channel_command(self, channel: str, command: str) -> None:
        channel = channel.upper()
        if channel not in {"A", "B"}:
            raise ValueError(f"Invalid green conveyor channel: {channel}")
        command = command.strip().upper()
        if not self._is_valid_command(command):
            raise ValueError(f"Invalid green conveyor command: {command}")

        last_error = None
        for attempt in range(1, self.reconnect_attempts + 1):
            try:
                with self._serial_lock:
                    if self._serial is None or not self._serial.is_open:
                        self._open_serial_locked()
                    self._send_and_wait_locked(channel, command)
                return
            except Exception as exc:
                if not self._is_serial_error(exc) and not isinstance(exc, RuntimeError):
                    raise
                last_error = exc
                with self._serial_lock:
                    self._close_serial_locked()
                self._warn(
                    f"Green conveyor {channel}:{command} failed "
                    f"(attempt {attempt}/{self.reconnect_attempts}): {exc}"
                )
                if attempt < self.reconnect_attempts:
                    time.sleep(self.reconnect_delay_sec)
        raise RuntimeError(f"Green conveyor {channel}:{command} failed: {last_error}")

    def connect(self) -> None:
        last_error = None
        for attempt in range(1, self.reconnect_attempts + 1):
            try:
                with self._serial_lock:
                    if self._serial is not None and self._serial.is_open:
                        return
                    self._open_serial_locked()
                return
            except Exception as exc:
                if not self._is_serial_error(exc):
                    raise
                last_error = exc
                self._warn(
                    f"Could not open green conveyor serial link "
                    f"(attempt {attempt}/{self.reconnect_attempts}): {exc}"
                )
                if attempt < self.reconnect_attempts:
                    time.sleep(self.reconnect_delay_sec)
        raise RuntimeError(f"Green conveyor serial connection failed: {last_error}")

    def close(self, stop_first: bool = True) -> None:
        should_stop = (
            stop_first
            and self._serial is not None
            and getattr(self._serial, "is_open", False)
        )
        if should_stop:
            for channel in ("A", "B"):
                try:
                    self.send_channel_command(channel, "STOP")
                except Exception:
                    pass
        with self._serial_lock:
            self._close_serial_locked()

    def _send_and_wait_locked(self, channel: str, command: str) -> None:
        line = f"{channel}:{command}"
        self._drain_stale_locked(0.05)
        self._serial.write(f"{line}\n".encode())
        self._serial.flush()
        self._info(f"Green conveyor -> {line}")

        deadline = time.monotonic() + self.command_timeout_sec
        while time.monotonic() < deadline:
            while self._serial.in_waiting:
                response = self._serial.readline().decode(errors="replace").strip()
                if not response:
                    continue
                normalized = response.upper()
                self._info(f"Green conveyor <- {normalized}")
                status = self._parse_status(normalized)
                if status is None:
                    continue
                resp_channel, ok, resp_command = status
                if resp_channel != channel:
                    continue
                if not ok:
                    raise RuntimeError(f"Arduino rejected {line}: {normalized}")
                if self._commands_match(command, resp_command):
                    return
            time.sleep(0.02)
        raise RuntimeError(f"Timeout waiting for ACK to {line}")

    def _open_serial_locked(self):
        serial = self._serial_lib()
        self._close_serial_locked()
        self._info(
            f"Connecting to green conveyor Arduino on {self.port} "
            f"at {self.baudrate} baud"
        )
        ser = serial.Serial(self.port, self.baudrate, timeout=0.1)
        self._serial = ser
        time.sleep(self.startup_wait_sec)
        self._drain_startup_locked()
        self._info("Green conveyor Arduino connected")
        return ser

    def _close_serial_locked(self) -> None:
        if self._serial is None:
            return
        try:
            if self._serial.is_open:
                self._serial.close()
        finally:
            self._serial = None

    def _drain_startup_locked(self) -> None:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            while self._serial.in_waiting:
                line = self._serial.readline().decode(errors="replace").strip()
                if line:
                    self._info(f"Green conveyor [startup] << {line}")
            time.sleep(0.02)

    def _drain_stale_locked(self, duration_s: float) -> None:
        deadline = time.monotonic() + max(float(duration_s), 0.0)
        while time.monotonic() < deadline:
            while self._serial.in_waiting:
                line = self._serial.readline().decode(errors="replace").strip()
                if line:
                    self._info(f"Green conveyor [stale] << {line}")
            time.sleep(0.02)

    @staticmethod
    def _parse_status(line: str) -> Optional[tuple]:
        if line == "READY":
            return None
        parts = [part for part in line.split(":") if part]
        if len(parts) >= 3 and parts[0] in {"A", "B"}:
            channel = parts[0]
            status = "OK" if parts[1] == "ACK" else parts[1]
            command = ":".join(parts[2:])
            return channel, status == "OK", command
        if len(parts) >= 3 and parts[0] in {"OK", "ACK", "ERR", "ERROR"}:
            status = "OK" if parts[0] == "ACK" else parts[0]
            channel = parts[1]
            command = ":".join(parts[2:])
            if channel in {"A", "B"}:
                return channel, status == "OK", command
        return None

    @staticmethod
    def _commands_match(sent: str, received: str) -> bool:
        return sent.strip().upper() == received.strip().upper()

    @staticmethod
    def _is_valid_command(command: str) -> bool:
        return command in {"START", "STOP", "FWD", "REV"} or command.startswith("SPEED:")

    @staticmethod
    def _normalize_direction(direction: str) -> str:
        direction = str(direction).strip().upper()
        if direction not in {"FWD", "REV"}:
            return "FWD"
        return direction

    def _sleep_between_commands(self) -> None:
        if self.inter_command_delay_sec > 0:
            time.sleep(self.inter_command_delay_sec)

    def _serial_lib(self):
        if self._serial_module is None:
            import serial  # noqa: PLC0415
            self._serial_module = serial
        return self._serial_module

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
