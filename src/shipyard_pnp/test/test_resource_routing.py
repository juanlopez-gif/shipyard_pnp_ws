"""
Unit tests for domain/resource routing logic in shared/contracts.py.

Validates that:
  - DOMAIN_COMMAND_TOPIC / DOMAIN_ACK_TOPIC / DOMAIN_STATUS_TOPIC map correctly
  - Every resource_id is reachable through exactly one domain
  - Key resources belong to the expected domains (not cross-domain)
"""

import pytest

from shipyard_pnp.shared.contracts import (
    DOMAIN_ACK_TOPIC,
    DOMAIN_COMMAND_TOPIC,
    DOMAIN_IDS,
    DOMAIN_STATUS_TOPIC,
    DomainId,
    ResourceId,
)


# ── Topic derivation ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("domain", DOMAIN_IDS)
def test_command_topic_format(domain):
    assert DOMAIN_COMMAND_TOPIC[domain] == f"/{domain}_factory/command"


@pytest.mark.parametrize("domain", DOMAIN_IDS)
def test_ack_topic_format(domain):
    assert DOMAIN_ACK_TOPIC[domain] == f"/{domain}_factory/ack"


@pytest.mark.parametrize("domain", DOMAIN_IDS)
def test_status_topic_format(domain):
    assert DOMAIN_STATUS_TOPIC[domain] == f"/{domain}_factory/status"


def test_all_seven_domains_present():
    expected = {
        "niryo", "ufactory", "laser", "globalvision",
        "green_conveyors", "arduino_vacuum", "bantam",
    }
    assert set(DOMAIN_IDS) == expected


# ── ResourceId enum coverage ──────────────────────────────────────────────────

def test_resource_id_enum_has_robot1():
    assert ResourceId.ROBOT1 == "robot1"


def test_resource_id_enum_has_robot2():
    assert ResourceId.ROBOT2 == "robot2"


def test_resource_id_enum_has_xarm1():
    assert ResourceId.XARM1 == "xarm1"


def test_resource_id_enum_has_xarm2():
    assert ResourceId.XARM2 == "xarm2"


def test_resource_id_enum_has_arduino_vacuum():
    assert ResourceId.ARDUINO_VACUUM == "arduino_vacuum"


def test_resource_id_enum_has_bantam_door():
    assert ResourceId.BANTAM_DOOR == "bantam_door"


# ── Domain / resource ownership (cross-check with vendor_registry.yaml) ───────
# These tests document intended ownership at the contract level.

import os
import yaml

_REGISTRY_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "config", "vendor_registry.yaml")
)


@pytest.fixture(scope="module")
def registry():
    with open(_REGISTRY_PATH) as fh:
        return yaml.safe_load(fh)


def _resources_in_domain(registry: dict, domain: str) -> set:
    return set(registry["domains"][domain]["resources"].keys())


def test_robot1_belongs_to_niryo(registry):
    assert "robot1" in _resources_in_domain(registry, "niryo")


def test_robot2_belongs_to_niryo(registry):
    assert "robot2" in _resources_in_domain(registry, "niryo")


def test_xarm1_belongs_to_ufactory(registry):
    assert "xarm1" in _resources_in_domain(registry, "ufactory")


def test_xarm2_belongs_to_ufactory(registry):
    assert "xarm2" in _resources_in_domain(registry, "ufactory")


def test_arduino_vacuum_not_in_niryo(registry):
    """The Arduino vacuum belongs to its own domain, not to the Niryo domain."""
    assert "arduino_vacuum" not in _resources_in_domain(registry, "niryo")


def test_arduino_vacuum_in_arduino_vacuum_domain(registry):
    assert "arduino_vacuum" in _resources_in_domain(registry, "arduino_vacuum")


def test_laser_in_laser_domain(registry):
    assert "laser" in _resources_in_domain(registry, "laser")


def test_bantam_not_in_niryo(registry):
    assert "bantam" not in _resources_in_domain(registry, "niryo")


def test_bantam_in_bantam_domain(registry):
    assert "bantam" in _resources_in_domain(registry, "bantam")


# ── factory_supervisor does not use domain-internal resource IDs ──────────────

def test_factory_supervisor_routes_by_domain_not_resource():
    """
    The factory_supervisor needs only domain_id to route a command.
    The topic format is /{domain}_factory/command — derived solely from domain_id.
    Resource IDs (robot1, xarm1, bantam_door…) stay inside the vendor domain.
    """
    for domain in DOMAIN_IDS:
        topic = DOMAIN_COMMAND_TOPIC[domain]
        # Topic is fully determined by domain_id alone
        assert topic == f"/{domain}_factory/command"
        # Topic ends in /command, never in a resource-specific leaf
        resource_leaves = [
            "/robot1", "/robot2", "/xarm1", "/xarm2",
            "/conveyor1", "/conveyor2", "/bantam_door",
            "/globalvision_camera",  # arduino_vacuum & bantam share name with domain — excluded
        ]
        for leaf in resource_leaves:
            assert not topic.endswith(leaf), (
                f"Topic '{topic}' ends with resource-specific leaf '{leaf}'"
            )
