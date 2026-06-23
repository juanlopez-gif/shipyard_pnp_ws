import json
import os
from abc import ABC, abstractmethod
from typing import Optional, Tuple

import yaml
from rclpy.node import Node
from std_msgs.msg import String

from shipyard_pnp.shared.acl_guard import check_outbound
from shipyard_pnp.shared.messages import (
    build_ack,
    build_status,
    to_json,
    verify_message,
)
from shipyard_pnp.shared import topic_acl as _topic_acl
from shipyard_pnp.vendors.common.internal_bus import InternalBus
from shipyard_pnp.vendors.common.task_runner import TaskRunner

_HMAC_SECRETS_SEARCH = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "..", "..", "..", "config", "hmac_secrets.yaml"),
]


def _find_secrets_file() -> Optional[str]:
    for path in _HMAC_SECRETS_SEARCH:
        path = os.path.normpath(path)
        if os.path.isfile(path):
            return path
    try:
        from ament_index_python.packages import get_package_share_directory
        pkg = get_package_share_directory("shipyard_pnp")
        candidate = os.path.join(pkg, "config", "hmac_secrets.yaml")
        if os.path.isfile(candidate):
            return candidate
    except Exception:
        pass
    return None


class BaseVendorSupervisor(Node, ABC):
    """
    Abstract base for all seven vendor supervisors.
    Provides the three-channel ROS2 wiring, JSON parsing, HMAC validation
    (warn-only in Phases 1-5), and publish_ack / publish_status helpers.
    Concrete subclasses implement only handle_task().
    """

    def __init__(self, domain_id: str):
        super().__init__(f"{domain_id}_vendor_supervisor")
        self.domain_id = domain_id
        self._hmac_secret = self._load_hmac_secret()

        self.cmd_sub = self.create_subscription(
            String,
            f"/{domain_id}_factory/command",
            self._on_command_raw,
            10,
        )
        self.ack_pub = self.create_publisher(
            String,
            f"/{domain_id}_factory/ack",
            10,
        )
        self.status_pub = self.create_publisher(
            String,
            f"/{domain_id}_factory/status",
            10,
        )

        self.task_runner = TaskRunner()
        self.bus = InternalBus()

        # Pre-warm ACL so first real command is not penalised by YAML I/O.
        _topic_acl.load()

        self._acl_event_pub = self.create_publisher(
            String, "/shipyard/acl_events", 10
        )

        self.get_logger().info(f"{domain_id}_vendor_supervisor ready")

    # ------------------------------------------------------------------
    # Command ingestion
    # ------------------------------------------------------------------

    def _on_command_raw(self, msg: String) -> None:
        try:
            cmd = json.loads(msg.data)
        except json.JSONDecodeError as exc:
            self.get_logger().error(f"Invalid JSON on command topic: {exc}")
            return

        if cmd.get("domain_id") != self.domain_id:
            self.get_logger().error(
                f"Wrong domain_id '{cmd.get('domain_id')}' — expected '{self.domain_id}'"
            )
            return

        decision = check_outbound(
            sender_id=cmd.get("sender_id", ""),
            topic=f"/{self.domain_id}_factory/command",
            payload=cmd,
            secret=self._hmac_secret or None,
            enforce_hmac=bool(self._hmac_secret),
        )
        if not decision.allowed:
            self.get_logger().error(
                f"AclGuard REJECTED command_id='{cmd.get('command_id')}' "
                f"sender='{cmd.get('sender_id')}' "
                f"reason={decision.rejection_reason} "
                f"latency={decision.acl_latency_us:.1f}µs"
            )
            self._publish_acl_event(
                command_id=cmd.get("command_id", ""),
                sender_id=cmd.get("sender_id", ""),
                topic=f"/{self.domain_id}_factory/command",
                reason=decision.rejection_reason,
                latency_us=decision.acl_latency_us,
            )
            return  # no ack — unauthorized senders get no feedback

        try:
            accepted, reason = self.handle_task(cmd)
        except Exception as exc:
            self.get_logger().error(f"handle_task raised: {exc}")
            accepted, reason = False, str(exc)

        self.publish_ack(
            command_id=cmd["command_id"],
            resource_id=cmd.get("resource_id", ""),
            accepted=accepted,
            reason=reason,
            correlation_id=cmd.get("correlation_id"),
        )

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def handle_task(self, cmd: dict) -> Tuple[bool, Optional[str]]:
        """
        Return (accepted, rejection_reason_or_None).
        Must NOT block — start hardware work via self.task_runner.run().
        """

    # ------------------------------------------------------------------
    # Publishing helpers
    # ------------------------------------------------------------------

    def publish_ack(
        self,
        command_id: str,
        resource_id: str,
        accepted: bool,
        reason: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        payload = build_ack(
            command_id=command_id,
            domain_id=self.domain_id,
            resource_id=resource_id,
            accepted=accepted,
            reason=reason,
            correlation_id=correlation_id,
        )
        out = String()
        out.data = to_json(payload)
        self.ack_pub.publish(out)

    def publish_status(
        self,
        command_id: str,
        resource_id: str,
        task: str,
        task_state: str,
        resource_state: str,
        piece_id: Optional[str] = None,
        source: Optional[str] = None,
        target: Optional[str] = None,
        route: Optional[str] = None,
        result: Optional[dict] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        payload = build_status(
            command_id=command_id,
            domain_id=self.domain_id,
            resource_id=resource_id,
            task=task,
            task_state=task_state,
            resource_state=resource_state,
            piece_id=piece_id,
            source=source,
            target=target,
            route=route,
            result=result,
            correlation_id=correlation_id,
        )
        out = String()
        out.data = to_json(payload)
        self.status_pub.publish(out)

    # ------------------------------------------------------------------
    # ACL event publisher
    # ------------------------------------------------------------------

    def _publish_acl_event(
        self,
        command_id: str,
        sender_id: str,
        topic: str,
        reason: str,
        latency_us: float,
    ) -> None:
        import time as _time
        event = {
            "event": "ACL_REJECTED",
            "command_id": command_id,
            "sender_id": sender_id,
            "topic": topic,
            "reason": reason,
            "latency_us": round(latency_us, 2),
            "timestamp_ns": _time.time_ns(),
        }
        msg = String()
        msg.data = json.dumps(event)
        self._acl_event_pub.publish(msg)

    # ------------------------------------------------------------------
    # HMAC secret loading
    # ------------------------------------------------------------------

    def _load_hmac_secret(self) -> str:
        secrets_file = _find_secrets_file()
        if secrets_file is None:
            self.get_logger().warning(
                "config/hmac_secrets.yaml not found — HMAC auth disabled"
            )
            return ""
        try:
            with open(secrets_file) as fh:
                data = yaml.safe_load(fh)
            secret = data.get(self.domain_id, "")
            if not secret:
                self.get_logger().warning(
                    f"No HMAC secret for domain '{self.domain_id}' in hmac_secrets.yaml"
                )
            return secret
        except Exception as exc:
            self.get_logger().warning(f"Failed to load hmac_secrets.yaml: {exc}")
            return ""
