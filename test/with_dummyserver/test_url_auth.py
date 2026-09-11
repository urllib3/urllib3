from __future__ import annotations

import pytest

from dummyserver.socketserver import DEFAULT_CA
from dummyserver.testcase import (
    HypercornDummyProxyTestCase,
    HypercornDummyServerTestCase,
)
from urllib3 import HTTPConnectionPool, PoolManager, ProxyManager


class TestURLAuthentication(HypercornDummyServerTestCase):
    @pytest.mark.parametrize("use_manager", [False, True])
    def test_origin_credentials_on_wire(self, use_manager: bool) -> None:
        url = f"http://user:pass@{self.host}:{self.port}/headers"
        client = (
            PoolManager() if use_manager else HTTPConnectionPool(self.host, self.port)
        )
        with client:
            response = client.request("GET", url)
            assert response.json()["Authorization"] == "Basic dXNlcjpwYXNz"
            assert response.url is not None
            assert "user:pass" not in response.url
            response = client.request("GET", f"http://{self.host}:{self.port}/headers")
            assert "Authorization" not in response.json()

    @pytest.mark.parametrize("same_host", [False, True])
    @pytest.mark.parametrize("use_manager", [False, True])
    def test_redirect_credentials(self, same_host: bool, use_manager: bool) -> None:
        target = (
            "/headers" if same_host else f"http://{self.host_alt}:{self.port}/headers"
        )
        url = f"http://user:pass@{self.host}:{self.port}/redirect"
        client = (
            PoolManager() if use_manager else HTTPConnectionPool(self.host, self.port)
        )
        with client:
            response = client.request(
                "GET", url, fields={"target": target}, assert_same_host=False
            )
            assert response.json().get("Authorization") == (
                "Basic dXNlcjpwYXNz" if same_host else None
            )


class TestProxyURLAuthentication(HypercornDummyProxyTestCase):
    @pytest.mark.parametrize("proxy_scheme", ["http", "https"])
    @pytest.mark.parametrize("target_scheme", ["http", "https"])
    def test_origin_and_proxy_credentials(
        self, proxy_scheme: str, target_scheme: str
    ) -> None:
        proxy_port = (
            self.proxy_port if proxy_scheme == "http" else self.https_proxy_port
        )
        target_host = self.http_host if target_scheme == "http" else self.https_host
        target_port = self.http_port if target_scheme == "http" else self.https_port
        with ProxyManager(
            f"{proxy_scheme}://proxy:password@{self.proxy_host}:{proxy_port}",
            ca_certs=DEFAULT_CA,
        ) as manager:
            response = manager.request(
                "GET",
                f"{target_scheme}://user:pass@{target_host}:{target_port}/headers",
            )
            headers = response.json()
            assert headers["Authorization"] == "Basic dXNlcjpwYXNz"
            # CONNECT credentials must never appear in the tunneled origin request.
            assert headers.get("Proxy-Authorization") == (
                "Basic cHJveHk6cGFzc3dvcmQ=" if target_scheme == "http" else None
            )
