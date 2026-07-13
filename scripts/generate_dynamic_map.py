#!/usr/bin/env python3
"""
Offline generator for dynamic dispatch maps.

Two-stage search per initial-stack composition (counts of BLUE/RED/GREEN),
matching the plan discussed for docs/dynamic_map_brrbrb/:

  1. Prefilter: run the cheap fixed-priority simulation for every unique
     permutation of the requested color composition, ranked by makespan.
     If there are more than --sample-cap unique permutations (compositions
     with 10+ pieces routinely have tens of thousands), a random sample of
     --sample-cap of them is scored instead of all of them -- exhaustive
     enumeration is fine to build (it's cheap), but simulating all of them
     one by one is not.
  2. Full search: run beam_search() (the expensive policy-portfolio search,
     which also considers robot1/robot2 waiting on a single ready option
     when the resource it would wait for is actively WORKING -- see
     beam_search.py's _worth_waiting) only on the top --top-k candidates
     from stage 1.

Saves the winning {order, decision path, expected_schedule, timing, search
stats, Config hash} as ONE JSON FILE PER COMPOSITION under
config/dynamic_maps/{n_blue}b{n_red}r{n_green}g.json (atomic write via a
temp file + os.replace, so a crash mid-write cannot corrupt a previously
saved map -- each composition's file is independent). Looked up by
composition at runtime, falling back to the fixed optimizer when a
composition has no precomputed file.

No ROS dependency -- pure simulation/search. Needs the shipyard_pnp package
importable (source install/setup.bash).

Usage:
    python3 scripts/generate_dynamic_map.py BRGBRGBRG
    python3 scripts/generate_dynamic_map.py BLUE,RED,GREEN,BLUE,RED,GREEN,BLUE,RED,GREEN --top-k 20
"""
import argparse
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

from shipyard_pnp.factory.expected_schedule import build_schedule_from_state_changes
from shipyard_pnp.nodes import dispatch_search2 as ds
from shipyard_pnp.nodes import beam_search as bs

_LETTER_TO_COLOR = {"B": "BLUE", "R": "RED", "G": "GREEN"}
_SHIPYARD_SIM_SEARCH_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "src", "shipyard_pnp", "shipyard_pnp", "nodes", "shipyard_sim_search.py",
))
_DEFAULT_OUT_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "src", "shipyard_pnp", "config", "dynamic_maps",
))


def parse_order(raw: str) -> list:
    raw = raw.strip()
    if "," in raw:
        return [c.strip().upper() for c in raw.split(",")]
    colors = []
    for ch in raw.upper():
        if ch not in _LETTER_TO_COLOR:
            raise ValueError(f"Unknown color letter '{ch}' in compact order '{raw}'")
        colors.append(_LETTER_TO_COLOR[ch])
    return colors


def _config_hash() -> str:
    with open(_SHIPYARD_SIM_SEARCH_PATH, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def _tag(order) -> str:
    return "".join(c[0] for c in order)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("order", help="Initial stack, e.g. BRGBRGBRG or BLUE,RED,GREEN,...")
    parser.add_argument("--top-k", type=int, default=20,
                         help="How many permutations (ranked by the cheap fixed-priority "
                              "sim) get the expensive full beam search")
    parser.add_argument("--beam-width", type=int, default=40)
    parser.add_argument("--max-levels", type=int, default=250)
    parser.add_argument("--patience", type=int, default=6)
    parser.add_argument("--max-rollouts", type=int, default=1800)
    parser.add_argument("--sample-cap", type=int, default=2000,
                         help="If a composition has more unique permutations than this, "
                              "randomly sample this many for stage 1 instead of all of them")
    parser.add_argument("--out-dir", default=_DEFAULT_OUT_DIR)
    parser.add_argument("--seed", type=int, default=None,
                         help="Random seed for the stage-1 sample, for reproducibility")
    args = parser.parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    order = parse_order(args.order)
    n_blue = order.count("BLUE")
    n_red = order.count("RED")
    n_green = order.count("GREEN")
    total = n_blue + n_red + n_green
    print(f"[input] order={_tag(order)} composition=BLUE:{n_blue} RED:{n_red} "
          f"GREEN:{n_green} (n={total})", flush=True)

    t_start = time.time()

    # Stage 1: cheap prefilter over every unique permutation of this composition.
    all_permutations = list(bs.unique_color_orders(n_blue, n_red, n_green))
    n_perms_total = len(all_permutations)
    sampled = n_perms_total > args.sample_cap
    if sampled:
        permutations = random.sample(all_permutations, args.sample_cap)
        print(f"[stage 1/2] {n_perms_total} unique permutations exceeds "
              f"--sample-cap={args.sample_cap} -- randomly sampling "
              f"{len(permutations)} of them instead of enumerating all.", flush=True)
    else:
        permutations = all_permutations
    n_perms = len(permutations)
    print(f"[stage 1/2] prefiltering {n_perms} permutations "
          f"({'sampled' if sampled else 'exhaustive'}) with the "
          f"fixed-priority simulation...", flush=True)
    scored = []
    report_every = max(1, n_perms // 20)
    for i, perm in enumerate(permutations, 1):
        system = ds.run_system(
            perm, ds.fixed_priority_decide_r2, ds.fixed_priority_decide_r1,
            ds.fixed_priority_decide_x1,
        )
        ms = ds.makespan(system, n_blue, n_red, n_green)
        scored.append((ms if ms is not None else float("inf"), perm))
        if i % report_every == 0 or i == n_perms:
            pct = 100.0 * i / n_perms
            best_so_far = min(s[0] for s in scored)
            print(f"    [{pct:5.1f}%] {i}/{n_perms} permutations scored -- "
                  f"best fixed_ms so far: {best_so_far:.1f}s", flush=True)

    scored.sort(key=lambda x: x[0])
    top_k = scored[: args.top_k]
    print(f"[stage 1/2] done in {time.time() - t_start:.1f}s. "
          f"Top {len(top_k)} candidates: "
          + ", ".join(f"{_tag(p)}={ms:.1f}s" for ms, p in top_k[:5])
          + (" ..." if len(top_k) > 5 else ""), flush=True)

    # Stage 2: expensive beam search, only on the pre-filtered candidates.
    print(f"[stage 2/2] running beam_search on {len(top_k)} candidates "
          f"(beam_width={args.beam_width}, max_rollouts={args.max_rollouts})...",
          flush=True)
    best_overall = None  # (ms, order, path, n_completed)
    t_stage2 = time.time()
    for i, (fixed_ms, perm) in enumerate(top_k, 1):
        t_cand = time.time()
        result, n_completed = bs.beam_search(
            perm, n_blue, n_red, n_green,
            beam_width=args.beam_width, max_levels=args.max_levels,
            patience=args.patience, max_rollouts=args.max_rollouts,
        )
        elapsed = time.time() - t_cand
        pct = 100.0 * i / len(top_k)
        if result is None:
            print(f"    [{pct:5.1f}%] ({i}/{len(top_k)}) {_tag(perm)} "
                  f"fixed={fixed_ms:.1f}s -> beam=NO RESULT ({elapsed:.1f}s)", flush=True)
            continue
        ms, path = result
        is_new_best = best_overall is None or ms < best_overall[0]
        marker = " *** new best ***" if is_new_best else ""
        print(f"    [{pct:5.1f}%] ({i}/{len(top_k)}) {_tag(perm)} "
              f"fixed={fixed_ms:.1f}s -> beam={ms:.1f}s "
              f"(completed_paths={n_completed}, {elapsed:.1f}s){marker}", flush=True)
        if is_new_best:
            best_overall = (ms, perm, path, n_completed)

    if best_overall is None:
        print("No candidate produced a completed schedule within the search "
              "budget -- nothing saved.")
        sys.exit(1)

    best_ms, best_order, best_path, best_completed = best_overall
    print(f"[stage 2/2] done in {time.time() - t_stage2:.1f}s. "
          f"Winner: {_tag(best_order)} = {best_ms:.1f}s", flush=True)

    # Replay the winning fully-specified decision path to get expected_schedule.
    system, nd = ds.run_with_path_tagged(best_order, best_path)
    if nd is not None:
        print("WARNING: winning path did not fully determine the run "
              "(unexpected) -- schedule may be incomplete.")
    expected_schedule = build_schedule_from_state_changes(system.state_changes)

    # The fixed reference must be the best fixed-priority order actually
    # found in stage 1 (scored[0]), NOT a fresh simulation of the raw input
    # order -- that order is arbitrary (the CLI argument only fixes the
    # composition, stage 1 already searches/samples every permutation) and
    # using it as "the fixed result" silently compared the dynamic winner
    # against a random point instead of the best one, inflating the
    # reported saving. For sampled compositions this is still only the best
    # found within the sample, not a proven global optimum -- see `sampled`
    # in search_stats.
    fixed_reference_ms, fixed_reference_order = scored[0]

    entry = {
        "map_id": f"dynamic_{n_blue}b{n_red}r{n_green}g_{_tag(best_order)}_v1",
        "composition": {"BLUE": n_blue, "RED": n_red, "GREEN": n_green},
        "requested_order": _tag(order),
        "best_order": _tag(best_order),
        "best_time_s": best_ms,
        "fixed_reference_order": _tag(fixed_reference_order),
        "fixed_reference_time_s": fixed_reference_ms,
        "saving_s": (round(fixed_reference_ms - best_ms, 1)
                      if fixed_reference_ms is not None else None),
        "decision_path": [[entity, choice] for entity, choice in best_path],
        "expected_schedule": expected_schedule,
        "search_stats": {
            "permutations_total": n_perms_total,
            "permutations_searched": n_perms,
            "sampled": sampled,
            "sample_cap": args.sample_cap,
            "top_k_searched": len(top_k),
            "completed_paths_for_winner": best_completed,
            "beam_width": args.beam_width,
            "max_levels": args.max_levels,
            "patience": args.patience,
            "max_rollouts": args.max_rollouts,
            "wall_time_s": round(time.time() - t_start, 1),
        },
        "config_hash": _config_hash(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, f"{n_blue}b{n_red}r{n_green}g.json")
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w") as fh:
        json.dump(entry, fh, indent=2)
    os.replace(tmp_path, out_path)  # atomic: a crash mid-write never corrupts out_path

    print(f"Saved map '{entry['map_id']}' to {out_path}.")
    print(f"Total wall time: {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    main()
