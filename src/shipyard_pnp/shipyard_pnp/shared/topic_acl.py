import os
from typing import Dict, List, Optional

import yaml

_ACL: Optional[dict] = None
_ACL_PATH: Optional[str] = None

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "config", "topic_acl.yaml",
)


def load(path: Optional[str] = None) -> dict:
    global _ACL, _ACL_PATH
    if path is None:
        try:
            from ament_index_python.packages import get_package_share_directory
            pkg_dir = get_package_share_directory("shipyard_pnp")
            path = os.path.join(pkg_dir, "config", "topic_acl.yaml")
        except Exception:
            path = _DEFAULT_CONFIG_PATH
    path = os.path.normpath(path)
    if _ACL is not None and _ACL_PATH == path:
        return _ACL
    with open(path) as fh:
        _ACL = yaml.safe_load(fh)
    _ACL_PATH = path
    return _ACL


def reset() -> None:
    global _ACL, _ACL_PATH
    _ACL = None
    _ACL_PATH = None


def _node_acl(node_id: str) -> dict:
    acl = load()
    return acl.get("nodes", {}).get(node_id, {})


def check_publish(node_id: str, topic: str) -> bool:
    return topic in _node_acl(node_id).get("publishes", [])


def check_subscribe(node_id: str, topic: str) -> bool:
    return topic in _node_acl(node_id).get("subscribes", [])


def get_allowed_publishes(node_id: str) -> List[str]:
    return list(_node_acl(node_id).get("publishes", []))


def get_allowed_subscribes(node_id: str) -> List[str]:
    return list(_node_acl(node_id).get("subscribes", []))


def all_node_ids() -> List[str]:
    acl = load()
    return list(acl.get("nodes", {}).keys())


def verify_graph() -> List[str]:
    """
    Cross-checks that every topic a node publishes is subscribed to by
    at least one other node, and vice versa. Returns a list of violation
    strings (empty means the graph is consistent).
    """
    acl = load()
    nodes: Dict[str, dict] = acl.get("nodes", {})
    all_published: Dict[str, List[str]] = {}
    all_subscribed: Dict[str, List[str]] = {}
    for node_id, cfg in nodes.items():
        all_published[node_id] = cfg.get("publishes", [])
        all_subscribed[node_id] = cfg.get("subscribes", [])

    violations = []
    for publisher, topics in all_published.items():
        for topic in topics:
            subscribers = [
                n for n, subs in all_subscribed.items() if topic in subs
            ]
            if not subscribers:
                violations.append(
                    f"Topic '{topic}' published by '{publisher}' has no subscribers"
                )
    for subscriber, topics in all_subscribed.items():
        for topic in topics:
            publishers = [
                n for n, pubs in all_published.items() if topic in pubs
            ]
            if not publishers:
                violations.append(
                    f"Topic '{topic}' subscribed by '{subscriber}' has no publisher"
                )
    return violations
