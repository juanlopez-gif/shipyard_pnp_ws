#!/usr/bin/env python3
"""
Experiment 3 — Coordination Overhead Analyzer (Physical ROS2 bag)

Reads a ROS2 MCAP bag recorded during system operation and computes
per-task coordination latencies:

  T_cmd_ms     = command published by FS → ack received by bag recorder
                 (≈ command DDS transit + VS immediate processing + ack DDS transit)
  T_status_ms  = status published by VS → status received by bag recorder
                 (= status DDS transit, derived from published_at vs bag timestamp)
  T_coord_ms   = T_cmd_ms + T_status_ms  [total coordination overhead per task]
  physical_s   = ack published_at → terminal status published_at  [hardware time]
  overhead_%   = T_coord_ms / (T_coord_ms + physical_s*1000) * 100

Validates RQ5: T_coord stays in milliseconds; physical tasks take seconds.
Each task uses exactly 1 command + 1 ack + 1 status (3-message contract).

Prerequisites:
  source /opt/ros/jazzy/setup.bash
  source install/setup.bash

Usage:
  python3 experiments/coordination_overhead/analyze_rosbag.py \\
    --bag results/bags/exp3_coordination_overhead \\
    --vendors niryo ufactory laser globalvision green_conveyors arduino_vacuum bantam \\
    --out results/experiment_3_coordination_overhead/coordination_latencies.csv \\
    --summary results/experiment_3_coordination_overhead/coordination_summary.csv

Pass criteria:
  - Every complete cycle has exactly 1 command, 1 ack, 1 terminal status
  - T_coord max < 1000 ms (sub-second coordination overhead)
  - Physical task time >> T_coord (overhead % < 1%)
"""

import argparse
import csv
import json
import struct
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Optional

try:
    import rosbag2_py
    _HAS_ROS2 = True
except ImportError:
    _HAS_ROS2 = False

_CYCLE_FIELDS = [
    "vendor", "resource_id", "task", "command_id",
    "T_cmd_ms", "T_status_ms", "T_coord_ms",
    "physical_task_s", "overhead_percent",
    "task_state", "piece_id",
]

_SUMMARY_FIELDS = ["metric", "mean", "std", "min", "max", "count", "unit"]

TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "REJECTED", "TIMEOUT", "CANCELED"})


def _iso_to_ns(iso: str) -> int:
    ts = iso.rstrip("Z")
    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


def _decode_string_msg(data: bytes) -> Optional[str]:
    """Decode CDR-serialized std_msgs/String."""
    if len(data) < 8:
        return None
    length = struct.unpack_from("<I", data, 4)[0]
    if length == 0 or len(data) < 8 + length:
        return None
    return data[8:8 + length].rstrip(b"\x00").decode("utf-8", errors="replace")


def _read_bag(bag_path: str, topics: list) -> list:
    """Return list of (topic, payload_dict, bag_timestamp_ns)."""
    storage = rosbag2_py.StorageOptions(uri=bag_path, storage_id="mcap")
    converter = rosbag2_py.ConverterOptions(
        input_serialization_format="cdr",
        output_serialization_format="cdr",
    )
    reader = rosbag2_py.SequentialReader()
    reader.open(storage, converter)
    topic_set = set(topics)
    out = []
    while reader.has_next():
        topic, data, stamp_ns = reader.read_next()
        if topic not in topic_set:
            continue
        text = _decode_string_msg(data)
        if text is None:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        out.append((topic, payload, stamp_ns))
    return out


def _build_topics(vendors: list) -> list:
    topics = []
    for v in vendors:
        for suffix in ("command", "ack", "status"):
            topics.append(f"/{v}_factory/{suffix}")
    return topics


def _stats(values: list) -> dict:
    if not values:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "count": 0}
    return {
        "mean": round(mean(values), 3),
        "std": round(stdev(values) if len(values) > 1 else 0.0, 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "count": len(values),
    }


def analyze(bag_path: str, vendors: list, out_path: str, summary_path: str, verbose: bool) -> None:
    topics = _build_topics(vendors)
    print(f"Bag:     {bag_path}")
    print(f"Vendors: {', '.join(vendors)}")
    print(f"Topics:  {len(topics)}")

    messages = _read_bag(bag_path, topics)
    print(f"Messages read: {len(messages)}")

    by_cmd: dict = defaultdict(lambda: {
        "command": None, "cmd_bag_ns": None,
        "ack": None, "ack_bag_ns": None,
        "status": None, "status_bag_ns": None,
    })

    for topic, payload, bag_ns in messages:
        cmd_id = payload.get("command_id", "")
        if not cmd_id or cmd_id == "AUTO":
            continue
        schema = payload.get("schema", "")
        entry = by_cmd[cmd_id]
        if "command" in schema and entry["command"] is None:
            entry["command"] = payload
            entry["cmd_bag_ns"] = bag_ns
        elif "ack" in schema and entry["ack"] is None:
            entry["ack"] = payload
            entry["ack_bag_ns"] = bag_ns
        elif "status" in schema:
            if payload.get("task_state") in TERMINAL_STATES and entry["status"] is None:
                entry["status"] = payload
                entry["status_bag_ns"] = bag_ns

    cycles = []
    skipped = 0

    for cmd_id, entry in by_cmd.items():
        cmd, ack, status = entry["command"], entry["ack"], entry["status"]
        if cmd is None or ack is None or status is None:
            skipped += 1
            if verbose:
                miss = [n for n, v in [("cmd", cmd), ("ack", ack), ("status", status)] if v is None]
                print(f"  SKIP {cmd_id[:24]}: missing {miss}")
            continue

        try:
            # T_cmd: command bag arrival → ack bag arrival (roundtrip seen by bag recorder)
            T_cmd_ms = (entry["ack_bag_ns"] - entry["cmd_bag_ns"]) / 1e6

            # Physical task time: ack accepted_at → terminal status published_at (ISO timestamps)
            t_ack_pub_ns = _iso_to_ns(ack["accepted_at"])
            t_status_pub_ns = _iso_to_ns(status["published_at"])
            physical_task_s = (t_status_pub_ns - t_ack_pub_ns) / 1e9

            # T_status: DDS transit for status (published_at → bag recorder received it)
            T_status_ms = max(0.0, (entry["status_bag_ns"] - t_status_pub_ns) / 1e6)

            T_coord_ms = T_cmd_ms + T_status_ms
            overhead_pct = (
                100.0 if physical_task_s <= 0
                else T_coord_ms / (T_coord_ms + physical_task_s * 1000) * 100
            )
        except (KeyError, ValueError) as exc:
            skipped += 1
            if verbose:
                print(f"  SKIP {cmd_id[:24]}: {exc}")
            continue

        row = {
            "vendor":          cmd.get("domain_id", ""),
            "resource_id":     cmd.get("resource_id", ""),
            "task":            cmd.get("task", ""),
            "command_id":      cmd_id,
            "T_cmd_ms":        round(T_cmd_ms, 3),
            "T_status_ms":     round(T_status_ms, 3),
            "T_coord_ms":      round(T_coord_ms, 3),
            "physical_task_s": round(physical_task_s, 3),
            "overhead_percent": round(overhead_pct, 2),
            "task_state":      status.get("task_state", ""),
            "piece_id":        cmd.get("piece_id", ""),
        }
        cycles.append(row)

        if verbose:
            print(
                f"  {row['vendor']:20s} {row['task']:25s}"
                f"  T_coord={T_coord_ms:.1f}ms  phys={physical_task_s:.2f}s"
                f"  overhead={overhead_pct:.2f}%"
            )

    print(f"\nComplete cycles: {len(cycles)}  Skipped (incomplete): {skipped}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_CYCLE_FIELDS)
        w.writeheader()
        w.writerows(cycles)
    print(f"Per-cycle CSV: {out_path}")

    if not cycles:
        print("No complete cycles. Check bag content and topic names.")
        return

    t_cmd_vals = [c["T_cmd_ms"] for c in cycles]
    t_status_vals = [c["T_status_ms"] for c in cycles]
    t_coord_vals = [c["T_coord_ms"] for c in cycles]
    phys_vals = [c["physical_task_s"] for c in cycles]
    overhead_vals = [c["overhead_percent"] for c in cycles]

    summary_rows = [
        {"metric": "command_to_ack_roundtrip_T_cmd", **_stats(t_cmd_vals),    "unit": "ms"},
        {"metric": "status_transit_T_status",         **_stats(t_status_vals), "unit": "ms"},
        {"metric": "total_T_coord_per_task",          **_stats(t_coord_vals),  "unit": "ms"},
        {"metric": "physical_task_time",              **_stats(phys_vals),     "unit": "s"},
        {"metric": "overhead_percent",                **_stats(overhead_vals), "unit": "%"},
    ]

    summary_path = Path(summary_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_SUMMARY_FIELDS)
        w.writeheader()
        w.writerows(summary_rows)
    print(f"Summary CSV:   {summary_path}")

    print()
    print("=" * 66)
    print("  EXPERIMENT 3 — COORDINATION OVERHEAD RESULTS")
    print("=" * 66)
    print(f"  {'Metric':<40}  {'Mean':>8}  {'Std':>7}  {'Max':>7}  {'N':>5}")
    print(f"  {'-'*40}  {'-'*8}  {'-'*7}  {'-'*7}  {'-'*5}")
    for row in summary_rows:
        u = row["unit"]
        print(
            f"  {row['metric']:<40}  {row['mean']:>7.2f}{u}"
            f"  {row['std']:>6.2f}{u}  {row['max']:>6.2f}{u}  {row['count']:>5}"
        )

    print()
    print(f"  T_coord range: {min(t_coord_vals):.1f} – {max(t_coord_vals):.1f} ms")
    print(f"  Physical task: {min(phys_vals):.1f} – {max(phys_vals):.1f} s")
    print(f"  Mean overhead: {mean(overhead_vals):.3f}%")
    print()

    verdict = "PASS ✓" if max(t_coord_vals) < 1000 else "NOTE: check outliers"
    print(f"  T_coord max < 1000 ms:    {verdict}")
    all_terminal = all(c["task_state"] in TERMINAL_STATES for c in cycles)
    print(f"  All cycles terminal:      {'PASS ✓' if all_terminal else 'FAIL ✗'}")

    print()
    print("  Per-vendor breakdown:")
    per_vendor: dict = defaultdict(list)
    for c in cycles:
        per_vendor[c["vendor"]].append(c)
    for vendor, vc in sorted(per_vendor.items()):
        v_coord = [c["T_coord_ms"] for c in vc]
        v_phys = [c["physical_task_s"] for c in vc]
        print(
            f"    {vendor:<22} n={len(vc):>3}"
            f"  T_coord={mean(v_coord):.1f}ms  phys={mean(v_phys):.2f}s"
        )


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Experiment 3 — Coordination overhead bag analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--bag", required=True, help="Path to ROS2 MCAP bag directory")
    ap.add_argument(
        "--vendors", nargs="+",
        default=["niryo", "ufactory", "laser", "globalvision",
                 "green_conveyors", "arduino_vacuum", "bantam"],
    )
    ap.add_argument("--out", default="results/experiment_3_coordination_overhead/coordination_latencies.csv")
    ap.add_argument("--summary", default="results/experiment_3_coordination_overhead/coordination_summary.csv")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    if not _HAS_ROS2:
        print("ERROR: rosbag2_py not available.", file=sys.stderr)
        print("  source /opt/ros/jazzy/setup.bash && source install/setup.bash", file=sys.stderr)
        sys.exit(1)

    if not Path(args.bag).exists():
        print(f"ERROR: bag not found: {args.bag}", file=sys.stderr)
        sys.exit(1)

    analyze(args.bag, args.vendors, args.out, args.summary, args.verbose)


if __name__ == "__main__":
    main()
