import pytest

import urllib3
from urllib3.backends import Backend
from urllib3._backends._loader import normalize_backend, load_backend


requires_async_pool_manager = pytest.mark.skipif(
    not hasattr(urllib3, "AsyncPoolManager"),
    reason="async backends require AsyncPoolManager",
)


class TestNormalizeBackend(object):
    """
    Assert that we fail correctly if we attempt to use an unknown or incompatible backend.
    """
    def test_unknown(self):
        with pytest.raises(ValueError) as excinfo:
            normalize_backend("_unknown", async_mode=False)

        assert 'unknown backend specifier _unknown' == str(excinfo.value)

    def test_sync(self):
        assert normalize_backend(Backend("sync"), async_mode=False) == Backend("sync")
        assert normalize_backend("sync", async_mode=False) == Backend("sync")
        assert normalize_backend(None, async_mode=False) == Backend("sync")

        with pytest.raises(ValueError) as excinfo:
            normalize_backend(Backend("trio"), async_mode=False)
        assert ('trio backend needs to be run in async mode' == str(excinfo.value))

    @requires_async_pool_manager
    def test_async(self):
        assert normalize_backend(Backend("trio"), async_mode=True) == Backend("trio")
        assert normalize_backend("twisted", async_mode=True) == Backend("twisted")

        with pytest.raises(ValueError) as excinfo:
            normalize_backend(Backend("sync"), async_mode=True)
        assert ('sync backend needs to be run in sync mode' == str(excinfo.value))

        from twisted.internet import reactor
        assert (
            normalize_backend(Backend("twisted", reactor=reactor), async_mode=True)
            == Backend("twisted", reactor=reactor))


class TestLoadBackend(object):
    """
    Assert that we can load a normalized backend
    """
    def test_sync(self):
        load_backend(normalize_backend("sync", async_mode=False))

    @requires_async_pool_manager()
    def test_async(self):
        from twisted.internet import reactor
        load_backend(Backend("twisted", reactor=reactor))
