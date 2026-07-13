"""
Shipyard 4.0 MVP2 — SimPy simulation core (no visualization).

Used by dashboard_node to run the optimizer in a background thread.
Only the simulation logic is here — Gantt/log generation lives in
shipyard_final_v02.py (which requires PIL and is not imported here).
"""

import time


# ─────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────

class Config:
    # Calibrated from shipyard_pnp_ws DB medians on 2026-06-27 runs.
    # xArm2
    XARM2_MOVE_TO_STACK             = 3.8
    XARM2_VISION                    = 0.05
    XARM2_PICK_STACK                = 2.5
    XARM2_PLACE_C1S1                = 5.2
    # TRIED 2026-07-08, REVERTED: FEED_GREEN_TO_C3 real avg 16.19s (n=119,
    # std 0.62) vs nominal 15.4s, +0.79s/+5.1% -- just over REVISAR, not
    # noise with 119 samples. Bumping PLACE_C3 to 5.94 (+0.79s) fixed that
    # ONE task's own average cleanly (5.1% -> -0.1%) without moving
    # FEED_TO_C1S1 (shares MOVE_TO_STACK/VISION/PICK_STACK with this path,
    # stayed at +4.3%). But checked against total real-vs-sim makespan
    # across the same 26 runs (not just this task's isolated average) and
    # it made the SYSTEM-LEVEL prediction worse, not better: mean
    # |diff%| across all 26 runs went 4.84% -> 4.90%, with 10 runs getting
    # worse vs only 4 improving (the rest have no GREEN pieces, unaffected).
    # Same failure mode as ROBOT2_PLACE_BANTAM below -- a clean per-task fix
    # that doesn't survive contact with the rest of the schedule's queuing/
    # contention once GREEN pieces interleave with RED/BLUE. Left at the
    # original 5.15; the +5.1% on FEED_GREEN_TO_C3 alone stands, needs a
    # coordinated pass same as bantam, not another isolated point-fix.
    # RE-TRIED 2026-07-08 (same day, bigger dataset): confirmed via code
    # reading that the real GREEN/C3 place path genuinely has one extra
    # waypoint (preplace_c3) plus a deliberately slower final placing speed
    # (20.0/60.0 vs C1S1's 30.0/100.0) in xarm2_adapter.py -- a real,
    # structural difference, not measurement noise. Re-tested the identical
    # 5.94 value against the FULL 29-run dataset (grown from 26) on the
    # chance more data would flip the verdict -- it didn't: mean |diff%|
    # went 5.30% -> 5.35% and median 4.54% -> 5.09%, worse on both. Same
    # conclusion as before, now confirmed twice: left at 5.15.
    # APPLIED 2026-07-08 (3rd round, coordinated across ENTITIES not just
    # within xarm2's own path): FEED_GREEN_TO_C3 and FEED_TO_C1S1 both need
    # MORE time (no oppositely-biased sibling within xarm2 to lean on, see
    # the ROBOT2_PLACE_BANTAM fix above for contrast) -- but robot1's
    # UNLOAD_C4 was independently running -3.0% (real faster than nominal),
    # on ROBOT1_PLACE_FINAL_C4, a constant NOT shared with UNLOAD_C3 (which
    # was already fine at +0.9-1.0% and stays there no matter what
    # PLACE_FINAL_C4 does -- confirmed empirically, not assumed). Fixing
    # C3's own bias alone (PLACE_C3 5.15->5.8) would have cost total
    # accuracy like every previous isolated attempt; pairing it with
    # PLACE_FINAL_C4's independent fix (15.8->14.0) instead nets out on the
    # total ledger even though the two tasks aren't causally related --
    # confirmed on the 24-run clean baseline: FEED_GREEN_TO_C3 +5.8%->+1.2%,
    # UNLOAD_C4 -3.0%->+1.8%, UNLOAD_C3 unaffected (+1.0%, confirmed flat
    # across the whole PLACE_FINAL_C4 sweep), total mean 3.16%->2.75%,
    # median 3.52%->3.16%, max 6.85%->6.66%. Stopped here deliberately --
    # pushing PLACE_FINAL_C4 lower kept "improving" the total further but
    # only by dragging UNLOAD_C4's own accuracy past 5% (e.g. +7.8% at
    # PLACE_FINAL_C4=12.0) -- that's gaming the total metric at the expense
    # of a real task's calibration, not a genuine joint fix, so rejected.
    XARM2_PLACE_C3                  = 5.8
    XARM2_RETURN_HOME_FROM_C3       = 3.93
    XARM2_RETURN_HOME_FROM_C1S1     = 2.0

    # Conveyor 1
    CONVEYOR1_TRANSPORT             = 5.86

    # Conveyor 2
    CONVEYOR2_TRANSPORT             = 9.18

    # xArm1
    XARM1_MOVE_TO_C1S2              = 4.0
    XARM1_PICK_C1S2                 = 0.55
    XARM1_PLACE_LASER               = 8.9
    XARM1_PLACE_C2S1                = 9.4
    XARM1_RETURN_HOME_C2S1          = 1.8
    XARM1_MOVE_TO_LASER             = 4.0
    XARM1_PICK_LASER                = 0.55
    XARM1_LASER_TO_C2S1             = 8.6
    XARM1_RETURN_HOME_LASER         = 1.8

    # Laser
    LASER_HEATING                   = 0.0
    LASER_PROCESSING                = 22.8

    # Robot2
    ROBOT2_MOVE_TO_C2S2             = 2.5
    ROBOT2_VISION_1                 = 10.3
    ROBOT2_VISION_2                 = 3.7
    ROBOT2_VISION_3                 = 2.7
    ROBOT2_VISION                   = 6.2
    ROBOT2_PICK_C2S2                = 3.5
    ROBOT2_PLACE_C4                 = 11.9
    ROBOT2_RETURN_C4                = 9.5
    ROBOT2_PLACE_IBS                = 12.0
    ROBOT2_RETURN_IBS               = 6.65
    ROBOT2_PLACE_BANTAM             = 21.0
    # NOTE (2026-07-06, 3rd attempt): real MOVE_PIECE C2S2->BANTAM_BED is
    # rock-solid at ~29.0s across 16 samples spanning 2026-06-27 to 07-06
    # (28.6-29.3s, zero drift — this is a real, reproducible gap, not noise).
    # Nominal PICK_C2S2(3.5)+PLACE_BANTAM(14.0)+CLEAR_BANTAM(2.5)=20.0 is
    # ~9s short. Tried raising PLACE_BANTAM to 19.8 to close it (reasoning:
    # ROBOT2_MOVE_TO_C2S2+VISION *also* over-estimates real CAPTURE_LOCAL_
    # VISION by ~2.6-3.4s from the same double-counted-travel cause, so only
    # ~5.2s of the 9s actually needs adding once that's netted out). Measured
    # effect: blue_single error grew from 1.16% to 4.02% high, bggbgr from
    # 0.18% to 1.94% high, AND the 18pc run's real bantam-vs-RED priority race
    # (bantam interrupts RED classification exactly once, right after RED
    # piece 1, in all 3 real 18pc runs so far — sim currently shows zero
    # interruptions) got marginally WORSE, not better. Reverted. This gap is
    # real but not closeable via this constant in isolation — the RED feed
    # pipeline (laser+xarm1+conveyor2) timing relative to bantam's own
    # schedule decides which side of a <3s margin wins that race, and it's
    # sensitive to ~15 compounding upstream constants at once. Needs a
    # coordinated multi-constant recalibration pass, not another point-fix.
    # TRIED 2026-07-08 (4th attempt), REVERTED: confirmed via code reading
    # that the ~9s gap is a genuinely missing PHASE, not just a wrong
    # constant -- robot2_adapter.py's _place_bantam() unconditionally calls
    # self.move_home() after clearing bantam, and the real cycle_event only
    # closes AFTER that whole MOVE_PIECE command (incl. move_home)
    # completes, so the real "CLASSIFY_C2S2_TO_BANTAM" cycle genuinely
    # includes a return-home leg the sim never modeled (the "no home
    # command" belief in classification_rules.py's own comment does not
    # match what the adapter actually does). Added a dedicated
    # ROBOT2_RETURN_BANTAM=5.2 phase (same net magnitude as the 3rd
    # attempt's reasoning) right before bantam_robot2_clear.succeed(), so it
    # also correctly delays bantam's own processing start like the real
    # dependency does. Re-validated against the FULL 29-run total-makespan
    # dataset (grown from 26, now including a clean 18-piece interleaved
    # run) on the theory that more data might change the verdict -- it
    # didn't: mean |diff%| went 5.30% -> 5.33%, with 12 of 29 runs getting
    # worse vs only 5 improving (near-identical ratio to the 3rd attempt's
    # 10-worse/4-better). Confirms this is NOT just a smaller-dataset
    # artifact -- adding this much serial robot2-busy time to the BANTAM
    # branch, regardless of which named phase it's split into, reliably
    # pushes the total predicted makespan later for more runs than it
    # helps. The gap is real (confirmed structurally, not just numerically)
    # but still needs the coordinated multi-constant pass the 3rd attempt's
    # note already called for, not another isolated addition.
    # APPLIED 2026-07-08 (5th attempt, the coordinated pass): found the
    # actually load-bearing lever by accident while sweeping ROBOT2_VISION
    # in isolation and seeing zero effect -- get_vision_duration() uses
    # _VISION_CURVE (a "cold start" table built from ROBOT2_VISION_1/2/3 at
    # import time) for robot2's first 3 vision calls of the run, and
    # ROBOT2_VISION only from the 4th call onward. Since a BLUE piece is
    # usually fed early in the optimized order, almost every real
    # CLASSIFY_C2S2_TO_BANTAM sample falls inside those first 3 calls --
    # ROBOT2_VISION was never the constant actually governing bantam's
    # timing at all, VISION_1/2/3 were. Jointly grid-searched PLACE_BANTAM
    # x (VISION_1/2/3 shifted together) against the 24-run clean baseline
    # (see valid_runs.py) instead of one constant at a time: unlike the
    # 3rd/4th attempts, this pair has genuinely independent, OPPOSITE-signed
    # leverage -- CLASSIFY_C2S2_TO_C4/IBS were already negatively biased
    # (real faster than nominal), so lowering the shared vision curve helps
    # them at the same time PLACE_BANTAM's increase fixes bantam, instead of
    # only ever trading one task's accuracy for the total's. Confirmed
    # clean win on ALL axes simultaneously (24-run baseline, mean|diff%|):
    # CLASSIFY_C2S2_TO_BANTAM +9.2%->-0.4%, CLASSIFY_C2S2_TO_C4 -3.5%->-1.9%,
    # CLASSIFY_C2S2_TO_IBS -3.1%->+1.6%, total mean 3.94%->3.16%, median
    # 3.97%->3.52%, max 7.64%->6.85%. No run got worse on any metric.
    ROBOT2_CLEAR_BANTAM             = 2.5
    ROBOT2_MOVE_TO_BANTAM           = 8.9
    ROBOT2_PICK_BANTAM              = 3.1
    ROBOT2_BANTAM_TO_C4             = 14.9
    ROBOT2_RETURN_C4_BLUE           = 9.5
    ROBOT2_MOVE_TO_IBS              = 9.0
    ROBOT2_PICK_IBS                 = 3.0
    ROBOT2_IBS_TO_BANTAM            = 15.3
    # Real IBS->Bantam MOVE_PIECE clears/returns before Bantam RUN_JOB starts.
    ROBOT2_CLEAR_BANTAM_FROM_IBS    = 9.6

    # Bantam
    BANTAM_CLOSE_DOOR               = 11.4
    BANTAM_PROCESSING               = 25.0
    BANTAM_OPEN_DOOR                = 12.1

    # C3 / C4
    C3_PROCESSING                   = 10.0
    C4_PROCESSING                   = 14.5

    # Robot1
    # Vision recalibrated from shipyard_pnp_ws DB run 20260704_112132_RRRRRRBBBBBB
    # (12 real VISION_C4 samples, all from a fresh process start): mean 5.33s,
    # min 4.95s, max 6.06s, NO cold-start pattern visible across the run. The
    # 2026-07-03 "cold start" curve (13.0/7.0/6.4) was fit to only 2 samples
    # and turned out to be an artifact, not a real per-call effect — flattened
    # here.
    ROBOT1_MOVE_TO_C4               = 2.2
    ROBOT1_VISION_1                 = 5.3
    ROBOT1_VISION_2                 = 5.3
    ROBOT1_VISION_3                 = 5.3
    ROBOT1_VISION_C4                = 5.3
    # ROBOT1_VISION_C3 recalibrated from run 20260704_120002 (6 real VISION_C3
    # samples, mean 6.76s, 6.42-7.32). PLACE_FINAL_C3 recalibrated in the same
    # run: real UNLOAD_C3 total avg was 40.49s (6 samples) vs old nominal
    # 44.20s (+3.70s over) even though VISION_C3 was UNDER the real value —
    # PLACE_FINAL_C3=19.8 alone accounted for the rest of the gap once vision
    # is fixed (it had never been touched since the original 2026-06-27
    # calibration, unlike PLACE_FINAL_C4 which was already revalidated).
    # Re-checked against run 20260706_180404 (12G/3R/3B interleaved, 11
    # UNLOAD_C3 samples excl. the first-of-run outlier): real averaged 41.12s
    # vs nominal 40.0s (+1.12s / +2.8%). Bumped PLACE_FINAL_C3 by +1.1s to
    # 15.9 on that basis -- then re-checked against run 20260706_191425 (18
    # pure-GREEN pieces, 17 clean UNLOAD_C3 samples, much larger and more
    # homogeneous): real averaged only 39.32s, i.e. LOWER than the original
    # 40.0s nominal. Combined across both real runs (28 samples): 40.02s --
    # essentially exactly the original value. The 180404 run's 41.12s was
    # run-to-run noise, not a systematic bias; reverted to 14.8.
    ROBOT1_VISION_C3                = 6.8
    # Cold-start effect confirmed across 16 historical runs: robot1's FIRST
    # C3 unload of a run is reliably slower than every subsequent one, and
    # phase breakdown (run 20260706_184436) shows the entire excess sits in
    # VISION_C3 alone (10.33s vs ~5.3-6.8s later) -- every other sub-phase
    # (move/pick/place/return) is normal. Two regimes seen: when C3 is
    # robot1's literal first action of the run, avg +11.5% (9 samples,
    # 20260627/20260703/20260706 runs); when robot1 already did C4 jobs
    # first, avg +6.5% (4 samples, the 6R+6B+6G runs). Combined 13-sample
    # average: +10.0% (~+4.0s on the ~40s nominal). Modeled as a flat
    # one-time addition to VISION_C3 on the run's first C3 visit only.
    ROBOT1_VISION_C3_COLD_START_EXTRA = 4.0
    ROBOT1_PICK_C4                  = 5.1
    # APPLIED 2026-07-08: UNLOAD_C4 was running -3.0% (real faster than
    # nominal) across the 24-run clean baseline (see valid_runs.py) --
    # confirmed this constant is NOT shared with UNLOAD_C3 (empirically:
    # UNLOAD_C3's own diff% stayed flat at +1.0% across the whole sweep
    # below, not just assumed from the Config split). Paired with the
    # XARM2_PLACE_C3 fix above (see that comment for the full joint-search
    # reasoning) -- fixing this independently-biased task at the same time
    # keeps the total-makespan ledger net neutral-to-better instead of
    # only ever trading FEED_GREEN_TO_C3's own accuracy for the total's.
    ROBOT1_PLACE_FINAL_C4           = 14.0
    ROBOT1_MOVE_TO_C3               = 3.0
    ROBOT1_PICK_C3                  = 5.6
    ROBOT1_PLACE_FINAL_C3           = 14.8
    ROBOT1_RETURN_HOME              = 9.8


# ─────────────────────────────────────────────────────────────────
# SYSTEM STATE
# ─────────────────────────────────────────────────────────────────

class System:
    def __init__(self, env, initial_stack=None):
        self.env = env
        self.initial_stack = initial_stack or [
            "GREEN", "BLUE", "GREEN", "RED", "BLUE", "RED",
            "GREEN", "BLUE", "GREEN", "RED",
        ]

        self.c1s1_occupied = False
        self.c1s2_occupied = False
        self.c1s2_piece = None
        self.c1s2_color = None
        self.conveyor1_running = True
        self.pieces_on_conveyor1 = []

        self.c2s1_occupied = False
        self.c2s2_occupied = False
        self.c2s2_piece = None
        self.c2s2_color = None
        self.conveyor2_running = True
        self.pieces_on_conveyor2 = []

        self.xarm2_state = "IDLE"
        self.xarm1_state = "IDLE"
        self.robot1_state = "IDLE"
        self.robot2_state = "IDLE"
        self.piece_counter = 0

        self.vision_counts = {"robot1": 0, "robot2": 0}

        self.laser_state = "IDLE"
        self.laser_piece = None
        self.laser_color = None

        self.bantam_state = "INITIALIZING"
        self.bantam_piece = None
        self.bantam_color = None
        self.bantam_bed   = "EMPTY"
        self.door_state   = "CLOSED"
        self.bantam_robot2_clear = None

        self.ibs_pieces = []

        self.c4_occupied = False
        self.c4_piece = None
        self.c4_color = None
        self.c4_state = "IDLE"
        self.c4_finish_time = None

        self.c3_occupied = False
        self.c3_piece = None
        self.c3_color = None
        self.c3_state = "IDLE"
        self.c3_finish_time = None
        self.robot1_c3_warmed_up = False

        self.final_red_stack   = []
        self.final_green_stack = []
        self.final_blue_stack  = []

        self.state_changes = []

    def log(self, msg):
        pass  # silenced for optimizer runs

    def track(self, entity, state, piece=None, color=None):
        self.state_changes.append({
            "time": self.env.now, "entity": entity,
            "state": state, "piece": piece, "color": color,
        })

    def next_pid(self):
        self.piece_counter += 1
        return f"P{self.piece_counter:02d}"


# ─────────────────────────────────────────────────────────────────
# VISION LEARNING CURVE
# ─────────────────────────────────────────────────────────────────

_VISION_CURVE = {
    "robot1": [Config.ROBOT1_VISION_1, Config.ROBOT1_VISION_2, Config.ROBOT1_VISION_3],
    "robot2": [Config.ROBOT2_VISION_1, Config.ROBOT2_VISION_2, Config.ROBOT2_VISION_3],
}


def get_vision_duration(system, entity, learned_duration):
    n = system.vision_counts[entity]
    system.vision_counts[entity] += 1
    curve = _VISION_CURVE[entity]
    return curve[n] if n < len(curve) else learned_duration


# ─────────────────────────────────────────────────────────────────
# ATOMIC OPERATIONS
# ─────────────────────────────────────────────────────────────────

def move_to(env, system, entity, dest, duration, piece=None, color=None):
    system.track(entity, f"MOVE_TO_{dest}", piece, color)
    yield env.timeout(duration)


def do_vision(env, system, entity, duration, piece=None, color=None):
    system.track(entity, "VISION", piece, color)
    yield env.timeout(duration)


def do_pick(env, system, entity, location, duration, piece, color):
    system.track(entity, f"PICK_{location}", piece, color)
    yield env.timeout(duration)


def do_place(env, system, entity, location, duration, piece, color):
    system.track(entity, f"PLACE_{location}", piece, color)
    yield env.timeout(duration)


def do_return_home(env, system, entity, duration, piece=None, color=None):
    system.track(entity, "RETURN_HOME", piece, color)
    yield env.timeout(duration)


def clear_bantam(env, system, entity, duration, piece=None, color=None):
    system.track(entity, "CLEAR_BANTAM", piece, color)
    yield env.timeout(duration)


def set_idle(system, entity, piece=None, color=None):
    system.track(entity, "IDLE", piece, color)


# ─────────────────────────────────────────────────────────────────
# PARALLEL PROCESSES
# ─────────────────────────────────────────────────────────────────

def laser_process(env, system, piece, color):
    if Config.LASER_HEATING > 0:
        system.track("laser", "HEATING", piece, color)
        yield env.timeout(Config.LASER_HEATING)
    system.track("laser", "PROCESSING", piece, color)
    yield env.timeout(Config.LASER_PROCESSING)
    system.laser_state = "FINISHED"
    system.track("laser", "FINISHED", piece, color)


def bantam_machine_process(env, system):
    system.door_state = "MOVING_TO_OPEN"
    system.track("bantam", "DOOR_OPENING_INIT")
    yield env.timeout(Config.BANTAM_OPEN_DOOR)
    system.door_state = "OPEN"
    system.bantam_state = "IDLE"
    system.track("bantam", "IDLE")

    while True:
        while system.bantam_state != "WORKING":
            yield env.timeout(0.1)

        piece = system.bantam_piece
        color = system.bantam_color

        system.track("bantam", "WAITING_ROBOT2", piece, color)
        yield system.bantam_robot2_clear

        system.track("bantam", "WORKING", piece, color)
        system.door_state = "MOVING_TO_CLOSED"
        system.track("bantam", "DOOR_CLOSING", piece, color)
        yield env.timeout(Config.BANTAM_CLOSE_DOOR)
        system.door_state = "CLOSED"

        system.track("bantam", "PROCESSING", piece, color)
        yield env.timeout(Config.BANTAM_PROCESSING)

        system.door_state = "MOVING_TO_OPEN"
        system.track("bantam", "DOOR_OPENING", piece, color)
        yield env.timeout(Config.BANTAM_OPEN_DOOR)
        system.door_state = "OPEN"

        system.bantam_state = "FINISHED"
        system.track("bantam", "FINISHED", piece, color)

        while system.bantam_state == "FINISHED":
            yield env.timeout(0.1)


def c3_station_process(env, system, piece, color):
    system.track("c3_station", "PROCESSING", piece, color)
    yield env.timeout(Config.C3_PROCESSING)
    system.c3_state = "FINISHED"
    system.c3_finish_time = env.now
    system.track("c3_station", "FINISHED", piece, color)


def c4_station_process(env, system, piece, color):
    system.track("c4_station", "PROCESSING", piece, color)
    yield env.timeout(Config.C4_PROCESSING)
    system.c4_state = "FINISHED"
    system.c4_finish_time = env.now
    system.track("c4_station", "FINISHED", piece, color)


# ─────────────────────────────────────────────────────────────────
# xArm2 — feeder
# ─────────────────────────────────────────────────────────────────

def xarm2_process(env, system):
    set_idle(system, "xarm2")

    while system.initial_stack:
        color = system.initial_stack[0]

        if color == "GREEN":
            if system.xarm2_state == "IDLE" and not system.c3_occupied:
                system.initial_stack.pop(0)
                piece = system.next_pid()
                system.xarm2_state = "WORKING"

                yield from move_to(env, system, "xarm2", "STACK", Config.XARM2_MOVE_TO_STACK, piece, color)
                yield from do_vision(env, system, "xarm2", Config.XARM2_VISION, piece, color)
                yield from do_pick(env, system, "xarm2", "STACK", Config.XARM2_PICK_STACK, piece, color)
                yield from do_place(env, system, "xarm2", "C3", Config.XARM2_PLACE_C3, piece, color)

                system.c3_occupied = True
                system.c3_piece = piece
                system.c3_color = "GREEN"
                system.c3_state = "WORKING"
                env.process(c3_station_process(env, system, piece, "GREEN"))

                yield from do_return_home(env, system, "xarm2", Config.XARM2_RETURN_HOME_FROM_C3, piece, color)
                system.xarm2_state = "IDLE"
                set_idle(system, "xarm2")
            else:
                yield env.timeout(0.1)
        else:
            if system.xarm2_state == "IDLE" and not system.c1s1_occupied:
                system.initial_stack.pop(0)
                piece = system.next_pid()
                system.xarm2_state = "WORKING"

                yield from move_to(env, system, "xarm2", "STACK", Config.XARM2_MOVE_TO_STACK, piece, color)
                yield from do_vision(env, system, "xarm2", Config.XARM2_VISION, piece, color)
                yield from do_pick(env, system, "xarm2", "STACK", Config.XARM2_PICK_STACK, piece, color)
                yield from do_place(env, system, "xarm2", "C1S1", Config.XARM2_PLACE_C1S1, piece, color)

                system.c1s1_occupied = True
                system.pieces_on_conveyor1.append({"name": piece, "color": color})

                yield from do_return_home(env, system, "xarm2", Config.XARM2_RETURN_HOME_FROM_C1S1, piece, color)
                system.xarm2_state = "IDLE"
                set_idle(system, "xarm2")
            else:
                yield env.timeout(0.1)


# ─────────────────────────────────────────────────────────────────
# CONVEYORS
# ─────────────────────────────────────────────────────────────────

def conveyor1_process(env, system):
    while True:
        if system.conveyor1_running and system.pieces_on_conveyor1:
            pdata = system.pieces_on_conveyor1.pop(0)
            system.c1s1_occupied = False
            yield env.timeout(Config.CONVEYOR1_TRANSPORT)
            system.c1s2_piece = pdata["name"]
            system.c1s2_color = pdata["color"]
            system.c1s2_occupied = True
            system.conveyor1_running = False
        else:
            yield env.timeout(0.1)


def conveyor1_control(env, system):
    while True:
        if not system.c1s2_occupied and not system.conveyor1_running:
            system.conveyor1_running = True
        yield env.timeout(0.1)


def conveyor2_process(env, system):
    while True:
        if system.conveyor2_running and system.pieces_on_conveyor2:
            pdata = system.pieces_on_conveyor2.pop(0)
            system.c2s1_occupied = False
            yield env.timeout(Config.CONVEYOR2_TRANSPORT)
            system.c2s2_piece = pdata["name"]
            system.c2s2_color = pdata["color"]
            system.c2s2_occupied = True
            system.conveyor2_running = False
        else:
            yield env.timeout(0.1)


def conveyor2_control(env, system):
    while True:
        if not system.c2s2_occupied and not system.conveyor2_running:
            system.conveyor2_running = True
        yield env.timeout(0.1)


# ─────────────────────────────────────────────────────────────────
# xArm1 — bridge C1S2 / Laser → C2S1
# ─────────────────────────────────────────────────────────────────

def xarm1_process(env, system):
    set_idle(system, "xarm1")

    while True:
        if system.xarm1_state == "IDLE" and system.laser_state == "FINISHED":
            if system.c2s1_occupied:
                yield env.timeout(0.1)
                continue
            piece = system.laser_piece
            color = system.laser_color
            system.xarm1_state = "WORKING"

            yield from move_to(env, system, "xarm1", "LASER", Config.XARM1_MOVE_TO_LASER, piece, color)
            yield from do_pick(env, system, "xarm1", "LASER", Config.XARM1_PICK_LASER, piece, color)

            system.laser_piece = None
            system.laser_color = None
            system.laser_state = "IDLE"
            system.track("laser", "IDLE")

            yield from do_place(env, system, "xarm1", "C2S1", Config.XARM1_LASER_TO_C2S1, piece, color)
            system.c2s1_occupied = True
            system.pieces_on_conveyor2.append({"name": piece, "color": color})

            yield from do_return_home(env, system, "xarm1", Config.XARM1_RETURN_HOME_LASER, piece, color)
            system.xarm1_state = "IDLE"
            set_idle(system, "xarm1")

        elif system.xarm1_state == "IDLE" and system.c1s2_occupied:
            piece = system.c1s2_piece
            color = system.c1s2_color

            if color == "RED":
                if system.laser_state in ("WORKING", "FINISHED"):
                    yield env.timeout(0.1)
                    continue
                system.xarm1_state = "WORKING"

                yield from move_to(env, system, "xarm1", "C1S2", Config.XARM1_MOVE_TO_C1S2, piece, color)
                yield from do_pick(env, system, "xarm1", "C1S2", Config.XARM1_PICK_C1S2, piece, color)

                system.c1s2_occupied = False
                system.c1s2_piece = None
                system.c1s2_color = None

                yield from do_place(env, system, "xarm1", "LASER_BED", Config.XARM1_PLACE_LASER, piece, color)
                system.laser_piece = piece
                system.laser_color = "RED"
                # Real laser RUN_JOB is only sent once xarm1's MOVE_PIECE
                # (C1S2->LASER_BED) command reports COMPLETED (see
                # processing_rules.py _on_xarm1_to_laser_complete ->
                # _send_laser_job) -- i.e. after the piece is physically
                # placed, not when xarm1 merely starts heading there. This
                # process used to start here at branch-entry, running the
                # laser's 22.8s job concurrently with the 13.45s of xarm1
                # travel/pick/place that must happen first in reality.
                system.laser_state = "WORKING"
                env.process(laser_process(env, system, piece, "RED"))

                yield from do_return_home(env, system, "xarm1", Config.XARM1_RETURN_HOME_C2S1, piece, color)
                system.xarm1_state = "IDLE"
                set_idle(system, "xarm1")

            else:  # BLUE
                if system.c2s1_occupied:
                    yield env.timeout(0.1)
                    continue
                system.xarm1_state = "WORKING"

                yield from move_to(env, system, "xarm1", "C1S2", Config.XARM1_MOVE_TO_C1S2, piece, color)
                yield from do_pick(env, system, "xarm1", "C1S2", Config.XARM1_PICK_C1S2, piece, color)

                system.c1s2_occupied = False
                system.c1s2_piece = None
                system.c1s2_color = None

                yield from do_place(env, system, "xarm1", "C2S1", Config.XARM1_PLACE_C2S1, piece, color)
                system.c2s1_occupied = True
                system.pieces_on_conveyor2.append({"name": piece, "color": color})

                yield from do_return_home(env, system, "xarm1", Config.XARM1_RETURN_HOME_C2S1, piece, color)
                system.xarm1_state = "IDLE"
                set_idle(system, "xarm1")
        else:
            yield env.timeout(0.1)


# ─────────────────────────────────────────────────────────────────
# Robot2 — classifier
# ─────────────────────────────────────────────────────────────────

def robot2_process(env, system):
    set_idle(system, "robot2")

    while True:
        # P1: classify C2S2 (blocked if C4 full)
        if (system.robot2_state == "IDLE"
                and system.c2s2_occupied
                and not system.c4_occupied):

            piece = system.c2s2_piece
            color = system.c2s2_color
            system.robot2_state = "WORKING"

            yield from move_to(env, system, "robot2", "C2S2", Config.ROBOT2_MOVE_TO_C2S2, piece, color)
            yield from do_vision(env, system, "robot2",
                                 get_vision_duration(system, "robot2", Config.ROBOT2_VISION),
                                 piece, color)
            yield from do_pick(env, system, "robot2", "C2S2", Config.ROBOT2_PICK_C2S2, piece, color)

            system.c2s2_occupied = False
            system.c2s2_piece = None
            system.c2s2_color = None

            if color == "RED":
                yield from do_place(env, system, "robot2", "C4", Config.ROBOT2_PLACE_C4, piece, color)
                system.c4_occupied = True
                system.c4_piece = piece
                system.c4_color = "RED"
                system.c4_state = "WORKING"
                env.process(c4_station_process(env, system, piece, "RED"))
                yield from do_return_home(env, system, "robot2", Config.ROBOT2_RETURN_C4, piece, color)

            elif color == "BLUE":
                if system.bantam_state == "IDLE" and system.bantam_bed == "EMPTY":
                    system.bantam_robot2_clear = env.event()
                    yield from do_place(env, system, "robot2", "BANTAM", Config.ROBOT2_PLACE_BANTAM, piece, color)
                    system.bantam_piece = piece
                    system.bantam_color = "BLUE"
                    system.bantam_bed   = "BLUE_PIECE"
                    system.bantam_state = "WORKING"
                    yield from clear_bantam(env, system, "robot2", Config.ROBOT2_CLEAR_BANTAM, piece, color)
                    system.bantam_robot2_clear.succeed()
                else:
                    yield from do_place(env, system, "robot2", "IBS", Config.ROBOT2_PLACE_IBS, piece, color)
                    system.ibs_pieces.append({"name": piece, "color": "BLUE"})
                    yield from do_return_home(env, system, "robot2", Config.ROBOT2_RETURN_IBS, piece, color)

            system.robot2_state = "IDLE"
            set_idle(system, "robot2")

        # P2: empty Bantam -> C4. Physical preconditions only: a finished
        # piece is waiting in the Bantam bed and C4 is free. This deliberately
        # does not gate on C2S2 or the conveyor2 queue; BANTAM->C4 does not
        # touch either one, and the real classification rule no longer uses
        # the old conveyor2-count priority hack.
        elif (system.robot2_state == "IDLE"
              and system.bantam_state == "FINISHED"
              and not system.c4_occupied):

            piece = system.bantam_piece
            color = system.bantam_color
            system.robot2_state = "WORKING"

            yield from move_to(env, system, "robot2", "BANTAM", Config.ROBOT2_MOVE_TO_BANTAM, piece, color)
            yield from do_pick(env, system, "robot2", "BANTAM", Config.ROBOT2_PICK_BANTAM, piece, color)

            system.bantam_piece = None
            system.bantam_color = None
            system.bantam_bed   = "EMPTY"
            system.bantam_state = "IDLE"
            system.track("bantam", "IDLE")

            yield from do_place(env, system, "robot2", "C4", Config.ROBOT2_BANTAM_TO_C4, piece, color)
            system.c4_occupied = True
            system.c4_piece = piece
            system.c4_color = "BLUE"
            system.c4_state = "WORKING"
            env.process(c4_station_process(env, system, piece, "BLUE"))

            yield from do_return_home(env, system, "robot2", Config.ROBOT2_RETURN_C4_BLUE, piece, color)
            system.robot2_state = "IDLE"
            set_idle(system, "robot2")

        # P3: IBS -> Bantam. This only needs the Bantam bed idle/empty and
        # an IBS piece; it does not touch C2S2 or C4.
        elif (system.robot2_state == "IDLE"
              and system.bantam_state == "IDLE"
              and system.bantam_bed == "EMPTY"
              and system.ibs_pieces):

            pdata = system.ibs_pieces.pop(0)
            piece = pdata["name"]
            color = pdata["color"]
            system.robot2_state = "WORKING"

            system.bantam_robot2_clear = env.event()
            yield from move_to(env, system, "robot2", "IBS", Config.ROBOT2_MOVE_TO_IBS, piece, color)
            yield from do_pick(env, system, "robot2", "IBS", Config.ROBOT2_PICK_IBS, piece, color)
            yield from do_place(env, system, "robot2", "BANTAM", Config.ROBOT2_IBS_TO_BANTAM, piece, color)
            system.bantam_piece = piece
            system.bantam_color = "BLUE"
            system.bantam_bed   = "BLUE_PIECE"
            system.bantam_state = "WORKING"

            yield from clear_bantam(env, system, "robot2", Config.ROBOT2_CLEAR_BANTAM_FROM_IBS, piece, color)
            system.bantam_robot2_clear.succeed()
            system.robot2_state = "IDLE"
            set_idle(system, "robot2")

        else:
            yield env.timeout(0.1)


# ─────────────────────────────────────────────────────────────────
# Robot1 — unloader (C3/C4 ready by station settle time; earliest-ready wins)
# ─────────────────────────────────────────────────────────────────

def robot1_process(env, system):
    set_idle(system, "robot1")

    while True:
        c4_ready = system.c4_occupied and system.c4_state == "FINISHED"
        c3_ready = system.c3_occupied and system.c3_state == "FINISHED"

        if system.robot1_state == "IDLE" and (c4_ready or c3_ready):
            if c4_ready and c3_ready:
                go_c4 = system.c4_finish_time <= system.c3_finish_time
            else:
                go_c4 = c4_ready

            if go_c4:
                piece = system.c4_piece
                color = system.c4_color
                system.robot1_state = "WORKING"

                yield from move_to(env, system, "robot1", "C4", Config.ROBOT1_MOVE_TO_C4, piece, color)
                yield from do_vision(env, system, "robot1",
                                     get_vision_duration(system, "robot1", Config.ROBOT1_VISION_C4),
                                     piece, color)
                yield from do_pick(env, system, "robot1", "C4", Config.ROBOT1_PICK_C4, piece, color)

                system.c4_occupied = False
                system.c4_piece = None
                system.c4_color = None
                system.c4_state = "IDLE"
                system.c4_finish_time = None

                yield from do_place(env, system, "robot1", f"FINAL_{color}", Config.ROBOT1_PLACE_FINAL_C4, piece, color)

                if color == "RED":
                    system.final_red_stack.append(piece)
                else:
                    system.final_blue_stack.append(piece)

            else:
                piece = system.c3_piece
                color = "GREEN"
                system.robot1_state = "WORKING"

                yield from move_to(env, system, "robot1", "C3", Config.ROBOT1_MOVE_TO_C3, piece, color)
                vision_c3_dur = get_vision_duration(system, "robot1", Config.ROBOT1_VISION_C3)
                if not system.robot1_c3_warmed_up:
                    system.robot1_c3_warmed_up = True
                    vision_c3_dur += Config.ROBOT1_VISION_C3_COLD_START_EXTRA
                yield from do_vision(env, system, "robot1", vision_c3_dur, piece, color)
                yield from do_pick(env, system, "robot1", "C3", Config.ROBOT1_PICK_C3, piece, color)

                system.c3_occupied = False
                system.c3_piece = None
                system.c3_color = None
                system.c3_state = "IDLE"
                system.c3_finish_time = None

                yield from do_place(env, system, "robot1", "FINAL_GREEN", Config.ROBOT1_PLACE_FINAL_C3, piece, color)
                system.final_green_stack.append(piece)

            yield from do_return_home(env, system, "robot1", Config.ROBOT1_RETURN_HOME, piece, color)
            system.robot1_state = "IDLE"
            set_idle(system, "robot1")

        else:
            yield env.timeout(0.1)
