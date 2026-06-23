import time
from typing import Dict, Optional

from shipyard_pnp.shared.contracts import (
    DOMAIN_IDS,
    ConveyorState,
    DomainId,
    MachineState,
    RobotState,
    SensorState,
    VacuumState,
    VisionState,
)

_ROBOTS = ["robot1", "robot2", "xarm1", "xarm2"]
_CONVEYORS = ["conveyor1", "conveyor2", "conveyor3", "conveyor4"]
_SENSORS = ["c1s1", "c1s2", "c2s1", "c2s2", "c3", "c4"]
_MACHINES = ["laser", "bantam"]
_VACUUM = ["arduino_vacuum"]
_VISION = ["vision_robot1", "vision_robot2", "globalvision_camera"]


class StateTracker:
    """
    Tracks the coarse state of every resource and domain.
    Uses only the simplified vocabulary from contracts.py.
    Does NOT track piece locations (PieceTracker) or timing (CycleTracker).
    Not thread-safe on its own — the FactorySupervisor acquires _state_lock
    before every call into this object.
    """

    def __init__(self):
        self.robots: Dict[str, RobotState] = {r: RobotState.NOT_INITIALIZED for r in _ROBOTS}
        self.conveyors: Dict[str, ConveyorState] = {c: ConveyorState.STOPPED for c in _CONVEYORS}
        self.sensors: Dict[str, SensorState] = {s: SensorState.UNKNOWN for s in _SENSORS}
        self.machines: Dict[str, MachineState] = {m: MachineState.NOT_INITIALIZED for m in _MACHINES}
        self.vacuum: Dict[str, VacuumState] = {v: VacuumState.IDLE for v in _VACUUM}
        self.vision: Dict[str, VisionState] = {v: VisionState.IDLE for v in _VISION}
        self.domain_online: Dict[str, bool] = {d: False for d in DOMAIN_IDS}
        self.state_since: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Updaters — each records the transition timestamp in state_since
    # ------------------------------------------------------------------

    def update_robot(self, resource_id: str, state: RobotState) -> None:
        if resource_id not in self.robots:
            return
        self.robots[resource_id] = state
        self.state_since[resource_id] = time.time()

    def update_conveyor(self, resource_id: str, state: ConveyorState) -> None:
        if resource_id not in self.conveyors:
            return
        self.conveyors[resource_id] = state
        self.state_since[resource_id] = time.time()

    def update_sensor(self, resource_id: str, state: SensorState) -> None:
        if resource_id not in self.sensors:
            return
        self.sensors[resource_id] = state
        self.state_since[resource_id] = time.time()

    def update_machine(self, resource_id: str, state: MachineState) -> None:
        if resource_id not in self.machines:
            return
        self.machines[resource_id] = state
        self.state_since[resource_id] = time.time()

    def update_vacuum(self, resource_id: str, state: VacuumState) -> None:
        if resource_id not in self.vacuum:
            return
        self.vacuum[resource_id] = state
        self.state_since[resource_id] = time.time()

    def update_vision(self, resource_id: str, state: VisionState) -> None:
        if resource_id not in self.vision:
            return
        self.vision[resource_id] = state
        self.state_since[resource_id] = time.time()

    def set_domain_online(self, domain_id: str, online: bool) -> None:
        if domain_id in self.domain_online:
            self.domain_online[domain_id] = online

    # ------------------------------------------------------------------
    # Getters
    # ------------------------------------------------------------------

    def get_robot(self, resource_id: str) -> RobotState:
        return self.robots.get(resource_id, RobotState.ERROR)

    def get_conveyor(self, resource_id: str) -> ConveyorState:
        return self.conveyors.get(resource_id, ConveyorState.ERROR)

    def get_sensor(self, resource_id: str) -> SensorState:
        return self.sensors.get(resource_id, SensorState.ERROR)

    def get_machine(self, resource_id: str) -> MachineState:
        return self.machines.get(resource_id, MachineState.ERROR)

    def get_vacuum(self, resource_id: str) -> VacuumState:
        return self.vacuum.get(resource_id, VacuumState.ERROR)

    def get_vision(self, resource_id: str) -> VisionState:
        return self.vision.get(resource_id, VisionState.ERROR)

    def is_domain_online(self, domain_id: str) -> bool:
        return self.domain_online.get(domain_id, False)

    # ------------------------------------------------------------------
    # Aggregate queries
    # ------------------------------------------------------------------

    def all_initialized(self) -> bool:
        """True when every robot is IDLE and every domain is online."""
        all_robots_idle = all(s == RobotState.IDLE for s in self.robots.values())
        all_domains_online = all(self.domain_online.values())
        return all_robots_idle and all_domains_online

    def apply_resource_state(self, resource_id: str, state_str: str) -> bool:
        """
        Dispatch helper used by FactorySupervisor._apply_resource_state().
        Tries each category in order. Returns True if the resource was found
        and updated, False if it is unknown (caller logs a warning).
        """
        if resource_id in self.robots:
            try:
                self.update_robot(resource_id, RobotState(state_str))
                return True
            except ValueError:
                pass
        if resource_id in self.conveyors:
            try:
                self.update_conveyor(resource_id, ConveyorState(state_str))
                return True
            except ValueError:
                pass
        if resource_id in self.sensors:
            try:
                self.update_sensor(resource_id, SensorState(state_str))
                return True
            except ValueError:
                pass
        if resource_id in self.machines:
            try:
                self.update_machine(resource_id, MachineState(state_str))
                return True
            except ValueError:
                pass
        if resource_id in self.vacuum:
            try:
                self.update_vacuum(resource_id, VacuumState(state_str))
                return True
            except ValueError:
                pass
        if resource_id in self.vision:
            try:
                self.update_vision(resource_id, VisionState(state_str))
                return True
            except ValueError:
                pass
        return False

    # ------------------------------------------------------------------
    # Snapshot for system_state_publisher
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        return {
            "robots": {k: v.value for k, v in self.robots.items()},
            "conveyors": {k: v.value for k, v in self.conveyors.items()},
            "sensors": {k: v.value for k, v in self.sensors.items()},
            "machines": {k: v.value for k, v in self.machines.items()},
            "vacuum": {k: v.value for k, v in self.vacuum.items()},
            "vision": {k: v.value for k, v in self.vision.items()},
            "domain_online": dict(self.domain_online),
            "state_since": dict(self.state_since),
        }
