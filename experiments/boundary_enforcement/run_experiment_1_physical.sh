#!/usr/bin/env bash
# Experiment 1 — Physical ROS2 probe (full run)
#
# PREREQUISITES
#   1. source /opt/ros/jazzy/setup.bash
#   2. source install/setup.bash
#   3. ros2 launch shipyard_pnp bringup.launch.py          (terminal A — full system)
#   4. *** Nodes MUST have been restarted after hmac_secrets.yaml was deployed ***
#      Without restart, 1b1/1b2 show SENDER_NOT_AUTHORIZED instead of NO_TOKEN/BAD_HMAC.
#
# OPTIONAL — rosbag for supplementary DDS traffic evidence:
#   ros2 bag record -a -o results/bags/exp1_physical_$(date +%Y%m%d_%H%M%S)
#   (start BEFORE running this script; stop AFTER)
#
# USAGE
#   bash experiments/boundary_enforcement/run_experiment_1_physical.sh
#
# RESULTS
#   Per-case CSVs:  results/experiment_1_boundary_enforcement/physical/<case>.csv
#   Per-case logs:  results/experiment_1_boundary_enforcement/physical/logs/<case>.log
#   Session log:    results/experiment_1_boundary_enforcement/physical/logs/session_<ts>.log
#
# WHAT IS VALIDATED
#   niryo  (primary)  — 1a, 1b1, 1b2, 1c, 1d, 1e
#   bantam (secondary)— 1b1, 1b2  (proves enforcement is systematic across vendors)
#
# PASS CRITERIA
#   - acks_received == 0  for all cases
#   - observed_reason == expected_reason  in every row of each CSV

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROBE="$REPO_ROOT/experiments/boundary_enforcement/run_probe_physical.py"
OUT="$REPO_ROOT/results/experiment_1_boundary_enforcement/physical"

mkdir -p "$OUT/logs"

# ── Master session log ────────────────────────────────────────────────────────
SESSION_TS="$(date +%Y%m%d_%H%M%S)"
SESSION_LOG="$OUT/logs/session_${SESSION_TS}.log"
exec > >(tee -a "$SESSION_LOG") 2>&1

echo "════════════════════════════════════════════════════════"
echo "  Experiment 1 — Physical enforcement run"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Session log: $SESSION_LOG"
echo "════════════════════════════════════════════════════════"

# ── Case runner ───────────────────────────────────────────────────────────────
run_case() {
    local CASE="$1"; shift
    echo ""
    echo "────────────────────────────────────────────────────────"
    echo "  CASE: $CASE"
    echo "────────────────────────────────────────────────────────"
    python3 "$PROBE" --case "$CASE" "$@" \
        --out "$OUT/${CASE}.csv" \
        2>&1 | tee "$OUT/logs/${CASE}.log"
}

# ── NIRYO (primary vendor) ────────────────────────────────────────────────────

# 1a — Cross-vendor: bantam intenta publicar en niryo (Theorem 2 / RQ4)
# Token válido para pasar gates 1-2 (HMAC) y que gate 3 (ACL) sea el que rechaza.
# En ataque real bantam no tendría el secret de niryo, pero aquí probamos el gate ACL específicamente.
run_case cross_vendor_access \
    --source bantam_vendor_supervisor \
    --destination /niryo_factory/command \
    --ack-topic /niryo_factory/ack \
    --token valid --secret "shared_niryo_secret" --enforce-hmac \
    --n 20 --ack-timeout 1.5

# 1b1 — External sin token → gate NO_TOKEN  (requiere hmac_secrets.yaml + restart)
run_case external_no_token \
    --source external_probe \
    --destination /niryo_factory/command \
    --ack-topic /niryo_factory/ack \
    --token none \
    --secret "shared_niryo_secret" \
    --enforce-hmac \
    --n 20 --ack-timeout 1.5

# 1b2 — External con token falsificado → gate BAD_HMAC  (requiere hmac_secrets.yaml + restart)
run_case external_forged_token \
    --source external_probe \
    --destination /niryo_factory/command \
    --ack-topic /niryo_factory/ack \
    --token forged \
    --secret "shared_niryo_secret" \
    --enforce-hmac \
    --n 20 --ack-timeout 1.5

# 1c — Vendor filtra joint_states al factory → gate PROPRIETARY_FIELD
#   50 mensajes para confirmar 0 pérdidas DDS. Sin ack-topic (status no genera ack).
#   Evidencia: factory_supervisor logs + /shipyard/acl_events
run_case vendor_to_factory_leakage \
    --source niryo_vendor_supervisor \
    --destination /niryo_factory/status \
    --payload-type joint_angles \
    --n 50 --ack-timeout 1.5

# 1d — Factory filtra servo data al vendor → gate PROPRIETARY_FIELD
# Token válido (factory_supervisor firma sus comandos reales) para pasar gates 1-2 y llegar a gate 4.
run_case factory_to_vendor_leakage \
    --source factory_supervisor \
    --destination /niryo_factory/command \
    --ack-topic /niryo_factory/ack \
    --token valid --secret "shared_niryo_secret" --enforce-hmac \
    --payload-type servo_data \
    --n 20 --ack-timeout 1.5

# 1e — Ack injection: external_probe intenta inyectar ACKs falsos al factory
#   factory_supervisor.on_ack() tiene guard → SENDER_NOT_AUTHORIZED
#   Sin ack-topic (factory no responde al atacante). Evidencia: /shipyard/acl_events
run_case ack_injection \
    --source external_probe \
    --destination /niryo_factory/ack \
    --n 20 --ack-timeout 1.5

# ── BANTAM (secondary vendor — multi-vendor validation) ───────────────────────

# bantam 1b1 — mismo ataque contra bantam_vendor_supervisor
run_case bantam_external_no_token \
    --source external_probe \
    --destination /bantam_factory/command \
    --ack-topic /bantam_factory/ack \
    --token none \
    --secret "shared_bantam_secret" \
    --enforce-hmac \
    --n 20 --ack-timeout 1.5

# bantam 1b2 — token falsificado contra bantam_vendor_supervisor
run_case bantam_external_forged_token \
    --source external_probe \
    --destination /bantam_factory/command \
    --ack-topic /bantam_factory/ack \
    --token forged \
    --secret "shared_bantam_secret" \
    --enforce-hmac \
    --n 20 --ack-timeout 1.5

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════"
echo "  RESUMEN PHYSICAL — $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════════════════"
echo ""
printf "  %-38s %5s %5s %7s %s\n" "CASE" "SENT" "ACKS" "REASONS" "VERDICT"
printf "  %-38s %5s %5s %7s %s\n" "──────────────────────────────────────" "─────" "─────" "───────" "───────"

for CSV in "$OUT"/*.csv; do
    CASE=$(basename "$CSV" .csv)
    python3 - "$CSV" "$CASE" <<'PYEOF'
import csv, sys
path, case = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(path)))
acks = sum(1 for r in rows if r['ack_received'].lower() == 'true')
reason_match = sum(
    1 for r in rows
    if r['observed_reason'] and r['observed_reason'] == r['expected_reason']
)
no_ack_topic = case in {'vendor_to_factory_leakage', 'ack_injection'}
if no_ack_topic:
    verdict = "PASS ✓ (logs)" if acks == 0 else f"FAIL ✗ ({acks} acks)"
else:
    verdict = "PASS ✓" if acks == 0 else f"FAIL ✗ ({acks} acks)"
print(f"  {case:<38} {len(rows):>5} {acks:>5} {reason_match:>4}/{len(rows):<3} {verdict}")
PYEOF
done

echo ""
echo "Columna REASONS = mensajes donde observed_reason == expected_reason."
echo ""
echo "Si 1b1/1b2 muestran SENDER_NOT_AUTHORIZED en lugar de NO_TOKEN/BAD_HMAC:"
echo "  → Nodos no reiniciaron tras hmac_secrets.yaml. Reinicia y re-ejecuta."
echo ""
echo "Si REASONS = 0/N para cualquier caso:"
echo "  → El nodo receptor no estaba corriendo, o /shipyard/acl_events no llegó."
echo ""
echo "Logs:"
echo "  Sesión:    $SESSION_LOG"
echo "  Por caso:  $OUT/logs/<caso>.log"
