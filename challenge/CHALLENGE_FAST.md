# Challenge: Thread-Safe Weighted Sliding Window Rate Limiter (Demo Fast Mode)

Build a Python rate limiter using the **sliding window** algorithm, with
weighted costs and thread-safety. This is the demo-fast variant of the full
spec — it keeps the parts that give the reviewer agent real work
(concurrency, weighted accounting) and drops the larger surface area
(`snapshot`, `time_until_allowed`, stale eviction).

## API

Implement a `RateLimiter` class in `src/rate_limiter.py`:

```python
RateLimiter(max_requests: int, window_seconds: float)
allow_request(client_id: str, cost: int = 1) -> bool
```

## Functional Requirements

1. **Sliding window** — requests older than `window_seconds` expire
   continuously, not on fixed buckets.
2. **Weighted cost** — a request consumes `cost` units (default `1`).
   Allowed iff `used_in_window + cost <= max_requests`.
3. **Per-client isolation** — one client hitting its limit must not
   affect any other client.
4. **Thread-safe** — `allow_request` may be called concurrently from
   multiple threads. The total units granted in any window must never
   exceed `max_requests`.

## Edge Cases (the reviewer must catch all of these)

- `max_requests <= 0` → `ValueError`
- `window_seconds <= 0` → `ValueError`
- `cost <= 0` → `ValueError`
- `cost > max_requests` → `ValueError`
- Two requests whose combined cost exceeds `max_requests` — second denied
- Request at exactly `(now - window_seconds)` is treated as expired
- Concurrent threads never grant more than `max_requests` units per window

## Tests

- Write tests in `src/test_rate_limiter.py` covering every requirement.
- Include at least one threaded test (use `threading.Barrier` for real
  contention) asserting total grants ≤ `max_requests`.
- Target **≥ 80% line coverage**.

## Files to Create

```
src/
├── rate_limiter.py
├── test_rate_limiter.py
└── __init__.py
```

## Run Tests

```bash
pytest src/test_rate_limiter.py -v --tb=short --cov=src --cov-report=json
```
