"""
Unit tests for shared/messages.py.

Covers message building, HMAC sign/verify, JSON serialisation, and the
basic structural requirements every boundary message must satisfy.
"""

import json
import pytest

from shipyard_pnp.shared.messages import (
    FORBIDDEN_BOUNDARY_KEYS,
    build_ack,
    build_command,
    build_status,
    parse_json,
    sign_message,
    to_json,
    validate_boundary,
    verify_message,
)

_SECRET = "test_hmac_secret_experiment_1"
_ALT_SECRET = "different_secret"

_REQUIRED_COMMAND_KEYS = {
    "schema", "command_id", "sender_id", "domain_id", "resource_id",
    "task", "issued_at", "nonce", "auth",
}
_REQUIRED_ACK_KEYS = {
    "schema", "command_id", "sender_id", "domain_id", "resource_id",
    "accepted", "accepted_at", "nonce", "auth",
}
_REQUIRED_STATUS_KEYS = {
    "schema", "command_id", "sender_id", "domain_id", "resource_id",
    "task", "task_state", "resource_state", "published_at", "nonce", "auth",
}


# ── build_command ─────────────────────────────────────────────────────────────

class TestBuildCommand:
    def test_required_keys_present(self):
        cmd = build_command("niryo", "robot1", "MOVE_PIECE")
        assert _REQUIRED_COMMAND_KEYS.issubset(cmd.keys())

    def test_schema_is_command(self):
        cmd = build_command("niryo", "robot1", "MOVE_PIECE")
        assert cmd["schema"] == "shipyard.pnp.command.v1"

    def test_domain_id_set(self):
        cmd = build_command("niryo", "robot1", "MOVE_PIECE")
        assert cmd["domain_id"] == "niryo"

    def test_resource_id_set(self):
        cmd = build_command("niryo", "robot1", "MOVE_PIECE")
        assert cmd["resource_id"] == "robot1"

    def test_task_set(self):
        cmd = build_command("niryo", "robot1", "MOVE_PIECE")
        assert cmd["task"] == "MOVE_PIECE"

    def test_command_id_unique(self):
        ids = {build_command("niryo", "robot1", "T")["command_id"] for _ in range(20)}
        assert len(ids) == 20

    def test_nonce_unique(self):
        nonces = {build_command("niryo", "robot1", "T")["nonce"] for _ in range(20)}
        assert len(nonces) == 20

    def test_auth_empty_without_secret(self):
        cmd = build_command("niryo", "robot1", "T")
        assert cmd["auth"] == ""

    def test_auth_signed_with_secret(self):
        cmd = build_command("niryo", "robot1", "T", secret=_SECRET)
        assert len(cmd["auth"]) == 64  # SHA-256 hex digest

    def test_optional_fields_passed_through(self):
        cmd = build_command(
            "niryo", "robot1", "MOVE_PIECE",
            piece_id="piece-001", source="C1", target="C3",
        )
        assert cmd["piece_id"] == "piece-001"
        assert cmd["source"] == "C1"
        assert cmd["target"] == "C3"


# ── build_ack ─────────────────────────────────────────────────────────────────

class TestBuildAck:
    def test_required_keys_present(self):
        ack = build_ack("CMD-001", "niryo", "robot1", accepted=True)
        assert _REQUIRED_ACK_KEYS.issubset(ack.keys())

    def test_schema_is_ack(self):
        ack = build_ack("CMD-001", "niryo", "robot1", accepted=True)
        assert ack["schema"] == "shipyard.pnp.ack.v1"

    def test_default_sender_id(self):
        ack = build_ack("CMD-001", "niryo", "robot1", accepted=True)
        assert ack["sender_id"] == "niryo_vendor_supervisor"

    def test_accepted_false(self):
        ack = build_ack("CMD-001", "niryo", "robot1", accepted=False, reason="busy")
        assert ack["accepted"] is False
        assert ack["reason"] == "busy"

    def test_command_id_preserved(self):
        ack = build_ack("CMD-XYZ", "niryo", "robot1", accepted=True)
        assert ack["command_id"] == "CMD-XYZ"


# ── build_status ──────────────────────────────────────────────────────────────

class TestBuildStatus:
    def test_required_keys_present(self):
        s = build_status("CMD-001", "niryo", "robot1", "MOVE_PIECE", "COMPLETED", "IDLE")
        assert _REQUIRED_STATUS_KEYS.issubset(s.keys())

    def test_schema_is_status(self):
        s = build_status("CMD-001", "niryo", "robot1", "MOVE_PIECE", "COMPLETED", "IDLE")
        assert s["schema"] == "shipyard.pnp.status.v1"

    def test_task_state_set(self):
        s = build_status("CMD-001", "niryo", "robot1", "MOVE_PIECE", "FAILED", "ERROR")
        assert s["task_state"] == "FAILED"
        assert s["resource_state"] == "ERROR"


# ── HMAC sign / verify ────────────────────────────────────────────────────────

class TestHmac:
    def _signed_cmd(self) -> dict:
        cmd = build_command("niryo", "robot1", "MOVE_PIECE")
        cmd["auth"] = sign_message(cmd, _SECRET)
        return cmd

    def test_verify_valid_signature(self):
        cmd = self._signed_cmd()
        assert verify_message(cmd, _SECRET) is True

    def test_reject_wrong_secret(self):
        cmd = self._signed_cmd()
        assert verify_message(cmd, _ALT_SECRET) is False

    def test_reject_empty_auth(self):
        cmd = build_command("niryo", "robot1", "T")
        assert verify_message(cmd, _SECRET) is False

    def test_reject_forged_auth(self):
        cmd = self._signed_cmd()
        cmd["auth"] = "de" * 32
        assert verify_message(cmd, _SECRET) is False

    def test_reject_tampered_payload(self):
        cmd = self._signed_cmd()
        cmd["task"] = "INJECTED_TASK"
        assert verify_message(cmd, _SECRET) is False

    def test_build_command_with_secret_verifies(self):
        cmd = build_command("niryo", "robot1", "MOVE_PIECE", secret=_SECRET)
        assert verify_message(cmd, _SECRET) is True


# ── JSON serialisation ────────────────────────────────────────────────────────

class TestJsonSerialisation:
    def test_to_json_roundtrip(self):
        cmd = build_command("niryo", "robot1", "MOVE_PIECE")
        raw = to_json(cmd)
        restored = parse_json(raw)
        assert restored == cmd

    def test_to_json_is_string(self):
        assert isinstance(to_json({"key": "val"}), str)

    def test_parse_json_is_dict(self):
        assert isinstance(parse_json('{"k": 1}'), dict)
