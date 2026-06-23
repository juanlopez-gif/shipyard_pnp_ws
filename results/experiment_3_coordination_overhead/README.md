# Experiment 3 — Coordination Overhead

**Research question:** RQ5 — Is the coordination overhead bounded by exactly 3 messages per vendor task?
**Theorem validated:** T_coord stays in milliseconds; physical tasks take seconds → overhead negligible.
**Status: COMPLETE — Offline PASS + Physical PASS (2026-06-23)**

---

## What this experiment validates

The Plug-and-Plan protocol uses exactly **3 messages per vendor task**:

```
Factory Supervisor  →  /{vendor}_factory/command  →  Vendor Supervisor
Vendor Supervisor   →  /{vendor}_factory/ack      →  Factory Supervisor
Vendor Supervisor   →  /{vendor}_factory/status   →  Factory Supervisor
```

Coordination overhead per task:

```
T_coord = T_cmd + T_status

T_cmd    = time from command published (FS) to ack received by bag recorder
           ≈ command DDS transit + VS immediate processing + ack DDS transit
T_status = time from status.published_at (ISO) to status bag timestamp
           = status DDS transit latency
```

Physical task time = `ack.accepted_at → status.published_at` (hardware execution, seconds).

**Pass criteria:**
- `T_coord` max < 1000 ms
- All complete cycles have exactly 1 command + 1 ack + 1 terminal status (3-message contract)
- Overhead % < 1% for tasks with meaningful physical duration (> 1 s)

---

## Results — Offline (no ROS2, no hardware)

Measures software-layer lower bound: build + HMAC-sign + JSON-serialize + parse + verify for
a full command/ack/status cycle. 1000 iterations. Domain: `niryo/GOTO_PICK_POSITION`.

Run date: 2026-06-23.

| Metric | Mean µs | Std µs | Max µs |
|--------|---------|--------|--------|
| command_build_and_sign | 38.05 | 10.36 | 118.31 |
| command_json_serialize | 13.22 | 5.07 | 70.54 |
| command_json_parse | 13.18 | 6.21 | 76.20 |
| command_hmac_verify | 9.72 | 4.75 | 61.53 |
| ack_build_and_sign | 23.70 | 6.64 | 87.65 |
| ack_json_serialize | 11.61 | 5.48 | 119.92 |
| status_build_and_sign | 24.72 | 7.35 | 77.80 |
| status_json_serialize | 12.88 | 4.86 | 69.21 |
| **T_coord_total** | **147.08** | **31.64** | **290.54** |

**PASS ✓ — T_coord max 290.5 µs < 1000 µs (sub-millisecond, software only)**

---

## Results — Physical (ROS2 DDS, full testbed running)

**86 complete cycles** across all 7 vendor domains, recorded from a live production run.
2 messages skipped (incomplete cycles at bag start/end).
Run date: 2026-06-23. Log: `session_20260623_162754.log`.

### Global summary

| Metric | Mean | Std | Min | Max | N |
|--------|------|-----|-----|-----|---|
| T_cmd (command roundtrip) | 6.49 ms | 6.22 ms | 1.13 ms | 47.83 ms | 86 |
| T_status (status transit) | 0.44 ms | 0.38 ms | 0.11 ms | 2.62 ms | 86 |
| **T_coord total** | **6.93 ms** | **6.24 ms** | **1.49 ms** | **47.99 ms** | **86** |
| Physical task time | 8.90 s | 9.99 s | 0.005 s | 49.05 s | 86 |
| Overhead % | 2.93% | 10.31% | 0.01% | 75.01% | 86 |

**PASS ✓ — T_coord max 47.99 ms < 1000 ms. All 86 cycles terminal.**

### Per-vendor breakdown

| Vendor | N | T_coord mean | Physical mean |
|--------|---|-------------|---------------|
| arduino_vacuum | 12 | 2.4 ms | 1.46 s |
| bantam | 3 | 11.7 ms | 36.50 s |
| globalvision | 5 | 5.8 ms | 0.01 s |
| green_conveyors | 14 | 3.0 ms | 0.41 s |
| laser | 1 | 2.9 ms | 22.88 s |
| niryo | 39 | 8.7 ms | 12.19 s |
| ufactory | 12 | 10.0 ms | 11.19 s |

### Overhead for tasks with physical duration > 1 s

| Vendor | N | T_coord mean | Physical mean | Overhead mean |
|--------|---|-------------|---------------|---------------|
| arduino_vacuum | 12 | 2.4 ms | 1.46 s | 0.164% |
| bantam | 3 | 11.7 ms | 36.50 s | 0.067% |
| laser | 1 | 2.9 ms | 22.88 s | 0.010% |
| niryo | 36 | 8.9 ms | 13.18 s | 0.084% |
| ufactory | 12 | 10.0 ms | 11.19 s | 0.103% |

**For all tasks with real physical duration: overhead < 0.2%**

---

## Key findings

1. **3-message contract holds across all 7 vendors**: Every coordination cycle uses exactly command + ack + terminal status — no additional topics regardless of vendor internal complexity (niryo controls 6 resources through a single domain, still 3 messages per task).

2. **T_coord is sub-50 ms in the worst case**: The 47.99 ms maximum corresponds to an `ufactory MOVE_PIECE` command at system startup (DDS discovery overhead). Steady-state T_coord is 2–11 ms per task.

3. **T_status latency is < 3 ms**: Status DDS transit (mean 0.44 ms, max 2.62 ms) confirms the status message reaches the Factory Supervisor near-instantaneously after the vendor publishes it.

4. **Overhead for physical tasks is < 0.2%**: For all tasks with hardware execution > 1 s (robot motion, laser job, CNC job, vacuum), the coordination overhead represents less than 0.2% of total task time. The protocol is negligible relative to the physical work.

5. **Apparent high overhead for near-instant tasks** (globalvision LOCATE_NEXT_PIECE ~10ms, STOP_CONVEYOR ~80ms): T_coord (5–20ms DDS) is comparable to the physical task time for these operations. This is expected — fast camera queries and conveyor stops complete in milliseconds, so any fixed DDS overhead appears large in percentage terms. The absolute overhead (< 20 ms) remains small.

6. **Software-only lower bound** (offline): The 3-message cycle costs 147 µs mean (290 µs worst case) in pure software. DDS adds ~6.5 ms on average. Combined T_coord is dominated by DDS transport, not by message processing.

---

## Reproduce

```bash
# Offline baseline (no hardware needed):
python3 experiments/coordination_overhead/run_experiment_3_offline.py --n 1000

# Full run (offline + bag analysis):
bash experiments/coordination_overhead/run_experiment_3.sh --physical
```

---

## Files

| File | Description |
|------|-------------|
| `offline_baseline.csv` | 1000 per-cycle software measurements (µs per step) |
| `offline_summary.csv` | mean/std/min/max per serialization step |
| `coordination_latencies.csv` | 86 physical cycles: T_cmd / T_status / T_coord / phys / overhead |
| `coordination_summary.csv` | Global statistics from physical run |
| `session_20260623_162754.log` | Full session log |

### Scripts

| Script | Description |
|--------|-------------|
| `experiments/coordination_overhead/run_experiment_3_offline.py` | Offline baseline (no ROS2) |
| `experiments/coordination_overhead/analyze_rosbag.py` | Reads MCAP bag, computes T_coord |
| `experiments/coordination_overhead/run_experiment_3.sh` | Master runner |
