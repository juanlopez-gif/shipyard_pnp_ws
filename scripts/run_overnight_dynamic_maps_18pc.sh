#!/usr/bin/env bash
# Overnight batch generation of dynamic dispatch maps for 3 compositions of
# 18 pieces (E1-E3, see chat). Same driver pattern as the 9-12pc and 15pc
# batches, but --top-k defaults even lower (6) because per-composition cost
# roughly tripled going from 9 to 15 pieces in the previous batches -- at 18
# pieces the honest expectation is that even 3 compositions may not all
# finish in one night. Override TOP_K/BEAM_WIDTH/MAX_ROLLOUTS below if you
# want to trade more thoroughness for more (possibly much more) time.
#
# Requires scripts/generate_dynamic_map.py's closed-form permutation count +
# direct random sampling fix (2026-07-12) -- without it, the two balanced/
# skewed compositions here (17M+ and 14M+ unique permutations) would try to
# enumerate the full space before sampling and likely exhaust memory.
#
# Usage:
#   cd /home/isecapstone/shipyard_pnp_ws
#   source /opt/ros/jazzy/setup.bash
#   source install/setup.bash
#   mkdir -p results/dynamic_map_generation_logs
#   nohup ./scripts/run_overnight_dynamic_maps_18pc.sh > results/dynamic_map_generation_logs/_overnight_18pc_driver.log 2>&1 &
#   disown

set -uo pipefail

BEAM_WIDTH="${BEAM_WIDTH:-60}"
MAX_ROLLOUTS="${MAX_ROLLOUTS:-3000}"
MAX_LEVELS="${MAX_LEVELS:-400}"
PATIENCE="${PATIENCE:-8}"
TOP_K="${TOP_K:-6}"
SAMPLE_CAP="${SAMPLE_CAP:-2000}"
SEED="${SEED:-42}"

LOG_DIR="results/dynamic_map_generation_logs"
mkdir -p "$LOG_DIR"

# tag: order string (any permutation of the composition works)
COMPOSITIONS=(
  "E1:BBBBBBBBBRRRRRRRRR"
  "E2:BBBBBBRRRRRRGGGGGG"
  "E3:BBBBBBBRRRRRRGGGGG"
)

echo "=== overnight 18-piece dynamic map generation started at $(date -Iseconds) ==="
echo "params: beam_width=$BEAM_WIDTH max_rollouts=$MAX_ROLLOUTS max_levels=$MAX_LEVELS patience=$PATIENCE top_k=$TOP_K sample_cap=$SAMPLE_CAP seed=$SEED"
echo "${#COMPOSITIONS[@]} compositions queued -- E2/E3 have 14-17M unique permutations, sampled at $SAMPLE_CAP"
echo

ok=0
failed=()
total=${#COMPOSITIONS[@]}
i=0

for entry in "${COMPOSITIONS[@]}"; do
  i=$((i + 1))
  tag="${entry%%:*}"
  order="${entry#*:}"
  ts="$(date +%Y%m%d_%H%M%S)"
  log_file="$LOG_DIR/${tag}_${order}_${ts}.log"

  echo "[$i/$total] ($(date -Iseconds)) starting $tag ($order) -> $log_file"

  python3 scripts/generate_dynamic_map.py "$order" \
    --top-k "$TOP_K" \
    --beam-width "$BEAM_WIDTH" \
    --max-levels "$MAX_LEVELS" \
    --patience "$PATIENCE" \
    --max-rollouts "$MAX_ROLLOUTS" \
    --sample-cap "$SAMPLE_CAP" \
    --seed "$SEED" \
    > "$log_file" 2>&1

  status=$?
  if [ $status -eq 0 ]; then
    ok=$((ok + 1))
    echo "[$i/$total] ($(date -Iseconds)) OK   $tag ($order)"
  else
    failed+=("$tag:$order")
    echo "[$i/$total] ($(date -Iseconds)) FAIL $tag ($order) -- exit $status, see $log_file"
  fi
done

echo
echo "=== overnight 18-piece dynamic map generation finished at $(date -Iseconds) ==="
echo "ok=$ok / $total"
if [ "${#failed[@]}" -gt 0 ]; then
  echo "failed (${#failed[@]}): ${failed[*]}"
else
  echo "no failures"
fi
