#!/usr/bin/env bash
# Overnight batch generation of dynamic dispatch maps for the 17 pending
# compositions from the docs/dynamic_map_brrbrb/ proposal (3b3r3g already
# generated separately, skipped here). Runs generate_dynamic_map.py once per
# composition, sequentially (one candidate is beam-searched at a time inside
# each run already, no point parallelizing on top), continuing to the next
# composition even if one fails, with a per-run log file and a summary at
# the end.
#
# Usage:
#   cd /home/isecapstone/shipyard_pnp_ws
#   source /opt/ros/jazzy/setup.bash
#   source install/setup.bash
#   nohup ./scripts/run_overnight_dynamic_maps.sh > results/dynamic_map_generation_logs/_overnight_driver.log 2>&1 &
#   disown
#
# Then in the morning:
#   ls src/shipyard_pnp/config/dynamic_maps/
#   tail -f results/dynamic_map_generation_logs/_overnight_driver.log

set -uo pipefail

BEAM_WIDTH="${BEAM_WIDTH:-80}"
MAX_ROLLOUTS="${MAX_ROLLOUTS:-4000}"
MAX_LEVELS="${MAX_LEVELS:-400}"
PATIENCE="${PATIENCE:-8}"
TOP_K="${TOP_K:-20}"
SAMPLE_CAP="${SAMPLE_CAP:-2000}"
SEED="${SEED:-42}"

LOG_DIR="results/dynamic_map_generation_logs"
mkdir -p "$LOG_DIR"

# tag: order string   (any permutation of the composition works -- the
# script searches all/sampled permutations itself, this just fixes counts)
COMPOSITIONS=(
  "A1:BBBBBRRRR"
  "A2:BBBBRRRRR"
  "A3:BBBBBBRRRR"
  "A4:BBBBRRRRRR"
  "C1:BBBBBBRRGG"
  "C2:BBRRRRRRGG"
  "C3:BBRRGGGGGG"
  "B3:BBBBRRRGGG"
  "B4:BBBRRRRGGG"
  "B5:BBBRRRGGGG"
  "B6:BBBBRRRRGGG"
  "B7:BBBBRRRGGGG"
  "B8:BBBRRRRGGGG"
  "C4:BBBBBRRRRRGG"
  "C5:BBBBBRRGGGGG"
  "C6:BBRRRRRGGGGG"
  "B2:BBBBRRRRGGGG"
)

echo "=== overnight dynamic map generation started at $(date -Iseconds) ==="
echo "params: beam_width=$BEAM_WIDTH max_rollouts=$MAX_ROLLOUTS max_levels=$MAX_LEVELS patience=$PATIENCE top_k=$TOP_K sample_cap=$SAMPLE_CAP seed=$SEED"
echo "${#COMPOSITIONS[@]} compositions queued (3b3r3g already done, not included)"
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
echo "=== overnight dynamic map generation finished at $(date -Iseconds) ==="
echo "ok=$ok / $total"
if [ "${#failed[@]}" -gt 0 ]; then
  echo "failed (${#failed[@]}): ${failed[*]}"
else
  echo "no failures"
fi
