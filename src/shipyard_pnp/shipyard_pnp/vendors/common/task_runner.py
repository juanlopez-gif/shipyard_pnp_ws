import threading
from typing import Callable, Optional


class TaskRunner:
    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def run(
        self,
        task_fn: Callable[[], dict],
        on_complete: Callable[[dict], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        if self.is_running():
            raise RuntimeError("TaskRunner already busy — caller must check is_running() first")

        def _wrapper():
            try:
                result = task_fn()
                on_complete(result)
            except Exception as exc:
                on_error(exc)
            finally:
                with self._lock:
                    self._thread = None

        with self._lock:
            self._thread = threading.Thread(target=_wrapper, daemon=True)
            self._thread.start()

    def join(self, timeout: Optional[float] = None) -> None:
        with self._lock:
            t = self._thread
        if t is not None:
            t.join(timeout=timeout)
