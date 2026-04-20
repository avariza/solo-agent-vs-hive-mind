import threading
import time

import pytest

from src.rate_limiter import RateLimiter


# --- Constructor validation ---

class TestConstructorValidation:
    def test_max_requests_zero(self):
        with pytest.raises(ValueError):
            RateLimiter(0, 1.0)

    def test_max_requests_negative(self):
        with pytest.raises(ValueError):
            RateLimiter(-5, 1.0)

    def test_window_seconds_zero(self):
        with pytest.raises(ValueError):
            RateLimiter(10, 0)

    def test_window_seconds_negative(self):
        with pytest.raises(ValueError):
            RateLimiter(10, -1.0)


# --- Cost validation ---

class TestCostValidation:
    def test_cost_zero(self):
        rl = RateLimiter(10, 1.0)
        with pytest.raises(ValueError):
            rl.allow_request("a", cost=0)

    def test_cost_negative(self):
        rl = RateLimiter(10, 1.0)
        with pytest.raises(ValueError):
            rl.allow_request("a", cost=-1)

    def test_cost_exceeds_max(self):
        rl = RateLimiter(5, 1.0)
        with pytest.raises(ValueError):
            rl.allow_request("a", cost=6)


# --- Basic sliding window ---

class TestSlidingWindow:
    def test_allow_up_to_max(self):
        rl = RateLimiter(3, 1.0)
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is False

    def test_requests_expire_after_window(self):
        rl = RateLimiter(2, 0.1)
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is False
        time.sleep(0.15)
        assert rl.allow_request("a") is True

    def test_exact_boundary_is_expired(self):
        """A request at exactly (now - window_seconds) is treated as expired."""
        rl = RateLimiter(1, 0.05)
        assert rl.allow_request("a") is True
        time.sleep(0.06)
        # The old request is now >= window_seconds old, so it's expired
        assert rl.allow_request("a") is True


# --- Weighted cost ---

class TestWeightedCost:
    def test_weighted_single_request(self):
        rl = RateLimiter(5, 1.0)
        assert rl.allow_request("a", cost=5) is True
        assert rl.allow_request("a", cost=1) is False

    def test_combined_cost_exceeds_max(self):
        rl = RateLimiter(5, 1.0)
        assert rl.allow_request("a", cost=3) is True
        assert rl.allow_request("a", cost=3) is False

    def test_mixed_costs(self):
        rl = RateLimiter(10, 1.0)
        assert rl.allow_request("a", cost=4) is True
        assert rl.allow_request("a", cost=4) is True
        assert rl.allow_request("a", cost=2) is True
        assert rl.allow_request("a", cost=1) is False

    def test_default_cost_is_one(self):
        rl = RateLimiter(2, 1.0)
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is False

    def test_cost_equal_to_max_requests(self):
        rl = RateLimiter(5, 1.0)
        assert rl.allow_request("a", cost=5) is True
        assert rl.allow_request("a", cost=5) is False


# --- Per-client isolation ---

class TestClientIsolation:
    def test_separate_clients(self):
        rl = RateLimiter(2, 1.0)
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is False
        # Client b is unaffected
        assert rl.allow_request("b") is True
        assert rl.allow_request("b") is True
        assert rl.allow_request("b") is False

    def test_many_clients(self):
        rl = RateLimiter(1, 1.0)
        for i in range(100):
            assert rl.allow_request(f"client-{i}") is True


# --- Thread safety ---

class TestThreadSafety:
    def test_concurrent_threads_respect_limit(self):
        max_req = 10
        n_threads = 20
        rl = RateLimiter(max_req, 2.0)
        barrier = threading.Barrier(n_threads)
        results = []
        results_lock = threading.Lock()

        def worker():
            barrier.wait()
            granted = rl.allow_request("shared")
            with results_lock:
                results.append(granted)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        granted_count = sum(1 for r in results if r)
        assert granted_count <= max_req

    def test_concurrent_weighted_requests(self):
        max_req = 10
        cost = 3
        n_threads = 10
        rl = RateLimiter(max_req, 2.0)
        barrier = threading.Barrier(n_threads)
        results = []
        results_lock = threading.Lock()

        def worker():
            barrier.wait()
            granted = rl.allow_request("shared", cost=cost)
            with results_lock:
                results.append(granted)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        granted_count = sum(1 for r in results if r)
        total_cost = granted_count * cost
        assert total_cost <= max_req
        # With cost=3 and max=10, at most 3 can be granted (3*3=9 <= 10)
        assert granted_count <= max_req // cost

    def test_concurrent_different_clients(self):
        """Different clients should not interfere with each other."""
        rl = RateLimiter(1, 2.0)
        n_threads = 10
        barrier = threading.Barrier(n_threads)
        results = []
        results_lock = threading.Lock()

        def worker(cid):
            barrier.wait()
            granted = rl.allow_request(cid)
            with results_lock:
                results.append((cid, granted))

        threads = [
            threading.Thread(target=worker, args=(f"client-{i}",))
            for i in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each client had limit=1 and made 1 request, so all should succeed
        assert all(granted for _, granted in results)
