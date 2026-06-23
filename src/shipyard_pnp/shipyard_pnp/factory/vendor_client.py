import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from shipyard_pnp.shared.messages import build_command, to_json
from shipyard_pnp.shared.contracts import TERMINAL_TASK_STATES

_log = logging.getLogger(__name__)

# Per-task status timeout overrides (seconds). Default applied in check_timeout().
_TASK_STATUS_TIMEOUTS: dict = {
    "INITIALIZE_DOMAIN": 30.0,
    "SCAN_STACK": 15.0,
    "LOCATE_NEXT_PIECE": 10.0,
    "GOTO_PICK_POSITION": 60.0,
    "LIFT_AND_PLACE": 60.0,
    "RETURN_HOME": 60.0,
    "RUN_NIRYO_CONVEYOR": 30.0,
    "PICK": 5.0,
    "RELEASE": 5.0,
    # RUN_JOB is domain-dependent; caller may override via parameters
    # laser → 300s, bantam → 600s — set per-domain in FS setup
}

_DEFAULT_ACK_TIMEOUT = 5.0
_DEFAULT_STATUS_TIMEOUT = 120.0


@dataclass
class PendingCommand:
    command_id: str
    correlation_id: Optional[str]
    domain_id: str
    resource_id: str
    task: str
    piece_id: Optional[str]
    source: Optional[str]
    target: Optional[str]
    parameters: dict
    issued_at: float                          # time.time() when command was sent
    status_timeout_sec: float                 # per-task override or default
    ack_received: bool = False
    ack_at: Optional[float] = None
    status_received: bool = False
    last_task_state: Optional[str] = None
    last_result: Optional[dict] = None
    on_complete: Optional[Callable[[str, dict], None]] = None
    # on_complete(task_state, result) is called once when a terminal STATUS arrives


class VendorClient:
    """
    One instance per vendor domain, owned by the FactorySupervisor.
    Holds the ROS2 publisher, tracks the one active pending command per domain,
    and handles ack/status correlation and timeout detection.
    Not thread-safe on its own — protected by FactorySupervisor._state_lock.
    """

    def __init__(
        self,
        domain_id: str,
        publisher: Any,                        # rclpy Publisher[String]
        hmac_secret: str = "",
        status_timeout_overrides: Optional[dict] = None,
        concurrent_resources: bool = False,
    ):
        self.domain_id = domain_id
        self._publisher = publisher
        self._hmac_secret = hmac_secret
        self._timeout_overrides = status_timeout_overrides or {}
        self._concurrent_resources = bool(concurrent_resources)

        self._pending_by_command: dict[str, PendingCommand] = {}
        self._pending_by_resource: dict[str, PendingCommand] = {}
        self.domain_online: bool = False
        self.last_ack_time: Optional[float] = None
        self.last_status_time: Optional[float] = None
        self._seq: int = 0

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    @property
    def pending(self) -> Optional[PendingCommand]:
        """Compatibility view: first pending command, if any."""
        return next(iter(self._pending_by_command.values()), None)

    def is_busy(self, resource_id: Optional[str] = None) -> bool:
        if resource_id:
            return resource_id in self._pending_by_resource
        return bool(self._pending_by_command)

    def pending_command_ids(self) -> list:
        return sorted(self._pending_by_command.keys())

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def send_command(
        self,
        resource_id: str,
        task: str,
        piece_id: Optional[str] = None,
        source: Optional[str] = None,
        target: Optional[str] = None,
        route: Optional[str] = None,
        parameters: Optional[dict] = None,
        correlation_id: Optional[str] = None,
        on_complete: Optional[Callable[[str, dict], None]] = None,
    ) -> str:
        if not self._concurrent_resources and self._pending_by_command:
            pending = self.pending
            raise RuntimeError(
                f"VendorClient '{self.domain_id}' is busy with "
                f"'{pending.command_id}' — caller must check is_busy() first"
            )
        if self._concurrent_resources and resource_id in self._pending_by_resource:
            pending = self._pending_by_resource[resource_id]
            raise RuntimeError(
                f"VendorClient '{self.domain_id}/{resource_id}' is busy with "
                f"'{pending.command_id}' — caller must check is_busy(resource_id) first"
            )

        self._seq += 1
        params = parameters or {}

        payload = build_command(
            domain_id=self.domain_id,
            resource_id=resource_id,
            task=task,
            correlation_id=correlation_id,
            piece_id=piece_id,
            source=source,
            target=target,
            route=route,
            parameters=params,
            secret=self._hmac_secret or None,
        )
        command_id = payload["command_id"]

        status_timeout = (
            self._timeout_overrides.get(task)
            or _TASK_STATUS_TIMEOUTS.get(task)
            or _DEFAULT_STATUS_TIMEOUT
        )

        pending = PendingCommand(
            command_id=command_id,
            correlation_id=correlation_id,
            domain_id=self.domain_id,
            resource_id=resource_id,
            task=task,
            piece_id=piece_id,
            source=source,
            target=target,
            parameters=params,
            issued_at=time.time(),
            status_timeout_sec=status_timeout,
            on_complete=on_complete,
        )
        self._pending_by_command[command_id] = pending
        self._pending_by_resource[resource_id] = pending

        from std_msgs.msg import String  # deferred — tests run without ROS2
        msg = String()
        msg.data = to_json(payload)
        self._publisher.publish(msg)

        _log.debug("Sent %s → %s/%s %s", command_id, self.domain_id, resource_id, task)
        return command_id

    # ------------------------------------------------------------------
    # Incoming message handlers (called by FS callbacks under _state_lock)
    # ------------------------------------------------------------------

    def on_ack_received(self, ack_payload: dict) -> None:
        cid = ack_payload.get("command_id")
        pending = self._pending_by_command.get(cid)
        if pending is None:
            _log.warning(
                "ACK command_id mismatch/unknown for domain '%s': got '%s'",
                self.domain_id, cid,
            )
            return
        pending.ack_received = True
        pending.ack_at = time.time()
        self.last_ack_time = pending.ack_at
        if not ack_payload.get("accepted", True):
            reason = ack_payload.get("reason", "REJECTED")
            _log.warning("Command '%s' rejected: %s", cid, reason)
            self._complete(pending, "REJECTED", {"reason": reason})

    def on_status_received(self, status_payload: dict) -> None:
        cid = status_payload.get("command_id")
        # Allow autonomous sensor updates (command_id="AUTO") to pass through
        # without matching the pending command — the FS handles them separately.
        if cid == "AUTO":
            return
        pending = self._pending_by_command.get(cid)
        if pending is None:
            _log.warning(
                "STATUS command_id mismatch/unknown for domain '%s': got '%s'",
                self.domain_id, cid,
            )
            return
        pending.status_received = True
        self.last_status_time = time.time()
        task_state = status_payload.get("task_state", "")
        result = status_payload.get("result", {})
        pending.last_task_state = task_state
        pending.last_result = result

        if task_state in TERMINAL_TASK_STATES:
            self._complete(pending, task_state, result)

    # ------------------------------------------------------------------
    # Timeout watchdog (called by FS watchdog timer every 1.0 s)
    # ------------------------------------------------------------------

    def check_timeout(
        self,
        ack_timeout_sec: float = _DEFAULT_ACK_TIMEOUT,
        status_timeout_sec: Optional[float] = None,
    ) -> None:
        now = time.time()
        for p in list(self._pending_by_command.values()):
            self._check_pending_timeout(p, now, ack_timeout_sec, status_timeout_sec)

    def _check_pending_timeout(
        self,
        p: PendingCommand,
        now: float,
        ack_timeout_sec: float,
        status_timeout_sec: Optional[float],
    ) -> None:
        if not p.ack_received:
            elapsed = now - p.issued_at
            if elapsed > ack_timeout_sec:
                _log.error(
                    "ACK timeout for '%s' (%s/%s %s) after %.1fs",
                    p.command_id, p.domain_id, p.resource_id, p.task, elapsed,
                )
                self._complete(p, "TIMEOUT", {"reason": "ACK_TIMEOUT"})
            return

        # ACK received but no terminal STATUS yet
        effective_timeout = status_timeout_sec or p.status_timeout_sec
        if p.ack_at is not None:
            elapsed = now - p.ack_at
            if elapsed > effective_timeout:
                _log.error(
                    "STATUS timeout for '%s' (%s/%s %s) after %.1fs",
                    p.command_id, p.domain_id, p.resource_id, p.task, elapsed,
                )
                self._complete(p, "TIMEOUT", {"reason": "STATUS_TIMEOUT"})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _complete(self, pending: PendingCommand, task_state: str, result: dict) -> None:
        callback = pending.on_complete
        self._pending_by_command.pop(pending.command_id, None)
        if self._pending_by_resource.get(pending.resource_id) is pending:
            self._pending_by_resource.pop(pending.resource_id, None)
        if callback is not None:
            try:
                callback(task_state, result)
            except Exception as exc:
                _log.error(
                    "on_complete callback raised for '%s': %s",
                    pending.command_id, exc,
                )
