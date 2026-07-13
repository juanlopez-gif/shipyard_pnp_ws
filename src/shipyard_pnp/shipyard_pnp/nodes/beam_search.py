"""
Beam search over dispatch decisions.

The old beam ranked partial paths by the next decision time (`nd.now`). That
was a bad heuristic: a path can reach the next decision earlier simply because
it refused to wait for a better option, so the beam pruned good schedules.

This version ranks each candidate by rollouts: replay the candidate decisions,
then finish the run with a small portfolio of fallback policies. The score is
the best resulting makespan. That keeps the beam focused on "what this choice
does to the rest of the factory", not just on the clock at the next branch
point.

Two details matter a lot:

* Single-option decisions are auto-advanced EXCEPT the ones listed in
  _SINGLE_OPTION_WAIT_ALLOWED below, and even those only when the resource
  being waited on is actually WORKING (see _worth_waiting). Most
  single-option decisions are provably safe to force: none of the station
  timers (Bantam, laser, C3, C4) depend on whether the robot is busy or
  idle, so waiting instead of acting can only delay clearing that station,
  never speed up the other one. Blanket-allowing WAIT on every single-option
  decision was tried and reverted -- it multiplies the number of full
  from-scratch replays (see run_with_path_tagged) by the number of trivial
  forced moves in the whole run (dozens), not just the 2-3 real conflicts.
  Restricting it to (robot1, C3), (robot1, C4), (robot2, P1) was *still* too
  slow on its own, because e.g. offering WAIT to robot2 while Bantam is
  IDLE and empty (nobody has ever placed a piece there yet) is a dead end --
  Bantam will never become FINISHED on its own, so that branch always runs
  out the full simulation horizon before giving up, and that happened on
  every such candidate. _worth_waiting() gates the branch on the other
  station actually being WORKING (already given a piece, actively
  processing) -- only then can it plausibly finish "soon". Everything else
  (xarm1's LASER/C1, robot2's P2/P3 alone) stays forced.
* The rollout portfolio includes the current fixed priorities plus the known
  physical alternative where robot2 clears a finished Bantam part before
  classifying the next C2S2 part (P2 before P1). A single fixed fallback can
  badly underrate prefixes that only become good after repeated P2 choices.
"""
from shipyard_pnp.nodes import dispatch_search2 as ds

# (entity, single_ready_option) pairs that still get offered a WAIT branch
# even though only one option is physically ready. Everything not listed
# here is auto-forced (see _advance) to keep the search tractable -- see
# module docstring for why this pair specifically is not a no-op.
_SINGLE_OPTION_WAIT_ALLOWED = {
    ("robot1", "C3"),
    ("robot1", "C4"),
    ("robot2", "P1"),
}


def _worth_waiting(nd) -> bool:
    """True only if the resource being waited on is actively WORKING --
    i.e. it has already been given a piece and will plausibly finish soon.
    If it is IDLE/empty, nothing will ever make it FINISHED on its own, so
    offering WAIT there is a dead end that runs out the full horizon."""
    pair = (nd.tag, nd.ready_options[0])
    if pair not in _SINGLE_OPTION_WAIT_ALLOWED:
        return False
    system = nd.system
    if system is None:
        return False
    if pair == ("robot1", "C3"):
        return system.c4_occupied and system.c4_state == "WORKING"
    if pair == ("robot1", "C4"):
        return system.c3_occupied and system.c3_state == "WORKING"
    if pair == ("robot2", "P1"):
        return system.bantam_state == "WORKING"
    return False


def _ordered_decider(priority):
    def decide(ready_options, now=None, system=None):
        for option in priority:
            if option in ready_options:
                return option
        return "WAIT"

    return decide


def _fallback_policies():
    r2_variants = [
        ("r2_fixed", ds.fixed_priority_decide_r2),
        ("r2_p2_first", _ordered_decider(("P2", "P1", "P3"))),
        ("r2_drain_first", _ordered_decider(("P2", "P3", "P1"))),
    ]
    r1_variants = [
        ("r1_fixed", ds.fixed_priority_decide_r1),
        ("r1_c4_first", _ordered_decider(("C4", "C3"))),
        ("r1_c3_first", _ordered_decider(("C3", "C4"))),
    ]
    x1_variants = [
        ("x1_fixed", ds.fixed_priority_decide_x1),
        ("x1_c1_first", _ordered_decider(("C1", "LASER"))),
    ]

    policies = []
    for r2_name, r2_fn in r2_variants:
        for r1_name, r1_fn in r1_variants:
            for x1_name, x1_fn in x1_variants:
                policies.append((
                    f"{r2_name}+{r1_name}+{x1_name}",
                    r2_fn,
                    r1_fn,
                    x1_fn,
                ))
    return policies


def _path_key(path):
    return tuple(path)


def _wait_count(path):
    return sum(1 for _tag, choice in path if choice == "WAIT")


def unique_color_orders(n_blue, n_red, n_green):
    counts = {"BLUE": n_blue, "RED": n_red, "GREEN": n_green}
    colors = ("BLUE", "RED", "GREEN")
    total = n_blue + n_red + n_green
    order = []

    def build():
        if len(order) == total:
            yield list(order)
            return
        for color in colors:
            if counts[color] <= 0:
                continue
            counts[color] -= 1
            order.append(color)
            yield from build()
            order.pop()
            counts[color] += 1

    yield from build()


def _advance(order, path):
    """Run until completion or the next real branch.

    A real branch is a decision point with at least two executable physical
    options, OR a single-option decision where _worth_waiting() says the
    other resource is actively processing something. All other
    single-option decisions are forced moves, so spending beam depth on
    them only delays reaching the meaningful choices.
    """
    forced_path = list(path)
    while True:
        system, nd = ds.run_with_path_tagged(order, forced_path)
        if nd is None:
            return forced_path, system, None
        if len(nd.ready_options) != 1 or _worth_waiting(nd):
            return forced_path, None, nd
        forced_path.append((nd.tag, nd.ready_options[0]))


def beam_search(
    order,
    n_blue,
    n_red,
    n_green,
    beam_width=40,
    max_levels=250,
    patience=6,
    max_rollouts=1800,
):
    policies = _fallback_policies()
    rollout_cache = {}
    rollout_count = [0]

    def rollout(path):
        key = _path_key(path)
        if key in rollout_cache:
            return rollout_cache[key]

        best_ms = float("inf")
        best_policy_idx = None
        for idx, (_name, r2_fn, r1_fn, x1_fn) in enumerate(policies):
            if rollout_count[0] >= max_rollouts:
                break
            rollout_count[0] += 1
            system, _decisions = ds.run_with_path_and_fallback(
                order,
                path,
                fallback_r2=r2_fn,
                fallback_r1=r1_fn,
                fallback_x1=x1_fn,
            )
            ms = ds.makespan(system, n_blue, n_red, n_green)
            if ms is not None and ms < best_ms:
                best_ms = ms
                best_policy_idx = idx

        scored = (best_ms, best_policy_idx)
        rollout_cache[key] = scored
        return scored

    def record_rollout(path, policy_idx):
        name, r2_fn, r1_fn, x1_fn = policies[policy_idx]
        system, decisions = ds.run_with_path_and_fallback(
            order,
            path,
            record_decisions=True,
            fallback_r2=r2_fn,
            fallback_r1=r1_fn,
            fallback_x1=x1_fn,
        )
        ms = ds.makespan(system, n_blue, n_red, n_green)
        return float("inf") if ms is None else ms, decisions, name

    initial_path, initial_system, initial_nd = _advance(order, [])
    frontier = [initial_path] if initial_nd is not None else []
    completed = []
    best_rollout = None  # (makespan, full_decisions, scoring_prefix, policy_name)

    base_ms, base_policy_idx = rollout([])
    if base_ms != float("inf"):
        rec_ms, base_decisions, policy_name = record_rollout([], base_policy_idx)
        best_rollout = (rec_ms, base_decisions, [], policy_name)
    if initial_nd is None and initial_system is not None:
        ms = ds.makespan(initial_system, n_blue, n_red, n_green)
        if ms is not None:
            completed.append((ms, initial_path))
    stale_levels = 0

    for level in range(max_levels):
        if rollout_count[0] >= max_rollouts:
            break
        if not frontier:
            break
        next_frontier = []  # list of (path, rollout_ms)
        seen = set()
        best_before = best_rollout[0] if best_rollout is not None else float("inf")

        for path in frontier:
            if rollout_count[0] >= max_rollouts:
                break
            path, system, nd = _advance(order, path)
            if nd is None:
                ms = ds.makespan(system, n_blue, n_red, n_green)
                if ms is not None:
                    completed.append((ms, path))
                    if best_rollout is None or ms < best_rollout[0]:
                        best_rollout = (ms, None, path, None)
                continue

            for opt in nd.ready_options + ["WAIT"]:
                if rollout_count[0] >= max_rollouts:
                    break
                candidate, candidate_system, candidate_nd = _advance(
                    order, path + [(nd.tag, opt)]
                )
                key = _path_key(candidate)
                if key in seen:
                    continue
                seen.add(key)

                if candidate_nd is None and candidate_system is not None:
                    complete_ms = ds.makespan(
                        candidate_system, n_blue, n_red, n_green
                    )
                    if complete_ms is not None:
                        completed.append((complete_ms, candidate))
                        if best_rollout is None or complete_ms < best_rollout[0]:
                            best_rollout = (complete_ms, None, candidate, None)
                    continue

                ms, policy_idx = rollout(candidate)
                if ms == float("inf"):
                    continue

                if best_rollout is None or ms < best_rollout[0]:
                    rec_ms, decisions, policy_name = record_rollout(
                        candidate, policy_idx
                    )
                    best_rollout = (rec_ms, decisions, candidate, policy_name)

                next_frontier.append((candidate, ms))

        if not next_frontier:
            break

        best_after = best_rollout[0] if best_rollout is not None else float("inf")
        if best_after < best_before:
            stale_levels = 0
        else:
            stale_levels += 1
            if stale_levels >= patience:
                break

        next_frontier.sort(
            key=lambda pn: (
                pn[1],                 # rollout makespan
                _wait_count(pn[0]),    # avoid gratuitous waiting
                len(pn[0]),
            )
        )
        frontier = [p for p, _ms in next_frontier[:beam_width]]

    if best_rollout is not None:
        ms, decisions, prefix, _policy_name = best_rollout
        if decisions is None:
            _system, decisions = ds.run_with_path_and_fallback(
                order, prefix, record_decisions=True
            )
        compact_path = [(d["entity"], d["choice"]) for d in decisions]
        return (ms, compact_path), len(completed)

    if completed:
        return min(completed, key=lambda x: x[0]), len(completed)
    return None, 0


def search_initial_orders(
    n_blue,
    n_red,
    n_green,
    beam_width=24,
    max_levels=100,
    patience=8,
    max_rollouts=1200,
):
    """Search both the initial stack order and the variable dispatch map."""
    rows = []
    for order in unique_color_orders(n_blue, n_red, n_green):
        fixed_system = ds.run_system(
            order,
            ds.fixed_priority_decide_r2,
            ds.fixed_priority_decide_r1,
            ds.fixed_priority_decide_x1,
        )
        fixed_ms = ds.makespan(fixed_system, n_blue, n_red, n_green)
        best, completed = beam_search(
            order,
            n_blue,
            n_red,
            n_green,
            beam_width=beam_width,
            max_levels=max_levels,
            patience=patience,
            max_rollouts=max_rollouts,
        )
        rows.append({
            "order": order,
            "tag": "".join(color[0] for color in order),
            "fixed_ms": fixed_ms,
            "beam_ms": None if best is None else best[0],
            "path": None if best is None else best[1],
            "completed": completed,
        })

    return sorted(
        rows,
        key=lambda row: (
            float("inf") if row["beam_ms"] is None else row["beam_ms"],
            float("inf") if row["fixed_ms"] is None else row["fixed_ms"],
            row["tag"],
        ),
    )


if __name__ == "__main__":
    import time

    orders = [
        (["BLUE", "BLUE", "BLUE", "RED", "RED", "RED"], 3, 3, 0),
        (["RED", "RED", "RED", "BLUE", "BLUE", "BLUE"], 3, 3, 0),
        (["BLUE", "RED", "BLUE", "RED", "BLUE", "RED"], 3, 3, 0),
        (["GREEN", "BLUE", "RED", "GREEN", "BLUE", "RED", "GREEN", "BLUE", "RED"], 3, 3, 3),
        (["BLUE", "BLUE", "BLUE", "RED", "RED", "RED", "GREEN", "GREEN", "GREEN"], 3, 3, 3),
    ]
    for order, nb, nr, ng in orders:
        t0 = time.time()
        base_system, _ = ds.run_with_path_tagged(order, [])
        # Baseline uses fixed priority for every decision entity.
        base_system = ds.run_system(
            order,
            ds.fixed_priority_decide_r2,
            ds.fixed_priority_decide_r1,
            ds.fixed_priority_decide_x1,
        )
        base_ms = ds.makespan(base_system, nb, nr, ng)
        best, n_completed = beam_search(order, nb, nr, ng, beam_width=40)
        tag = "".join(c[0] for c in order)
        if best is None:
            print(f"orden={tag}  fija={base_ms:.2f}s  beam=SIN RESULTADO (nada completo dentro del horizonte)")
            continue
        best_ms, best_path = best
        diff = base_ms - best_ms
        print(f"orden={tag:12s} fija={base_ms:8.2f}s  beam={best_ms:8.2f}s  "
              f"diff={diff:+7.2f}s ({diff/base_ms*100:+.2f}%)  "
              f"completados={n_completed}  ({time.time()-t0:.1f}s)")
