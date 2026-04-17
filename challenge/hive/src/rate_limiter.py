import threading
import time
from collections import defaultdict


class RateLimiter:
    """Thread-safe weighted sliding window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        if not isinstance(max_requests, int) or max_requests <= 0:
            raise ValueError("max_requests must be a positive integer")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        self._max_requests = max_requests
        self._window_seconds = window_seconds
        # Per-client: list of (timestamp, cost) tuples
        self._requests: dict[str, list[tuple[float, int]]] = defaultdict(list)
        # Per-client lock to ensure thread-safety without global contention
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        # Guard for creating per-client locks atomically
        self._global_lock = threading.Lock()

    def _get_client_lock(self, client_id: str) -> threading.Lock:
        """Get or create a per-client lock atomically."""
        if client_id not in self._locks:
            with self._global_lock:
                # Double-check after acquiring global lock
                if client_id not in self._locks:
                    self._locks[client_id] = threading.Lock()
        return self._locks[client_id]

    def allow_request(self, client_id: str, cost: int = 1) -> bool:
        """Attempt to record a request. Returns True if allowed."""
        if not isinstance(cost, int) or cost <= 0:
            raise ValueError("cost must be a positive integer")
        if cost > self._max_requests:
            raise ValueError("cost cannot exceed max_requests")

        lock = self._get_client_lock(client_id)
        with lock:
            now = time.monotonic()
            cutoff = now - self._window_seconds

            # Evict expired entries (strictly <= cutoff means "at exactly
            # window_seconds ago" is expired)
            entries = self._requests[client_id]
            self._requests[client_id] = [
                (ts, c) for ts, c in entries if ts > cutoff
            ]

            # Sum current usage
            current_usage = sum(c for _, c in self._requests[client_id])

            if current_usage + cost <= self._max_requests:
                self._requests[client_id].append((now, cost))
                return True
            return False
