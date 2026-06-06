from __future__ import annotations

import socket

import pytest

from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.exceptions import MaxRetryError, NewConnectionError, ProxyError
from urllib3.poolmanager import ProxyManager
from urllib3.response import HTTPResponse
from urllib3.util.retry import Retry
from urllib3.util.url import parse_url

from .port_helpers import find_unused_port


class TestProxyManager:
    @pytest.mark.parametrize("proxy_scheme", ["http", "https"])
    def test_proxy_headers(self, proxy_scheme: str) -> None:
        url = "http://pypi.org/project/urllib3/"
        proxy_url = f"{proxy_scheme}://something:1234"
        with ProxyManager(proxy_url) as p:
            # Verify default headers
            default_headers = {"Accept": "*/*", "Host": "pypi.org"}
            headers = p._set_proxy_headers(url)

            assert headers == default_headers

            # Verify default headers don't overwrite provided headers
            provided_headers = {
                "Accept": "application/json",
                "custom": "header",
                "Host": "test.python.org",
            }
            headers = p._set_proxy_headers(url, provided_headers)

            assert headers == provided_headers

            # Verify proxy with nonstandard port
            provided_headers = {"Accept": "application/json"}
            expected_headers = provided_headers.copy()
            expected_headers.update({"Host": "pypi.org:8080"})
            url_with_port = "http://pypi.org:8080/project/urllib3/"
            headers = p._set_proxy_headers(url_with_port, provided_headers)

            assert headers == expected_headers

    def test_default_port(self) -> None:
        with ProxyManager("http://something") as p:
            assert p.proxy is not None
            assert p.proxy.port == 80
        with ProxyManager("https://something") as p:
            assert p.proxy is not None
            assert p.proxy.port == 443

    @pytest.mark.parametrize("url", ["http://example.com", "https://example.com"])
    def test_socket_options_default_to_empty_list_for_proxies(self, url: str) -> None:
        with ProxyManager("http://proxy:8080") as p:
            pool = p.connection_from_url(url)

        assert pool.conn_kw["socket_options"] == []

    @pytest.mark.parametrize("url", ["http://example.com", "https://example.com"])
    def test_socket_options_respect_custom_defaults_for_proxies(
        self, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        keepalive = (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        monkeypatch.setattr(
            HTTPConnection,
            "default_socket_options",
            HTTPConnection.default_socket_options + [keepalive],
        )

        with ProxyManager("http://proxy:8080") as p:
            pool = p.connection_from_url(url)

        assert pool.conn_kw["socket_options"] == [keepalive]

    def test_socket_options_respect_https_custom_defaults_for_proxies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        keepalive = (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        monkeypatch.setattr(
            HTTPSConnection,
            "default_socket_options",
            HTTPSConnection.default_socket_options + [keepalive],
        )

        with ProxyManager("http://proxy:8080") as p:
            pool = p.connection_from_url("https://example.com")

        assert pool.conn_kw["socket_options"] == [keepalive]

    def test_socket_options_override_default_for_proxies(self) -> None:
        proxy_socket_options = [
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
            (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
        ]

        with ProxyManager(
            "http://proxy:8080", socket_options=proxy_socket_options
        ) as p:
            pool = p.connection_from_url("http://example.com")

        assert pool.conn_kw["socket_options"] == proxy_socket_options

    def test_invalid_scheme(self) -> None:
        with pytest.raises(AssertionError):
            ProxyManager("invalid://host/p")
        with pytest.raises(ValueError):
            ProxyManager("invalid://host/p")

    def test_proxy_tunnel(self) -> None:
        http_url = parse_url("http://example.com")
        https_url = parse_url("https://example.com")
        with ProxyManager("http://proxy:8080") as p:
            assert p._proxy_requires_url_absolute_form(http_url)
            assert p._proxy_requires_url_absolute_form(https_url) is False

        with ProxyManager("https://proxy:8080") as p:
            assert p._proxy_requires_url_absolute_form(http_url)
            assert p._proxy_requires_url_absolute_form(https_url) is False

        with ProxyManager("https://proxy:8080", use_forwarding_for_https=True) as p:
            assert p._proxy_requires_url_absolute_form(http_url)
            assert p._proxy_requires_url_absolute_form(https_url)

    @pytest.mark.parametrize("proxy_scheme", ["http", "https"])
    def test_absolute_form_request_target_strips_fragment_for_custom_pool(
        self, proxy_scheme: str
    ) -> None:
        class CustomConnectionPool:
            requested_urls: list[str] = []

            def __init__(self, host: str, port: int | None = None, **kw: object):
                pass

            def urlopen(self, method: str, url: str, **kw: object) -> HTTPResponse:
                self.requested_urls.append(url)
                return HTTPResponse(status=200)

        with ProxyManager(f"{proxy_scheme}://proxy:8080") as p:
            p.pool_classes_by_scheme = p.pool_classes_by_scheme.copy()
            p.pool_classes_by_scheme[proxy_scheme] = CustomConnectionPool
            response = p.urlopen(
                "GET",
                "http://example.com/path?x=1#marker=value",
            )

        assert response.status == 200
        assert CustomConnectionPool.requested_urls == ["http://example.com/path?x=1"]

    def test_proxy_connect_retry(self) -> None:
        retry = Retry(total=None, connect=False)
        port = find_unused_port()
        with ProxyManager(f"http://localhost:{port}") as p:
            with pytest.raises(ProxyError) as ei:
                p.urlopen("HEAD", url="http://localhost/", retries=retry)
            assert isinstance(ei.value.original_error, NewConnectionError)

        retry = Retry(total=None, connect=2)
        with ProxyManager(f"http://localhost:{port}") as p:
            with pytest.raises(MaxRetryError) as ei1:
                p.urlopen("HEAD", url="http://localhost/", retries=retry)
            assert ei1.value.reason is not None
            assert isinstance(ei1.value.reason, ProxyError)
            assert isinstance(ei1.value.reason.original_error, NewConnectionError)
