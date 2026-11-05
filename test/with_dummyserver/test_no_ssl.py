"""
Test connections without the builtin ssl module

Note: Import urllib3 inside the test functions so it is loaded without SSL support.
"""

from __future__ import annotations

import pytest

from dummyserver.testcase import HypercornDummyServerTestCase

pytestmark = pytest.mark.usefixtures("without_ssl")


class TestHTTPWithoutSSL(HypercornDummyServerTestCase):
    def test_simple(self) -> None:
        import urllib3

        with urllib3.HTTPConnectionPool(self.host, self.port) as pool:
            r = pool.request("GET", "/")
            assert r.status == 200, r.data


class TestHTTPSWithoutSSL:
    def test_simple(self) -> None:
        import urllib3

        with urllib3.HTTPSConnectionPool("localhost") as pool:
            with pytest.raises(ImportError, match="SSL module is not available"):
                pool.request("GET", "/")
