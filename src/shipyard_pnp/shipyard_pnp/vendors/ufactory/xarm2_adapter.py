from typing import Callable, Optional

from shipyard_pnp.shared.contracts import RobotState
from shipyard_pnp.vendors.ufactory.lite6_service_driver import Lite6ServiceDriver


_XARM2_POSITIONS = {
    "home": [0.0000, 0.1733, 0.5550, 0.0002, 0.3817, -0.0002, 0.0],
    "approach_s1": [0.0496, 0.4107, 1.2834, 0.1398, 0.3571, -1.5417, 0.0],
    "approach_s1.1": [0.1335, 0.3127, 0.6301, 0.3204, -0.3981, -1.6550, 0.0],
    "pick_s1.1": [0.1440, 0.5043, 0.7339, 0.5758, -0.4537, -1.9499, 0.0],
    "approach_s1.2": [0.0784, 0.3858, 0.8651, 0.5031, -0.1353, -2.0785, 0.0],
    "pick_s1.2": [0.1047, 0.5199, 0.8654, 0.5595, -0.3503, -2.1148, 0.0],
    "approach_s1.3": [0.0370, 0.4703, 1.1198, 0.2660, 0.1556, -1.9248, 0.0],
    "pick_s1.3": [0.0415, 0.6010, 1.1696, -0.1423, 0.0173, -1.3754, 0.0],
    "approach_s1.4": [0.0260, 0.5915, 1.3520, 0.3494, 0.2247, -2.0433, 0.0],
    "pick_s1.4": [0.0490, 0.6733, 1.3520, -0.1415, 0.0827, -1.4444, 0.0],
    "approach_s1.5": [0.0600, 0.6714, 1.5348, -0.1390, 0.2303, -1.2652, 0.0],
    "pick_s1.5": [0.0715, 0.8108, 1.6746, -0.3060, 0.3478, -1.3758, 0.0],
    "approach_s1.6": [0.0842, 0.8071, 1.8861, -0.3250, 0.5549, -1.1911, 0.0],
    "pick_s1.6": [0.0453, 0.9688, 2.0131, -0.0853, 0.4600, -1.3721, 0.0],
    "approach_s2": [-0.0642, 0.4163, 1.2137, -0.0639, 0.2567, -1.6166, 0.0],
    "approach_s2.1": [-0.0972, 0.3086, 0.7196, -0.0621, -0.1186, -1.7455, 0.0],
    "pick_s2.1": [-0.1189, 0.4922, 0.7269, -0.0247, -0.3650, -1.8065, 0.0],
    "approach_s2.2": [-0.0884, 0.4252, 0.9092, 0.3162, -0.0628, -2.0592, 0.0],
    "pick_s2.2": [-0.0886, 0.5271, 0.9114, 0.2025, -0.2525, -1.9240, 0.0],
    "approach_s2.3": [-0.1174, 0.4911, 1.1538, 0.3319, 0.2103, -2.0876, 0.0],
    "pick_s2.3": [-0.0964, 0.6008, 1.1531, 0.3875, -0.0067, -2.0947, 0.0],
    "approach_s2.4": [-0.0850, 0.5572, 1.3285, 0.5469, 0.1563, -2.1915, 0.0],
    "pick_s2.4": [-0.0965, 0.6626, 1.3201, 0.3150, 0.0607, -2.1146, 0.0],
    "approach_s2.5": [-0.0450, 0.7487, 1.7116, -0.1544, 0.5058, -1.4676, 0.0],
    "pick_s2.5": [-0.0588, 0.8280, 1.7112, -0.2048, 0.3886, -1.4454, 0.0],
    "approach_s2.6": [-0.0588, 0.8852, 1.9916, -0.0430, 0.5584, -1.6084, 0.0],
    "pick_s2.6": [-0.0603, 0.9584, 1.9918, -0.1116, 0.4421, -1.5835, 0.0],
    "approach_s3": [-0.2630, 0.5467, 1.5073, 0.2328, 0.6058, -2.1211, 0.0],
    "approach_s3.1": [-0.2624, 0.4170, 0.8264, 0.0736, -0.0634, -2.0651, 0.0],
    "pick_s3.1": [-0.2624, 0.5264, 0.8263, 0.0483, -0.2413, -2.0341, 0.0],
    "approach_s3.2": [-0.2524, 0.4315, 0.9934, -0.0639, 0.0546, -1.7347, 0.0],
    "pick_s3.2": [-0.2666, 0.5641, 0.9932, -0.1551, -0.1470, -1.6228, 0.0],
    "approach_s3.3": [-0.2259, 0.4855, 1.1004, -0.0966, -0.0326, -1.6862, 0.0],
    "pick_s3.3": [-0.2328, 0.6160, 1.1545, -0.0750, -0.0781, -1.7386, 0.0],
    "approach_s3.4": [-0.2113, 0.5950, 1.3288, 0.2144, 0.1032, -2.1236, 0.0],
    "pick_s3.4": [-0.1912, 0.7201, 1.4419, -0.2533, 0.1935, -1.7025, 0.0],
    "approach_s3.5": [-0.1929, 0.7057, 1.6159, 0.0878, 0.2764, -1.8015, 0.0],
    "pick_s3.5": [-0.1954, 0.8407, 1.7253, 0.0061, 0.3272, -1.7043, 0.0],
    "approach_s3.6": [-0.1919, 0.9222, 2.0402, 0.0593, 0.5843, -1.7817, 0.0],
    "pick_s3.6": [-0.1823, 0.9890, 2.0399, 0.0132, 0.4329, -1.6766, 0.0],
    "approach_c1s1": [-0.6683, 0.4351, 1.0470, 0.1187, 0.6829, -2.3069, 0.0],
    "place_c1s1": [-0.6573, 0.6776, 0.9809, 0.1797, 0.3599, -2.3673, 0.0],
    "approach_c3": [-2.5459, 0.4384, 1.6066, -0.0023, 1.0910, -0.9033, 0.0],
    "preplace_c3": [-2.5342, 0.7958, 1.4726, -0.0970, 0.6843, -0.9129, 0.0],
    "place_c3": [-2.5791, 0.9619, 1.5154, -0.0660, 0.6067, -0.8245, 0.0],
}


class XArm2Adapter:
    def __init__(self, driver: Lite6ServiceDriver):
        self.driver = driver
        self._placed_at_c3 = False

    def initialize(self, status_cb: Optional[Callable] = None) -> dict:
        self._status(status_cb, RobotState.INITIALIZING.value, "INITIALIZING")
        self.driver.initialize_motion()
        self.driver.vacuum_off()
        self._move("home", "Inicializando a HOME", 30.0, 100.0, status_cb)
        self._status(status_cb, RobotState.IDLE.value, "IDLE")
        return {"resource_state": RobotState.IDLE.value, "code": "INITIALIZED"}

    def move_home(self, status_cb: Optional[Callable] = None) -> dict:
        self._status(status_cb, RobotState.RETURNING_HOME.value, "RETURNING_HOME")
        if self._placed_at_c3:
            self._move("preplace_c3", "Retorno Pre-Place C3", 25.0, 80.0, status_cb)
            self._move("approach_c3", "Retorno C3", 30.0, 100.0, status_cb)
            self._placed_at_c3 = False
        self._move("home", "Volviendo a HOME", 30.0, 100.0, status_cb)
        self.driver.vacuum_off()
        self._status(status_cb, RobotState.IDLE.value, "IDLE")
        return {"resource_state": RobotState.IDLE.value, "code": "HOME"}

    def reset(self, status_cb: Optional[Callable] = None) -> dict:
        return self.move_home(status_cb)

    def move_piece(
        self,
        pick_slot: str,
        target: str,
        route: str = "",
        status_cb: Optional[Callable] = None,
    ) -> dict:
        pick_slot = self._normalize_slot(pick_slot)
        target = self._normalize_location(target)
        route = (route or "").upper()

        if target not in {"C1S1", "C3"}:
            raise ValueError(f"Unsupported xarm2 target: {target}")

        self._pick_from_slot(pick_slot, status_cb)
        if target == "C3":
            self._place_to_c3(status_cb)
            # Robot is retracted near C3 approach — caller sends MOVE_XARM_HOME separately.
            return {
                "resource_state": RobotState.PLACE_DONE.value,
                "code": "PLACED_C3",
                "pick_slot": pick_slot,
                "target": target,
                "route": route,
            }

        self._place_to_c1s1(status_cb)
        self._status(status_cb, RobotState.IDLE.value, "IDLE")
        return {
            "resource_state": RobotState.IDLE.value,
            "code": "MOVE_DONE",
            "pick_slot": pick_slot,
            "target": target,
            "route": route,
        }

    def _pick_from_slot(self, slot_id: str, status_cb: Optional[Callable]) -> None:
        stack = slot_id.split(".")[0]
        approach_stack = f"approach_{stack}"
        approach_slot = f"approach_{slot_id}"
        pick_slot = f"pick_{slot_id}"
        for key in (approach_stack, approach_slot, pick_slot):
            if key not in _XARM2_POSITIONS:
                raise ValueError(f"Unsupported xarm2 slot position: {key}")

        self._status(status_cb, RobotState.GOING_TO_POSITION.value, "GOING_TO_PICK")
        self._move("home", "HOME inicial", 30.0, 100.0, status_cb)
        self._move(approach_stack, f"Approach {stack.upper()}", 30.0, 100.0, status_cb)
        self._move(approach_slot, f"Approach {slot_id.upper()}", 25.0, 80.0, status_cb)
        self._move(pick_slot, f"Pick {slot_id.upper()}", 20.0, 60.0, status_cb)

        self._status(status_cb, RobotState.PICKING.value, "PICKING_INITIAL_STACK")
        self.driver.vacuum_on()
        self._status(status_cb, RobotState.PICK_DONE.value, "PICKING_INITIAL_STACK_DONE")

        self._move(approach_slot, f"Retorno {slot_id.upper()}", 25.0, 80.0, status_cb)
        self._move(approach_stack, f"Retorno {stack.upper()}", 30.0, 100.0, status_cb)
        self._move("home", "HOME intermedio", 30.0, 100.0, status_cb)

    def _place_to_c1s1(self, status_cb: Optional[Callable]) -> None:
        self._status(status_cb, RobotState.GOING_TO_POSITION.value, "MOVING_TO_C1S1")
        self._move("approach_c1s1", "Approach C1S1", 30.0, 100.0, status_cb)
        self._move("place_c1s1", "Place C1S1", 30.0, 100.0, status_cb)

        self._status(status_cb, RobotState.PLACING.value, "PLACING_C1S1")
        self.driver.vacuum_off()
        self._status(status_cb, RobotState.PLACE_DONE.value, "PLACING_C1S1_DONE")

        self._move("approach_c1s1", "Retorno C1S1", 30.0, 100.0, status_cb)
        self.move_home(status_cb)

    def _place_to_c3(self, status_cb: Optional[Callable]) -> None:
        self._status(status_cb, RobotState.GOING_TO_POSITION.value, "MOVING_TO_C3")
        self._move("approach_c3", "Approach C3", 30.0, 100.0, status_cb)
        self._move("preplace_c3", "Pre-Place C3", 25.0, 80.0, status_cb)
        self._move("place_c3", "Place C3", 20.0, 60.0, status_cb)

        self._status(status_cb, RobotState.PLACING.value, "PLACING_C3")
        self.driver.vacuum_off()
        self._placed_at_c3 = True
        self._status(status_cb, RobotState.PLACE_DONE.value, "PLACING_C3_DONE")
        # Retraction happens in move_home so the PLACED_C3 callback fires
        # immediately after vacuum_off — conveyor starts at exact deposit moment.

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
        self.driver.move_joint(_XARM2_POSITIONS[position], description, speed, acc)

    @staticmethod
    def _normalize_location(value: str) -> str:
        return str(value or "").strip().upper()

    @staticmethod
    def _normalize_slot(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized:
            raise ValueError("xarm2 pick_slot is required")
        return normalized

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
