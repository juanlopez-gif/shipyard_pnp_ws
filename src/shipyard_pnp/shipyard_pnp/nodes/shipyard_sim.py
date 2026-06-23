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
    # xArm2
    XARM2_MOVE_TO_STACK             = 3.8
    XARM2_VISION                    = 0.20
    XARM2_PICK_STACK                = 2.5
    XARM2_PLACE_C1S1                = 6.5
    XARM2_PLACE_C3                  = 9.5
    XARM2_RETURN_HOME_FROM_C3       = 4.20
    XARM2_RETURN_HOME_FROM_C1S1     = 2.50

    # Conveyor 1
    CONVEYOR1_TRANSPORT             = 6.0

    # Conveyor 2
    CONVEYOR2_TRANSPORT             = 9.0

    # xArm1
    XARM1_MOVE_TO_C1S2              = 4.0
    XARM1_PICK_C1S2                 = 2.5
    XARM1_PLACE_LASER               = 10.50
    XARM1_PLACE_C2S1                = 11.0
    XARM1_RETURN_HOME_C2S1          = 5
    XARM1_MOVE_TO_LASER             = 5.0
    XARM1_PICK_LASER                = 1.5
    XARM1_LASER_TO_C2S1             = 10.5
    XARM1_RETURN_HOME_LASER         = 4.5

    # Laser
    LASER_HEATING                   = 30.0
    LASER_PROCESSING                = 23.5

    # Robot2
    ROBOT2_MOVE_TO_C2S2             = 3.0
    ROBOT2_VISION_1                 = 13.5
    ROBOT2_VISION_2                 = 7.0
    ROBOT2_VISION_3                 = 5.0
    ROBOT2_VISION                   = 3.0
    ROBOT2_PICK_C2S2                = 8.0
    ROBOT2_PLACE_C4                 = 16
    ROBOT2_RETURN_C4                = 8.0
    ROBOT2_PLACE_IBS                = 12.0
    ROBOT2_RETURN_IBS               = 7.0
    ROBOT2_PLACE_BANTAM             = 15
    ROBOT2_RETURN_BANTAM            = 8.0
    ROBOT2_MOVE_TO_BANTAM           = 9.0
    ROBOT2_PICK_BANTAM              = 3.5
    ROBOT2_BANTAM_TO_C4             = 15.0
    ROBOT2_RETURN_C4_BLUE           = 9.0
    ROBOT2_MOVE_TO_IBS              = 9.0
    ROBOT2_PICK_IBS                 = 3.0
    ROBOT2_IBS_TO_BANTAM            = 15.0
    ROBOT2_RETURN_BANTAM_P3         = 8.0

    # Bantam
    BANTAM_CLOSE_DOOR               = 10.0
    BANTAM_PROCESSING               = 25.0
    BANTAM_OPEN_DOOR                = 14.0

    # C3 / C4
    C3_PROCESSING                   = 10.0
    C4_PROCESSING                   = 12.0

    # Robot1
    ROBOT1_MOVE_TO_C4               = 2.5
    ROBOT1_VISION_1                 = 13.0
    ROBOT1_VISION_2                 = 5
    ROBOT1_VISION_3                 = 5
    ROBOT1_VISION_C4                = 4
    ROBOT1_VISION_C3                = 4
    ROBOT1_PICK_C4                  = 10.0
    ROBOT1_PLACE_FINAL_C4           = 17.5
    ROBOT1_MOVE_TO_C3               = 3.5
    ROBOT1_PICK_C3                  = 9.5
    ROBOT1_PLACE_FINAL_C3           = 16.5
    ROBOT1_RETURN_HOME              = 8


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


def set_idle(system, entity, piece=None, color=None):
    system.track(entity, "IDLE", piece, color)


# ─────────────────────────────────────────────────────────────────
# PARALLEL PROCESSES
# ─────────────────────────────────────────────────────────────────

def laser_process(env, system, piece, color):
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

                env.process(laser_process(env, system, piece, "RED"))
                system.laser_state = "WORKING"

                yield from move_to(env, system, "xarm1", "C1S2", Config.XARM1_MOVE_TO_C1S2, piece, color)
                yield from do_pick(env, system, "xarm1", "C1S2", Config.XARM1_PICK_C1S2, piece, color)

                system.c1s2_occupied = False
                system.c1s2_piece = None
                system.c1s2_color = None

                yield from do_place(env, system, "xarm1", "LASER_BED", Config.XARM1_PLACE_LASER, piece, color)
                system.laser_piece = piece
                system.laser_color = "RED"

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
                    yield from do_return_home(env, system, "robot2", Config.ROBOT2_RETURN_BANTAM, piece, color)
                    system.bantam_robot2_clear.succeed()
                else:
                    yield from do_place(env, system, "robot2", "IBS", Config.ROBOT2_PLACE_IBS, piece, color)
                    system.ibs_pieces.append({"name": piece, "color": "BLUE"})
                    yield from do_return_home(env, system, "robot2", Config.ROBOT2_RETURN_IBS, piece, color)

            system.robot2_state = "IDLE"
            set_idle(system, "robot2")

        # P2: empty Bantam → C4 (blocked if C4 full)
        elif (system.robot2_state == "IDLE"
              and system.bantam_state == "FINISHED"
              and not system.c2s2_occupied
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

        # P3: IBS → Bantam (allowed even if C4 full)
        elif (system.robot2_state == "IDLE"
              and system.bantam_state == "IDLE"
              and system.bantam_bed == "EMPTY"
              and system.ibs_pieces
              and (not system.c2s2_occupied or system.c4_occupied)):

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

            yield from do_return_home(env, system, "robot2", Config.ROBOT2_RETURN_BANTAM_P3, piece, color)
            system.bantam_robot2_clear.succeed()
            system.robot2_state = "IDLE"
            set_idle(system, "robot2")

        else:
            yield env.timeout(0.1)


# ─────────────────────────────────────────────────────────────────
# Robot1 — unloader (P1: C4 > P2: C3)
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
                yield from do_vision(env, system, "robot1",
                                     get_vision_duration(system, "robot1", Config.ROBOT1_VISION_C3),
                                     piece, color)
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
