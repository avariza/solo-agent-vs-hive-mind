# Challenge: Weighted Sliding Window Rate Limiter

Build a production-grade Python rate limiter using the **sliding window** algorithm.
This is intentionally more than a textbook deque — it must handle weighted costs,
concurrent callers, and bounded memory.

## API

Implement a `RateLimiter` class in `src/rate_limiter.py` with:

```python
RateLimiter(max_requests: int, window_seconds: float)

allow_request(client_id: str, cost: int = 1) -> bool
time_until_allowed(client_id: str, cost: int = 1) -> float
snapshot(client_id: str) -> dict  # {"used": int, "remaining": int, "reset_in": float}
```

## Functional Requirements

1. **Sliding window** — requests older than `window_seconds` expire continuously,
   not on fixed buckets.
2. **Weighted cost** — each request can consume `cost` units (default `1`).
   A request is allowed iff `used_in_window + cost <= max_requests`.
3. **`time_until_allowed`** — returns the number of seconds until a request of
   the given `cost` would be allowed. Returns `0.0` when it is currently allowed.
4. **Per-client isolation** — one client hitting its limit must not affect any
   other client.
5. **Thread-safe** — `allow_request` may be called concurrently from multiple
   threads. Under contention, the total number of units granted in any window
   must never exceed `max_requests`.
6. **Bounded memory** — a client that has not been seen for more than
   `2 * window_seconds` MUST be evicted from internal state. `snapshot` on an
   evicted/unknown client returns `{"used": 0, "remaining": max_requests, "reset_in": 0.0}`.

## Edge Cases (the reviewer must catch all of these)

- `max_requests <= 0` → `ValueError`
- `window_seconds <= 0` → `ValueError`
- `cost <= 0` on any call → `ValueError`
- `cost > max_requests` on any call → `ValueError` (impossible to ever satisfy)
- Two requests whose combined cost exceeds `max_requests` — second must be denied
- Request timestamped exactly at `(now - window_seconds)` is treated as expired
- Client that pauses > window and resumes — full quota restored
- Concurrent threads never grant more than `max_requests` units per window
- Long-idle clients are dropped from memory within `2 * window_seconds`

## Tests

- Write tests in `src/test_rate_limiter.py` covering every requirement above.
- Include at least one test that spawns threads (use `threading.Barrier` to
  force genuine contention) and asserts the total grants never exceed the cap.
- Include at least one test that asserts stale clients are evicted.
- Target **≥ 80% line coverage**.

## Files to Create

```
src/
├── rate_limiter.py        # Implementation
├── test_rate_limiter.py   # Tests
└── __init__.py            # Package init (export RateLimiter)
```

## Run Tests

```bash
pytest src/test_rate_limiter.py -v --tb=short --cov=src --cov-report=json
```
