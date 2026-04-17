#!/usr/bin/env python3
"""Behavioral probes for the weighted sliding window rate limiter.

Imports the candidate's RateLimiter and exercises it against 7 hidden
probes covering the enhanced spec (weighted cost, time_until_allowed,
thread safety, stale-client eviction). Each probe measures actual runtime
behavior, so scoring is immune to test naming, wording, or static-text
gaming.

Usage:
    python probes.py <path_to_candidate_dir>

Output:
    JSON on stdout with shape:
    {
      "probes": [{"name": ..., "passed": bool, "errors": [...]}, ...],
      "passed": int,
      "total":  int,
      "error":  str | null
    }

Exit code is always 0 so the Node evaluator can parse results even when
the candidate fails to import or crashes mid-probe.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
import traceback
from typing import Callable


def load_rate_limiter(root_dir: str):
    """Import the candidate's rate_limiter module in isolation."""
    impl_path = os.path.join(root_dir, "src", "rate_limiter.py")
    if not os.path.isfile(impl_path):
        raise FileNotFoundError(impl_path)

    sys.path.insert(0, root_dir)
    spec = importlib.util.spec_from_file_location(
        f"candidate_rate_limiter_{abs(hash(root_dir))}", impl_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {impl_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _expect_value_error(fn, *args, **kwargs) -> str | None:
    """Return None if fn raises ValueError, else an error string."""
    try:
        fn(*args, **kwargs)
    except ValueError:
        return None
    except Exception as exc:
        return f"wrong exception type {type(exc).__name__}: {exc}"
    return "no exception raised"


def probe_invalid_constructor_args(mod) -> list[str]:
    """Constructor must reject non-positive max_requests and window_seconds."""
    RL = mod.RateLimiter
    errors: list[str] = []
    for bad in (0, -1, -100):
        err = _expect_value_error(RL, bad, 1.0)
        if err:
            errors.append(f"max_requests={bad}: {err}")
    for bad in (0, 0.0, -0.5, -50):
        err = _expect_value_error(RL, 1, bad)
        if err:
            errors.append(f"window_seconds={bad}: {err}")
    return errors


def probe_invalid_cost(mod) -> list[str]:
    """allow_request must reject cost <= 0 and cost > max_requests."""
    RL = mod.RateLimiter
    rl = RL(5, 10.0)
    errors: list[str] = []
    for bad in (0, -1, -10):
        err = _expect_value_error(rl.allow_request, "c", bad)
        if err:
            errors.append(f"cost={bad}: {err}")
    err = _expect_value_error(rl.allow_request, "c", 6)
    if err:
        errors.append(f"cost > max_requests (6 vs 5): {err}")
    return errors


def probe_multiple_clients_independent(mod) -> list[str]:
    """Distinct client_ids must be tracked fully independently."""
    RL = mod.RateLimiter
    rl = RL(2, 60.0)
    errors: list[str] = []

    for _ in range(2):
        if not rl.allow_request("alice"):
            errors.append("alice allowed requests wrongly denied")
    if rl.allow_request("alice"):
        errors.append("alice should be blocked at limit")

    if not rl.allow_request("bob"):
        errors.append("bob blocked due to alice (clients not independent)")

    for i in range(20):
        cid = f"probe_client_{i}"
        if not rl.allow_request(cid):
            errors.append(f"{cid} denied (interference across clients)")
            break
    return errors


def probe_sliding_window_expiry(mod) -> list[str]:
    """Requests older than window_seconds must expire (sliding, not fixed)."""
    RL = mod.RateLimiter
    window = 0.15
    rl = RL(2, window)
    errors: list[str] = []

    if not rl.allow_request("c"):
        errors.append("1st request denied")
    if not rl.allow_request("c"):
        errors.append("2nd request denied")
    if rl.allow_request("c"):
        errors.append("3rd request should be denied (at limit)")

    time.sleep(window + 0.08)

    if not rl.allow_request("c"):
        errors.append("request after window should be allowed")
    return errors


def probe_weighted_cost_accounting(mod) -> list[str]:
    """cost parameter must accumulate correctly across requests."""
    RL = mod.RateLimiter
    rl = RL(10, 60.0)
    errors: list[str] = []

    if not rl.allow_request("c", cost=4):
        errors.append("cost=4 on empty window unexpectedly denied")
    if not rl.allow_request("c", cost=4):
        errors.append("cost=4 with 4 used (8 total) unexpectedly denied")
    # 8 used, 10 max -> cost=3 would overflow, must be denied
    if rl.allow_request("c", cost=3):
        errors.append("cost=3 with 8 used (11 total) should be denied")
    # But cost=2 fits exactly
    if not rl.allow_request("c", cost=2):
        errors.append("cost=2 with 8 used (10 total) should be allowed")
    # Now fully saturated
    if rl.allow_request("c", cost=1):
        errors.append("cost=1 at saturation should be denied")
    return errors


def probe_time_until_allowed(mod) -> list[str]:
    """time_until_allowed must be ~0 when allowed, positive when blocked."""
    RL = mod.RateLimiter
    if not hasattr(RL, "time_until_allowed") and not hasattr(RL(1, 1.0), "time_until_allowed"):
        return ["RateLimiter has no time_until_allowed method"]

    rl = RL(2, 0.5)
    errors: list[str] = []

    t0 = rl.time_until_allowed("c")
    if t0 > 0.01:
        errors.append(f"empty client should be immediately allowed, got {t0:.3f}s")

    rl.allow_request("c")
    rl.allow_request("c")

    t_blocked = rl.time_until_allowed("c")
    if t_blocked <= 0:
        errors.append(f"blocked client should return positive wait, got {t_blocked}")
    if t_blocked > 0.6:
        errors.append(f"wait time {t_blocked:.3f}s exceeds window+tolerance (0.5s)")

    time.sleep(t_blocked + 0.05)
    if not rl.allow_request("c"):
        errors.append(
            "after sleeping for the advertised wait, request should be allowed"
        )
    return errors


def probe_thread_safety(mod) -> list[str]:
    """Concurrent allow_request must not grant more than max_requests."""
    RL = mod.RateLimiter
    max_requests = 50
    threads = 16
    attempts_per_thread = 20
    rl = RL(max_requests, 60.0)

    granted = [0]
    lock = threading.Lock()
    barrier = threading.Barrier(threads)
    errors: list[str] = []

    def worker():
        barrier.wait()
        local = 0
        for _ in range(attempts_per_thread):
            if rl.allow_request("shared"):
                local += 1
        with lock:
            granted[0] += local

    ts = [threading.Thread(target=worker) for _ in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=5.0)
        if t.is_alive():
            errors.append("worker thread hung (possible deadlock)")
            return errors

    if granted[0] > max_requests:
        errors.append(
            f"over-granted under contention: {granted[0]} > {max_requests} "
            "(race condition — missing or insufficient locking)"
        )
    if granted[0] < max_requests:
        errors.append(
            f"under-granted under contention: {granted[0]} < {max_requests} "
            "(limiter also losing legitimate requests)"
        )
    return errors


def probe_stale_client_eviction(mod) -> list[str]:
    """Clients idle > 2*window must be dropped from internal state."""
    RL = mod.RateLimiter
    window = 0.1
    rl = RL(5, window)
    errors: list[str] = []

    for i in range(25):
        rl.allow_request(f"ghost_{i}")

    time.sleep(window * 2 + 0.1)

    # Trigger any lazy sweep the implementation may use
    rl.allow_request("live")

    # Preferred contract: snapshot of evicted client returns defaults
    if hasattr(rl, "snapshot"):
        snap = rl.snapshot("ghost_0")
        if not isinstance(snap, dict):
            errors.append(f"snapshot must return dict, got {type(snap).__name__}")
        else:
            if snap.get("used", -1) != 0:
                errors.append(
                    f"evicted client snapshot.used should be 0, got {snap.get('used')}"
                )
            if snap.get("remaining", -1) != 5:
                errors.append(
                    f"evicted client snapshot.remaining should be 5, got {snap.get('remaining')}"
                )
    else:
        errors.append("RateLimiter missing snapshot() method")

    # Fallback structural check: internal dict should not still hold all ghosts
    for attr in ("_clients", "clients", "_buckets", "buckets"):
        store = getattr(rl, attr, None)
        if isinstance(store, dict):
            ghost_count = sum(1 for k in store if str(k).startswith("ghost_"))
            if ghost_count > 5:
                errors.append(
                    f"{ghost_count}/25 stale ghosts still in {attr!r} "
                    "(unbounded memory growth)"
                )
            break
    return errors


ALL_PROBES: list[tuple[str, Callable]] = [
    ("invalid_constructor_args", probe_invalid_constructor_args),
    ("invalid_cost", probe_invalid_cost),
    ("multiple_clients_independent", probe_multiple_clients_independent),
    ("sliding_window_expiry", probe_sliding_window_expiry),
    ("weighted_cost_accounting", probe_weighted_cost_accounting),
    ("time_until_allowed", probe_time_until_allowed),
    ("thread_safety", probe_thread_safety),
    ("stale_client_eviction", probe_stale_client_eviction),
]

# Fast-mode probe subset. Matches CHALLENGE_FAST.md which drops snapshot,
# time_until_allowed, and stale-client eviction from the spec.
FAST_PROBE_NAMES = {
    "invalid_constructor_args",
    "invalid_cost",
    "multiple_clients_independent",
    "sliding_window_expiry",
    "weighted_cost_accounting",
    "thread_safety",
}


def select_probes() -> list[tuple[str, Callable]]:
    mode = os.environ.get("DEMO_MODE", "full").lower()
    if mode == "fast":
        return [(n, fn) for n, fn in ALL_PROBES if n in FAST_PROBE_NAMES]
    return ALL_PROBES


PROBES: list[tuple[str, Callable]] = select_probes()


def main() -> None:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: probes.py <candidate_dir>"}))
        sys.exit(0)

    root = sys.argv[1]
    result: dict = {
        "probes": [],
        "passed": 0,
        "total": len(PROBES),
        "error": None,
    }

    try:
        mod = load_rate_limiter(root)
    except Exception as exc:
        result["error"] = f"import failed: {type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()
        print(json.dumps(result, indent=2))
        sys.exit(0)

    for name, fn in PROBES:
        try:
            errors = fn(mod)
            passed = not errors
            result["probes"].append(
                {"name": name, "passed": passed, "errors": errors}
            )
            if passed:
                result["passed"] += 1
        except Exception as exc:
            result["probes"].append(
                {
                    "name": name,
                    "passed": False,
                    "errors": [f"probe crashed: {type(exc).__name__}: {exc}"],
                }
            )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
