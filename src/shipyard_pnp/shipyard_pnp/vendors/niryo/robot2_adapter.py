from typing import Callable, Optional

from shipyard_pnp.shared.contracts import RobotState, VisionState
from shipyard_pnp.vendors.niryo.niryo_service_driver import NiryoServiceDriver


_ROBOT2_POSITIONS = {
    "home": [-0.0007, 0.4994, -1.2506, 0.0001, 0.0014, -0.0030],
    "at_capture_c2s2": [
        -1.7631204505189255,
        -0.17474191959869845,
        -0.7067526594744095,
        -0.11495590550163026,
        -0.9557626844425475,
        -1.1580628412638663,
    ],
    "prepick_c2s2": [-1.7190, -0.2611, -0.5734, -0.1226, -0.7794, -0.5936],
    "pick_c2s2": [-1.7129, -0.4277, -0.6037, -0.0597, -0.5953, -0.0014],
    "approach_place_c4": [-0.4269, 0.1646, -0.2750, -0.0398, -1.2963, -0.6917],
    "preplace_c4": [-0.0920, -0.7898, 0.2431, -0.1088, -0.9926, -0.7332],
    "place_c4": [-0.0997, -0.8777, 0.2855, 0.0062, -0.9358, 0.1903],
    "approach_bantam": [0.4269, -0.0005, 0.2431, 0.0139, -1.4865, -1.4848],
    "preplace_bantam": [0.4969, -0.6838, -0.0826, -0.0245, -0.8177, -1.5968],
    "place_bantam": [0.4421, -0.7125, -0.1659, 0.0967, -0.6903, -0.0045],
    "pick_bantam": [0.4223, -0.7610, -0.2174, 0.1672, -0.5553, -0.0014],
    "approach_ibs": [-1.8392, -0.2111, 0.2401, -0.0628, -1.5555, -1.5876],
    "preplace_ibs": [-2.1908, -0.7110, 0.5143, -0.6166, -1.1490, -1.2900],
    "place_ibs": [-2.2486, -0.7913, 0.5385, -0.4693, -1.1475, -1.2915],
    "prepick_ibs": [-1.8255, -0.5398, -0.0977, -0.5752, -1.0570, -1.1979],
    "pick_ibs": [-1.8635, -0.6564, -0.0871, -0.5628, -1.0140, 0.0491],
    "approach_scrap": [-0.3766, 0.2494, -0.0690, 0.0415, -1.2840, -1.5630],
    "preplace_scrap": [-0.3766, 0.0873, -0.9416, 0.0875, -0.7962, -1.7072],
    "place_scrap": [-0.3766, 0.0873, -0.9416, 0.0875, -0.7962, -1.7072],
}
    #VALORES PARA BANTAM FISICA
    #  "approach_bantam": [1.6338, -0.2171, -0.1628, -0.0535, -1.3085, -0.0106],
    # "preplace_bantam": [1.6794, -0.8291, 0.4567, -0.0336, -1.2196, -0.0106],
    # "place_bantam": [1.6459, -0.8685, 0.4112, -0.0505, -1.0922, 0.0077],
    # "pick_bantam": [1.6094, -0.9473, 0.4749, 0.0246, -1.1551, 0.3176],


class Robot2Adapter:
    """Robot2 adapter with internal Niryo vacuum control."""

    def __init__(self, driver: NiryoServiceDriver):
        self.driver = driver
        self._placed_at_c4 = False

    def initialize(self, status_cb: Optional[Callable] = None) -> dict:
        self._status(status_cb, RobotState.INITIALIZING.value, "INITIALIZING")
        self.driver.initialize_robot(use_vacuum=True)
        self.driver.vacuum("push")
        self._move("home", "Robot2 HOME", status_cb)
        self._status(status_cb, RobotState.IDLE.value, "IDLE")
        return {"resource_state": RobotState.IDLE.value, "code": "INITIALIZED"}

    def capture_local_vision(
        self,
        vision_adapter,
        status_cb: Optional[Callable] = None,
        vision_status_cb: Optional[Callable] = None,
    ) -> dict:
        self._status(status_cb, RobotState.WAITING_FOR_VISION.value, "GOING_TO_CAPTURE")
        self._move("at_capture_c2s2", "Robot2 capture C2S2", status_cb)
        if vision_status_cb:
            vision_status_cb(VisionState.SCANNING.value, {"code": "SCANNING"})
        result = vision_adapter.capture(vision_status_cb)
        self._status(status_cb, RobotState.IDLE.value, "VISION_RESULT_READY")
        return {
            "resource_state": RobotState.IDLE.value,
            "code": "VISION_RESULT_READY",
            "color": result["color"],
            "shape": result.get("shape", "UNKNOWN"),
        }

    def move_piece(
        self,
        source: str,
        target: str,
        status_cb: Optional[Callable] = None,
    ) -> dict:
        source = self._normalize_location(source)
        target = self._normalize_location(target)

        if source == "C2S2":
            self._pick_c2s2(status_cb)
            if target == "C4":
                self._place_c4(status_cb)
            elif target == "BANTAM_BED":
                self._place_bantam(status_cb)
            elif target == "IBS_BED":
                self._place_ibs(status_cb)
            elif target == "SCRAP":
                self._place_scrap(status_cb)
            else:
                raise ValueError(f"Unsupported robot2 target: {target}")
        elif source == "BANTAM_BED" and target == "C4":
            self._pick_bantam(status_cb)
            self._place_c4(status_cb)
        elif source == "IBS_BED" and target == "BANTAM_BED":
            self._pick_ibs(status_cb)
            self._place_bantam(status_cb)
        else:
            raise ValueError(f"Unsupported robot2 move: {source} -> {target}")

        if target == "C4":
            # Retraction + home happen via RETURN_HOME sent by classification_rules,
            # so the PLACED_C4 callback fires immediately at deposit moment.
            return {
                "resource_state": RobotState.PLACE_DONE.value,
                "code": "PLACED_C4",
                "source": source,
                "target": target,
            }
        self._status(status_cb, RobotState.IDLE.value, "IDLE")
        return {
            "resource_state": RobotState.IDLE.value,
            "code": "MOVE_DONE",
            "source": source,
            "target": target,
        }

    def move_home(self, status_cb: Optional[Callable] = None) -> dict:
        self._status(status_cb, RobotState.RETURNING_HOME.value, "RETURNING_HOME")
        self.driver.vacuum("push")
        if self._placed_at_c4:
            self._move("preplace_c4", "Retorno pre-place C4", status_cb)
            self._move("approach_place_c4", "Retorno C4", status_cb)
            self._placed_at_c4 = False
        self._move("home", "Robot2 HOME", status_cb)
        self._status(status_cb, RobotState.IDLE.value, "IDLE")
        return {"resource_state": RobotState.IDLE.value, "code": "HOME"}

    def reset(self, status_cb: Optional[Callable] = None) -> dict:
        return self.move_home(status_cb)

    def _pick_c2s2(self, status_cb: Optional[Callable]) -> None:
        self._status(status_cb, RobotState.PICKING.value, "PICKING_C2S2")
        self._move("prepick_c2s2", "Robot2 pre-pick C2S2", status_cb)
        self._move("pick_c2s2", "Robot2 pick C2S2", status_cb)
        self.driver.vacuum("pull")
        self._status(status_cb, RobotState.PICK_DONE.value, "PICKING_C2S2_DONE")
        self._move("prepick_c2s2", "Robot2 post-pick C2S2", status_cb)

    def _pick_bantam(self, status_cb: Optional[Callable]) -> None:
        self._status(status_cb, RobotState.PICKING.value, "PICKING_BANTAM")
        self._move("approach_bantam", "Robot2 approach Bantam pick", status_cb)
        self._move("preplace_bantam", "Robot2 pre-pick Bantam", status_cb)
        self._move("pick_bantam", "Robot2 pick Bantam", status_cb)
        self.driver.vacuum("pull")
        self._status(status_cb, RobotState.PICK_DONE.value, "PICKING_BANTAM_DONE")
        self._move("preplace_bantam", "Robot2 post-pick Bantam", status_cb)
        self._move("approach_bantam", "Robot2 return Bantam", status_cb)

    def _place_c4(self, status_cb: Optional[Callable]) -> None:
        self._status(status_cb, RobotState.GOING_TO_POSITION.value, "MOVING_TO_C4")
        self._move("approach_place_c4", "Robot2 approach C4", status_cb)
        self._move("preplace_c4", "Robot2 pre-place C4", status_cb)
        self._move("place_c4", "Robot2 place C4", status_cb)
        self._status(status_cb, RobotState.PLACING.value, "PLACING_C4")
        self.driver.vacuum("push")
        self._placed_at_c4 = True
        self._status(status_cb, RobotState.PLACE_DONE.value, "PLACING_C4_DONE")
        # Retraction happens in move_home so the PLACED_C4 callback fires
        # immediately after vacuum_push — conveyor starts at exact deposit moment.

    def _place_bantam(self, status_cb: Optional[Callable]) -> None:
        self._status(status_cb, RobotState.PLACING.value, "PLACING_BANTAM")
        self._move("approach_bantam", "Robot2 approach Bantam", status_cb)
        self._move("preplace_bantam", "Robot2 pre-place Bantam", status_cb)
        self._move("place_bantam", "Robot2 place Bantam", status_cb)
        self.driver.vacuum("push")
        self._status(status_cb, RobotState.PLACE_DONE.value, "PLACING_BANTAM_DONE")
        self._move("preplace_bantam", "Robot2 post-place Bantam", status_cb)
        self._move("approach_bantam", "Robot2 return Bantam", status_cb)
        self.move_home(status_cb)

    def _pick_ibs(self, status_cb: Optional[Callable]) -> None:
        self._status(status_cb, RobotState.PICKING.value, "PICKING_IBS")
        self._move("approach_ibs", "Robot2 approach IBS pick", status_cb)
        self._move("prepick_ibs", "Robot2 pre-pick IBS", status_cb)
        self._move("pick_ibs", "Robot2 pick IBS", status_cb)
        self.driver.vacuum("pull")
        self._status(status_cb, RobotState.PICK_DONE.value, "PICKING_IBS_DONE")
        self._move("prepick_ibs", "Robot2 post-pick IBS", status_cb)
        self._move("approach_ibs", "Robot2 retract IBS", status_cb)

    def _place_ibs(self, status_cb: Optional[Callable]) -> None:
        self._status(status_cb, RobotState.PLACING.value, "PLACING_IBS")
        self._move("approach_ibs", "Robot2 approach IBS", status_cb)
        self._move("preplace_ibs", "Robot2 pre-place IBS", status_cb)
        self._move("place_ibs", "Robot2 place IBS", status_cb)
        self.driver.vacuum("push")
        self._status(status_cb, RobotState.PLACE_DONE.value, "PLACING_IBS_DONE")
        self._move("preplace_ibs", "Robot2 post-place IBS", status_cb)
        self._move("approach_ibs", "Robot2 retract IBS", status_cb)
        self.move_home(status_cb)

    def _place_scrap(self, status_cb: Optional[Callable]) -> None:
        self._status(status_cb, RobotState.PLACING.value, "PLACING_SCRAP")
        self._move("approach_scrap", "Robot2 approach Scrap", status_cb)
        self._move("preplace_scrap", "Robot2 pre-place Scrap", status_cb)
        self._move("place_scrap", "Robot2 place Scrap", status_cb)
        self.driver.vacuum("push")
        self._status(status_cb, RobotState.PLACE_DONE.value, "PLACING_SCRAP_DONE")
        self._move("preplace_scrap", "Robot2 post-place Scrap", status_cb)
        self._move("approach_scrap", "Robot2 return Scrap", status_cb)
        self.move_home(status_cb)

    def _move(
        self,
        position: str,
        description: str,
        status_cb: Optional[Callable],
    ) -> None:
        if position not in _ROBOT2_POSITIONS:
            raise ValueError(f"Unsupported robot2 position: {position}")
        self._status(
            status_cb,
            RobotState.GOING_TO_POSITION.value,
            "MOVING",
            position=position,
            description=description,
        )
        self.driver.move_joints(_ROBOT2_POSITIONS[position], description)

    @staticmethod
    def _normalize_location(value: str) -> str:
        normalized = str(value or "").strip().upper()
        if not normalized:
            raise ValueError("Robot2 source/target is required")
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
