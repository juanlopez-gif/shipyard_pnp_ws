import os
import threading
from datetime import datetime, timezone

_seq_lock = threading.Lock()
_seq_counter = 0


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def make_nonce() -> str:
    return os.urandom(16).hex()


def make_command_id(domain_id: str, resource_id: str) -> str:
    global _seq_counter
    with _seq_lock:
        _seq_counter += 1
        seq = _seq_counter
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "Z"
    return f"CMD-{domain_id}-{resource_id}-{ts}-{seq:06d}"


def reset_seq():
    global _seq_counter
    with _seq_lock:
        _seq_counter = 0
