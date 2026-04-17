import threading
import time
from unittest.mock import patch

import pytest

from src.rate_limiter import RateLimiter


# ── Constructor validation ──────────────────────────────────────────

class TestConstructorValidation:
    def test_max_requests_zero_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(max_requests=0, window_seconds=1.0)

    def test_max_requests_negative_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(max_requests=-5, window_seconds=1.0)

    def test_window_seconds_zero_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(max_requests=10, window_seconds=0)

    def test_window_seconds_negative_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(max_requests=10, window_seconds=-1.0)

    def test_valid_construction(self):
        rl = RateLimiter(max_requests=5, window_seconds=1.0)
        assert rl is not None


# ── Cost validation ─────────────────────────────────────────────────

class TestCostValidation:
    def test_cost_zero_raises(self):
        rl = RateLimiter(max_requests=10, window_seconds=1.0)
        with pytest.raises(ValueError):
            rl.allow_request("a", cost=0)

    def test_cost_negative_raises(self):
        rl = RateLimiter(max_requests=10, window_seconds=1.0)
        with pytest.raises(ValueError):
            rl.allow_request("a", cost=-1)

    def test_cost_exceeds_max_raises(self):
        rl = RateLimiter(max_requests=5, window_seconds=1.0)
        with pytest.raises(ValueError):
            rl.allow_request("a", cost=6)

    def test_cost_equal_to_max_allowed(self):
        rl = RateLimiter(max_requests=5, window_seconds=1.0)
        assert rl.allow_request("a", cost=5) is True


# ── Basic sliding window behavior ──────────────────────────────────

class TestSlidingWindow:
    def test_allows_up_to_limit(self):
        rl = RateLimiter(max_requests=3, window_seconds=1.0)
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is False

    def test_requests_expire_after_window(self):
        rl = RateLimiter(max_requests=2, window_seconds=0.1)
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is False
        time.sleep(0.15)
        assert rl.allow_request("a") is True

    def test_request_at_exact_boundary_is_expired(self):
        """A request timestamped exactly window_seconds ago is expired."""
        rl = RateLimiter(max_requests=1, window_seconds=1.0)

        fake_time = [100.0]

        def mock_monotonic():
            return fake_time[0]

        with patch("src.rate_limiter.time.monotonic", side_effect=mock_monotonic):
            assert rl.allow_request("a") is True
            assert rl.allow_request("a") is False

            # Advance time by exactly window_seconds
            fake_time[0] = 101.0
            # The old entry at t=100 is exactly 1.0s ago → expired
            assert rl.allow_request("a") is True


# ── Weighted cost ───────────────────────────────────────────────────

class TestWeightedCost:
    def test_weighted_requests_respect_budget(self):
        rl = RateLimiter(max_requests=10, window_seconds=1.0)
        assert rl.allow_request("a", cost=4) is True
        assert rl.allow_request("a", cost=4) is True
        # 8 used, requesting 4 more → 12 > 10
        assert rl.allow_request("a", cost=4) is False
        # But 2 more fits
        assert rl.allow_request("a", cost=2) is True

    def test_combined_cost_exceeds_limit_second_denied(self):
        rl = RateLimiter(max_requests=5, window_seconds=1.0)
        assert rl.allow_request("a", cost=3) is True
        assert rl.allow_request("a", cost=3) is False

    def test_default_cost_is_one(self):
        rl = RateLimiter(max_requests=2, window_seconds=1.0)
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is False


# ── Per-client isolation ────────────────────────────────────────────

class TestClientIsolation:
    def test_clients_have_independent_limits(self):
        rl = RateLimiter(max_requests=2, window_seconds=1.0)
        assert rl.allow_request("alice") is True
        assert rl.allow_request("alice") is True
        assert rl.allow_request("alice") is False
        # Bob is unaffected
        assert rl.allow_request("bob") is True
        assert rl.allow_request("bob") is True
        assert rl.allow_request("bob") is False


# ── Thread safety ───────────────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_threads_respect_limit(self):
        """
        Spawn many threads that all try to claim 1 unit each.
        Total granted must never exceed max_requests.
        """
        max_req = 10
        num_threads = 50
        rl = RateLimiter(max_requests=max_req, window_seconds=5.0)

        barrier = threading.Barrier(num_threads)
        results = [False] * num_threads

        def worker(idx):
            barrier.wait()
            results[idx] = rl.allow_request("shared")

        threads = [
            threading.Thread(target=worker, args=(i,))
            for i in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        granted = sum(1 for r in results if r)
        assert granted <= max_req
        # With 50 threads and limit 10, at least some should succeed
        assert granted > 0

    def test_concurrent_weighted_threads_respect_limit(self):
        """Weighted concurrent requests must not overshoot."""
        max_req = 20
        cost_per = 3
        num_threads = 30
        rl = RateLimiter(max_requests=max_req, window_seconds=5.0)

        barrier = threading.Barrier(num_threads)
        results = [False] * num_threads

        def worker(idx):
            barrier.wait()
            results[idx] = rl.allow_request("shared", cost=cost_per)

        threads = [
            threading.Thread(target=worker, args=(i,))
            for i in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        granted = sum(cost_per for r in results if r)
        assert granted <= max_req

    def test_concurrent_different_clients(self):
        """Different clients under contention should each get their full budget."""
        max_req = 5
        num_clients = 4
        threads_per_client = 10
        rl = RateLimiter(max_requests=max_req, window_seconds=5.0)

        barrier = threading.Barrier(num_clients * threads_per_client)
        results: dict[str, list[bool]] = {
            f"client_{i}": [False] * threads_per_client
            for i in range(num_clients)
        }

        def worker(cid, idx):
            barrier.wait()
            results[cid][idx] = rl.allow_request(cid)

        threads = []
        for i in range(num_clients):
            cid = f"client_{i}"
            for j in range(threads_per_client):
                t = threading.Thread(target=worker, args=(cid, j))
                threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for cid, res in results.items():
            granted = sum(1 for r in res if r)
            assert granted <= max_req, f"{cid} exceeded limit: {granted}"
            assert granted > 0, f"{cid} got zero grants"
