from typing import Callable, Optional

from shipyard_pnp.shared.contracts import RobotState
from shipyard_pnp.vendors.ufactory.lite6_service_driver import Lite6ServiceDriver


_XARM1_POSITIONS = {
    "home": [0.0000, 0.1733, 0.5550, 0.0000, 0.3816, 0.0000, 0.0],
    "preapproach_c1s2": [-0.0049, -0.6421, 1.2600, -0.1634, 1.8119, 0.6172, 0.0],
    "approach_c1s2": [-1.5077, 0.3618, 1.0069, 0.0027, 0.4845, 0.0228, 0.0],
    "pick_c1s2": [-1.4721, 0.7055, 1.0129, -0.1615, 0.1161, 0.2261, 0.0],
    "preapproach_laser": [-0.1608, 0.7263, 1.9174, -0.0447, 1.1176, -0.0385, 0.0],
    "approach_laser": [-0.2428, 1.3724, 2.1971, -0.0968, 0.7393, -0.2100, 0.0],
    "place_laser": [-0.2441, 1.5071, 2.1950, -0.0683, 0.6138, -0.1492, 0.0],
    "preapproach_c2s2": [0.9647, 0.3348, 2.1943, 0.0882, 1.7904, -0.5509, 0.0],
    "approach_c2s2": [0.7886, 0.8259, 1.5257, 0.0805, 0.5908, -1.0071, 0.0],
    "place_c2s1": [0.7801, 0.9726, 1.5270, 0.2084, 0.4895, -1.0389, 0.0],
}


class XArm1Adapter:
    def __init__(self, driver: Lite6ServiceDriver):
        self.driver = driver

    def initialize(self, status_cb: Optional[Callable] = None) -> dict:
        self._status(status_cb, RobotState.INITIALIZING.value, "INITIALIZING")
        self.driver.initialize_motion()
        self.driver.vacuum_off()
        self._move("home", "Inicializando a HOME", 30.0, 100.0, status_cb)
        self._status(status_cb, RobotState.IDLE.value, "IDLE")
        return {"resource_state": RobotState.IDLE.value, "code": "INITIALIZED"}

    def move_home(self, status_cb: Optional[Callable] = None) -> dict:
        self._status(status_cb, RobotState.RETURNING_HOME.value, "RETURNING_HOME")
        self._move("home", "Volviendo a HOME", 30.0, 100.0, status_cb)
        self.driver.vacuum_off()
        self._status(status_cb, RobotState.IDLE.value, "IDLE")
        return {"resource_state": RobotState.IDLE.value, "code": "HOME"}

    def reset(self, status_cb: Optional[Callable] = None) -> dict:
        return self.move_home(status_cb)

    def move_piece(
        self,
        source: str,
        target: str,
        route: str = "",
        status_cb: Optional[Callable] = None,
    ) -> dict:
        source = self._normalize_location(source)
        target = self._normalize_location(target)
        route = (route or "").upper()

        if source == "C1S2" and target == "C2S1":
            self._c1s2_to_c2s1(route, status_cb)
        elif source == "C1S2" and target == "LASER_BED":
            self._c1s2_to_laser(status_cb)
        elif source == "LASER_BED" and target == "C2S1":
            self._laser_to_c2s1(status_cb)
        else:
            raise ValueError(f"Unsupported xarm1 move: {source} -> {target}")

        self._status(status_cb, RobotState.IDLE.value, "IDLE")
        return {
            "resource_state": RobotState.IDLE.value,
            "code": "MOVE_DONE",
            "source": source,
            "target": target,
            "route": route,
        }

    def _c1s2_to_c2s1(self, route: str, status_cb: Optional[Callable]) -> None:
        self._pick_from_c1s2(route or "DIRECT", status_cb)
        self._place_to_c2s1(status_cb)

    def _c1s2_to_laser(self, status_cb: Optional[Callable]) -> None:
        self._pick_from_c1s2("RED", status_cb)
        self._place_to_laser(status_cb)

    def _laser_to_c2s1(self, status_cb: Optional[Callable]) -> None:
        self._pick_from_laser(status_cb)
        self._place_to_c2s1(status_cb)

    def _pick_from_c1s2(self, route: str, status_cb: Optional[Callable]) -> None:
        self._status(status_cb, RobotState.GOING_TO_POSITION.value, "APPROACHING_C1S2")
        self._move("home", f"HOME inicial {route}", 30.0, 100.0, status_cb)
        self._move("preapproach_c1s2", "Pre-Approach C1S2", 30.0, 100.0, status_cb)
        self._move("approach_c1s2", "Approach C1S2", 25.0, 80.0, status_cb)
        self._move("pick_c1s2", "Pick C1S2", 20.0, 60.0, status_cb)

        self._status(status_cb, RobotState.PICKING.value, "PICKING_C1S2")
        self.driver.vacuum_on()
        self._status(status_cb, RobotState.PICK_DONE.value, "PICKING_C1S2_DONE")

        self._move("approach_c1s2", "Retorno C1S2", 25.0, 80.0, status_cb)
        self._move("preapproach_c1s2", "Retorno Pre-Approach C1S2", 25.0, 80.0, status_cb)
        self._move("home", "HOME intermedio", 30.0, 100.0, status_cb)

    def _place_to_c2s1(self, status_cb: Optional[Callable]) -> None:
        self._status(status_cb, RobotState.GOING_TO_POSITION.value, "APPROACHING_C2S1")
        self._move("preapproach_c2s2", "Pre-Approach C2S1", 30.0, 100.0, status_cb)
        self._move("approach_c2s2", "Approach C2S1", 30.0, 100.0, status_cb)
        self._move("place_c2s1", "Place C2S1", 30.0, 100.0, status_cb)

        self._status(status_cb, RobotState.PLACING.value, "PLACING_C2S1")
        self.driver.vacuum_off()
        self._status(status_cb, RobotState.PLACE_DONE.value, "PLACING_C2S1_DONE")

        self._move("approach_c2s2", "Retorno C2S1", 30.0, 100.0, status_cb)
        self._move("preapproach_c2s2", "Retorno Pre-Approach C2S1", 30.0, 100.0, status_cb)
        self.move_home(status_cb)

    def _place_to_laser(self, status_cb: Optional[Callable]) -> None:
        self._status(status_cb, RobotState.GOING_TO_POSITION.value, "APPROACHING_LASER")
        self._move("preapproach_laser", "Pre-Approach LASER", 30.0, 100.0, status_cb)
        self._move("approach_laser", "Approach LASER", 30.0, 100.0, status_cb)
        self._move("place_laser", "Place LASER", 30.0, 100.0, status_cb)

        self._status(status_cb, RobotState.PLACING.value, "PLACING_LASER")
        self.driver.vacuum_off()
        self._status(status_cb, RobotState.PLACE_DONE.value, "PLACING_LASER_DONE")

        self._move("approach_laser", "Retorno LASER", 30.0, 100.0, status_cb)
        self._move("preapproach_laser", "Retorno Pre-Approach LASER", 30.0, 100.0, status_cb)
        self.move_home(status_cb)

    def _pick_from_laser(self, status_cb: Optional[Callable]) -> None:
        self._status(status_cb, RobotState.GOING_TO_POSITION.value, "APPROACHING_LASER")
        self._move("home", "HOME inicial PICK_LASER", 30.0, 100.0, status_cb)
        self._move("preapproach_laser", "Pre-Approach LASER", 30.0, 100.0, status_cb)
        self._move("approach_laser", "Approach LASER", 30.0, 100.0, status_cb)
        self._move("place_laser", "Pick LASER", 30.0, 100.0, status_cb)

        self._status(status_cb, RobotState.PICKING.value, "PICKING_LASER")
        self.driver.vacuum_on()
        self._status(status_cb, RobotState.PICK_DONE.value, "PICKING_LASER_DONE")

        self._move("approach_laser", "Retorno LASER", 30.0, 100.0, status_cb)
        self._move("preapproach_laser", "Retorno Pre-Approach LASER", 30.0, 100.0, status_cb)
        self._move("home", "HOME intermedio", 30.0, 100.0, status_cb)

    def _move(
        self,
        position: str,
        description: str,
        speed: float,
        acc: float,
        status_cb: Optional[Callable],
    ) -> None:
        self._status(
            status_cb,
            RobotState.GOING_TO_POSITION.value,
            "MOVING",
            position=position,
            description=description,
        )
        self.driver.move_joint(_XARM1_POSITIONS[position], description, speed, acc)

    @staticmethod
    def _normalize_location(value: str) -> str:
        return str(value or "").strip().upper()

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
