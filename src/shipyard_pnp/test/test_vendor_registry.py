"""
Unit tests for config/vendor_registry.yaml.

Validates that the registry is structurally sound and satisfies the
three-topic contract requirements (every domain maps to exactly one
supervisor node and a non-empty set of resources).
"""

import os
import pytest
import yaml


_REGISTRY_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "config", "vendor_registry.yaml")
)

_EXPECTED_DOMAINS = {
    "niryo", "ufactory", "laser", "globalvision",
    "green_conveyors", "arduino_vacuum", "bantam",
}


@pytest.fixture(scope="module")
def registry() -> dict:
    with open(_REGISTRY_PATH) as fh:
        return yaml.safe_load(fh)


def test_registry_loads(registry):
    assert registry is not None


def test_domains_key_exists(registry):
    assert "domains" in registry


def test_all_expected_domains_present(registry):
    present = set(registry["domains"].keys())
    assert _EXPECTED_DOMAINS == present, (
        f"Missing: {_EXPECTED_DOMAINS - present}  Extra: {present - _EXPECTED_DOMAINS}"
    )


def test_each_domain_has_supervisor_node(registry):
    for domain, cfg in registry["domains"].items():
        assert "supervisor_node" in cfg, f"Domain '{domain}' missing supervisor_node"
        assert cfg["supervisor_node"], f"Domain '{domain}' supervisor_node is empty"


def test_each_domain_has_resources(registry):
    for domain, cfg in registry["domains"].items():
        assert "resources" in cfg, f"Domain '{domain}' missing resources"
        assert cfg["resources"], f"Domain '{domain}' resources is empty"


def test_supervisor_node_naming_convention(registry):
    """Each supervisor_node must be named {domain}_vendor_supervisor."""
    for domain, cfg in registry["domains"].items():
        expected = f"{domain}_vendor_supervisor"
        actual = cfg["supervisor_node"]
        assert actual == expected, (
            f"Domain '{domain}': supervisor_node='{actual}', expected='{expected}'"
        )


def test_no_duplicate_resource_across_domains(registry):
    seen: dict[str, str] = {}
    for domain, cfg in registry["domains"].items():
        for resource_id in cfg.get("resources", {}):
            if resource_id in seen:
                pytest.fail(
                    f"Resource '{resource_id}' appears in both "
                    f"'{seen[resource_id]}' and '{domain}'"
                )
            seen[resource_id] = domain


def test_each_domain_maps_to_three_topic_prefix(registry):
    """Every domain must be able to derive its three boundary topics."""
    for domain in registry["domains"]:
        cmd = f"/{domain}_factory/command"
        ack = f"/{domain}_factory/ack"
        status = f"/{domain}_factory/status"
        for topic in (cmd, ack, status):
            assert topic.startswith(f"/{domain}_factory/"), (
                f"Domain '{domain}' cannot derive topic '{topic}'"
            )


def test_niryo_specific_resources(registry):
    niryo = registry["domains"]["niryo"]["resources"]
    assert "robot1" in niryo
    assert "robot2" in niryo
    assert "conveyor1" in niryo
    assert "conveyor2" in niryo


def test_ufactory_specific_resources(registry):
    uf = registry["domains"]["ufactory"]["resources"]
    assert "xarm1" in uf
    assert "xarm2" in uf


def test_bantam_has_door_resource(registry):
    bantam = registry["domains"]["bantam"]["resources"]
    assert "bantam" in bantam
    assert "bantam_door" in bantam


def test_arduino_vacuum_is_separate_domain(registry):
    """arduino_vacuum must be its own domain, not inside niryo."""
    niryo_resources = set(registry["domains"]["niryo"]["resources"].keys())
    assert "arduino_vacuum" not in niryo_resources
    assert "arduino_vacuum" in registry["domains"]
