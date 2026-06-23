from enum import Enum


class DomainId(str, Enum):
    NIRYO = "niryo"
    UFACTORY = "ufactory"
    LASER = "laser"
    GLOBALVISION = "globalvision"
    GREEN_CONVEYORS = "green_conveyors"
    ARDUINO_VACUUM = "arduino_vacuum"
    BANTAM = "bantam"


class ResourceId(str, Enum):
    ROBOT1 = "robot1"
    ROBOT2 = "robot2"
    CONVEYOR1 = "conveyor1"
    CONVEYOR2 = "conveyor2"
    VISION_ROBOT1 = "vision_robot1"
    VISION_ROBOT2 = "vision_robot2"
    ROBOT2_NIRYO_VACUUM = "robot2_niryo_vacuum"
    XARM1 = "xarm1"
    XARM2 = "xarm2"
    LASER = "laser"
    GLOBALVISION_CAMERA = "globalvision_camera"
    CONVEYOR3 = "conveyor3"
    CONVEYOR4 = "conveyor4"
    ARDUINO_VACUUM = "arduino_vacuum"
    BANTAM = "bantam"
    BANTAM_DOOR = "bantam_door"


class TaskState(str, Enum):
    RECEIVED = "RECEIVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"
    CANCELED = "CANCELED"


class RobotState(str, Enum):
    NOT_INITIALIZED = "NOT_INITIALIZED"
    INITIALIZING = "INITIALIZING"
    IDLE = "IDLE"
    GOING_TO_POSITION = "GOING_TO_POSITION"
    WAITING_FOR_VISION = "WAITING_FOR_VISION"
    PICKING = "PICKING"
    PICK_DONE = "PICK_DONE"
    PLACING = "PLACING"
    PLACE_DONE = "PLACE_DONE"
    AT_PICK_POSITION = "AT_PICK_POSITION"
    AT_PLACE_POSITION = "AT_PLACE_POSITION"
    RETURNING_HOME = "RETURNING_HOME"
    ERROR = "ERROR"


class ConveyorState(str, Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    ERROR = "ERROR"


class SensorState(str, Enum):
    FREE = "FREE"
    OCCUPIED = "OCCUPIED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class VisionState(str, Enum):
    IDLE = "IDLE"
    SCANNING = "SCANNING"
    PROCESSING = "PROCESSING"
    RESULT_READY = "RESULT_READY"
    ERROR = "ERROR"


class VacuumState(str, Enum):
    IDLE = "IDLE"
    PICKING = "PICKING"
    PICK_DONE = "PICK_DONE"
    RELEASING = "RELEASING"
    RELEASE_DONE = "RELEASE_DONE"
    ERROR = "ERROR"


class MachineState(str, Enum):
    NOT_INITIALIZED = "NOT_INITIALIZED"
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    WORKING = "WORKING"
    FINISHED = "FINISHED"
    WAITING_PICKUP = "WAITING_PICKUP"
    ERROR = "ERROR"


class PlannerPhase(str, Enum):
    BOOT = "BOOT"
    INITIALIZING = "INITIALIZING"
    WAITING_FOR_ORDER = "WAITING_FOR_ORDER"
    RUNNING = "RUNNING"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    STOPPED = "STOPPED"


class TaskName(str, Enum):
    # Common
    INITIALIZE_DOMAIN = "INITIALIZE_DOMAIN"
    RESET = "RESET"
    # niryo
    MOVE_ROBOT = "MOVE_ROBOT"
    MOVE_PIECE = "MOVE_PIECE"
    CAPTURE_LOCAL_VISION = "CAPTURE_LOCAL_VISION"
    RUN_NIRYO_CONVEYOR = "RUN_NIRYO_CONVEYOR"
    STOP_NIRYO_CONVEYOR = "STOP_NIRYO_CONVEYOR"
    READ_IR_SENSOR = "READ_IR_SENSOR"
    SENSOR_UPDATE = "SENSOR_UPDATE"
    GOTO_PICK_POSITION = "GOTO_PICK_POSITION"
    CLASSIFY_AND_PICK = "CLASSIFY_AND_PICK"
    LIFT_AND_PLACE = "LIFT_AND_PLACE"
    RETURN_HOME = "RETURN_HOME"
    # ufactory
    MOVE_XARM_HOME = "MOVE_XARM_HOME"
    # laser / bantam
    PREPARE_JOB = "PREPARE_JOB"
    RUN_JOB = "RUN_JOB"
    # globalvision
    SCAN_STACK = "SCAN_STACK"
    LOCATE_NEXT_PIECE = "LOCATE_NEXT_PIECE"
    GET_INVENTORY = "GET_INVENTORY"
    # green_conveyors
    RUN_CONVEYOR = "RUN_CONVEYOR"
    STOP_CONVEYOR = "STOP_CONVEYOR"
    SET_SPEED = "SET_SPEED"
    # arduino_vacuum
    PICK = "PICK"
    RELEASE = "RELEASE"
    OFF = "OFF"
    # bantam
    GET_READY = "GET_READY"
    OPEN_DOOR = "OPEN_DOOR"
    CLOSE_DOOR = "CLOSE_DOOR"


TERMINAL_TASK_STATES = {
    TaskState.COMPLETED,
    TaskState.FAILED,
    TaskState.REJECTED,
    TaskState.TIMEOUT,
    TaskState.CANCELED,
}

DOMAIN_IDS = [d.value for d in DomainId]

DOMAIN_COMMAND_TOPIC = {d.value: f"/{d.value}_factory/command" for d in DomainId}
DOMAIN_ACK_TOPIC = {d.value: f"/{d.value}_factory/ack" for d in DomainId}
DOMAIN_STATUS_TOPIC = {d.value: f"/{d.value}_factory/status" for d in DomainId}
