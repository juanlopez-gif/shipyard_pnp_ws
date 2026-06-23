"""
Unit tests for proprietary data confinement (Theorem 3 / RQ2).

Validates that FORBIDDEN_BOUNDARY_KEYS covers the correct set of keys
and that validate_boundary() raises on any forbidden key while allowing
legitimate semantic result fields.
"""

import pytest

from shipyard_pnp.shared.messages import FORBIDDEN_BOUNDARY_KEYS, validate_boundary


# ── FORBIDDEN_BOUNDARY_KEYS coverage ─────────────────────────────────────────

_EXPECTED_FORBIDDEN = {
    "joint", "joint_states", "angle", "servo", "register",
    "gpio", "pin", "raw_image", "image", "frame",
    "hsv", "mask", "contour", "roi_pixels",
    "gcode_line", "serial_bytes", "tool_torque", "motor_current",
}


def test_all_expected_forbidden_keys_present():
    missing = _EXPECTED_FORBIDDEN - FORBIDDEN_BOUNDARY_KEYS
    assert not missing, f"Missing from FORBIDDEN_BOUNDARY_KEYS: {missing}"


def test_no_unexpected_forbidden_keys():
    extra = FORBIDDEN_BOUNDARY_KEYS - _EXPECTED_FORBIDDEN
    # Extra keys are acceptable — they represent stricter enforcement.
    # This test documents rather than blocks unexpected additions.
    if extra:
        pytest.skip(f"Extra forbidden keys present (not an error): {extra}")


# ── validate_boundary — top-level forbidden keys ──────────────────────────────

@pytest.mark.parametrize("forbidden_key", sorted(_EXPECTED_FORBIDDEN))
def test_rejects_top_level_forbidden_key(forbidden_key):
    payload = {
        "schema": "shipyard.pnp.status.v1",
        "command_id": "CMD-001",
        forbidden_key: "some_value",
    }
    with pytest.raises(ValueError, match="Forbidden"):
        validate_boundary(payload)


# ── validate_boundary — forbidden keys inside result dict ─────────────────────

@pytest.mark.parametrize("forbidden_key", sorted(_EXPECTED_FORBIDDEN))
def test_rejects_forbidden_key_in_result(forbidden_key):
    payload = {
        "schema": "shipyard.pnp.status.v1",
        "command_id": "CMD-001",
        "result": {forbidden_key: "leak"},
    }
    with pytest.raises(ValueError, match="Forbidden"):
        validate_boundary(payload)


# ── validate_boundary — allowed payloads ─────────────────────────────────────

_ALLOWED_CLEAN_PAYLOADS = [
    {"schema": "shipyard.pnp.command.v1", "command_id": "CMD-1", "task": "MOVE_PIECE"},
    {"schema": "shipyard.pnp.ack.v1", "command_id": "CMD-1", "accepted": True},
    {
        "schema": "shipyard.pnp.status.v1",
        "command_id": "CMD-1",
        "task_state": "COMPLETED",
        "result": {"code": "OK"},
    },
]


@pytest.mark.parametrize("payload", _ALLOWED_CLEAN_PAYLOADS)
def test_allows_clean_payload(payload):
    validate_boundary(payload)  # must not raise


# ── Semantic result fields are permitted ──────────────────────────────────────

_ALLOWED_SEMANTIC_RESULTS = [
    {"color": "BLUE"},
    {"shape": "CIRCLE"},
    {"slot_id": "C3"},
    {"occupied": True},
    {"confidence": 0.97},
    {"color": "RED", "shape": "SQUARE", "slot_id": "C4", "confidence": 0.85},
]


@pytest.mark.parametrize("result", _ALLOWED_SEMANTIC_RESULTS)
def test_allows_semantic_result_fields(result):
    payload = {
        "schema": "shipyard.pnp.status.v1",
        "command_id": "CMD-1",
        "result": result,
    }
    validate_boundary(payload)  # must not raise


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_payload_is_allowed():
    validate_boundary({})


def test_result_none_is_allowed():
    validate_boundary({"result": None})


def test_result_non_dict_is_allowed():
    validate_boundary({"result": "OK"})
    validate_boundary({"result": 42})


def test_multiple_forbidden_keys_caught():
    payload = {"joint_states": [], "servo": 0, "gcode_line": "G0"}
    with pytest.raises(ValueError):
        validate_boundary(payload)


def test_forbidden_key_in_nested_non_result_dict_not_checked():
    """
    validate_boundary only inspects top-level keys and the 'result' dict.
    Deeper nesting inside 'parameters' etc. is the responsibility of higher-
    level validators; we document that behaviour here.
    """
    payload = {
        "schema": "shipyard.pnp.command.v1",
        "parameters": {"servo": 45},  # nested inside 'parameters', not checked
    }
    validate_boundary(payload)  # must NOT raise at this level
