#!/usr/bin/env bash
# 5 dedicated lanes, 10 compositions each, 50 total NEW compositions (9-18
# pieces, none overlapping the 26 already in dynamic_maps/ nor the F1-F10
# from run_parallel_dynamic_maps_12to15pc.sh). Each lane runs its own queue
# of 10 SEQUENTIALLY; the 5 lanes run CONCURRENTLY (one background subshell
# per lane) -- so at most 5 generate_dynamic_map.py processes are alive at
# once, matching this machine's headroom (8 threads, ~3 free for the real
# ROS2 system if it's running too).
#
# Compositions were dealt round-robin (largest-n-first) across the 5 lanes
# so each lane's total piece-count sum is balanced (~132-138 each) --
# a lane isn't left doing all the cheap ones while another does all the
# expensive ones.
#
# --sample-cap 20000 throughout (see chat: cheap to raise, doesn't touch
# stage-2 cost, meaningfully improves "best found" confidence -- several of
# the smaller compositions here have <20000 total permutations and become
# fully exhaustive automatically).
#
# Per-composition entry format: tag:order:top_k:beam_width:max_rollouts.
# top_k/beam_width/max_rollouts follow the size bands already established:
#   n<=12:  top_k=20, beam_width=80,  max_rollouts=4000
#   n=13-15: top_k=10, beam_width=80,  max_rollouts=4000
#   n=16-18: top_k=6,  beam_width=60,  max_rollouts=3000  (matches the E1-E3
#            18-piece precedent; 16/17 have no direct precedent so this
#            rounds up to the more conservative band, not the cheaper one)
#
# Usage:
#   cd /home/isecapstone/shipyard_pnp_ws
#   source /opt/ros/jazzy/setup.bash
#   source install/setup.bash
#   mkdir -p results/dynamic_map_generation_logs
#   nohup ./scripts/run_5lane_dynamic_maps_50comp.sh > results/dynamic_map_generation_logs/_5lane_50comp_driver.log 2>&1 &
#   disown

set -uo pipefail

SAMPLE_CAP="${SAMPLE_CAP:-20000}"
PATIENCE="${PATIENCE:-8}"
MAX_LEVELS="${MAX_LEVELS:-400}"
SEED="${SEED:-42}"

LOG_DIR="results/dynamic_map_generation_logs"
mkdir -p "$LOG_DIR"

# tag:order:top_k:beam_width:max_rollouts
LANE_A=(
  "GA1:BBBBBBBBBRRRRRRRGG:6:60:3000"
  "GA2:BBBBBBBBBBBRRGGGG:6:60:3000"
  "GA3:BBBBBBBBBBBRRGGG:6:60:3000"
  "GA4:BBBRRRRRRRRRRRR:10:80:4000"
  "GA5:BBBBBBBBBBRRGG:10:80:4000"
  "GA6:BBBBBBRRGGGGG:10:80:4000"
  "GA7:BBBBBRRGGGGGG:10:80:4000"
  "GA8:BBBRRGGGGGGG:20:80:4000"
  "GA9:BBBBBBRRGGG:20:80:4000"
  "GA10:BBBBBRRGG:20:80:4000"
)
LANE_B=(
  "GB1:BBBBBBBBBBBRRGGGGG:6:60:3000"
  "GB2:BBBBBBBBBBBBBRRGG:6:60:3000"
  "GB3:BBBBRRRRRRRRRRGG:6:60:3000"
  "GB4:BBBBBBBBRRRRRGG:10:80:4000"
  "GB5:BBBBBBBBRRRRRR:10:80:4000"
  "GB6:BBBBBBBBRRRRR:10:80:4000"
  "GB7:BBBBBBRRGGGG:20:80:4000"
  "GB8:BBBBBBBRRGGG:20:80:4000"
  "GB9:BBBRRGGGGG:20:80:4000"
  "GB10:BBBRRRRRR:20:80:4000"
)
LANE_C=(
  "GC1:BBBBBBBBBBBRRRRRGG:6:60:3000"
  "GC2:BBBRRRRRRRRRRRRRR:6:60:3000"
  "GC3:BBBBBBRRGGGGGGGG:6:60:3000"
  "GC4:BBBBBRRGGGGGGGG:10:80:4000"
  "GC5:BBBBRRGGGGGGGG:10:80:4000"
  "GC6:BBBRRGGGGGGGG:10:80:4000"
  "GC7:BBRRGGGGGGGG:20:80:4000"
  "GC8:BBBBBRRGGGG:20:80:4000"
  "GC9:BBBBBRRGGG:20:80:4000"
  "GC10:BBRRRRRGG:20:80:4000"
)
LANE_D=(
  "GD1:BBBRRRRRRRRRRRRRRR:6:60:3000"
  "GD2:BBBBBBRRRRRRRRRGG:6:60:3000"
  "GD3:BBBRRRRRRGGGGGG:10:80:4000"
  "GD4:BBBBBBBBBBBRRGG:10:80:4000"
  "GD5:BBBBBBBBBBRRRR:10:80:4000"
  "GD6:BBBBBRRRGGGGG:10:80:4000"
  "GD7:BBBRRRRRRRGG:20:80:4000"
  "GD8:BBBBBRRRRGG:20:80:4000"
  "GD9:BBBBRRGGGG:20:80:4000"
  "GD10:BBRRRGGGG:20:80:4000"
)
LANE_E=(
  "GE1:BBBBBRRRRGGGGGGGG:6:60:3000"
  "GE2:BBBBBBBBBRRRRRGG:6:60:3000"
  "GE3:BBBBBBBRRRRRRRR:10:80:4000"
  "GE4:BBBBRRRRRRRRRRR:10:80:4000"
  "GE5:BBBBRRRRRRRRGG:10:80:4000"
  "GE6:BBBRRRGGGGGGG:10:80:4000"
  "GE7:BBBBBBBBRRGG:20:80:4000"
  "GE8:BBBRRRGGGGG:20:80:4000"
  "GE9:BBBBBBBRRR:20:80:4000"
  "GE10:BBBBRRGGG:20:80:4000"
)

run_lane() {
  local lane_name="$1"
  shift
  local entries=("$@")
  local ok=0
  local total=${#entries[@]}
  local i=0
  for entry in "${entries[@]}"; do
    i=$((i + 1))
    local tag order top_k beam_w rollouts ts log_file
    IFS=':' read -r tag order top_k beam_w rollouts <<< "$entry"
    ts="$(date +%Y%m%d_%H%M%S)"
    log_file="$LOG_DIR/${tag}_${order}_${ts}.log"
    echo "[lane $lane_name $i/$total] ($(date -Iseconds)) starting $tag ($order, top-k=$top_k) -> $log_file"
    python3 scripts/generate_dynamic_map.py "$order" \
      --top-k "$top_k" \
      --beam-width "$beam_w" \
      --max-levels "$MAX_LEVELS" \
      --patience "$PATIENCE" \
      --max-rollouts "$rollouts" \
      --sample-cap "$SAMPLE_CAP" \
      --seed "$SEED" \
      > "$log_file" 2>&1
    if [ $? -eq 0 ]; then
      ok=$((ok + 1))
      echo "[lane $lane_name $i/$total] ($(date -Iseconds)) OK   $tag"
    else
      echo "[lane $lane_name $i/$total] ($(date -Iseconds)) FAIL $tag"
    fi
  done
  echo "[lane $lane_name] finished: ok=$ok/$total"
}

echo "=== 5-lane 50-composition dynamic map generation started at $(date -Iseconds) ==="
echo "sample_cap=$SAMPLE_CAP patience=$PATIENCE max_levels=$MAX_LEVELS seed=$SEED"
echo "5 lanes x 10 compositions each, running concurrently"
echo

run_lane "A" "${LANE_A[@]}" &
run_lane "B" "${LANE_B[@]}" &
run_lane "C" "${LANE_C[@]}" &
run_lane "D" "${LANE_D[@]}" &
run_lane "E" "${LANE_E[@]}" &

wait

echo
echo "=== 5-lane 50-composition dynamic map generation finished at $(date -Iseconds) ==="
