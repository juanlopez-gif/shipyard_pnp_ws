"""
Unit tests for shared/topic_acl.py and config/topic_acl.yaml.

Validates that the ACL graph correctly expresses the three-topic contract:
  factory_supervisor → /{vendor}_factory/command → vendor_supervisor
  vendor_supervisor  → /{vendor}_factory/ack     → factory_supervisor
  vendor_supervisor  → /{vendor}_factory/status  → factory_supervisor
"""

import pytest

from shipyard_pnp.shared import topic_acl
from shipyard_pnp.shared.contracts import DomainId

_DOMAINS = [d.value for d in DomainId]


@pytest.fixture(autouse=True)
def fresh_acl():
    """Reload the real ACL file before every test."""
    topic_acl.reset()
    yield
    topic_acl.reset()


# ── Structural ────────────────────────────────────────────────────────────────

def test_acl_loads():
    acl = topic_acl.load()
    assert acl is not None
    assert "nodes" in acl


def test_all_vendor_nodes_in_acl():
    node_ids = topic_acl.all_node_ids()
    for domain in _DOMAINS:
        supervisor = f"{domain}_vendor_supervisor"
        assert supervisor in node_ids, f"'{supervisor}' missing from ACL"


def test_factory_supervisor_in_acl():
    assert "factory_supervisor" in topic_acl.all_node_ids()


# ── factory_supervisor publishes only commands ────────────────────────────────

def test_factory_supervisor_publishes_only_commands_and_system_state():
    allowed = set(topic_acl.get_allowed_publishes("factory_supervisor"))
    command_topics = {f"/{d}_factory/command" for d in _DOMAINS}
    unexpected = allowed - command_topics - {"/factory/system_state"}
    assert not unexpected, f"factory_supervisor has unexpected publish topics: {unexpected}"


def test_factory_supervisor_can_publish_all_command_topics():
    for domain in _DOMAINS:
        topic = f"/{domain}_factory/command"
        assert topic_acl.check_publish("factory_supervisor", topic), (
            f"factory_supervisor cannot publish to '{topic}'"
        )


def test_factory_supervisor_cannot_publish_ack_topics():
    for domain in _DOMAINS:
        topic = f"/{domain}_factory/ack"
        assert not topic_acl.check_publish("factory_supervisor", topic), (
            f"factory_supervisor should NOT publish to '{topic}'"
        )


def test_factory_supervisor_cannot_publish_status_topics():
    for domain in _DOMAINS:
        topic = f"/{domain}_factory/status"
        assert not topic_acl.check_publish("factory_supervisor", topic), (
            f"factory_supervisor should NOT publish to '{topic}'"
        )


# ── factory_supervisor subscribes only ack + status ──────────────────────────

def test_factory_supervisor_subscribes_only_ack_and_status():
    allowed = set(topic_acl.get_allowed_subscribes("factory_supervisor"))
    expected = (
        {f"/{d}_factory/ack" for d in _DOMAINS}
        | {f"/{d}_factory/status" for d in _DOMAINS}
    )
    assert allowed == expected, (
        f"Unexpected subscribe diff: extra={allowed - expected}, missing={expected - allowed}"
    )


# ── Vendor supervisors ────────────────────────────────────────────────────────

@pytest.mark.parametrize("domain", _DOMAINS)
def test_vendor_subscribes_only_its_own_command(domain):
    supervisor = f"{domain}_vendor_supervisor"
    subs = set(topic_acl.get_allowed_subscribes(supervisor))
    assert subs == {f"/{domain}_factory/command"}, (
        f"{supervisor} should subscribe only to /{domain}_factory/command, got {subs}"
    )


@pytest.mark.parametrize("domain", _DOMAINS)
def test_vendor_publishes_only_ack_and_status(domain):
    supervisor = f"{domain}_vendor_supervisor"
    pubs = set(topic_acl.get_allowed_publishes(supervisor))
    expected = {f"/{domain}_factory/ack", f"/{domain}_factory/status"}
    assert pubs == expected, (
        f"{supervisor} publishes {pubs}, expected {expected}"
    )


@pytest.mark.parametrize("domain", _DOMAINS)
def test_vendor_cannot_publish_commands(domain):
    supervisor = f"{domain}_vendor_supervisor"
    for other in _DOMAINS:
        topic = f"/{other}_factory/command"
        assert not topic_acl.check_publish(supervisor, topic), (
            f"{supervisor} should NOT be able to publish to '{topic}'"
        )


# ── No vendor-to-vendor direct communication ─────────────────────────────────

def test_no_vendor_to_vendor_direct_publish():
    """No vendor supervisor may publish directly to another vendor's topics."""
    for src_domain in _DOMAINS:
        supervisor = f"{src_domain}_vendor_supervisor"
        for dst_domain in _DOMAINS:
            if src_domain == dst_domain:
                continue
            for suffix in ("command", "ack", "status"):
                topic = f"/{dst_domain}_factory/{suffix}"
                assert not topic_acl.check_publish(supervisor, topic), (
                    f"{supervisor} should NOT publish to '{topic}'"
                )


# ── Graph consistency ─────────────────────────────────────────────────────────

def test_acl_graph_is_consistent():
    violations = topic_acl.verify_graph()
    assert not violations, "ACL graph has dangling topics:\n" + "\n".join(violations)


# ── Cross-check: internal topics must not appear as boundary topics ───────────

_INTERNAL_TOPICS = [
    "/robot1/command", "/robot2/command",
    "/xarm1/set_servo_angle", "/laser/private",
    "/bantam/gcode", "/serial_bytes",
]


@pytest.mark.parametrize("topic", _INTERNAL_TOPICS)
def test_internal_topics_not_in_acl(topic):
    for node_id in topic_acl.all_node_ids():
        assert not topic_acl.check_publish(node_id, topic), (
            f"Internal topic '{topic}' found in publish ACL for '{node_id}'"
        )
        assert not topic_acl.check_subscribe(node_id, topic), (
            f"Internal topic '{topic}' found in subscribe ACL for '{node_id}'"
        )
