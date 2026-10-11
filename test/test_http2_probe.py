from __future__ import annotations

from unittest import mock

from urllib3.http2.probe import _HTTP2ProbeCache


def test_waiter_releases_lock_when_probe_result_is_available() -> None:
    cache = _HTTP2ProbeCache()
    key = ("example.test", 443)
    key_lock = mock.MagicMock()

    def acquire() -> bool:
        cache._cache_values[key] = False
        return True

    key_lock.acquire.side_effect = acquire
    cache._cache_locks[key] = key_lock
    cache._cache_values[key] = None

    assert cache.acquire_and_get(*key) is False
    key_lock.release.assert_called_once_with()
