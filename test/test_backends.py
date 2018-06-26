import pytest

import urllib3
from urllib3.backends import Backend
from urllib3._backends._loader import normalize_backend, load_backend


requires_async_pool_manager = pytest.mark.skipif(
    not hasattr(urllib3, "AsyncPoolManager"),
    reason="async backends require AsyncPoolManager",
)


requires_sync_pool_manager = pytest.mark.skipif(
    hasattr(urllib3, "AsyncPoolManager"),
    reason="sync backends cannot be used with AsyncPoolManager",
)


class TestNormalizeBackend(object):
    """
    Assert that we fail correctly if we attempt to use an unknown or incompatible backend.
    """
    def test_unknown(self):
        with pytest.raises(ValueError) as excinfo:
            normalize_backend("_unknown")

        assert 'unknown backend specifier _unknown' == str(excinfo.value)

    @requires_sync_pool_manager
    def test_sync(self):
        assert normalize_backend(Backend("sync")) == Backend("sync")
        assert normalize_backend("sync") == Backend("sync")
        assert normalize_backend(None) == Backend("sync")

        with pytest.raises(ValueError) as excinfo:
            normalize_backend(Backend("trio"))

        assert ('trio backend requires urllib3 to be built with async support'
                == str(excinfo.value))

    @requires_async_pool_manager
    def test_async(self):
        assert normalize_backend(Backend("trio")) == Backend("trio")
        assert normalize_backend("twisted") == Backend("twisted")

        with pytest.raises(ValueError) as excinfo:
            normalize_backend(Backend("sync"))

        assert (
            'sync backend requires urllib3 to be built without async support'
            == str(excinfo.value))

        from twisted.internet import reactor
        assert (
            normalize_backend(Backend("twisted", reactor=reactor))
            == Backend("twisted", reactor=reactor))


class TestLoadBackend(object):
    """
    Assert that we can load a normalized backend
    """
    @requires_sync_pool_manager()
    def test_sync(self):
        load_backend(normalize_backend("sync"))

    @requires_async_pool_manager()
    def test_async(self):
        from twisted.internet import reactor
        load_backend(Backend("twisted", reactor=reactor))
