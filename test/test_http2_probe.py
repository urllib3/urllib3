from __future__ import annotations

import threading
import time

import pytest

from urllib3.http2.probe import _HTTP2ProbeCache


class TestHTTP2ProbeCache:
    def test_single_thread_lifecycle(self) -> None:
        cache = _HTTP2ProbeCache()
        host, port = "example.com", 443

        # First call: unknown origin, current thread owns probe.
        assert cache.acquire_and_get(host, port) is None

        # Publish result:
        cache.set_and_release(host, port, True)

        # Subsequent call: returns cached result immediately.
        assert cache.acquire_and_get(host, port) is True

    def test_concurrent_waiters_unblocked_on_probe_result(self) -> None:
        cache = _HTTP2ProbeCache()
        host, port = "example.com", 443

        # Thread 0 owns the initial probe.
        assert cache.acquire_and_get(host, port) is None

        num_waiters = 4
        barrier = threading.Barrier(num_waiters + 1)
        results: list[tuple[int, bool | None]] = []

        def wait_for_probe(index: int) -> None:
            barrier.wait()
            val = cache.acquire_and_get(host, port)
            results.append((index, val))

        threads = [
            threading.Thread(target=wait_for_probe, args=(i,), daemon=True)
            for i in range(num_waiters)
        ]
        for t in threads:
            t.start()

        barrier.wait()
        # Allow waiting threads to reach and block on the per-origin lock
        time.sleep(0.05)

        # Publish the result from the initial probe thread
        cache.set_and_release(host, port, False)

        for t in threads:
            t.join(timeout=2.0)
            assert not t.is_alive(), f"Thread {t} remained blocked"

        assert len(results) == num_waiters
        assert all(val is False for _, val in results)

        # Lock must be completely unlocked
        key_lock = cache._cache_locks[(host, port)]
        # Acquiring without blocking verifies it was unlocked
        assert key_lock.acquire(blocking=False)
        key_lock.release()

    def test_concurrent_waiters_succeed_with_http2_true(self) -> None:
        cache = _HTTP2ProbeCache()
        host, port = "example.com", 443

        assert cache.acquire_and_get(host, port) is None

        num_waiters = 5
        barrier = threading.Barrier(num_waiters + 1)
        results: list[bool | None] = []

        def wait_for_probe() -> None:
            barrier.wait()
            results.append(cache.acquire_and_get(host, port))

        threads = [
            threading.Thread(target=wait_for_probe, daemon=True)
            for _ in range(num_waiters)
        ]
        for t in threads:
            t.start()

        barrier.wait()
        time.sleep(0.05)

        cache.set_and_release(host, port, True)

        for t in threads:
            t.join(timeout=2.0)
            assert not t.is_alive()

        assert len(results) == num_waiters
        assert all(val is True for val in results)

    def test_probe_failure_allows_next_waiter_to_probe(self) -> None:
        cache = _HTTP2ProbeCache()
        host, port = "example.com", 443

        # Initial thread acquires probe ownership
        assert cache.acquire_and_get(host, port) is None

        barrier = threading.Barrier(2)
        next_probe_result: list[bool | None] = []

        def waiter() -> None:
            barrier.wait()
            res = cache.acquire_and_get(host, port)
            next_probe_result.append(res)
            if res is None:
                cache.set_and_release(host, port, True)

        t = threading.Thread(target=waiter, daemon=True)
        t.start()

        barrier.wait()
        time.sleep(0.05)

        # First probe fails: reset with supports_http2=None
        cache.set_and_release(host, port, None)

        t.join(timeout=2.0)
        assert not t.is_alive()

        # The waiting thread became the new prober, received None, and published True
        assert next_probe_result == [None]
        assert cache.acquire_and_get(host, port) is True

    def test_cannot_reset_after_value_set(self) -> None:
        cache = _HTTP2ProbeCache()
        host, port = "example.com", 443

        assert cache.acquire_and_get(host, port) is None
        cache.set_and_release(host, port, True)

        with pytest.raises(
            ValueError,
            match="Cannot reset HTTP/2 support for origin after value has been set.",
        ):
            cache.set_and_release(host, port, None)
