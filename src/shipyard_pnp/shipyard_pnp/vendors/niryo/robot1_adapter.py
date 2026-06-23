from typing import Callable, Optional

from shipyard_pnp.shared.contracts import RobotState, VisionState
from shipyard_pnp.vendors.niryo.niryo_service_driver import NiryoServiceDriver


_ROBOT1_POSITIONS = {
    "home": [-0.0007, 0.4994, -1.2506, -0.0014, -0.0016, 0.0078],
    "at_capture_c3": [1.7342, -0.2671, -0.4083, -0.0244, -1.0293, 0.4464],
    "prepick_c3": [1.6993, -0.5929, -0.0629, 0.0292, -0.9757, 0.0078],
    "pick_c3": [
        1.7068733551261208,
        -0.7595109948208946,
        -0.13713304215952427,
        0.10747130874178756,
        -0.713393719956616,
        -0.16557727150185642,
    ],
    "at_capture_c4": [0.2321, 0.4857, -1.1597, 0.0215, -1.0293, 0.4357],
    "prepick_c4": [0.1758, 0.0071, -0.9673, -0.0260, -0.5907, 0.2777],
    "pick_c4": [
        0.2260382792960196,
        -0.2413995343908658,
        -1.0339809502723223,
        0.17036452104509925,
        -0.2746752146213227,
        -0.1763151370170557,
    ],
    "approach_submarine": [-1.5668, 0.3403, -0.5219, -0.1441, -1.4129, 0.3959],
    # SQUARE final stacks
    "approach_blue_final_square": [-1.5637, -0.3474, 0.1265, -0.0245, -1.2150, 0.2946],
    "approach_green_final_square": [-1.5637, -0.3474, 0.1265, -0.0245, -1.2150, 0.2946],
    "approach_red_final_square": [-1.5637, -0.3474, 0.1265, -0.0245, -1.2150, 0.2946],
    "preplace_blue_final_square": [-1.3492, -0.2535, 0.1174, 0.5891, -1.5279, -0.3527],
    "place_blue_final_square": [-1.3659, -0.1899, -0.1159, 0.9818, -1.3362, -0.7654],
    "preplace_green_final_square": [-1.5181, -0.5489, 0.5340, 0.8929, -1.1905, -0.7638],
    "place_green_final_square": [-1.4116, -0.6807, 0.5976, 1.0018, -1.1061, -0.7638],
    "preplace_red_final_square": [-1.6855, -0.5005, -0.0811, 0.9404, -1.2626, -0.7654],
    "place_red_final_square": [-1.4283, -0.6201, -0.0674, 0.9972, -1.0769, -0.6120],
    # CIRCLE final stacks
    "approach_blue_final_circle":  [-1.5196, -0.0460, -0.4295, -0.9863, -1.0739, -0.0919],
    "approach_green_final_circle": [-1.5653, -0.5595,  0.4007, -0.5767, -1.0739,  0.1121],
    "approach_red_final_circle":   [-1.5531, -0.5520, -0.0099, -0.5874, -1.0509,  0.1167],
    "preplace_blue_final_circle":  [-1.7540, -0.1278, -0.2629, -1.2915, -1.0769, -0.0919],
    "place_blue_final_circle":     [-1.8636, -0.2156, -0.1493, -1.1151, -1.0739,  0.1151],
    "preplace_green_final_circle": [-1.5896, -0.7035,  0.5522, -1.2746, -1.2580,  0.1151],
    "place_green_final_circle":    [-1.7844, -0.7535,  0.5507, -1.2225, -1.0631,  0.1182],
    "preplace_red_final_circle":   [-1.6414, -0.6262, -0.0629, -0.9433, -1.0509,  0.1182],
    "place_red_final_circle":      [-1.7327, -0.6883, -0.0447, -1.2869, -1.0524,  0.1197],
    "approach_scrap": [-0.0007, 0.4994, -1.2506, -0.0014, -0.0016, 0.0078],
    "preplace_scrap": [-0.0007, 0.4994, -1.2506, -0.0014, -0.0016, 0.0078],
    "place_scrap": [-0.0007, 0.4994, -1.2506, -0.0014, -0.0016, 0.0078],
}


_FINAL_TARGETS = {
    "FINAL_BLUE_STACK": "blue_final_square",
    "FINAL_GREEN_STACK": "green_final_square",
    "FINAL_RED_STACK": "red_final_square",
    "FINAL_BLUE_CIRCLE": "blue_final_circle",
    "FINAL_GREEN_CIRCLE": "green_final_circle",
    "FINAL_RED_CIRCLE": "red_final_circle",
    "SCRAP": "scrap",
}


class Robot1Adapter:
    """Robot1 motion adapter. The external Arduino vacuum is a separate domain."""

    def __init__(self, driver: NiryoServiceDriver):
        self.driver = driver
        self._last_pick_position: Optional[str] = None
        self._last_target_key: Optional[str] = None
        self._at_place_position = False

    def initialize(self, status_cb: Optional[Callable] = None) -> dict:
        self._status(status_cb, RobotState.INITIALIZING.value, "INITIALIZING")
        self.driver.initialize_robot(use_vacuum=False)
        self._move("home", "Robot1 HOME", status_cb)
        self._at_place_position = False
        self._status(status_cb, RobotState.IDLE.value, "IDLE")
        return {"resource_state": RobotState.IDLE.value, "code": "INITIALIZED"}

    def classify_and_goto_pick(
        self,
        position: str,
        vision_adapter,
        status_cb: Optional[Callable] = None,
        vision_status_cb: Optional[Callable] = None,
    ) -> dict:
        """Go to capture position, run YOLO ML, then continue to pick position.

        Returns AT_PICK_POSITION with color+shape embedded in the result so the
        factory supervisor can route directly without a separate vision command.
        """
        pick_position = self._normalize_pick_position(position)
        prefix = pick_position.lower()

        self._status(status_cb, RobotState.GOING_TO_POSITION.value,
                     f"GOING_TO_CAPTURE_{pick_position}")
        self._move("home", "Robot1 HOME before capture", status_cb)
        self._move(f"at_capture_{prefix}", f"Robot1 capture {pick_position}", status_cb)

        # ML vision at capture position
        self._status(status_cb, RobotState.WAITING_FOR_VISION.value, "AT_CAPTURE_POSITION")
        if vision_status_cb:
            vision_status_cb(VisionState.SCANNING.value, {"code": "SCANNING"})
        vision_result = vision_adapter.capture(vision_status_cb)

        # Continue to pick
        self._move(f"prepick_{prefix}", f"Robot1 pre-pick {pick_position}", status_cb)
        self._move(f"pick_{prefix}", f"Robot1 pick {pick_position}", status_cb)

        self._last_pick_position = pick_position
        self._at_place_position = False
        self._status(status_cb, RobotState.AT_PICK_POSITION.value, "AT_PICK_POSITION")
        return {
            "resource_state": RobotState.AT_PICK_POSITION.value,
            "code": "AT_PICK_POSITION",
            "position": pick_position,
            "color": vision_result.get("color"),
            "shape": vision_result.get("shape"),
            "confidence": vision_result.get("confidence"),
            "confidence_score": vision_result.get("confidence_score"),
        }

    def goto_pick_position(
        self,
        position: str,
        status_cb: Optional[Callable] = None,
    ) -> dict:
        pick_position = self._normalize_pick_position(position)
        prefix = pick_position.lower()
        self._status(
            status_cb,
            RobotState.GOING_TO_POSITION.value,
            f"GOING_TO_{pick_position}",
        )
        self._move("home", "Robot1 HOME before pick", status_cb)
        self._move(f"at_capture_{prefix}", f"Robot1 capture {pick_position}", status_cb)
        self._move(f"prepick_{prefix}", f"Robot1 pre-pick {pick_position}", status_cb)
        self._move(f"pick_{prefix}", f"Robot1 pick {pick_position}", status_cb)
        self._last_pick_position = pick_position
        self._at_place_position = False
        self._status(status_cb, RobotState.AT_PICK_POSITION.value, "AT_PICK_POSITION")
        return {
            "resource_state": RobotState.AT_PICK_POSITION.value,
            "code": "AT_PICK_POSITION",
            "position": pick_position,
        }

    def lift_and_place(
        self,
        target: str,
        status_cb: Optional[Callable] = None,
    ) -> dict:
        target_key = self._target_key(target)
        self._status(status_cb, RobotState.PICK_DONE.value, "EXTERNAL_VACUUM_PICK_DONE")
        if self._last_pick_position:
            self._move(
                f"prepick_{self._last_pick_position.lower()}",
                "Robot1 lift after pick",
                status_cb,
            )
        self._move("home", "Robot1 HOME after pick", status_cb)

        self._status(status_cb, RobotState.PLACING.value, "GOING_TO_FINAL_PLACE")
        self._move("approach_submarine", "Robot1 approach final zone", status_cb)
        for key in self._place_path(target_key):
            self._move(key, f"Robot1 {key}", status_cb)

        self._last_target_key = target_key
        self._at_place_position = True
        self._status(status_cb, RobotState.AT_PLACE_POSITION.value, "AT_PLACE_POSITION")
        return {
            "resource_state": RobotState.AT_PLACE_POSITION.value,
            "code": "AT_PLACE_POSITION",
            "target": self._normalize_target(target),
        }

    def move_home(self, status_cb: Optional[Callable] = None) -> dict:
        self._status(status_cb, RobotState.RETURNING_HOME.value, "RETURNING_HOME")
        if self._at_place_position and self._last_target_key:
            for key in reversed(self._place_path(self._last_target_key)[:-1]):
                self._move(key, f"Robot1 return {key}", status_cb)
            if self._last_target_key != "scrap":
                self._move(
                    "approach_submarine",
                    "Robot1 return final zone",
                    status_cb,
                )
        self._move("home", "Robot1 HOME", status_cb)
        self._last_pick_position = None
        self._last_target_key = None
        self._at_place_position = False
        self._status(status_cb, RobotState.IDLE.value, "IDLE")
        return {"resource_state": RobotState.IDLE.value, "code": "HOME"}

    def reset(self, status_cb: Optional[Callable] = None) -> dict:
        return self.move_home(status_cb)

    def _place_path(self, target_key: str) -> list:
        if target_key == "scrap":
            return ["approach_scrap", "preplace_scrap", "place_scrap"]
        return [
            f"approach_{target_key}",
            f"preplace_{target_key}",
            f"place_{target_key}",
        ]

    def _move(
        self,
        position: str,
        description: str,
        status_cb: Optional[Callable],
    ) -> None:
        if position not in _ROBOT1_POSITIONS:
            raise ValueError(f"Unsupported robot1 position: {position}")
        self._status(
            status_cb,
            RobotState.GOING_TO_POSITION.value,
            "MOVING",
            position=position,
            description=description,
        )
        self.driver.move_joints(_ROBOT1_POSITIONS[position], description)

    @staticmethod
    def _normalize_pick_position(position: str) -> str:
        normalized = str(position or "").strip().upper()
        if normalized not in {"C3", "C4"}:
            raise ValueError(f"Unsupported robot1 pick position: {position}")
        return normalized

    @staticmethod
    def _normalize_target(target: str) -> str:
        return str(target or "").strip().upper()

    def _target_key(self, target: str) -> str:
        normalized = self._normalize_target(target)
        if normalized not in _FINAL_TARGETS:
            raise ValueError(f"Unsupported robot1 target: {target}")
        return _FINAL_TARGETS[normalized]

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
