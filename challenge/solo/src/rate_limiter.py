import threading
import time
from collections import deque


class RateLimiter:
    """Thread-safe weighted sliding window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        if not isinstance(max_requests, int) or max_requests <= 0:
            raise ValueError("max_requests must be a positive integer")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._clients: dict[str, deque[tuple[float, int]]] = {}
        self._client_costs: dict[str, int] = {}
        self._lock = threading.Lock()

    def allow_request(self, client_id: str, cost: int = 1) -> bool:
        if not isinstance(cost, int) or cost <= 0:
            raise ValueError("cost must be a positive integer")
        if cost > self._max_requests:
            raise ValueError("cost cannot exceed max_requests")

        now = time.monotonic()
        cutoff = now - self._window_seconds

        with self._lock:
            if client_id not in self._clients:
                self._clients[client_id] = deque()
                self._client_costs[client_id] = 0

            window = self._clients[client_id]

            # Evict expired entries (strictly <= cutoff, i.e. exactly at boundary is expired)
            while window and window[0][0] <= cutoff:
                _, expired_cost = window.popleft()
                self._client_costs[client_id] -= expired_cost

            current_cost = self._client_costs[client_id]

            if current_cost + cost <= self._max_requests:
                window.append((now, cost))
                self._client_costs[client_id] += cost
                return True

            return False
