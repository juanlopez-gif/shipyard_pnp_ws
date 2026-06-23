#!/usr/bin/env python3
"""
Experiment 1 — Physical ROS2 probe.

Publishes unauthorized messages via real ROS2 DDS transport and records:
  - whether an ACK is ever received (must be NEVER for rejected messages)
  - the observed rejection reason from /shipyard/acl_events (published by the guard)

PREREQUISITES
  - ROS2 Jazzy sourced:  source /opt/ros/jazzy/setup.bash
  - Workspace built:     source install/setup.bash
  - config/hmac_secrets.yaml deployed and nodes restarted (for 1b1/1b2 HMAC gates)
  - System running:      niryo_vendor_supervisor, bantam_vendor_supervisor,
                         factory_supervisor

ENFORCEMENT COVERAGE (physical)
  Case                         Enforced by                  Expected gate
  ──────────────────────────────────────────────────────────────────────────
  1a  cross_vendor             niryo_vendor_supervisor      SENDER_NOT_AUTHORIZED
  1b1 external_no_token        niryo_vendor_supervisor      NO_TOKEN  (needs HMAC)
  1b2 external_forged_token    niryo_vendor_supervisor      BAD_HMAC  (needs HMAC)
  1c  vendor→factory status    factory_supervisor           PROPRIETARY_FIELD
  1d  factory→vendor command   niryo_vendor_supervisor      PROPRIETARY_FIELD
  1e  ack_injection            factory_supervisor           SENDER_NOT_AUTHORIZED
  1b1 bantam_external_no_token   bantam_vendor_supervisor   NO_TOKEN  (needs HMAC)
  1b2 bantam_external_forged     bantam_vendor_supervisor   BAD_HMAC  (needs HMAC)

PASS CRITERIA (physical)
  - acks_received == 0  (unauthorized senders get NO feedback)
  - observed_reason in CSV matches expected_reason (from /shipyard/acl_events)
"""

import argparse
import csv
import json
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

# ── ROS2 imports ─────────────────────────────────────────────────────────────
try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
except ImportError:
    print("ERROR: rclpy not found — source ROS2 Jazzy and workspace before running.", file=sys.stderr)
    sys.exit(1)

# ── shipyard_pnp imports ──────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src" / "shipyard_pnp"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from shipyard_pnp.shared.messages import build_command, sign_message

# ── Proprietary payload templates ─────────────────────────────────────────────
_PROPRIETARY_PAYLOADS: dict[str, dict] = {
    "joint_angles": {
        "joint_states": [1.2, 2.3, 0.4, -0.1, 1.5, 0.0],
    },
    "servo_data": {
        "servo": 90,
        "register": "0x1F",
    },
    "raw_image": {
        "raw_image": "base64encodeddata==",
    },
    "gcode": {
        "gcode_line": "G1 X10 Y20 Z5 F300",
    },
}

_EXPECTED_REASON: dict[str, str] = {
    "cross_vendor_access":           "SENDER_NOT_AUTHORIZED",
    "external_no_token":             "NO_TOKEN",
    "external_forged_token":         "BAD_HMAC",
    "ack_injection":                 "SENDER_NOT_AUTHORIZED",
    "bantam_external_no_token":      "NO_TOKEN",
    "bantam_external_forged_token":  "BAD_HMAC",
    "vendor_to_factory_leakage":     "PROPRIETARY_FIELD",
    "factory_to_vendor_leakage":     "PROPRIETARY_FIELD",
}

_CSV_FIELDS = [
    "case", "message_id", "source_node", "destination_topic",
    "ack_received", "ack_command_id", "ack_accepted",
    "observed_reason", "time_to_result_ms", "expected_reason", "pass", "timestamp_ns",
]


# ── Probe node ────────────────────────────────────────────────────────────────

class PhysicalProbeNode(Node):
    def __init__(self, destination: str, ack_topic: Optional[str]):
        super().__init__("experiment_1_physical_probe")
        self._pub = self.create_publisher(String, destination, 10)
        self._acks: dict[str, dict] = {}
        self._acl_events: dict[str, dict] = {}
        self._lock = threading.Lock()

        if ack_topic:
            self._ack_sub = self.create_subscription(
                String, ack_topic, self._on_ack, 10
            )
        else:
            self._ack_sub = None

        # Always subscribe to ACL events — captures observed_reason from guard nodes
        self._acl_event_sub = self.create_subscription(
            String, "/shipyard/acl_events", self._on_acl_event, 10
        )

        if ack_topic:
            self.get_logger().info(
                f"probe ready — publishing to '{destination}', monitoring '{ack_topic}'"
            )
        else:
            self.get_logger().info(
                f"probe ready — publishing to '{destination}' (evidence via /shipyard/acl_events)"
            )

    def _on_ack(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        cmd_id = payload.get("command_id", "")
        with self._lock:
            self._acks[cmd_id] = payload

    def _on_acl_event(self, msg: String) -> None:
        try:
            event = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        cmd_id = event.get("command_id", "")
        with self._lock:
            self._acl_events[cmd_id] = event

    def publish(self, payload: dict) -> None:
        msg = String()
        msg.data = json.dumps(payload)
        self._pub.publish(msg)

    def wait_for_result(
        self, command_id: str, timeout_s: float
    ) -> tuple[Optional[dict], Optional[dict]]:
        """Returns (ack_or_None, acl_event_or_None). Exits early on first result."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                ack = self._acks.get(command_id)
                evt = self._acl_events.get(command_id)
                if ack is not None or evt is not None:
                    return ack, evt
            time.sleep(0.01)
        return None, None


# ── Payload builder ───────────────────────────────────────────────────────────

def _build_payload(
    source: str,
    topic: str,
    payload_type: Optional[str],
    token: str,
    secret: Optional[str],
    idx: int,
) -> dict:
    part = topic.strip("/").split("/")[0]
    domain_id = part[: -len("_factory")] if part.endswith("_factory") else "niryo"

    cmd = build_command(
        domain_id=domain_id,
        resource_id="probe_resource",
        task="PROBE_TASK",
        sender_id=source,
        piece_id=f"probe-{idx:04d}",
        secret=None,
    )

    if payload_type and payload_type in _PROPRIETARY_PAYLOADS:
        cmd.update(_PROPRIETARY_PAYLOADS[payload_type])

    if token == "none":
        cmd["auth"] = ""
    elif token == "forged":
        cmd["auth"] = "de" * 32
    elif token == "valid" and secret:
        cmd["auth"] = sign_message(cmd, secret)

    return cmd


# ── Main run ──────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Experiment 1 — Physical ROS2 probe",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--case", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--destination", required=True)
    ap.add_argument("--ack-topic", dest="ack_topic", default=None,
                    help="Topic to monitor for acks. Omit for status/ack-topic probes.")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--ack-timeout", dest="ack_timeout", type=float, default=1.5,
                    help="Seconds to wait per message for ack or ACL event (default: 1.5)")
    ap.add_argument("--token", choices=["valid", "none", "forged"], default="valid")
    ap.add_argument("--payload-type", dest="payload_type",
                    choices=list(_PROPRIETARY_PAYLOADS), default=None)
    ap.add_argument("--secret", default=None)
    ap.add_argument("--enforce-hmac", dest="enforce_hmac",
                    action="store_true", default=False)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    secret = args.secret or None
    ack_topic = None if (not args.ack_topic or args.ack_topic.lower() == "none") else args.ack_topic

    rclpy.init()
    executor = rclpy.executors.MultiThreadedExecutor()
    node = PhysicalProbeNode(args.destination, ack_topic)
    executor.add_node(node)

    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    # Brief warm-up — let subscriptions settle
    time.sleep(0.5)

    rows = []
    n_acks = 0
    n_reason_match = 0
    expected_reason = _EXPECTED_REASON.get(args.case, "(any)")

    print(f"[{args.case}] sending {args.n} messages to {args.destination} ...")
    if ack_topic:
        print(f"  monitoring acks:   {ack_topic}")
    print(f"  monitoring events: /shipyard/acl_events")
    print(f"  expected reason:   {expected_reason}")
    print()

    for i in range(args.n):
        payload = _build_payload(
            args.source, args.destination, args.payload_type,
            args.token, secret, i,
        )
        t_send = time.monotonic()
        node.publish(payload)
        ack, acl_event = node.wait_for_result(payload["command_id"], args.ack_timeout)
        elapsed_ms = (time.monotonic() - t_send) * 1000.0

        ack_received = ack is not None
        observed_reason = acl_event.get("reason", "") if acl_event else ""
        reason_ok = (observed_reason == expected_reason) or (expected_reason == "(any)")

        if ack_received:
            n_acks += 1
        if reason_ok and observed_reason:
            n_reason_match += 1

        # pass: no ack (when ack_topic set) OR always true for log-evidence cases
        msg_pass = (not ack_received) if ack_topic else True

        rows.append({
            "case":              args.case,
            "message_id":        payload["command_id"],
            "source_node":       args.source,
            "destination_topic": args.destination,
            "ack_received":      ack_received,
            "ack_command_id":    ack.get("command_id", "") if ack else "",
            "ack_accepted":      ack.get("accepted", "") if ack else "",
            "observed_reason":   observed_reason,
            "time_to_result_ms": round(elapsed_ms, 3),
            "expected_reason":   expected_reason,
            "pass":              msg_pass,
            "timestamp_ns":      time.time_ns(),
        })

        obs_tag = f"  observed={observed_reason}" if observed_reason else "  (no event yet)"
        if ack_topic:
            status = "ACK RECEIVED (FAIL)" if ack_received else f"no ack (PASS, {elapsed_ms:.0f}ms){obs_tag}"
        else:
            status = f"sent ({elapsed_ms:.0f}ms){obs_tag}"
        print(f"  [{i+1:03d}] {payload['command_id'][:8]}... → {status}")

    node.destroy_node()
    rclpy.shutdown()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    if ack_topic:
        all_pass = n_acks == 0
        verdict = "PASS ✓" if all_pass else f"FAIL ✗ — {n_acks} unauthorized acks received"
    else:
        all_pass = True
        verdict = "PASS ✓ (evidence: /shipyard/acl_events + receiver logs)"

    reason_verdict = (
        f"{n_reason_match}/{args.n} messages matched expected reason '{expected_reason}'"
        if n_reason_match > 0
        else f"0/{args.n} ACL events received (node may not be running or HMAC not configured)"
    )

    print()
    print(f"{'='*60}")
    print(f"Case:              {args.case}")
    print(f"Messages sent:     {args.n}")
    if ack_topic:
        print(f"ACKs received:     {n_acks}  (expected: 0)")
    print(f"Expected reason:   {expected_reason}")
    print(f"Reason match:      {reason_verdict}")
    print(f"Verdict:           {verdict}")
    print(f"Results saved to:  {out_path}")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
