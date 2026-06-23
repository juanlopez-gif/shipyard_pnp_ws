#!/usr/bin/env bash
# Experiment 1 — Boundary Enforcement
# Reproduces all 5 sub-experiments and generates summary.csv
# No ROS2 required. Run from the repository root.
#
# Usage:
#   cd /path/to/shipyard_pnp_ws
#   bash results/experiment_1_boundary_enforcement/run_experiment_1.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONPATH="$REPO_ROOT/src/shipyard_pnp"
export PYTHONPATH

OUT="$REPO_ROOT/results/experiment_1_boundary_enforcement"
mkdir -p "$OUT/logs"

run_probe() {
  local CASE="$1"; shift
  echo "=== $CASE ==="
  python3 "$REPO_ROOT/experiments/boundary_enforcement/run_probe.py" \
    --case "$CASE" "$@" \
    --sequential 100 --batch 100 \
    --out "$OUT/${CASE}.csv" \
    2>&1 | tee "$OUT/logs/${CASE}.log"
}

# 1a — Cross-vendor direct access (Theorem 2 / RQ4)
run_probe cross_vendor_access \
  --source bantam_vendor_probe \
  --destination /niryo_factory/command

# 1b1 — External injection, no token (Theorem 2 / RQ4)
run_probe external_no_token \
  --source external_probe \
  --destination /niryo_factory/command \
  --token none \
  --secret "shared_niryo_secret" \
  --enforce-hmac

# 1b2 — External injection, forged token (Theorem 2 / RQ4)
run_probe external_forged_token \
  --source external_probe \
  --destination /niryo_factory/command \
  --token forged \
  --secret "shared_niryo_secret" \
  --enforce-hmac

# 1c — Vendor-to-factory proprietary leakage (Theorem 3 / RQ2)
run_probe vendor_to_factory_leakage \
  --source niryo_vendor_supervisor \
  --destination /niryo_factory/status \
  --payload-type joint_angles

# 1d — Factory-to-vendor proprietary leakage (Theorem 3 / RQ2)
run_probe factory_to_vendor_leakage \
  --source factory_supervisor \
  --destination /niryo_factory/command \
  --payload-type servo_data

echo ""
echo "=== ANALYSIS ==="
python3 "$REPO_ROOT/experiments/boundary_enforcement/analyze_boundary_results.py" \
  --results-dir "$OUT" \
  --out "$OUT/summary.csv"
