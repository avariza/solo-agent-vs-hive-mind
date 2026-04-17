import threading
import time

import pytest

from src.rate_limiter import RateLimiter


# --- Constructor validation ---

class TestConstructorValidation:
    def test_max_requests_zero_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(0, 1.0)

    def test_max_requests_negative_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(-5, 1.0)

    def test_window_seconds_zero_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(10, 0)

    def test_window_seconds_negative_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(10, -1.0)


# --- Cost validation ---

class TestCostValidation:
    def test_cost_zero_raises(self):
        rl = RateLimiter(10, 1.0)
        with pytest.raises(ValueError):
            rl.allow_request("a", cost=0)

    def test_cost_negative_raises(self):
        rl = RateLimiter(10, 1.0)
        with pytest.raises(ValueError):
            rl.allow_request("a", cost=-1)

    def test_cost_exceeds_max_raises(self):
        rl = RateLimiter(5, 1.0)
        with pytest.raises(ValueError):
            rl.allow_request("a", cost=6)


# --- Basic sliding window ---

class TestSlidingWindow:
    def test_allows_within_limit(self):
        rl = RateLimiter(3, 1.0)
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is True

    def test_denies_over_limit(self):
        rl = RateLimiter(2, 1.0)
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is False

    def test_window_expires_and_allows_again(self):
        rl = RateLimiter(1, 0.1)
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is False
        time.sleep(0.15)
        assert rl.allow_request("a") is True

    def test_exact_boundary_is_expired(self):
        """A request at exactly (now - window_seconds) is treated as expired."""
        rl = RateLimiter(1, 0.05)
        assert rl.allow_request("a") is True
        # Sleep exactly the window duration — entry should be expired
        time.sleep(0.05)
        assert rl.allow_request("a") is True


# --- Weighted cost ---

class TestWeightedCost:
    def test_single_heavy_request(self):
        rl = RateLimiter(5, 1.0)
        assert rl.allow_request("a", cost=5) is True
        assert rl.allow_request("a", cost=1) is False

    def test_combined_cost_exceeds_limit(self):
        rl = RateLimiter(5, 1.0)
        assert rl.allow_request("a", cost=3) is True
        assert rl.allow_request("a", cost=3) is False

    def test_combined_cost_fits(self):
        rl = RateLimiter(5, 1.0)
        assert rl.allow_request("a", cost=3) is True
        assert rl.allow_request("a", cost=2) is True

    def test_cost_exactly_equals_max(self):
        rl = RateLimiter(5, 1.0)
        assert rl.allow_request("a", cost=5) is True

    def test_cost_frees_after_window(self):
        rl = RateLimiter(3, 0.1)
        assert rl.allow_request("a", cost=3) is True
        assert rl.allow_request("a", cost=1) is False
        time.sleep(0.15)
        assert rl.allow_request("a", cost=2) is True


# --- Per-client isolation ---

class TestClientIsolation:
    def test_different_clients_independent(self):
        rl = RateLimiter(2, 1.0)
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is False
        # Client b is unaffected
        assert rl.allow_request("b") is True
        assert rl.allow_request("b") is True

    def test_one_client_limit_does_not_block_another(self):
        rl = RateLimiter(1, 1.0)
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is False
        assert rl.allow_request("b") is True


# --- Thread safety ---

class TestThreadSafety:
    def test_concurrent_requests_respect_limit(self):
        """Spawn many threads hitting the same client — total grants must not exceed max."""
        max_requests = 10
        num_threads = 50
        rl = RateLimiter(max_requests, 5.0)

        barrier = threading.Barrier(num_threads)
        results = [False] * num_threads

        def worker(idx: int) -> None:
            barrier.wait()
            results[idx] = rl.allow_request("contended")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        granted = sum(1 for r in results if r)
        assert granted <= max_requests
        assert granted == max_requests  # exactly max should be granted

    def test_concurrent_weighted_requests(self):
        """Weighted concurrent requests must not exceed budget."""
        max_requests = 10
        cost = 3
        num_threads = 20
        rl = RateLimiter(max_requests, 5.0)

        barrier = threading.Barrier(num_threads)
        results = [False] * num_threads

        def worker(idx: int) -> None:
            barrier.wait()
            results[idx] = rl.allow_request("weighted", cost=cost)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        granted = sum(1 for r in results if r)
        total_cost = granted * cost
        assert total_cost <= max_requests
        # With max=10, cost=3 → exactly 3 requests fit (9 units)
        assert granted == max_requests // cost

    def test_concurrent_multi_client(self):
        """Multiple clients concurrently — each should get its full allowance."""
        max_requests = 5
        clients = ["c1", "c2", "c3"]
        threads_per_client = 10
        rl = RateLimiter(max_requests, 5.0)

        barrier = threading.Barrier(len(clients) * threads_per_client)
        results: dict[str, list[bool]] = {c: [False] * threads_per_client for c in clients}

        def worker(cid: str, idx: int) -> None:
            barrier.wait()
            results[cid][idx] = rl.allow_request(cid)

        threads = []
        for cid in clients:
            for i in range(threads_per_client):
                t = threading.Thread(target=worker, args=(cid, i))
                threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for cid in clients:
            granted = sum(1 for r in results[cid] if r)
            assert granted == max_requests


# --- Default cost ---

class TestDefaultCost:
    def test_default_cost_is_one(self):
        rl = RateLimiter(1, 1.0)
        assert rl.allow_request("a") is True
        assert rl.allow_request("a") is False
