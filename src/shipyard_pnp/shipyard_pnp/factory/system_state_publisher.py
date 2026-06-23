import json
from typing import Dict

from std_msgs.msg import String

from shipyard_pnp.shared.time_ids import iso_now


class SystemStatePublisher:
    """
    Helper owned by FactorySupervisor. Called by the 2.0 s dashboard timer.
    Builds and publishes /factory/system_state as a single JSON payload.
    """

    def __init__(self, publisher, state_tracker, piece_tracker, cycle_tracker, vendor_clients,
                 initial_order=None, get_planner_phase=None):
        self._pub = publisher
        self._state = state_tracker
        self._pieces = piece_tracker
        self._cycles = cycle_tracker
        self._clients: Dict = vendor_clients
        self._initial_order: list = list(initial_order or [])
        self._get_planner_phase = get_planner_phase

    def publish(self) -> None:
        payload = {
            "schema": "shipyard.pnp.system_state.v1",
            "published_at": iso_now(),
            "planner_phase": self._get_planner_phase() if self._get_planner_phase else "UNKNOWN",
            "initial_order": self._initial_order,
            "domains": {
                domain_id: {
                    "online": vc.domain_online,
                    "busy": vc.is_busy(),
                    "last_ack": vc.last_ack_time,
                    "pending_command_id": (
                        vc.pending.command_id if vc.pending else None
                    ),
                    "pending_command_ids": vc.pending_command_ids(),
                }
                for domain_id, vc in self._clients.items()
            },
            "resources": self._state.snapshot(),
            "pipeline": self._pieces.snapshot(),
            "cycles": self._cycles.snapshot(),
        }
        msg = String()
        msg.data = json.dumps(payload)
        self._pub.publish(msg)
