"""
Brings all seven vendor domains online in dependency order.
Called by evaluate_rules() when planner_phase == BOOT.

Boot order (each waits for COMPLETED before kicking the next):
  arduino_vacuum → green_conveyors → globalvision → ufactory → niryo → laser → bantam → RUNNING
"""

from shipyard_pnp.shared.contracts import PlannerPhase

DOMAIN_INIT_RESOURCE = {
    "arduino_vacuum": "arduino_vacuum",
    "green_conveyors": "conveyor3",      # VS initialises 3+4 together internally
    "globalvision": "globalvision_camera",
    "ufactory": "xarm1",                 # VS initialises xarm1 then xarm2 internally
    "niryo": "robot1",                   # VS initialises all Niryo resources in order
    "laser": "laser",
    "bantam": "bantam",
}

INIT_SEQUENCE = {
    "arduino_vacuum": "green_conveyors",
    "green_conveyors": "globalvision",
    "globalvision": "ufactory",
    "ufactory": "niryo",
    "niryo": "laser",
    "laser": "bantam",
    "bantam": None,
}

INIT_ORDER = [
    "arduino_vacuum",
    "green_conveyors",
    "globalvision",
    "ufactory",
    "niryo",
    "laser",
    "bantam",
]


def evaluate(fs) -> None:
    if fs._init_started:
        return
    if all(fs.state.domain_online.values()):
        fs.planner_phase = PlannerPhase.WAITING_FOR_ORDER
        return
    fs._init_started = True
    _kick_domain(fs, _first_offline_domain(fs))


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _kick_domain(fs, domain_id: str) -> None:
    resource_id = DOMAIN_INIT_RESOURCE[domain_id]
    vc = fs.vendor_clients[domain_id]
    if vc.is_busy():
        fs.get_logger().warning(
            f"init: domain '{domain_id}' is busy, will retry on next tick"
        )
        fs._init_started = False
        return
    if fs.command_subscriber_count(domain_id) < 1:
        if domain_id not in fs._init_wait_logged_domains:
            fs._init_wait_logged_domains.add(domain_id)
            fs.get_logger().warning(
                f"init: domain '{domain_id}' command subscriber not discovered yet"
            )
        fs._init_started = False
        return
    fs._init_wait_logged_domains.discard(domain_id)
    fs.send_command(
        domain_id,
        resource_id,
        "INITIALIZE_DOMAIN",
        on_complete=_make_callback(fs, domain_id),
    )


def _make_callback(fs, domain_id: str):
    next_domain = INIT_SEQUENCE[domain_id]

    def on_complete(task_state: str, result: dict) -> None:
        if task_state == "COMPLETED":
            fs.state.set_domain_online(domain_id, True)
            fs.get_logger().info(f"Domain '{domain_id}' ONLINE")
            if next_domain is None:
                fs.planner_phase = PlannerPhase.WAITING_FOR_ORDER
                fs.get_logger().info("ALL DOMAINS ONLINE — waiting for optimized order from dashboard")
            else:
                _kick_domain(fs, next_domain)
        else:
            fs.get_logger().error(
                f"INITIALIZE_DOMAIN FAILED for '{domain_id}': {result} — will retry"
            )
            fs._init_started = False  # let evaluate() re-trigger on next tick

    return on_complete


def _first_offline_domain(fs) -> str:
    for domain_id in INIT_ORDER:
        if not fs.state.is_domain_online(domain_id):
            return domain_id
    return INIT_ORDER[-1]
