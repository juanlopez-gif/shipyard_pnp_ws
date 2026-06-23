"""
Session-wide pytest fixtures for the shipyard_pnp test suite.

Pre-loads the ACL YAML once before any test runs so that the first
check_outbound() call in timing tests is not penalized by cold YAML I/O.
"""
import pytest
from shipyard_pnp.shared import topic_acl


def pytest_configure(config):
    topic_acl.reset()
    topic_acl.load()
