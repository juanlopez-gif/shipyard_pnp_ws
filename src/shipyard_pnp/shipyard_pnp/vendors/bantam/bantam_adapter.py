"""
BantamAdapter — orchestrates one RUN_JOB cycle for the Bantam CNC.

Current mode: SIMULATED machining (sleep) + REAL door control.

The piece is already on the Bantam bed when RUN_JOB arrives
(robot2 MOVE_PIECE completed before the factory supervisor sends RUN_JOB).

Sequence:
  1. Open door (confirm piece is accessible)       [door = real]
  2. Settle briefly
  3. Close door                                     [door = real]
  4. SIMULATE machining: sleep(processing_time_sec) [CNC = simulated]
  5. Open door                                      [door = real]
  6. Return COMPLETED

# ── FUTURE: real CNC serial integration ─────────────────────────────────────
# To connect the Bantam CNC via USB serial:
#   1. Identify port: `ls /dev/ttyACM*` with the USB connected.
#   2. Install pyserial: `pip install pyserial`
#   3. Replace the `time.sleep(processing_time_sec)` block in `run_job()` with
#      a call to `_run_cnc_serial(port, baud)` that:
#        a. Opens the port with `serial.Serial(port, baud, timeout=0.5)`.
#        b. Waits ~3 s for the board to reset after DTR toggle.
#        c. Sends the GCode sequence (e.g. b'M3 S5000\n', b'G4 P0.1\n', b'M5\n').
#        d. Flushes and closes the port.
#        e. Waits for the actual machining duration before returning.
#      The port and baud should come from hardware_ports.yaml (bantam section).
#   4. Add `bantam_serial_port` and `bantam_serial_baud` to hardware_ports.yaml.
#   5. Pass them through BantamVendorSupervisor.__init__ → BantamAdapter.__init__.
# ─────────────────────────────────────────────────────────────────────────────
"""

import time
from typing import Callable, Optional

from shipyard_pnp.shared.contracts import MachineState
from shipyard_pnp.vendors.bantam.door_adapter import DoorAdapter, DoorState


class BantamAdapter:
    def __init__(
        self,
        door: DoorAdapter,
        processing_time_sec: float = 25.0,
        settle_sec:          float = 1.5,
        door_timeout_sec:    float = 12.0,
    ):
        self._door               = door
        self._processing_time    = processing_time_sec
        self._settle_sec         = settle_sec
        self._door_timeout       = door_timeout_sec

    def initialize(self, status_cb: Optional[Callable] = None) -> dict:
        self._status(status_cb, MachineState.IDLE.value, "INITIALIZING")
        self._door.open("initialize")
        self._status(status_cb, MachineState.IDLE.value, "INITIALIZED")
        return {"resource_state": MachineState.IDLE.value, "code": "INITIALIZED"}

    def run_job(
        self,
        job_type:  str = "BLUE_PROCESS",
        status_cb: Optional[Callable] = None,
    ) -> dict:
        # Door is already open (robot2 just placed the piece).
        # Close immediately — no need to re-open and wait.
        self._status(status_cb, MachineState.PREPARING.value, "CLOSING_DOOR")
        self._door.close("starting machining cycle")
        if not self._door.wait_for_closed(self._door_timeout):
            self._status(status_cb, MachineState.PREPARING.value,
                         "DOOR_CLOSE_TIMEOUT_CONTINUING")

        # ── SIMULATED machining ──────────────────────────────────────────
        # Replace this block with real CNC serial commands when hardware
        # is connected — see module docstring for the full integration guide.
        self._status(status_cb, MachineState.WORKING.value, "MACHINING_SIMULATED")
        time.sleep(self._processing_time)
        # ────────────────────────────────────────────────────────────────

        self._status(status_cb, MachineState.FINISHED.value, "OPENING_DOOR_AFTER_JOB")
        self._door.open("job done, ready for piece pickup")
        if not self._door.wait_for_open(self._door_timeout):
            self._status(status_cb, MachineState.FINISHED.value,
                         "DOOR_OPEN_TIMEOUT_CONTINUING")

        self._status(status_cb, MachineState.FINISHED.value, "JOB_COMPLETE")
        return {
            "resource_state": MachineState.FINISHED.value,
            "code": "JOB_COMPLETE",
            "job_type": job_type,
        }

    def reset(self, status_cb: Optional[Callable] = None) -> dict:
        self._door.open("reset to idle")
        self._status(status_cb, MachineState.IDLE.value, "IDLE")
        return {"resource_state": MachineState.IDLE.value, "code": "IDLE"}

    @staticmethod
    def _status(cb: Optional[Callable], resource_state: str, code: str) -> None:
        if cb:
            cb(resource_state, {"code": code})
