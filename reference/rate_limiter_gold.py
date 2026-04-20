"""Reference rate limiter — seeded into hive's RAG memory.

Retrieved via `ruflo memory search` before the hive writes code. Encodes
the taste we want the hive to adopt; the hive still authors its own code.

Design principles (why this beats a naive impl):

1. ONE dict lookup per call: client state is a single 3-element list
   `[deque, used, last_seen]`, not parallel `dict[id]->deque` +
   `dict[id]->cost` dicts. Halves dict traffic on the hot path.

2. O(1) expiry: `deque.popleft()` + incrementally maintained `used`
   counter. Never `sum()` the window, never rebuild the list.

3. Single global lock with a tight critical section. Python's GIL
   makes per-client locks pure overhead for CPU-bound work — they only
   help with IO, which this has none of.

4. `time.monotonic()` (not `time.time()`) — stable across NTP adjust.

5. Strict bool rejection in validators: `isinstance(True, int) is True`
   in Python, so a naive type check accepts booleans. The probe suite
   tests for this.

6. Full spec: implements `allow_request`, `time_until_allowed`, AND
   `snapshot`. Skipping the latter two is a spec violation even if
   nothing tests it directly — senior reviewers flag incomplete APIs.

Targets (enforced by the self-verification loop in scripts/hive.sh):
- ops_per_sec >= 500,000  (scoreboard caps here anyway)
- max cyclomatic complexity <= 5
- all 6 behavioural probes pass
- implementation <= ~80 lines
"""
from __future__ import annotations

import threading
import time
from collections import deque


def _bad_int(x) -> bool:
    return isinstance(x, bool) or not isinstance(x, int) or x <= 0


class RateLimiter:
    """Thread-safe weighted sliding-window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        if _bad_int(max_requests):
            raise ValueError("max_requests must be a positive integer")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max = max_requests
        self._win = float(window_seconds)
        self._clients: dict[str, list] = {}
        self._lock = threading.Lock()

    def _prune(self, st: list, cutoff: float) -> None:
        w = st[0]
        while w and w[0][0] <= cutoff:
            st[1] -= w.popleft()[1]

    def _check_cost(self, cost: int) -> None:
        if _bad_int(cost):
            raise ValueError("cost must be a positive integer")
        if cost > self._max:
            raise ValueError("cost cannot exceed max_requests")

    def allow_request(self, client_id: str, cost: int = 1) -> bool:
        self._check_cost(cost)
        now = time.monotonic()
        with self._lock:
            st = self._clients.get(client_id) or self._clients.setdefault(
                client_id, [deque(), 0, now]
            )
            self._prune(st, now - self._win)
            st[2] = now
            if st[1] + cost <= self._max:
                st[0].append((now, cost))
                st[1] += cost
                return True
            return False

    def time_until_allowed(self, client_id: str, cost: int = 1) -> float:
        self._check_cost(cost)
        now = time.monotonic()
        with self._lock:
            st = self._clients.get(client_id)
            if st is None:
                return 0.0
            self._prune(st, now - self._win)
            if st[1] + cost <= self._max:
                return 0.0
            running = st[1]
            for ts, c in st[0]:
                running -= c
                if running + cost <= self._max:
                    return max(0.0, ts + self._win - now)
            return 0.0

    def snapshot(self, client_id: str) -> dict:
        now = time.monotonic()
        with self._lock:
            stale = now - 2 * self._win
            for cid in [c for c, s in self._clients.items() if s[2] <= stale]:
                del self._clients[cid]
            st = self._clients.get(client_id)
            if st is None:
                return {"used": 0, "remaining": self._max, "reset_in": 0.0}
            self._prune(st, now - self._win)
            reset = (st[0][0][0] + self._win - now) if st[0] else 0.0
            return {"used": st[1], "remaining": self._max - st[1], "reset_in": max(0.0, reset)}
