import threading
import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: float):
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._requests: dict[str, list[tuple[float, int]]] = defaultdict(list)
        self._global_lock = threading.Lock()

    def _get_lock(self, client_id: str) -> threading.Lock:
        with self._global_lock:
            return self._locks[client_id]

    def allow_request(self, client_id: str, cost: int = 1) -> bool:
        if cost <= 0:
            raise ValueError("cost must be positive")
        if cost > self.max_requests:
            raise ValueError("cost exceeds max_requests")

        lock = self._get_lock(client_id)
        with lock:
            now = time.monotonic()
            cutoff = now - self.window_seconds

            # Evict expired entries (strictly greater than window age)
            entries = self._requests[client_id]
            self._requests[client_id] = [
                (ts, c) for ts, c in entries if ts > cutoff
            ]

            used = sum(c for _, c in self._requests[client_id])

            if used + cost <= self.max_requests:
                self._requests[client_id].append((now, cost))
                return True
            return False
