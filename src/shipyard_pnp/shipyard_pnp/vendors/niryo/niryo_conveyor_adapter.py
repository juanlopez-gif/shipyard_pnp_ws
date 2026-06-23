import time
from typing import Callable, Optional

from shipyard_pnp.shared.contracts import ConveyorState, SensorState
from shipyard_pnp.vendors.niryo.niryo_service_driver import NiryoServiceDriver


class NiryoConveyorAdapter:
    def __init__(
        self,
        resource_id: str,
        driver: NiryoServiceDriver,
        hardware_id: int,
        speed: int,
        direction: int,
        sensors: dict,
        exit_sensor_id: str,
        poll_interval_sec: float = 0.1,
        run_timeout_sec: float = 30.0,
        dry_run_duration_sec: float = 1.0,
    ):
        self.resource_id = resource_id
        self.driver = driver
        self.hardware_id = int(hardware_id)
        self.speed = int(speed)
        self.direction = int(direction)
        self.sensors = sensors
        self.exit_sensor_id = exit_sensor_id
        self.poll_interval_sec = float(poll_interval_sec)
        self.run_timeout_sec = float(run_timeout_sec)
        self.dry_run_duration_sec = float(dry_run_duration_sec)
        self._last_sensor_states: dict[str, str] = {}

    def initialize(
        self,
        status_cb: Optional[Callable] = None,
        sensor_cb: Optional[Callable] = None,
    ) -> dict:
        self.driver.initialize_conveyor()
        self.stop(status_cb)
        self.poll_sensors(sensor_cb, force=True)
        return {
            "resource_state": ConveyorState.STOPPED.value,
            "code": "INITIALIZED",
            "conveyor_id": self.resource_id,
        }

    def run_until_exit_sensor(
        self,
        status_cb: Optional[Callable] = None,
        sensor_cb: Optional[Callable] = None,
    ) -> dict:
        self._status(status_cb, ConveyorState.RUNNING.value, "RUNNING")
        self.driver.control_conveyor(
            self.hardware_id,
            control_on=True,
            speed=self.speed,
            direction=self.direction,
        )

        started = time.monotonic()
        if self.driver.dry_run:
            time.sleep(min(self.dry_run_duration_sec, self.run_timeout_sec))
            self._emit_sensor(sensor_cb, self.exit_sensor_id, SensorState.OCCUPIED.value)
        else:
            while True:
                self.poll_sensors(sensor_cb)
                if (
                    self._last_sensor_states.get(self.exit_sensor_id)
                    == SensorState.OCCUPIED.value
                ):
                    break
                if time.monotonic() - started >= self.run_timeout_sec:
                    self.driver.control_conveyor(
                        self.hardware_id, control_on=False, speed=0, direction=self.direction
                    )
                    raise TimeoutError(
                        f"{self.resource_id} timeout waiting for {self.exit_sensor_id}"
                    )
                time.sleep(self.poll_interval_sec)

        self.stop(status_cb)
        return {
            "resource_state": ConveyorState.STOPPED.value,
            "code": "STOPPED_AT_EXIT_SENSOR",
            "conveyor_id": self.resource_id,
            "sensor_id": self.exit_sensor_id,
            "state": SensorState.OCCUPIED.value,
        }

    def stop(self, status_cb: Optional[Callable] = None) -> dict:
        self.driver.control_conveyor(
            self.hardware_id,
            control_on=False,
            speed=0,
            direction=self.direction,
        )
        self._status(status_cb, ConveyorState.STOPPED.value, "STOPPED")
        return {
            "resource_state": ConveyorState.STOPPED.value,
            "code": "STOPPED",
            "conveyor_id": self.resource_id,
        }

    def poll_sensors(
        self,
        sensor_cb: Optional[Callable] = None,
        force: bool = False,
    ) -> list:
        updates = []
        if self.driver.dry_run:
            return updates

        for sensor_id, cfg in self.sensors.items():
            raw_value = self.driver.read_digital_io(cfg["pin"])
            active_low = cfg.get("active_low", True)
            occupied = not raw_value if active_low else raw_value
            state = SensorState.OCCUPIED.value if occupied else SensorState.FREE.value
            previous = self._last_sensor_states.get(sensor_id)
            self._last_sensor_states[sensor_id] = state
            if force or previous != state:
                updates.append({
                    "sensor_id": sensor_id,
                    "state": state,
                    "raw": raw_value,
                    "pin": cfg["pin"],
                    "active_low": active_low,
                })
                self._emit_sensor(sensor_cb, sensor_id, state)
        return updates

    def _emit_sensor(
        self,
        sensor_cb: Optional[Callable],
        sensor_id: str,
        state: str,
    ) -> None:
        self._last_sensor_states[sensor_id] = state
        if sensor_cb:
            sensor_cb(sensor_id, state)

    @staticmethod
    def _status(
        status_cb: Optional[Callable],
        resource_state: str,
        code: str,
        **result,
    ) -> None:
        if status_cb:
            payload = {"code": code}
            payload.update(result)
            status_cb(resource_state, payload)
