#!/usr/bin/env bash
# Overnight batch generation of dynamic dispatch maps for 10 NEW compositions
# spanning 12-15 pieces (F1-F10, see chat), distinct from the 4 (12pc) + 5
# (15pc) compositions already in the dataset.
#
# --top-k is set PER COMPOSITION to match the precedent already established
# for that size in the previous batches, not a single global value:
#   - n=12 (F1,F2):        --top-k 20  (matches run_overnight_dynamic_maps.sh,
#                                        used for all 9-12 piece compositions)
#   - n=13/14/15 (F3-F10): --top-k 10  (matches run_overnight_dynamic_maps_15pc.sh;
#                                        13/14 have no direct precedent, so this
#                                        rounds up to the more conservative
#                                        15pc setting rather than assuming the
#                                        cheaper 12pc setting still holds)
# beam_width/max_rollouts/max_levels/patience/sample_cap are unchanged from
# both previous batches (80/4000/400/8/2000) -- those never differed between
# the two precedents.
#
# Usage:
#   cd /home/isecapstone/shipyard_pnp_ws
#   source /opt/ros/jazzy/setup.bash
#   source install/setup.bash
#   mkdir -p results/dynamic_map_generation_logs
#   nohup ./scripts/run_overnight_dynamic_maps_12to15pc.sh > results/dynamic_map_generation_logs/_overnight_12to15pc_driver.log 2>&1 &
#   disown

set -uo pipefail

BEAM_WIDTH="${BEAM_WIDTH:-80}"
MAX_ROLLOUTS="${MAX_ROLLOUTS:-4000}"
MAX_LEVELS="${MAX_LEVELS:-400}"
PATIENCE="${PATIENCE:-8}"
SAMPLE_CAP="${SAMPLE_CAP:-2000}"
SEED="${SEED:-42}"

LOG_DIR="results/dynamic_map_generation_logs"
mkdir -p "$LOG_DIR"

# tag:order:top_k
COMPOSITIONS=(
  "F1:BBBBBBRRRRGG:20"
  "F2:BBBBRRRRRRGG:20"
  "F3:BBBBBRRRRRGGG:10"
  "F4:BBBBRRRRGGGGG:10"
  "F5:BBBBBBRRRRRGG:10"
  "F6:BBBBBRRRRRGGGG:10"
  "F7:BBBBBBRRRRGGGG:10"
  "F8:BBBBRRRRRRGGGG:10"
  "F9:BBBBBBRRRRRRGGG:10"
  "F10:BBBBBBBRRRRRGGG:10"
)

echo "=== overnight 12-15 piece dynamic map generation started at $(date -Iseconds) ==="
echo "shared params: beam_width=$BEAM_WIDTH max_rollouts=$MAX_ROLLOUTS max_levels=$MAX_LEVELS patience=$PATIENCE sample_cap=$SAMPLE_CAP seed=$SEED"
echo "${#COMPOSITIONS[@]} compositions queued, top-k per composition (20 for n=12, 10 for n=13-15)"
echo

ok=0
failed=()
total=${#COMPOSITIONS[@]}
i=0

for entry in "${COMPOSITIONS[@]}"; do
  i=$((i + 1))
  tag="${entry%%:*}"
  rest="${entry#*:}"
  order="${rest%%:*}"
  top_k="${rest#*:}"
  ts="$(date +%Y%m%d_%H%M%S)"
  log_file="$LOG_DIR/${tag}_${order}_${ts}.log"

  echo "[$i/$total] ($(date -Iseconds)) starting $tag ($order, top-k=$top_k) -> $log_file"

  python3 scripts/generate_dynamic_map.py "$order" \
    --top-k "$top_k" \
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
echo "=== overnight 12-15 piece dynamic map generation finished at $(date -Iseconds) ==="
echo "ok=$ok / $total"
if [ "${#failed[@]}" -gt 0 ]; then
  echo "failed (${#failed[@]}): ${failed[*]}"
else
  echo "no failures"
fi
