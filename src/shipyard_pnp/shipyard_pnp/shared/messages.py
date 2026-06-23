import hashlib
import hmac as _hmac
import json
from typing import Optional

from .time_ids import iso_now, make_nonce, make_command_id

FORBIDDEN_BOUNDARY_KEYS = frozenset({
    "joint", "joint_states", "angle", "servo", "register", "gpio", "pin",
    "raw_image", "image", "frame", "hsv", "mask", "contour", "roi_pixels",
    "gcode_line", "serial_bytes", "tool_torque", "motor_current",
})


def _hmac_string(payload: dict) -> str:
    ts = (
        payload.get("issued_at")
        or payload.get("accepted_at")
        or payload.get("published_at", "")
    )
    return f"{payload['command_id']}:{payload['nonce']}:{payload.get('task', '')}:{ts}"


def sign_message(payload: dict, secret: str) -> str:
    msg = _hmac_string(payload).encode()
    return _hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def verify_message(payload: dict, secret: str) -> bool:
    expected = sign_message(payload, secret)
    received = payload.get("auth", "")
    return _hmac.compare_digest(expected, received)


def validate_boundary(payload: dict) -> None:
    top_level_bad = FORBIDDEN_BOUNDARY_KEYS & set(payload.keys())
    if top_level_bad:
        raise ValueError(f"Forbidden boundary key(s) in payload: {top_level_bad}")
    result = payload.get("result")
    if isinstance(result, dict):
        result_bad = FORBIDDEN_BOUNDARY_KEYS & set(result.keys())
        if result_bad:
            raise ValueError(f"Forbidden boundary key(s) in result: {result_bad}")


def build_command(
    domain_id: str,
    resource_id: str,
    task: str,
    command_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    sender_id: str = "factory_supervisor",
    piece_id: Optional[str] = None,
    source: Optional[str] = None,
    target: Optional[str] = None,
    route: Optional[str] = None,
    parameters: Optional[dict] = None,
    secret: Optional[str] = None,
) -> dict:
    nonce = make_nonce()
    issued_at = iso_now()
    if command_id is None:
        command_id = make_command_id(domain_id, resource_id)
    payload = {
        "schema": "shipyard.pnp.command.v1",
        "command_id": command_id,
        "correlation_id": correlation_id,
        "sender_id": sender_id,
        "domain_id": domain_id,
        "resource_id": resource_id,
        "task": task,
        "piece_id": piece_id,
        "source": source,
        "target": target,
        "route": route,
        "parameters": parameters or {},
        "issued_at": issued_at,
        "nonce": nonce,
        "auth": "",
    }
    if secret:
        payload["auth"] = sign_message(payload, secret)
    return payload


def build_ack(
    command_id: str,
    domain_id: str,
    resource_id: str,
    accepted: bool,
    reason: Optional[str] = None,
    sender_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    secret: Optional[str] = None,
) -> dict:
    nonce = make_nonce()
    accepted_at = iso_now()
    if sender_id is None:
        sender_id = f"{domain_id}_vendor_supervisor"
    payload = {
        "schema": "shipyard.pnp.ack.v1",
        "command_id": command_id,
        "correlation_id": correlation_id,
        "sender_id": sender_id,
        "domain_id": domain_id,
        "resource_id": resource_id,
        "accepted": accepted,
        "reason": reason,
        "accepted_at": accepted_at,
        "nonce": nonce,
        "auth": "",
    }
    if secret:
        payload["auth"] = sign_message(payload, secret)
    return payload


def build_status(
    command_id: str,
    domain_id: str,
    resource_id: str,
    task: str,
    task_state: str,
    resource_state: str,
    piece_id: Optional[str] = None,
    source: Optional[str] = None,
    target: Optional[str] = None,
    route: Optional[str] = None,
    result: Optional[dict] = None,
    sender_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    secret: Optional[str] = None,
) -> dict:
    nonce = make_nonce()
    published_at = iso_now()
    if sender_id is None:
        sender_id = f"{domain_id}_vendor_supervisor"
    payload = {
        "schema": "shipyard.pnp.status.v1",
        "command_id": command_id,
        "correlation_id": correlation_id,
        "sender_id": sender_id,
        "domain_id": domain_id,
        "resource_id": resource_id,
        "task": task,
        "task_state": task_state,
        "resource_state": resource_state,
        "piece_id": piece_id,
        "source": source,
        "target": target,
        "route": route,
        "result": result or {},
        "published_at": published_at,
        "nonce": nonce,
        "auth": "",
    }
    if secret:
        payload["auth"] = sign_message(payload, secret)
    return payload


def parse_json(raw: str) -> dict:
    return json.loads(raw)


def to_json(payload: dict) -> str:
    return json.dumps(payload)
