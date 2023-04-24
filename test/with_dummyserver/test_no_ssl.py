"""
Test connections without the builtin ssl module

Note: Import urllib3 inside the test functions to get the importblocker to work
"""
from __future__ import annotations

import pytest

import urllib3
from dummyserver.testcase import HTTPDummyServerTestCase, HTTPSDummyServerTestCase
from urllib3.exceptions import InsecureRequestWarning

from ..test_no_ssl import TestWithoutSSL


class TestHTTPWithoutSSL(HTTPDummyServerTestCase, TestWithoutSSL):
    def test_simple(self) -> None:
        with urllib3.HTTPConnectionPool(self.host, self.port) as pool:
            r = pool.request("GET", "/")
            assert r.status == 200, r.data


class TestHTTPSWithoutSSL(HTTPSDummyServerTestCase, TestWithoutSSL):
    def test_simple(self) -> None:
        with urllib3.HTTPSConnectionPool(
            self.host, self.port, cert_reqs="NONE"
        ) as pool:
            with pytest.warns(InsecureRequestWarning):
                try:
                    pool.request("GET", "/")
                except urllib3.exceptions.SSLError as e:
                    assert "SSL module is not available" in str(e)
