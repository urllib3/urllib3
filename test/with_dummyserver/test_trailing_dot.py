from __future__ import annotations

import typing
from test import resolvesLocalhostFQDN

from dummyserver.server import DEFAULT_CA
from dummyserver.testcase import HTTPDummyProxyTestCase
from urllib3.poolmanager import proxy_from_url


class TestHTTPProxyManagerAndTrailingDot(HTTPDummyProxyTestCase):
    """
    Test cases for https://github.com/urllib3/urllib3/issues/2244
    """

    http_url_with_dot: typing.ClassVar[str]
    https_url_with_dot: typing.ClassVar[str]

    @classmethod
    def setup_class(cls) -> None:
        super().setup_class()
        cls.http_url_with_dot = f"http://{cls.http_host}.:{int(cls.http_port)}"
        cls.https_url_with_dot = f"https://{cls.https_host}.:{int(cls.https_port)}"
        cls.proxy_url = f"http://{cls.proxy_host}:{int(cls.proxy_port)}"
        cls.https_proxy_url = f"https://{cls.proxy_host}:{int(cls.https_proxy_port)}"

    @classmethod
    def teardown_class(cls) -> None:
        super().teardown_class()

    @resolvesLocalhostFQDN()
    def test_basic_proxy(self) -> None:
        with proxy_from_url(self.proxy_url, ca_certs=DEFAULT_CA) as http:
            r = http.request("GET", f"{self.http_url_with_dot}/")
            assert r.status == 200

            r = http.request("GET", f"{self.https_url_with_dot}/")
            assert r.status == 200

    @resolvesLocalhostFQDN()
    def test_https_proxy(self) -> None:
        with proxy_from_url(self.https_proxy_url, ca_certs=DEFAULT_CA) as https:
            r = https.request("GET", f"{self.https_url_with_dot}/")
            assert r.status == 200

            r = https.request("GET", f"{self.http_url_with_dot}/")
            assert r.status == 200
