#!/usr/bin/env python3
"""Non-correctness metrics for the rate-limiter challenge.

Runs two analyses against a candidate's implementation and writes the
combined result to a JSON file:

1. Cyclomatic complexity via `radon.complexity.cc_visit`. Senior reviewers
   care whether `allow_request` is O(1)-in-branching or a 40-path monster.
2. A tiny contention throughput benchmark. We hammer `allow_request` with
   8 threads and measure ops/sec + p50/p99 latency. The limiter is sized
   huge so it virtually never denies — we're measuring lock + bookkeeping
   cost, not the rate-limit verdict distribution.

Usage:
    python metrics.py <candidate_dir> <output_json>

Exit code is always 0 so the Node evaluator can parse results even if
complexity or benchmark fails.
"""
from __future__ import annotations

import importlib.util
import json
import os
import statistics
import sys
import threading
import time
import traceback
from pathlib import Path


def load_module(impl_path: Path):
    root = impl_path.parent.parent
    sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location(
        f"metrics_candidate_{abs(hash(str(impl_path)))}", str(impl_path)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {impl_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def measure_complexity(impl_path: Path) -> dict:
    try:
        from radon.complexity import cc_visit
        from radon.raw import analyze
    except ImportError:
        return {"error": "radon not installed (pip install radon)"}

    try:
        source = impl_path.read_text()
        blocks = cc_visit(source)
        raw = analyze(source)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    per_block = [
        {"name": b.name, "cc": b.complexity, "line": b.lineno}
        for b in blocks
    ]
    cc_values = [b["cc"] for b in per_block] or [0]
    return {
        "max_cc": max(cc_values),
        "avg_cc": round(statistics.mean(cc_values), 2),
        "total_blocks": len(per_block),
        "top_blocks": sorted(per_block, key=lambda x: -x["cc"])[:5],
        "loc": raw.loc,
        "lloc": raw.lloc,
        "sloc": raw.sloc,
        "comments": raw.comments,
    }


def measure_throughput(mod) -> dict:
    RL = getattr(mod, "RateLimiter", None)
    if RL is None:
        return {"error": "RateLimiter class not found"}

    # Big capacity + long window so virtually no request is denied: we're
    # benchmarking the lock + sliding-window bookkeeping, not the verdict
    # distribution.
    try:
        limiter = RL(10**9, 3600.0)
    except Exception as exc:
        return {"error": f"constructor failed: {type(exc).__name__}: {exc}"}

    n_threads = 8
    ops_per_thread = 4000
    total_ops = n_threads * ops_per_thread
    barrier = threading.Barrier(n_threads)

    # Pre-allocate per-thread latency buffers to avoid contention on a
    # shared list during timing.
    per_thread_latencies: list[list[int]] = [[] for _ in range(n_threads)]
    errors: list[str] = []

    def worker(idx: int) -> None:
        buf = per_thread_latencies[idx]
        local_err = None
        barrier.wait()
        for i in range(ops_per_thread):
            cid = f"bench_{(idx * 131 + i) % 64}"
            t0 = time.perf_counter_ns()
            try:
                limiter.allow_request(cid)
            except Exception as exc:  # noqa: BLE001
                if local_err is None:
                    local_err = f"{type(exc).__name__}: {exc}"
            buf.append(time.perf_counter_ns() - t0)
        if local_err:
            errors.append(local_err)

    start = time.perf_counter()
    threads = [
        threading.Thread(target=worker, args=(i,)) for i in range(n_threads)
    ]
    for t in threads:
        t.start()
    hung = False
    for t in threads:
        t.join(timeout=30.0)
        if t.is_alive():
            hung = True
    elapsed = time.perf_counter() - start

    if hung:
        return {"error": "benchmark worker hung (possible deadlock)", "elapsed_sec": round(elapsed, 3)}
    if elapsed <= 0:
        return {"error": "zero elapsed"}

    all_latencies: list[int] = []
    for buf in per_thread_latencies:
        all_latencies.extend(buf)
    all_latencies.sort()

    def _pct(p: float) -> float:
        if not all_latencies:
            return 0.0
        idx = min(len(all_latencies) - 1, int(len(all_latencies) * p))
        return all_latencies[idx] / 1000.0  # ns → µs

    return {
        "ops_per_sec": round(total_ops / elapsed, 1),
        "total_ops": total_ops,
        "threads": n_threads,
        "elapsed_sec": round(elapsed, 3),
        "p50_latency_us": round(_pct(0.50), 2),
        "p99_latency_us": round(_pct(0.99), 2),
        "errors_sample": errors[:3],
    }


def main() -> None:
    if len(sys.argv) != 3:
        print(json.dumps({"error": "usage: metrics.py <dir> <out>"}))
        sys.exit(0)

    root = Path(sys.argv[1])
    out = Path(sys.argv[2])
    impl = root / "src" / "rate_limiter.py"

    result: dict = {
        "complexity": None,
        "throughput": None,
        "error": None,
    }

    if not impl.is_file():
        result["error"] = f"no implementation at {impl}"
        out.write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        return

    result["complexity"] = measure_complexity(impl)

    try:
        mod = load_module(impl)
        result["throughput"] = measure_throughput(mod)
    except Exception as exc:
        result["throughput"] = {
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=3),
        }

    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
