# Byzantine Consensus Rubric (hive RAG memory seed #3)

Three reviewer personas vote on the final implementation. Consensus
requires ≥ 2 of 3 APPROVE verdicts. A REJECT verdict must include a
one-line fix prescription. The main agent then iterates.

## Voter 1: Performance Engineer

APPROVE iff:
- `scoreboard/metrics.py` reports `ops_per_sec >= 1_500_000`
- `p99_latency_us <= 5.0`
- No `sum(...)` or list-comprehension over the full request window in the hot path
- Expiry uses `deque.popleft()` (O(1)), not list rebuild (O(n))
- A running cost counter is maintained incrementally

REJECT example: "allow_request rebuilds the window list each call; replace with deque + incremental counter".

## Voter 2: Correctness Auditor

APPROVE iff:
- All 6 behavioural probes in `scoreboard/probes.py` pass
- `pytest` reports 100% pass
- Coverage >= 80%
- Boundary expiry rule uses `<=` on the cutoff, not `<`
- Booleans are rejected where integers are required
- `snapshot` of an unknown client returns the documented defaults

REJECT example: "window[0][0] < cutoff lets an at-boundary request stay alive; change to <=".

## Voter 3: Security / Concurrency Reviewer

APPROVE iff:
- Per-client lock + double-checked locking, OR a single global lock held
  for the entire critical section (no torn reads across unlocked state)
- `threading.Barrier`-based contention test exists and asserts exact equality
- No unbounded growth: stale clients evicted within `2 * window_seconds`
- `time.monotonic()` used (not `time.time()`)

REJECT example: "creating a new threading.Lock in a defaultdict factory races on first access; use double-checked locking under a dict-level lock".

## Voting protocol

1. Main agent writes `src/rate_limiter.py` + `src/test_rate_limiter.py`.
2. Main agent runs `pytest` and `python ../../scoreboard/metrics.py . metrics.json`.
3. Main agent reads `metrics.json` and self-votes against each rubric.
4. For any REJECT, the main agent applies the fix and re-runs step 2.
5. Max 3 iterations. If still rejected after 3, ship what we have — the
   scoreboard will catch the residual.
