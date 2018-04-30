import sys

import pytest

from urllib3.backends import Backend as UserSpecifiedBackend
from urllib3._backends._loader import load_backend


class TestLoadBackend(object):
    """
    We assert that we are able to import compatible backends,
    and that we fail correctly if we attempt to use an unavailable or unknown backend.
    """
    def test_dummy(self):
        with pytest.raises(ImportError):
            load_backend("dummy")

    def test_sync(self):
        load_backend("sync")
        load_backend(UserSpecifiedBackend("sync"))

    @pytest.mark.skipif(
        sys.version_info < (3, 5),
        reason="async backends require Python 3.5 or greater",
    )
    def test_async(self):
        load_backend("trio")
        load_backend("twisted")

        from twisted.internet import reactor
        load_backend(UserSpecifiedBackend("twisted", reactor=reactor))
