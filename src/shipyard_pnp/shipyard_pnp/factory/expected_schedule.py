"""
Expected production schedule: runs the SimPy model for a confirmed dispatch
order and groups its raw state_changes into per-entity cycles (task, color,
cycle_number, t_start, dur).

Shared by:
  - dashboard_node.py: live "Cycle Tracking" panel + persisted alarms
    (monitoring only).
  - factory_supervisor.py: the dynamic control layer that lets this schedule
    break ties between two simultaneously-ready physical options, with a
    grace period before falling back to the plain reactive rule (control).

Kept dependency-free of both callers so neither has to import the other.
"""

from collections import defaultdict

SCHEDULE_ENTITIES = ["xarm2", "xarm1", "laser", "robot2", "bantam", "robot1"]

SCHEDULE_CYCLE_START = {
    "xarm2":  {"MOVE_TO_STACK"},
    "xarm1":  {"MOVE_TO_C1S2", "MOVE_TO_LASER"},
    "robot2": {"MOVE_TO_C2S2", "MOVE_TO_BANTAM", "MOVE_TO_IBS"},
    "robot1": {"MOVE_TO_C4", "MOVE_TO_C3"},
    "laser":  {"PROCESSING", "HEATING"},
    "bantam": {"DOOR_CLOSING"},
}

# A trailing piece=None event (e.g. the IDLE that closes out a RETURN_HOME)
# normally extends whatever cycle is still open -- correct for xarm1/xarm2/
# robot1/robot2, whose own real cycle_event also doesn't complete until THEY
# finish moving home. laser and bantam are different: they're stationary --
# "FINISHED" is a real piece-tagged event, but robot2/xarm1 physically has
# to come pick the piece up afterwards, and that pickup is tracked as ITS
# OWN separate cycle (BANTAM_TO_C4 / LASER_TO_C2S1), not laser/bantam's. So
# the piece=None event that follows (xarm1/robot2 finishing that pickup, not
# laser/bantam doing anything) must NOT extend laser/bantam's own cycle --
# hard-close it right at FINISHED instead. See CLAUDE.md.
SCHEDULE_HARD_END = {
    "laser":  {"FINISHED"},
    "bantam": {"FINISHED"},
}


def infer_task(entity: str, states: set, color: str) -> str:
    if entity == "xarm2":
        return "FEED_GREEN_TO_C3" if color == "GREEN" else "FEED_TO_C1S1"
    if entity == "xarm1":
        if "MOVE_TO_LASER" in states:
            return "LASER_TO_C2S1"
        if "MOVE_TO_C1S2" in states and color == "RED":
            return "C1S2_TO_LASER"
        return "C1S2_TO_C2S1"
    if entity == "robot1":
        return "UNLOAD_C3" if "MOVE_TO_C3" in states else "UNLOAD_C4"
    if entity == "robot2":
        if "MOVE_TO_BANTAM" in states:
            return "BANTAM_TO_C4"
        if "MOVE_TO_IBS" in states and "PLACE_BANTAM" in states:
            return "IBS_TO_BANTAM"
        if "PLACE_BANTAM" in states:
            return "CLASSIFY_C2S2_TO_BANTAM"
        if "PLACE_IBS" in states:
            return "CLASSIFY_C2S2_TO_IBS"
        return "CLASSIFY_C2S2_TO_C4"
    if entity == "laser":
        return "PROCESS_RED"
    if entity == "bantam":
        return "PROCESS_BLUE"
    return entity


def compute_expected_schedule(order: list) -> dict:
    """Run the SimPy model for the confirmed order and group its raw
    state_changes into per-entity cycles (task, color, cycle_number,
    t_start, dur) -- same grouping used for the offline sim-vs-real
    analyses, kept simple here since only order/timing matter for the
    live comparison, not exact sub-phase duration accounting."""
    import io
    import contextlib
    import simpy
    from shipyard_pnp.nodes.shipyard_sim import (
        System, bantam_machine_process, xarm2_process,
        conveyor1_process, conveyor1_control,
        conveyor2_process, conveyor2_control,
        xarm1_process, robot2_process, robot1_process,
    )

    env = simpy.Environment()
    system = System(env, list(order))
    env.process(bantam_machine_process(env, system))
    env.process(xarm2_process(env, system))
    env.process(conveyor1_process(env, system))
    env.process(conveyor1_control(env, system))
    env.process(conveyor2_process(env, system))
    env.process(conveyor2_control(env, system))
    env.process(xarm1_process(env, system))
    env.process(robot2_process(env, system))
    env.process(robot1_process(env, system))
    with contextlib.redirect_stdout(io.StringIO()):
        env.run(until=2500)

    # Keep every event, including piece=None ones (e.g. the IDLE that marks
    # a RETURN_HOME actually finishing) -- dropping them here previously
    # made every cycle's dur/t_end stop at the START of its trailing
    # RETURN_HOME instead of its end, silently hiding that travel time as a
    # gap before the next cycle instead of counting it. See CLAUDE.md.
    entity_stream = defaultdict(list)
    for c in sorted(system.state_changes, key=lambda x: x["time"]):
        entity_stream[c["entity"]].append(c)

    schedule = {}
    for entity in SCHEDULE_ENTITIES:
        markers = SCHEDULE_CYCLE_START[entity]
        hard_ends = SCHEDULE_HARD_END.get(entity, ())
        groups = []
        current = None
        for c in entity_stream[entity]:
            # A piece=None event (e.g. the IDLE that closes out a
            # RETURN_HOME) never starts a new group on its own -- it belongs
            # to whatever cycle is already open, extending its t_end. Only a
            # marker state, or a *different real* piece, starts a new one.
            new_piece = c["piece"] is not None and (
                current is None or current["piece"] != c["piece"]
            )
            if c["state"] in markers or current is None or new_piece:
                if current is not None:
                    groups.append(current)
                current = {"piece": c["piece"], "color": c["color"], "events": [c]}
            else:
                current["events"].append(c)
            if current is not None and c["state"] in hard_ends:
                groups.append(current)
                current = None
        if current is not None:
            groups.append(current)
        groups = [g for g in groups if g["events"][0]["state"] in markers]

        task_counts = defaultdict(int)
        entity_cycles = []
        for g in groups:
            states = {e["state"] for e in g["events"]}
            t_start = g["events"][0]["time"]
            t_end = g["events"][-1]["time"]
            task = infer_task(entity, states, g["color"])
            # classification_rules.py creates the robot2 cycle as generic
            # "CLASSIFY_C2S2" (cycle_number assigned then) and only renames
            # it to CLASSIFY_C2S2_TO_{C4,BANTAM,IBS,SCRAP} once vision
            # confirms the color -- so real cycle_number for all four is one
            # SHARED counter, not one per final route. Match that here so
            # comparisons against the live cycle_number (read straight from
            # cycle_tracker) aren't spuriously flagged.
            if entity == "robot2" and task.startswith("CLASSIFY_C2S2_TO_"):
                counter_key = "CLASSIFY_C2S2"
            else:
                counter_key = task
            task_counts[counter_key] += 1
            entity_cycles.append({
                "task": task, "color": g["color"],
                "cycle_number": task_counts[counter_key],
                "t_start": round(t_start, 1),
                "dur": round(max(t_end - t_start, 0.1), 1),
            })
        entity_cycles.sort(key=lambda d: d["t_start"])
        schedule[entity] = entity_cycles

    return schedule


def find_expected_now(cycle_list: list, elapsed: float):
    """What should this entity be doing right now, given elapsed seconds
    since production start. Used by the dashboard's time-based monitoring
    view -- the control layer in factory_supervisor uses a per-entity
    completed-cycle counter instead (see FactorySupervisor._map_next),
    which doesn't drift with clock skew the way this lookup does."""
    if not cycle_list:
        return None
    if elapsed < cycle_list[0]["t_start"]:
        return {"status": "not_started"}
    for c in cycle_list:
        if c["t_start"] <= elapsed < c["t_start"] + c["dur"]:
            d = dict(c)
            d["status"] = "active"
            return d
    return {"status": "finished_all"}
