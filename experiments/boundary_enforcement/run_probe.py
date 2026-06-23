"""
Experiment 1 — Boundary Enforcement probe.

Sends unauthorized messages through the AclGuard and records whether each
was rejected and at what latency.  No ROS2 required — calls the guard directly.

Sub-experiment examples
-----------------------

1a — Cross-vendor direct access:
  python3 experiments/boundary_enforcement/run_probe.py \
    --case cross_vendor_access \
    --source bantam_vendor_probe \
    --destination /niryo_factory/command \
    --sequential 100 --batch 100 \
    --out results/experiment_1_boundary_enforcement/cross_vendor_access.csv

1b1 — External injection, no token:
  python3 experiments/boundary_enforcement/run_probe.py \
    --case external_no_token \
    --source external_probe \
    --destination /niryo_factory/command \
    --token none \
    --secret "shared_niryo_secret" \
    --enforce-hmac \
    --out results/experiment_1_boundary_enforcement/external_no_token.csv

1b2 — External injection, forged token:
  python3 experiments/boundary_enforcement/run_probe.py \
    --case external_forged_token \
    --source external_probe \
    --destination /niryo_factory/command \
    --token forged \
    --secret "shared_niryo_secret" \
    --enforce-hmac \
    --out results/experiment_1_boundary_enforcement/external_forged_token.csv

1c — Vendor-to-factory proprietary leakage:
  python3 experiments/boundary_enforcement/run_probe.py \
    --case vendor_to_factory_leakage \
    --source niryo_vendor_supervisor \
    --destination /niryo_factory/status \
    --payload-type joint_angles \
    --out results/experiment_1_boundary_enforcement/vendor_to_factory_leakage.csv

1d — Factory-to-vendor proprietary leakage:
  python3 experiments/boundary_enforcement/run_probe.py \
    --case factory_to_vendor_leakage \
    --source factory_supervisor \
    --destination /niryo_factory/command \
    --payload-type servo_data \
    --out results/experiment_1_boundary_enforcement/factory_to_vendor_leakage.csv
"""

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from typing import Optional

# Allow import without sourcing the ROS2/colcon workspace
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src" / "shipyard_pnp"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from shipyard_pnp.shared.acl_guard import check_outbound
from shipyard_pnp.shared.messages import build_command, sign_message

# ── Payload templates for proprietary-key injection tests ────────────────────

_PROPRIETARY_PAYLOADS: dict[str, dict] = {
    "joint_angles": {
        "joint_states": [1.2, 2.3, 0.4, -0.1, 1.5, 0.0],
    },
    "servo_data": {
        # Top-level forbidden keys — validate_boundary checks top-level and result
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

_CSV_FIELDS = [
    "case", "mode", "message_id", "source_node", "destination_topic",
    "allowed", "acted_upon", "acl_latency_us", "rejection_reason", "timestamp_ns",
]


# ── Message factory ───────────────────────────────────────────────────────────

def _domain_from_topic(topic: str) -> str:
    """Extract domain_id from /{domain}_factory/... topic string."""
    part = topic.strip("/").split("/")[0]
    if part.endswith("_factory"):
        return part[: -len("_factory")]
    return "unknown"


def _build_probe_payload(
    source: str,
    topic: str,
    payload_type: Optional[str],
    token: str,
    secret: Optional[str],
    idx: int,
) -> dict:
    domain_id = _domain_from_topic(topic)
    cmd = build_command(
        domain_id=domain_id,
        resource_id="probe_resource",
        task="PROBE_TASK",
        sender_id=source,
        piece_id=f"probe-{idx:04d}",
        secret=None,  # we control auth below
    )

    if payload_type and payload_type in _PROPRIETARY_PAYLOADS:
        cmd.update(_PROPRIETARY_PAYLOADS[payload_type])

    if token == "none":
        cmd["auth"] = ""
    elif token == "forged":
        cmd["auth"] = "de" * 32  # 64-char hex, wrong signature
    elif token == "valid" and secret:
        cmd["auth"] = sign_message(cmd, secret)
    # else: token=="valid" but no secret → auth stays "" (build_command default)

    return cmd


# ── Sequential and batch probe runners ───────────────────────────────────────

def _run_sequential(args, n: int, secret: Optional[str]) -> list[dict]:
    rows = []
    for i in range(n):
        payload = _build_probe_payload(
            args.source, args.destination, args.payload_type,
            args.token, secret, i,
        )
        decision = check_outbound(
            args.source, args.destination, payload,
            secret=secret, enforce_hmac=args.enforce_hmac,
        )
        rows.append({
            "case": args.case,
            "mode": "sequential",
            "message_id": payload["command_id"],
            "source_node": args.source,
            "destination_topic": args.destination,
            "allowed": decision.allowed,
            "acted_upon": decision.acted_upon,
            "acl_latency_us": round(decision.acl_latency_us, 4),
            "rejection_reason": decision.rejection_reason or "",
            "timestamp_ns": time.time_ns(),
        })
    return rows


def _run_batch(args, n: int, secret: Optional[str]) -> list[dict]:
    payloads = [
        _build_probe_payload(
            args.source, args.destination, args.payload_type,
            args.token, secret, i,
        )
        for i in range(n)
    ]

    decisions = [
        check_outbound(
            args.source, args.destination, p,
            secret=secret, enforce_hmac=args.enforce_hmac,
        )
        for p in payloads
    ]

    rows = []
    for payload, decision in zip(payloads, decisions):
        rows.append({
            "case": args.case,
            "mode": "batch",
            "message_id": payload["command_id"],
            "source_node": args.source,
            "destination_topic": args.destination,
            "allowed": decision.allowed,
            "acted_upon": decision.acted_upon,
            "acl_latency_us": round(decision.acl_latency_us, 4),
            "rejection_reason": decision.rejection_reason or "",
            "timestamp_ns": time.time_ns(),
        })
    return rows


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Experiment 1 — Boundary Enforcement probe (no ROS2 required)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--case", required=True,
                    help="Sub-experiment identifier, used as label in CSV rows")
    ap.add_argument("--source", required=True,
                    help="Node ID claiming to publish (e.g. bantam_vendor_probe)")
    ap.add_argument("--destination", required=True,
                    help="Topic the probe attempts to publish to")
    ap.add_argument("--sequential", type=int, default=100,
                    help="Number of messages to send one at a time (default: 100)")
    ap.add_argument("--batch", type=int, default=100,
                    help="Number of messages to send in a tight batch (default: 100)")
    ap.add_argument("--token", choices=["valid", "none", "forged"], default="valid",
                    help="Auth field mode: valid (signed), none (empty), forged (wrong)")
    ap.add_argument("--payload-type", dest="payload_type",
                    choices=list(_PROPRIETARY_PAYLOADS), default=None,
                    help="Inject proprietary keys into the payload to test boundary check")
    ap.add_argument("--secret", default=None,
                    help="HMAC shared secret (required for --enforce-hmac)")
    ap.add_argument("--enforce-hmac", dest="enforce_hmac", action="store_true",
                    default=False,
                    help="Enable HMAC enforcement (gates NO_TOKEN / BAD_HMAC)")
    ap.add_argument("--out", required=True, help="Output CSV path")
    return ap


def main() -> None:
    args = _build_parser().parse_args()
    secret = args.secret or None

    # Pre-load ACL YAML so the first timed check_outbound call is not penalized
    # by file I/O.  This mirrors how an online system (already initialised) behaves.
    from shipyard_pnp.shared import topic_acl as _acl
    _acl.load()

    rows: list[dict] = []
    rows.extend(_run_sequential(args, args.sequential, secret))
    rows.extend(_run_batch(args, args.batch, secret))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    acted = sum(1 for r in rows if str(r["acted_upon"]).lower() == "true")
    reasons = {r["rejection_reason"] for r in rows if r["rejection_reason"]}

    print(f"[{args.case}]  sent={total}  acted_upon={acted}  "
          f"reasons={reasons or '{none}'}  -> {out_path}")

    if acted > 0:
        print(f"FAIL: {acted} unauthorized messages were acted upon!")
        sys.exit(1)
    print("PASS: 0 unauthorized messages acted upon")


if __name__ == "__main__":
    main()
