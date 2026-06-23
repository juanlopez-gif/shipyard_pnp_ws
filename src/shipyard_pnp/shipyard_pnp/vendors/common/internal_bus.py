import threading
from collections import defaultdict
from typing import Callable, Dict, List


class InternalBus:
    """
    Lightweight in-process pub/sub for adapter ↔ VS communication.
    No network, no serialization, no ROS2. Pure Python.
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[dict], None]]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, callback: Callable[[dict], None]) -> None:
        with self._lock:
            self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable[[dict], None]) -> None:
        with self._lock:
            subs = self._subscribers.get(event_type, [])
            try:
                subs.remove(callback)
            except ValueError:
                pass

    def publish(self, event_type: str, payload: dict) -> None:
        with self._lock:
            callbacks = list(self._subscribers.get(event_type, []))
        for cb in callbacks:
            try:
                cb(payload)
            except Exception as exc:
                print(f"[InternalBus] handler error for '{event_type}': {exc}")

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()
