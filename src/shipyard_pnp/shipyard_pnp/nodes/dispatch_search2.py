"""
v2: corrige el bug de fondo que el usuario detecto -- la condicion de "P2
listo" (recoger bantam) copiada de la regla real exigia "not c2s2_occupied",
lo que hacia P1 y P2 mutuamente EXCLUYENTES POR DEFINICION DE SOFTWARE, no
por imposibilidad fisica. Aqui "listo" se redefine en terminos puramente
fisicos:

  P1 (clasificar C2S2): hay una pieza fisicamente en C2S2 Y C4 esta libre.
  P2 (recoger bantam):  bantam ha terminado Y C4 esta libre.
       (sin exigir que C2S2 este vacio -- fisicamente robot2 SI puede elegir
       ir a bantam aunque haya algo esperando en C2S2 al mismo tiempo)
  P3 (vaciar IBS a bantam): bantam esta IDLE+vacia Y hay algo en IBS.
       (sin exigir nada sobre C2S2/C4 -- no los toca physicamente)

Y anade GREEN (via C3) + el dilema real de robot1 (C3 vs C4, tambien
buscado en vez de "el que lleva mas tiempo esperando").
"""
import simpy

from shipyard_pnp.nodes import shipyard_sim_search as sim
from shipyard_pnp.nodes.shipyard_sim_search import Config


class NeedDecision(Exception):
    def __init__(self, ready_options, system=None):
        self.ready_options = ready_options
        self.system = system


def _decide(system, entity, ready, last_decided, decide_fn):
    """Shared decision-point bookkeeping for both robot1 and robot2."""
    ready_key = tuple(sorted(ready))
    if ready and ready_key != last_decided[entity]:
        choice = decide_fn(ready, system.env.now, system)
        if choice == "WAIT":
            last_decided[entity] = ready_key
            return None
        last_decided[entity] = None
        return choice
    return None


def robot2_process_v2(env, system, decide_fn, last_decided):
    sim.set_idle(system, "robot2")
    while True:
        ready = []
        if system.robot2_state == "IDLE" and system.c2s2_occupied and not system.c4_occupied:
            ready.append("P1")
        if system.robot2_state == "IDLE" and system.bantam_state == "FINISHED" and not system.c4_occupied:
            ready.append("P2")
        if (system.robot2_state == "IDLE" and system.bantam_state == "IDLE"
                and system.bantam_bed == "EMPTY" and system.ibs_pieces):
            ready.append("P3")

        choice = _decide(system, "robot2", ready, last_decided, decide_fn) if ready else None
        if choice is None:
            yield env.timeout(0.1)
            continue

        if choice == "P1":
            piece = system.c2s2_piece
            color = system.c2s2_color
            system.robot2_state = "WORKING"
            yield from sim.move_to(env, system, "robot2", "C2S2", Config.ROBOT2_MOVE_TO_C2S2, piece, color)
            yield from sim.do_vision(env, system, "robot2",
                                      sim.get_vision_duration(system, "robot2", Config.ROBOT2_VISION),
                                      piece, color)
            yield from sim.do_pick(env, system, "robot2", "C2S2", Config.ROBOT2_PICK_C2S2, piece, color)
            system.c2s2_occupied = False
            system.c2s2_piece = None
            system.c2s2_color = None
            if color == "RED":
                yield from sim.do_place(env, system, "robot2", "C4", Config.ROBOT2_PLACE_C4, piece, color)
                system.c4_occupied = True
                system.c4_piece = piece
                system.c4_color = "RED"
                system.c4_state = "WORKING"
                system.c4_finish_time = None
                env.process(c4_station_process_v2(env, system, piece, "RED"))
                yield from sim.do_return_home(env, system, "robot2", Config.ROBOT2_RETURN_C4, piece, color)
            elif color == "BLUE":
                if system.bantam_state == "IDLE" and system.bantam_bed == "EMPTY":
                    system.bantam_robot2_clear = env.event()
                    yield from sim.do_place(env, system, "robot2", "BANTAM", Config.ROBOT2_PLACE_BANTAM, piece, color)
                    system.bantam_piece = piece
                    system.bantam_color = "BLUE"
                    system.bantam_bed = "BLUE_PIECE"
                    system.bantam_state = "WORKING"
                    yield from sim.clear_bantam(env, system, "robot2", Config.ROBOT2_CLEAR_BANTAM, piece, color)
                    system.bantam_robot2_clear.succeed()
                else:
                    yield from sim.do_place(env, system, "robot2", "IBS", Config.ROBOT2_PLACE_IBS, piece, color)
                    system.ibs_pieces.append({"name": piece, "color": "BLUE"})
                    yield from sim.do_return_home(env, system, "robot2", Config.ROBOT2_RETURN_IBS, piece, color)
            system.robot2_state = "IDLE"
            sim.set_idle(system, "robot2")

        elif choice == "P2":
            piece = system.bantam_piece
            color = system.bantam_color
            system.robot2_state = "WORKING"
            yield from sim.move_to(env, system, "robot2", "BANTAM", Config.ROBOT2_MOVE_TO_BANTAM, piece, color)
            yield from sim.do_pick(env, system, "robot2", "BANTAM", Config.ROBOT2_PICK_BANTAM, piece, color)
            system.bantam_piece = None
            system.bantam_color = None
            system.bantam_bed = "EMPTY"
            system.bantam_state = "IDLE"
            system.track("bantam", "IDLE")
            yield from sim.do_place(env, system, "robot2", "C4", Config.ROBOT2_BANTAM_TO_C4, piece, color)
            system.c4_occupied = True
            system.c4_piece = piece
            system.c4_color = "BLUE"
            system.c4_state = "WORKING"
            system.c4_finish_time = None
            env.process(c4_station_process_v2(env, system, piece, "BLUE"))
            yield from sim.do_return_home(env, system, "robot2", Config.ROBOT2_RETURN_C4_BLUE, piece, color)
            system.robot2_state = "IDLE"
            sim.set_idle(system, "robot2")

        elif choice == "P3":
            pdata = system.ibs_pieces.pop(0)
            piece = pdata["name"]
            color = pdata["color"]
            system.robot2_state = "WORKING"
            system.bantam_robot2_clear = env.event()
            yield from sim.move_to(env, system, "robot2", "IBS", Config.ROBOT2_MOVE_TO_IBS, piece, color)
            yield from sim.do_pick(env, system, "robot2", "IBS", Config.ROBOT2_PICK_IBS, piece, color)
            yield from sim.do_place(env, system, "robot2", "BANTAM", Config.ROBOT2_IBS_TO_BANTAM, piece, color)
            system.bantam_piece = piece
            system.bantam_color = "BLUE"
            system.bantam_bed = "BLUE_PIECE"
            system.bantam_state = "WORKING"
            yield from sim.clear_bantam(env, system, "robot2", Config.ROBOT2_CLEAR_BANTAM_FROM_IBS, piece, color)
            system.bantam_robot2_clear.succeed()
            system.robot2_state = "IDLE"
            sim.set_idle(system, "robot2")


def c4_station_process_v2(env, system, piece, color):
    yield env.timeout(Config.C4_PROCESSING)
    system.c4_state = "FINISHED"
    system.c4_finish_time = env.now


def c3_station_process_v2(env, system, piece, color):
    yield env.timeout(Config.C3_PROCESSING)
    system.c3_state = "FINISHED"
    system.c3_finish_time = env.now


def robot1_process_v2(env, system, decide_fn, last_decided):
    sim.set_idle(system, "robot1")
    while True:
        ready = []
        if system.robot1_state == "IDLE" and system.c4_occupied and system.c4_state == "FINISHED":
            ready.append("C4")
        if system.robot1_state == "IDLE" and system.c3_occupied and system.c3_state == "FINISHED":
            ready.append("C3")

        choice = _decide(system, "robot1", ready, last_decided, decide_fn) if ready else None
        if choice is None:
            yield env.timeout(0.1)
            continue

        if choice == "C4":
            piece = system.c4_piece
            color = system.c4_color
            system.robot1_state = "WORKING"
            yield from sim.move_to(env, system, "robot1", "C4", Config.ROBOT1_MOVE_TO_C4, piece, color)
            yield from sim.do_vision(env, system, "robot1",
                                      sim.get_vision_duration(system, "robot1", Config.ROBOT1_VISION_C4),
                                      piece, color)
            yield from sim.do_pick(env, system, "robot1", "C4", Config.ROBOT1_PICK_C4, piece, color)
            system.c4_occupied = False
            system.c4_piece = None
            system.c4_color = None
            system.c4_state = "IDLE"
            system.c4_finish_time = None
            yield from sim.do_place(env, system, "robot1", f"FINAL_{color}", Config.ROBOT1_PLACE_FINAL_C4, piece, color)
            if color == "RED":
                system.final_red_stack.append(piece)
            else:
                system.final_blue_stack.append(piece)
        else:
            piece = system.c3_piece
            color = "GREEN"
            system.robot1_state = "WORKING"
            yield from sim.move_to(env, system, "robot1", "C3", Config.ROBOT1_MOVE_TO_C3, piece, color)
            vision_c3_dur = sim.get_vision_duration(system, "robot1", Config.ROBOT1_VISION_C3)
            if not system.robot1_c3_warmed_up:
                system.robot1_c3_warmed_up = True
                vision_c3_dur += Config.ROBOT1_VISION_C3_COLD_START_EXTRA
            yield from sim.do_vision(env, system, "robot1", vision_c3_dur, piece, color)
            yield from sim.do_pick(env, system, "robot1", "C3", Config.ROBOT1_PICK_C3, piece, color)
            system.c3_occupied = False
            system.c3_piece = None
            system.c3_color = None
            system.c3_state = "IDLE"
            system.c3_finish_time = None
            yield from sim.do_place(env, system, "robot1", "FINAL_GREEN", Config.ROBOT1_PLACE_FINAL_C3, piece, color)
            system.final_green_stack.append(piece)

        yield from sim.do_return_home(env, system, "robot1", Config.ROBOT1_RETURN_HOME, piece, color)
        system.robot1_state = "IDLE"
        sim.set_idle(system, "robot1")


def xarm1_process_v2(env, system, decide_fn, last_decided):
    sim.set_idle(system, "xarm1")

    while True:
        ready = []
        if system.xarm1_state == "IDLE":
            retrieve_ready = (
                system.laser_state == "FINISHED"
                and not system.c2s1_occupied
            )
            c1s2_ready = False
            if system.c1s2_occupied:
                color = system.c1s2_color
                if color == "RED":
                    c1s2_ready = system.laser_state == "IDLE"
                else:
                    c1s2_ready = not system.c2s1_occupied

            if retrieve_ready:
                ready.append("LASER")
            if c1s2_ready:
                ready.append("C1")

        choice = _decide(system, "xarm1", ready, last_decided, decide_fn) if ready else None
        if choice is None:
            yield env.timeout(0.1)
            continue

        if choice == "LASER":
            piece = system.laser_piece
            color = system.laser_color
            system.xarm1_state = "WORKING"

            yield from sim.move_to(env, system, "xarm1", "LASER", Config.XARM1_MOVE_TO_LASER, piece, color)
            yield from sim.do_pick(env, system, "xarm1", "LASER", Config.XARM1_PICK_LASER, piece, color)

            system.laser_piece = None
            system.laser_color = None
            system.laser_state = "IDLE"
            system.track("laser", "IDLE")

            yield from sim.do_place(env, system, "xarm1", "C2S1", Config.XARM1_LASER_TO_C2S1, piece, color)
            system.c2s1_occupied = True
            system.pieces_on_conveyor2.append({"name": piece, "color": color})

            yield from sim.do_return_home(env, system, "xarm1", Config.XARM1_RETURN_HOME_LASER, piece, color)
            system.xarm1_state = "IDLE"
            sim.set_idle(system, "xarm1")

        elif choice == "C1":
            piece = system.c1s2_piece
            color = system.c1s2_color
            system.xarm1_state = "WORKING"

            yield from sim.move_to(env, system, "xarm1", "C1S2", Config.XARM1_MOVE_TO_C1S2, piece, color)
            yield from sim.do_pick(env, system, "xarm1", "C1S2", Config.XARM1_PICK_C1S2, piece, color)

            system.c1s2_occupied = False
            system.c1s2_piece = None
            system.c1s2_color = None

            if color == "RED":
                yield from sim.do_place(env, system, "xarm1", "LASER_BED", Config.XARM1_PLACE_LASER, piece, color)
                system.laser_piece = piece
                system.laser_color = "RED"
                system.laser_state = "WORKING"
                env.process(sim.laser_process(env, system, piece, "RED"))
            else:
                yield from sim.do_place(env, system, "xarm1", "C2S1", Config.XARM1_PLACE_C2S1, piece, color)
                system.c2s1_occupied = True
                system.pieces_on_conveyor2.append({"name": piece, "color": color})

            yield from sim.do_return_home(env, system, "xarm1", Config.XARM1_RETURN_HOME_C2S1, piece, color)
            system.xarm1_state = "IDLE"
            sim.set_idle(system, "xarm1")


def xarm2_process_v2(env, system):
    """Same as the original but hooked to c3_station_process_v2 (which
    reports FINISHED without also nudging robot1 -- robot1 decides on its
    own via robot1_process_v2)."""
    sim.set_idle(system, "xarm2")
    while system.initial_stack:
        color = system.initial_stack[0]
        if color == "GREEN":
            if system.xarm2_state == "IDLE" and not system.c3_occupied:
                system.initial_stack.pop(0)
                piece = system.next_pid()
                system.xarm2_state = "WORKING"
                yield from sim.move_to(env, system, "xarm2", "STACK", Config.XARM2_MOVE_TO_STACK, piece, color)
                yield from sim.do_vision(env, system, "xarm2", Config.XARM2_VISION, piece, color)
                yield from sim.do_pick(env, system, "xarm2", "STACK", Config.XARM2_PICK_STACK, piece, color)
                yield from sim.do_place(env, system, "xarm2", "C3", Config.XARM2_PLACE_C3, piece, color)
                system.c3_occupied = True
                system.c3_piece = piece
                system.c3_color = "GREEN"
                system.c3_state = "WORKING"
                system.c3_finish_time = None
                env.process(c3_station_process_v2(env, system, piece, "GREEN"))
                yield from sim.do_return_home(env, system, "xarm2", Config.XARM2_RETURN_HOME_FROM_C3, piece, color)
                system.xarm2_state = "IDLE"
                sim.set_idle(system, "xarm2")
            else:
                yield env.timeout(0.1)
        else:
            if system.xarm2_state == "IDLE" and not system.c1s1_occupied:
                system.initial_stack.pop(0)
                piece = system.next_pid()
                system.xarm2_state = "WORKING"
                yield from sim.move_to(env, system, "xarm2", "STACK", Config.XARM2_MOVE_TO_STACK, piece, color)
                yield from sim.do_vision(env, system, "xarm2", Config.XARM2_VISION, piece, color)
                yield from sim.do_pick(env, system, "xarm2", "STACK", Config.XARM2_PICK_STACK, piece, color)
                yield from sim.do_place(env, system, "xarm2", "C1S1", Config.XARM2_PLACE_C1S1, piece, color)
                system.c1s1_occupied = True
                system.pieces_on_conveyor1.append({"name": piece, "color": color})
                yield from sim.do_return_home(env, system, "xarm2", Config.XARM2_RETURN_HOME_FROM_C1S1, piece, color)
                system.xarm2_state = "IDLE"
                sim.set_idle(system, "xarm2")
            else:
                yield env.timeout(0.1)


def run_system(order, decide_fn_r2, decide_fn_r1, decide_fn_x1=None, horizon=2000):
    env = simpy.Environment()
    system = sim.System(env, list(order))
    if decide_fn_x1 is None:
        decide_fn_x1 = fixed_priority_decide_x1
    last_decided = {"robot2": None, "robot1": None, "xarm1": None}
    env.process(sim.bantam_machine_process(env, system))
    env.process(xarm2_process_v2(env, system))
    env.process(sim.conveyor1_process(env, system))
    env.process(sim.conveyor1_control(env, system))
    env.process(sim.conveyor2_process(env, system))
    env.process(sim.conveyor2_control(env, system))
    env.process(xarm1_process_v2(env, system, decide_fn_x1, last_decided))
    env.process(robot2_process_v2(env, system, decide_fn_r2, last_decided))
    env.process(robot1_process_v2(env, system, decide_fn_r1, last_decided))
    env.run(until=horizon)
    return system


def makespan(system, n_blue, n_red, n_green):
    done = (len(system.final_blue_stack) == n_blue
            and len(system.final_red_stack) == n_red
            and len(system.final_green_stack) == n_green)
    if not done:
        return None
    return max(c["time"] for c in system.state_changes)


def fixed_priority_decide_r2(ready_options, now=None, system=None):
    for p in ("P1", "P2", "P3"):
        if p in ready_options:
            return p
    return "WAIT"


def fixed_priority_decide_r1(ready_options, now=None, system=None):
    # Matches unloading_rules.py's plain fallback: if both C3 and C4 are
    # already ready and the map has no opinion, pick the one that settled
    # first. For single-ready cases, take the only physical option.
    if system is not None and {"C3", "C4"}.issubset(set(ready_options)):
        c4_t = (
            system.c4_finish_time
            if system.c4_finish_time is not None
            else float("inf")
        )
        c3_t = (
            system.c3_finish_time
            if system.c3_finish_time is not None
            else float("inf")
        )
        return "C4" if c4_t <= c3_t else "C3"
    for p in ("C4", "C3"):
        if p in ready_options:
            return p
    return "WAIT"


def fixed_priority_decide_x1(ready_options, now=None, system=None):
    # Current processing_rules.py fallback: when laser retrieval and C1S2
    # handling are both executable, retrieve the finished laser piece first.
    for p in ("LASER", "C1"):
        if p in ready_options:
            return p
    return "WAIT"


def make_decide_tagged(path, tag, tag_holder, now_holder):
    """Replays `path`'s choices for this entity in order; once exhausted,
    raises NeedDecision carrying the ready options AND the sim clock at the
    pause point (now_holder[0] gets set by the caller before raising isn't
    possible here directly, so the caller of run_system must read
    now_holder after catching -- see run_with_path_tagged)."""
    idx = [0]

    def decide_fn(ready_options, now, system=None):
        my_choices = [c for (t, c) in path if t == tag]
        if idx[0] < len(my_choices):
            choice = my_choices[idx[0]]
            idx[0] += 1
            return choice
        tag_holder[0] = tag
        now_holder[0] = now
        raise NeedDecision(list(ready_options), system=system)
    return decide_fn


def run_with_path_tagged(order, path):
    """Run the sim replaying `path` (a list of (entity_tag, choice) tuples,
    interleaved in whatever order each entity encounters its own decisions)
    until either it completes or hits a decision point beyond what `path`
    covers. Returns (system, None) on completion, or (None, NeedDecision)
    with .tag/.ready_options/.now set on the raised exception otherwise."""
    tag_holder = [None]
    now_holder = [None]
    r2 = make_decide_tagged(path, "robot2", tag_holder, now_holder)
    r1 = make_decide_tagged(path, "robot1", tag_holder, now_holder)
    x1 = make_decide_tagged(path, "xarm1", tag_holder, now_holder)
    try:
        system = run_system(order, r2, r1, x1)
        return system, None
    except NeedDecision as nd:
        nd.tag = tag_holder[0]
        nd.now = now_holder[0]
        return None, nd


def make_decide_tagged_with_fallback(path, tag, fallback_fn, decision_log=None):
    """Replay explicit choices for one entity, then use fallback_fn.

    The search path stores only deliberate deviations explored so far. A
    rollout needs to complete the rest of the simulation, so once the tagged
    path choices are exhausted this switches to the current fixed-priority
    rule for that entity.
    """
    idx = [0]
    my_choices = [c for (t, c) in path if t == tag]

    def decide_fn(ready_options, now, system=None):
        source = "path"
        if idx[0] < len(my_choices):
            choice = my_choices[idx[0]]
            idx[0] += 1
            if choice != "WAIT" and choice not in ready_options:
                choice = fallback_fn(ready_options, now, system)
                source = "fallback-invalid-path"
        else:
            choice = fallback_fn(ready_options, now, system)
            source = "fallback"
        if decision_log is not None:
            decision_log.append({
                "entity": tag,
                "choice": choice,
                "time": round(now, 1),
                "ready": tuple(ready_options),
                "source": source,
            })
        return choice

    return decide_fn


def run_with_path_and_fallback(
    order,
    path,
    horizon=2000,
    record_decisions=False,
    fallback_r2=None,
    fallback_r1=None,
    fallback_x1=None,
):
    """Replay `path`, then finish with configurable fallback decisions.

    This is the scoring rollout used by beam_search: it answers "if I make
    this partial sequence of decisions, what does the rest of the run look
    like under the selected fallback policy?"
    """
    decision_log = [] if record_decisions else None
    fallback_r2 = fallback_r2 or fixed_priority_decide_r2
    fallback_r1 = fallback_r1 or fixed_priority_decide_r1
    fallback_x1 = fallback_x1 or fixed_priority_decide_x1
    r2 = make_decide_tagged_with_fallback(
        path, "robot2", fallback_r2, decision_log
    )
    r1 = make_decide_tagged_with_fallback(
        path, "robot1", fallback_r1, decision_log
    )
    x1 = make_decide_tagged_with_fallback(
        path, "xarm1", fallback_x1, decision_log
    )
    system = run_system(order, r2, r1, x1, horizon=horizon)
    return system, decision_log


def search_best(order, n_blue, n_red, n_green, max_leaves=200000):
    best = {"makespan": None, "path": None}
    leaves = [0]

    def explore2(path):
        if leaves[0] > max_leaves:
            return
        system, nd = run_with_path_tagged(order, path)
        if nd is not None:
            for opt in nd.ready_options + ["WAIT"]:
                explore2(path + [(nd.tag, opt)])
            return
        leaves[0] += 1
        ms = makespan(system, n_blue, n_red, n_green)
        if ms is not None and (best["makespan"] is None or ms < best["makespan"]):
            best["makespan"] = ms
            best["path"] = list(path)

    explore2([])
    return best, leaves[0]
