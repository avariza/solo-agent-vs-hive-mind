import pytest
import threading
import time
from rate_limiter import RateLimiter


class TestConstructorValidation:
    def test_zero_max_requests(self):
        with pytest.raises(ValueError):
            RateLimiter(0, 60)

    def test_negative_max_requests(self):
        with pytest.raises(ValueError):
            RateLimiter(-1, 60)

    def test_boolean_max_requests(self):
        with pytest.raises(ValueError):
            RateLimiter(True, 60)

    def test_zero_window_seconds(self):
        with pytest.raises(ValueError):
            RateLimiter(10, 0)

    def test_negative_window_seconds(self):
        with pytest.raises(ValueError):
            RateLimiter(10, -1.5)


class TestCostValidation:
    def test_zero_cost(self):
        rl = RateLimiter(10, 1)
        with pytest.raises(ValueError):
            rl.allow_request("c", 0)

    def test_negative_cost(self):
        rl = RateLimiter(10, 1)
        with pytest.raises(ValueError):
            rl.allow_request("c", -1)

    def test_cost_exceeds_max(self):
        rl = RateLimiter(10, 1)
        with pytest.raises(ValueError):
            rl.allow_request("c", 11)

    def test_boolean_cost(self):
        rl = RateLimiter(10, 1)
        with pytest.raises(ValueError):
            rl.allow_request("c", True)


class TestWeightedCostAccounting:
    def test_two_requests_exceed_capacity(self):
        rl = RateLimiter(10, 1)
        assert rl.allow_request("c", 6) is True
        assert rl.allow_request("c", 5) is False

    def test_two_requests_fit_capacity(self):
        rl = RateLimiter(10, 1)
        assert rl.allow_request("c", 6) is True
        assert rl.allow_request("c", 4) is True

    def test_snapshot_after_successful_requests(self):
        rl = RateLimiter(10, 1)
        rl.allow_request("c", 6)
        rl.allow_request("c", 4)
        snap = rl.snapshot("c")
        assert snap["used"] == 10
        assert snap["remaining"] == 0


class TestSlidingWindowExpiry:
    def test_request_expires_at_boundary(self):
        rl = RateLimiter(5, 0.1)
        assert rl.allow_request("c", 5) is True
        time.sleep(0.11)
        assert rl.allow_request("c", 1) is True

    def test_full_quota_restored_after_window(self):
        rl = RateLimiter(5, 0.05)
        assert rl.allow_request("c", 5) is True
        time.sleep(0.06)
        assert rl.allow_request("c", 5) is True

    def test_continuous_expiry_no_buckets(self):
        rl = RateLimiter(10, 1)
        assert rl.allow_request("c", 10) is True
        time.sleep(0.5)
        assert rl.allow_request("c", 1) is False
        time.sleep(0.51)
        assert rl.allow_request("c", 1) is True


class TestPerClientIsolation:
    def test_client_isolation(self):
        rl = RateLimiter(5, 1)
        assert rl.allow_request("a", 5) is True
        assert rl.allow_request("a", 1) is False
        assert rl.allow_request("b", 5) is True

    def test_snapshot_unknown_client(self):
        rl = RateLimiter(10, 1)
        snap = rl.snapshot("never_seen")
        assert snap["used"] == 0
        assert snap["remaining"] == 10
        assert snap["reset_in"] == 0.0


class TestThreadSafety:
    def test_concurrent_contention(self):
        rl = RateLimiter(100, 1)
        barrier = threading.Barrier(10)
        grants = []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            for _ in range(200):
                if rl.allow_request("contention", 1):
                    with lock:
                        grants.append(1)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sum(grants) == 100


class TestBoundedMemory:
    def test_evict_stale_client(self):
        rl = RateLimiter(10, 0.05)
        rl.allow_request("old", 5)
        time.sleep(0.11)
        rl.allow_request("new", 1)
        snap = rl.snapshot("old")
        assert snap["used"] == 0


class TestTimeUntilAllowed:
    def test_allowed_returns_zero(self):
        rl = RateLimiter(10, 1)
        assert rl.allow_request("c", 5) is True
        assert rl.time_until_allowed("c", 1) == 0.0

    def test_denied_returns_wait_time(self):
        rl = RateLimiter(10, 1)
        assert rl.allow_request("c", 10) is True
        wait = rl.time_until_allowed("c", 1)
        assert 0.9 < wait <= 1.0

    def test_weighted_case_first_request_expiry(self):
        rl = RateLimiter(10, 1)
        assert rl.allow_request("c", 4) is True
        assert rl.allow_request("c", 3) is True
        assert rl.allow_request("c", 3) is True
        wait = rl.time_until_allowed("c", 4)
        assert 0.9 < wait <= 1.0

    def test_unknown_client_returns_zero(self):
        rl = RateLimiter(10, 1)
        assert rl.time_until_allowed("never_seen", 1) == 0.0
