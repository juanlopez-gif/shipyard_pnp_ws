#!/usr/bin/env bash
# Overnight batch generation of dynamic dispatch maps for 5 compositions of
# 15 pieces (D1-D5, see chat). Same driver pattern as
# run_overnight_dynamic_maps.sh, but --top-k defaults lower (10 instead of
# 20) because the 9-12 piece batch already showed some single compositions
# taking up to ~228 minutes at top-k=20 -- at 15 pieces that risk is worse,
# not better, so this trades some search thoroughness for an actual chance
# of finishing overnight. Override TOP_K=20 (or any value) if you want the
# same thoroughness as the previous batch and are fine with it possibly
# spilling into the next day.
#
# Usage:
#   cd /home/isecapstone/shipyard_pnp_ws
#   source /opt/ros/jazzy/setup.bash
#   source install/setup.bash
#   mkdir -p results/dynamic_map_generation_logs
#   nohup ./scripts/run_overnight_dynamic_maps_15pc.sh > results/dynamic_map_generation_logs/_overnight_15pc_driver.log 2>&1 &
#   disown

set -uo pipefail

BEAM_WIDTH="${BEAM_WIDTH:-80}"
MAX_ROLLOUTS="${MAX_ROLLOUTS:-4000}"
MAX_LEVELS="${MAX_LEVELS:-400}"
PATIENCE="${PATIENCE:-8}"
TOP_K="${TOP_K:-10}"
SAMPLE_CAP="${SAMPLE_CAP:-2000}"
SEED="${SEED:-42}"

LOG_DIR="results/dynamic_map_generation_logs"
mkdir -p "$LOG_DIR"

# tag: order string (any permutation of the composition works)
COMPOSITIONS=(
  "D1:BBBBBBBBRRRRRRR"
  "D2:BBBBBRRRRRGGGGG"
  "D3:BBBBBBBBRRRRGGG"
  "D4:BBBRRRRRRRRGGGG"
  "D5:BBBBRRRGGGGGGGG"
)

echo "=== overnight 15-piece dynamic map generation started at $(date -Iseconds) ==="
echo "params: beam_width=$BEAM_WIDTH max_rollouts=$MAX_ROLLOUTS max_levels=$MAX_LEVELS patience=$PATIENCE top_k=$TOP_K sample_cap=$SAMPLE_CAP seed=$SEED"
echo "${#COMPOSITIONS[@]} compositions queued"
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
echo "=== overnight 15-piece dynamic map generation finished at $(date -Iseconds) ==="
echo "ok=$ok / $total"
if [ "${#failed[@]}" -gt 0 ]; then
  echo "failed (${#failed[@]}): ${failed[*]}"
else
  echo "no failures"
fi
