#!/usr/bin/env bash
# Parallel batch generation of dynamic dispatch maps for the same 10 F1-F10
# compositions (12-15 pieces) as run_overnight_dynamic_maps_12to15pc.sh, but
# with two changes:
#
#   1. Up to MAX_PARALLEL compositions run at once instead of one at a time.
#      Each generate_dynamic_map.py process is single-threaded and fully
#      independent (own JSON output file, no shared state), so this is
#      embarrassingly parallel -- on an 8-thread machine, 5 concurrent jobs
#      leaves 3 threads free for the real ROS2 system if it's running too.
#
#   2. --sample-cap raised 2000 -> 20000. Stage 1 (fixed-priority scoring) is
#      cheap per sample (~0.2-0.25s at this piece count) and does NOT affect
#      stage 2's cost at all (beam search only ever looks at --top-k
#      candidates regardless of how large the stage-1 sample was) -- so this
#      buys much better "best found" confidence for a modest ~1h/composition
#      addition, not a multiplier on the expensive part. F1/F2 (13,860 total
#      permutations) drop UNDER the new cap and become fully exhaustive.
#
# Usage:
#   cd /home/isecapstone/shipyard_pnp_ws
#   source /opt/ros/jazzy/setup.bash
#   source install/setup.bash
#   mkdir -p results/dynamic_map_generation_logs
#   nohup ./scripts/run_parallel_dynamic_maps_12to15pc.sh > results/dynamic_map_generation_logs/_parallel_12to15pc_driver.log 2>&1 &
#   disown

set -uo pipefail

MAX_PARALLEL="${MAX_PARALLEL:-5}"
BEAM_WIDTH="${BEAM_WIDTH:-80}"
MAX_ROLLOUTS="${MAX_ROLLOUTS:-4000}"
MAX_LEVELS="${MAX_LEVELS:-400}"
PATIENCE="${PATIENCE:-8}"
SAMPLE_CAP="${SAMPLE_CAP:-20000}"
SEED="${SEED:-42}"

LOG_DIR="results/dynamic_map_generation_logs"
mkdir -p "$LOG_DIR"

# tag:order:top_k -- same 10 compositions and per-size top-k as the
# sequential version (20 for n=12, 10 for n=13-15, see chat).
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

echo "=== parallel 12-15 piece dynamic map generation started at $(date -Iseconds) ==="
echo "max_parallel=$MAX_PARALLEL beam_width=$BEAM_WIDTH max_rollouts=$MAX_ROLLOUTS max_levels=$MAX_LEVELS patience=$PATIENCE sample_cap=$SAMPLE_CAP seed=$SEED"
echo "${#COMPOSITIONS[@]} compositions queued, up to $MAX_PARALLEL running at once"
echo

ok=0
failed=()
total=${#COMPOSITIONS[@]}
pids=()
tags=()

launch() {
  local entry="$1"
  local tag="${entry%%:*}"
  local rest="${entry#*:}"
  local order="${rest%%:*}"
  local top_k="${rest#*:}"
  local ts log_file
  ts="$(date +%Y%m%d_%H%M%S)"
  log_file="$LOG_DIR/${tag}_${order}_${ts}.log"
  echo "($(date -Iseconds)) starting $tag ($order, top-k=$top_k) -> $log_file"
  python3 scripts/generate_dynamic_map.py "$order" \
    --top-k "$top_k" \
    --beam-width "$BEAM_WIDTH" \
    --max-levels "$MAX_LEVELS" \
    --patience "$PATIENCE" \
    --max-rollouts "$MAX_ROLLOUTS" \
    --sample-cap "$SAMPLE_CAP" \
    --seed "$SEED" \
    > "$log_file" 2>&1 &
  pids+=("$!")
  tags+=("$tag")
}

reap_finished() {
  # Poll tracked pids, reap (wait) any that already exited, report ok/fail,
  # and compact the arrays. Sleeps briefly between passes if none are done.
  while true; do
    for i in "${!pids[@]}"; do
      pid="${pids[$i]}"
      if ! kill -0 "$pid" 2>/dev/null; then
        wait "$pid"
        status=$?
        tag="${tags[$i]}"
        if [ $status -eq 0 ]; then
          ok=$((ok + 1))
          echo "($(date -Iseconds)) OK   $tag"
        else
          failed+=("$tag")
          echo "($(date -Iseconds)) FAIL $tag -- exit $status"
        fi
        unset 'pids[i]'
        unset 'tags[i]'
        pids=("${pids[@]}")
        tags=("${tags[@]}")
        return
      fi
    done
    sleep 5
  done
}

for entry in "${COMPOSITIONS[@]}"; do
  while [ "${#pids[@]}" -ge "$MAX_PARALLEL" ]; do
    reap_finished
  done
  launch "$entry"
done

# Drain remaining running jobs.
while [ "${#pids[@]}" -gt 0 ]; do
  reap_finished
done

echo
echo "=== parallel 12-15 piece dynamic map generation finished at $(date -Iseconds) ==="
echo "ok=$ok / $total"
if [ "${#failed[@]}" -gt 0 ]; then
  echo "failed (${#failed[@]}): ${failed[*]}"
else
  echo "no failures"
fi
