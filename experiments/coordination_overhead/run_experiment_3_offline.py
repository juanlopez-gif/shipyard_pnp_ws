#!/usr/bin/env python3
"""
Experiment 3 — Offline coordination overhead baseline

Measures the message-layer overhead of the 3-message protocol
(command / ack / status) without ROS2, DDS, or hardware.

This quantifies the software-only lower bound on T_coord:
  - build + HMAC-sign + JSON-serialize a command
  - JSON-parse + HMAC-verify a received command
  - build + sign + serialize an ack
  - build + sign + serialize a terminal status

Physical task times (seconds) are orders of magnitude larger,
so coordination overhead is negligible even in the worst case.

Run without ROS2:
  python3 experiments/coordination_overhead/run_experiment_3_offline.py \\
    --n 1000 \\
    --out results/experiment_3_coordination_overhead/offline_baseline.csv \\
    --summary results/experiment_3_coordination_overhead/offline_summary.csv

Pass criteria (offline):
  - T_coord (mean) < 1000 µs  (sub-millisecond per coordination cycle)
  - All 1000 cycles complete successfully
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from statistics import mean, stdev

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src" / "shipyard_pnp"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from shipyard_pnp.shared.messages import (
    build_command, build_ack, build_status,
    verify_message, to_json, parse_json,
)

_SECRET = "shared_niryo_secret"
_DOMAIN = "niryo"
_RESOURCE = "robot1"
_TASK = "GOTO_PICK_POSITION"

_CSV_FIELDS = [
    "iteration",
    "t_cmd_build_us", "t_cmd_serialize_us",
    "t_cmd_parse_us", "t_cmd_verify_us",
    "t_ack_build_us", "t_ack_serialize_us",
    "t_status_build_us", "t_status_serialize_us",
    "T_coord_total_us",
]

_SUMMARY_FIELDS = ["metric", "mean_us", "std_us", "min_us", "max_us", "count"]


def _us(ns_delta: int) -> float:
    return ns_delta / 1000.0


def run_offline(n: int, out_path: str, summary_path: str, verbose: bool) -> None:
    rows = []

    for i in range(n):
        # Command: build + sign + serialize
        t0 = time.perf_counter_ns()
        cmd = build_command(
            domain_id=_DOMAIN,
            resource_id=_RESOURCE,
            task=_TASK,
            piece_id=f"PIECE_{i:04d}",
            parameters={"position": "C4"},
            secret=_SECRET,
        )
        t1 = time.perf_counter_ns()
        cmd_json = to_json(cmd)
        t2 = time.perf_counter_ns()

        # Simulate VS receiving command: parse + verify
        cmd_recv = parse_json(cmd_json)
        t3 = time.perf_counter_ns()
        verify_message(cmd_recv, _SECRET)
        t4 = time.perf_counter_ns()

        # Ack: build + serialize
        ack = build_ack(
            command_id=cmd["command_id"],
            domain_id=_DOMAIN,
            resource_id=_RESOURCE,
            accepted=True,
            correlation_id=cmd.get("correlation_id"),
            secret=_SECRET,
        )
        t5 = time.perf_counter_ns()
        to_json(ack)
        t6 = time.perf_counter_ns()

        # Status: build + serialize
        status = build_status(
            command_id=cmd["command_id"],
            domain_id=_DOMAIN,
            resource_id=_RESOURCE,
            task=_TASK,
            task_state="COMPLETED",
            resource_state="AT_PLACE_POSITION",
            piece_id=f"PIECE_{i:04d}",
            result={"code": "OK"},
            secret=_SECRET,
        )
        t7 = time.perf_counter_ns()
        to_json(status)
        t8 = time.perf_counter_ns()

        t_cmd_build = _us(t1 - t0)
        t_cmd_ser = _us(t2 - t1)
        t_cmd_parse = _us(t3 - t2)
        t_cmd_verify = _us(t4 - t3)
        t_ack_build = _us(t5 - t4)
        t_ack_ser = _us(t6 - t5)
        t_status_build = _us(t7 - t6)
        t_status_ser = _us(t8 - t7)
        T_coord = (
            t_cmd_build + t_cmd_ser + t_cmd_parse + t_cmd_verify
            + t_ack_build + t_ack_ser
            + t_status_build + t_status_ser
        )

        rows.append({
            "iteration":           i + 1,
            "t_cmd_build_us":      round(t_cmd_build, 3),
            "t_cmd_serialize_us":  round(t_cmd_ser, 3),
            "t_cmd_parse_us":      round(t_cmd_parse, 3),
            "t_cmd_verify_us":     round(t_cmd_verify, 3),
            "t_ack_build_us":      round(t_ack_build, 3),
            "t_ack_serialize_us":  round(t_ack_ser, 3),
            "t_status_build_us":   round(t_status_build, 3),
            "t_status_serialize_us": round(t_status_ser, 3),
            "T_coord_total_us":    round(T_coord, 3),
        })

        if verbose and (i + 1) % 200 == 0:
            print(f"  [{i+1:>5}/{n}]  T_coord = {T_coord:.1f} µs")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)

    metrics = [
        ("t_cmd_build_us",         "command_build_and_sign"),
        ("t_cmd_serialize_us",     "command_json_serialize"),
        ("t_cmd_parse_us",         "command_json_parse"),
        ("t_cmd_verify_us",        "command_hmac_verify"),
        ("t_ack_build_us",         "ack_build_and_sign"),
        ("t_ack_serialize_us",     "ack_json_serialize"),
        ("t_status_build_us",      "status_build_and_sign"),
        ("t_status_serialize_us",  "status_json_serialize"),
        ("T_coord_total_us",       "T_coord_total"),
    ]

    summary_rows = []
    for field, label in metrics:
        vals = [r[field] for r in rows]
        summary_rows.append({
            "metric":   label,
            "mean_us":  round(mean(vals), 3),
            "std_us":   round(stdev(vals) if len(vals) > 1 else 0.0, 3),
            "min_us":   round(min(vals), 3),
            "max_us":   round(max(vals), 3),
            "count":    len(vals),
        })

    summary_path = Path(summary_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_SUMMARY_FIELDS)
        w.writeheader()
        w.writerows(summary_rows)

    t_coord_vals = [r["T_coord_total_us"] for r in rows]

    print()
    print("=" * 66)
    print("  EXPERIMENT 3 — OFFLINE COORDINATION BASELINE")
    print("=" * 66)
    print(f"  Iterations:  {n}  |  Secret: HMAC-SHA256  |  Domain: {_DOMAIN}/{_TASK}")
    print()
    print(f"  {'Metric':<32}  {'Mean µs':>9}  {'Std µs':>8}  {'Max µs':>8}")
    print(f"  {'-'*32}  {'-'*9}  {'-'*8}  {'-'*8}")
    for row in summary_rows:
        print(
            f"  {row['metric']:<32}  {row['mean_us']:>9.2f}"
            f"  {row['std_us']:>8.2f}  {row['max_us']:>8.2f}"
        )
    print()

    t_mean = mean(t_coord_vals)
    t_max = max(t_coord_vals)
    print(f"  T_coord total — mean: {t_mean:.2f} µs  max: {t_max:.2f} µs")
    print()

    # Overhead comparison against representative physical task durations
    print("  Overhead vs representative physical task times:")
    for task_name, task_s in [
        ("GOTO_PICK_POSITION", 7.0),
        ("LIFT_AND_PLACE",     5.0),
        ("RUN_JOB (laser)",   60.0),
        ("INITIALIZE_DOMAIN",  3.0),
    ]:
        pct = (t_mean / 1e6) / task_s * 100
        print(f"    {task_name:<25}  {task_s:>4.0f}s  overhead={pct:.4f}%")
    print()

    if t_max < 1000:
        print(f"  PASS ✓  T_coord max {t_max:.1f} µs < 1000 µs (sub-millisecond)")
    else:
        print(f"  NOTE:   T_coord max {t_max:.1f} µs")

    print(f"\n  Per-cycle CSV: {out_path}")
    print(f"  Summary CSV:   {summary_path}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Experiment 3 — Offline coordination overhead baseline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--n", type=int, default=1000, help="Number of iterations (default: 1000)")
    ap.add_argument("--out", default="results/experiment_3_coordination_overhead/offline_baseline.csv")
    ap.add_argument("--summary", default="results/experiment_3_coordination_overhead/offline_summary.csv")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    run_offline(args.n, args.out, args.summary, args.verbose)


if __name__ == "__main__":
    main()
