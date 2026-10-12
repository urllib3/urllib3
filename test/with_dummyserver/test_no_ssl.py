"""
Test connections without the builtin ssl module

Note: Import urllib3 inside the test functions to get the importblocker to work
"""

from __future__ import annotations

import pytest

import urllib3
from dummyserver.testcase import (
    HypercornDummyProxyTestCase,
    HypercornDummyServerTestCase,
)
from urllib3.exceptions import InsecureProxyWarning, InsecureRequestWarning

from ..test_no_ssl import TestWithoutSSL


class TestHTTPWithoutSSL(HypercornDummyServerTestCase, TestWithoutSSL):
    def test_simple(self) -> None:
        with urllib3.HTTPConnectionPool(self.host, self.port) as pool:
            r = pool.request("GET", "/")
            assert r.status == 200, r.data


class TestHTTPSWithoutSSL(HypercornDummyProxyTestCase, TestWithoutSSL):
    def test_simple(self) -> None:
        with urllib3.HTTPSConnectionPool(
            self.https_host, self.https_port, cert_reqs="NONE"
        ) as pool:
            with pytest.warns(InsecureRequestWarning):
                try:
                    pool.request("GET", "/")
                except urllib3.exceptions.SSLError as e:
                    assert "SSL module is not available" in str(e)

    def test_simple_proxy(self) -> None:
        https_proxy_url = f"https://{self.proxy_host}:{int(self.https_proxy_port)}"
        with urllib3.ProxyManager(https_proxy_url, cert_reqs="NONE") as pool:
            with pytest.warns((InsecureProxyWarning, InsecureRequestWarning)) as record:
                try:
                    pool.request("GET", "https://urllib3.readthedocs.io")
                except urllib3.exceptions.SSLError as e:
                    assert "SSL module is not available" in str(e)
            assert "localhost" in str(record[0].message)
            assert "urllib3.readthedocs.io" in str(record[1].message)

            with pytest.warns((InsecureProxyWarning, InsecureRequestWarning)) as record:
                try:
                    pool.request("GET", f"http://{self.http_host}:{self.http_port}")
                except urllib3.exceptions.SSLError as e:
                    assert "SSL module is not available" in str(e)
            assert "localhost" in str(record[0].message)
            assert self.http_host in str(record[1].message)
