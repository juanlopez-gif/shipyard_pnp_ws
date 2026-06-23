"""
AclGuard — enforces the three-topic contract boundary.

Check order (first failing gate terminates early, determines rejection_reason):
  1. Token presence   → NO_TOKEN             (only when secret + enforce_hmac=True)
  2. HMAC integrity   → BAD_HMAC             (only when secret + enforce_hmac=True)
  3. Topic ACL        → SENDER_NOT_AUTHORIZED (check_publish for sender on topic)
  4. Boundary keys    → PROPRIETARY_FIELD     (forbidden keys present in payload)

Gate 3 uses the sender's publish-allowlist from topic_acl.yaml.  For gate 3 to
pass when the topic IS in the sender's allowlist (e.g. niryo_vendor_supervisor
publishing to /niryo_factory/status), gate 4 then catches any proprietary data
embedded in the payload — this covers Experiment 1c and 1d (Theorem 3).
"""

import time
from dataclasses import dataclass
from typing import Optional

from .messages import validate_boundary, verify_message
from .topic_acl import check_publish


@dataclass
class AclDecision:
    allowed: bool
    acted_upon: bool            # True only when allowed=True
    rejection_reason: Optional[str]  # None when allowed
    acl_latency_us: float


def check_outbound(
    sender_id: str,
    topic: str,
    payload: dict,
    *,
    secret: Optional[str] = None,
    enforce_hmac: bool = False,
) -> AclDecision:
    """
    Gate check executed before a node publishes *payload* to *topic*.

    Args:
        sender_id:    The node claiming to publish (e.g. "bantam_vendor_probe").
        topic:        Destination topic (e.g. "/niryo_factory/command").
        payload:      Message dict that would be sent.
        secret:       HMAC shared secret. None disables auth gates entirely.
        enforce_hmac: When True and secret is set, NO_TOKEN / BAD_HMAC hard-reject.
                      When False (default), HMAC is not checked here — suitable for
                      cases where ACL or boundary keys are the intended gate.

    Returns:
        AclDecision with allowed=True only if all gates pass.
    """
    t0 = time.perf_counter()

    if secret and enforce_hmac:
        # Gate 1: token presence
        if not payload.get("auth", ""):
            return AclDecision(False, False, "NO_TOKEN", _elapsed_us(t0))
        # Gate 2: HMAC integrity
        if not verify_message(payload, secret):
            return AclDecision(False, False, "BAD_HMAC", _elapsed_us(t0))

    # Gate 3: topic ACL — is sender allowed to publish to this topic?
    if not check_publish(sender_id, topic):
        return AclDecision(False, False, "SENDER_NOT_AUTHORIZED", _elapsed_us(t0))

    # Gate 4: proprietary boundary key check
    try:
        validate_boundary(payload)
    except ValueError:
        return AclDecision(False, False, "PROPRIETARY_FIELD", _elapsed_us(t0))

    return AclDecision(True, True, None, _elapsed_us(t0))


def check_inbound(
    receiver_id: str,
    topic: str,
    payload: dict,
    *,
    secret: Optional[str] = None,
    enforce_hmac: bool = False,
) -> AclDecision:
    """
    Gate check executed when a node receives *payload* from *topic*.

    Mirrors check_outbound but uses the receiver's subscribe-allowlist (gate 3).
    Useful for validating that a subscriber is actually entitled to receive
    messages on a given topic.
    """
    from .topic_acl import check_subscribe

    t0 = time.perf_counter()

    if secret and enforce_hmac:
        if not payload.get("auth", ""):
            return AclDecision(False, False, "NO_TOKEN", _elapsed_us(t0))
        if not verify_message(payload, secret):
            return AclDecision(False, False, "BAD_HMAC", _elapsed_us(t0))

    if not check_subscribe(receiver_id, topic):
        return AclDecision(False, False, "RECEIVER_NOT_AUTHORIZED", _elapsed_us(t0))

    try:
        validate_boundary(payload)
    except ValueError:
        return AclDecision(False, False, "PROPRIETARY_FIELD", _elapsed_us(t0))

    return AclDecision(True, True, None, _elapsed_us(t0))


def _elapsed_us(t0: float) -> float:
    return (time.perf_counter() - t0) * 1_000_000
