#!/usr/bin/env bash
# Experiment 3 — Coordination Overhead
#
# Two modes:
#   offline  (default) — measures message-layer overhead without ROS2 or hardware.
#                        Runs immediately. Provides a sub-millisecond baseline.
#   physical           — requires full system + ROS2 bag. Measures real DDS latency.
#
# USAGE
#   bash experiments/coordination_overhead/run_experiment_3.sh            # offline only
#   bash experiments/coordination_overhead/run_experiment_3.sh --physical # offline + bag analysis
#
# PHYSICAL PREREQUISITES
#   1. source /opt/ros/jazzy/setup.bash && source install/setup.bash
#   2. ros2 launch shipyard_pnp bringup.launch.py    (terminal A — full system)
#   3. ros2 bag record -o results/bags/exp3_coordination_overhead \
#        /niryo_factory/command    /niryo_factory/ack    /niryo_factory/status \
#        /ufactory_factory/command /ufactory_factory/ack /ufactory_factory/status \
#        /laser_factory/command    /laser_factory/ack    /laser_factory/status \
#        /globalvision_factory/command /globalvision_factory/ack /globalvision_factory/status \
#        /green_conveyors_factory/command /green_conveyors_factory/ack /green_conveyors_factory/status \
#        /arduino_vacuum_factory/command  /arduino_vacuum_factory/ack  /arduino_vacuum_factory/status \
#        /bantam_factory/command   /bantam_factory/ack   /bantam_factory/status  (terminal B)
#   4. Let system run for at least 3 full production cycles
#   5. Stop bag recorder (Ctrl+C in terminal B)
#   6. bash experiments/coordination_overhead/run_experiment_3.sh --physical

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT_DIR="$REPO_ROOT/experiments/coordination_overhead"
OUT="$REPO_ROOT/results/experiment_3_coordination_overhead"
BAG="$REPO_ROOT/results/bags/exp3_coordination_overhead"

PHYSICAL=false
for arg in "$@"; do
    [[ "$arg" == "--physical" ]] && PHYSICAL=true
done

mkdir -p "$OUT"
SESSION_TS="$(date +%Y%m%d_%H%M%S)"
SESSION_LOG="$OUT/session_${SESSION_TS}.log"
exec > >(tee -a "$SESSION_LOG") 2>&1

echo "════════════════════════════════════════════════════════"
echo "  Experiment 3 — Coordination Overhead"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Log: $SESSION_LOG"
echo "════════════════════════════════════════════════════════"

# ── Phase 1: Offline baseline ─────────────────────────────────────────────────
echo ""
echo "────────────────────────────────────────────────────────"
echo "  Phase 1: Offline — message serialization overhead"
echo "────────────────────────────────────────────────────────"

python3 "$SCRIPT_DIR/run_experiment_3_offline.py" \
    --n 1000 \
    --out   "$OUT/offline_baseline.csv" \
    --summary "$OUT/offline_summary.csv"

echo ""
echo "Offline phase complete."
echo "  offline_baseline.csv  — 1000 per-cycle measurements"
echo "  offline_summary.csv   — mean/std/min/max per step"

# ── Phase 2: Physical bag analysis ───────────────────────────────────────────
if [[ "$PHYSICAL" == true ]]; then
    echo ""
    echo "────────────────────────────────────────────────────────"
    echo "  Phase 2: Physical — ROS2 bag analysis"
    echo "────────────────────────────────────────────────────────"

    if [[ ! -d "$BAG" ]]; then
        echo "ERROR: bag not found at $BAG"
        echo "  Record a bag first (see script header for instructions)."
        exit 1
    fi

    python3 "$SCRIPT_DIR/analyze_rosbag.py" \
        --bag "$BAG" \
        --vendors niryo ufactory laser globalvision green_conveyors arduino_vacuum bantam \
        --out     "$OUT/coordination_latencies.csv" \
        --summary "$OUT/coordination_summary.csv" \
        --verbose

    echo ""
    echo "Physical phase complete."
    echo "  coordination_latencies.csv — per-cycle T_cmd / T_status / T_coord"
    echo "  coordination_summary.csv   — aggregated statistics"
else
    echo ""
    echo "────────────────────────────────────────────────────────"
    echo "  Phase 2: Physical (skipped — run with --physical)"
    echo "────────────────────────────────────────────────────────"
    echo ""
    echo "  To run the physical bag analysis:"
    echo "    1. Record a bag (see script header)"
    echo "    2. bash experiments/coordination_overhead/run_experiment_3.sh --physical"
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo "  Experiment 3 complete — $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Results: $OUT/"
echo "════════════════════════════════════════════════════════"
