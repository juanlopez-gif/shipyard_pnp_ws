from typing import Callable, Optional

from shipyard_pnp.shared.contracts import VacuumState
from shipyard_pnp.vendors.niryo.niryo_service_driver import NiryoServiceDriver


class Robot2NiryoVacuumAdapter:
    def __init__(self, driver: NiryoServiceDriver):
        self.driver = driver

    def pick(self, status_cb: Optional[Callable] = None) -> dict:
        self._status(status_cb, VacuumState.PICKING.value, "PICKING")
        self.driver.vacuum("pull")
        self._status(status_cb, VacuumState.PICK_DONE.value, "PICK_DONE")
        return {"resource_state": VacuumState.PICK_DONE.value, "code": "PICK_DONE"}

    def release(self, status_cb: Optional[Callable] = None) -> dict:
        self._status(status_cb, VacuumState.RELEASING.value, "RELEASING")
        self.driver.vacuum("push")
        self._status(status_cb, VacuumState.RELEASE_DONE.value, "RELEASE_DONE")
        return {
            "resource_state": VacuumState.RELEASE_DONE.value,
            "code": "RELEASE_DONE",
        }

    def off(self, status_cb: Optional[Callable] = None) -> dict:
        self.driver.vacuum("neutral")
        self._status(status_cb, VacuumState.IDLE.value, "IDLE")
        return {"resource_state": VacuumState.IDLE.value, "code": "IDLE"}

    @staticmethod
    def _status(
        status_cb: Optional[Callable],
        resource_state: str,
        code: str,
    ) -> None:
        if status_cb:
            status_cb(resource_state, {"code": code})
