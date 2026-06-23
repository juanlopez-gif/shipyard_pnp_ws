from shipyard_pnp.shared.contracts import SensorState
from shipyard_pnp.vendors.niryo.niryo_service_driver import NiryoServiceDriver


class NiryoIRAdapter:
    def __init__(
        self,
        sensor_id: str,
        driver: NiryoServiceDriver,
        pin: str,
        active_low: bool = True,
    ):
        self.sensor_id = sensor_id
        self.driver = driver
        self.pin = pin
        self.active_low = bool(active_low)

    def read(self) -> dict:
        raw_value = self.driver.read_digital_io(self.pin)
        occupied = not raw_value if self.active_low else raw_value
        state = SensorState.OCCUPIED.value if occupied else SensorState.FREE.value
        return {
            "sensor_id": self.sensor_id,
            "state": state,
        }
