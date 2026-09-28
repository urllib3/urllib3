from __future__ import annotations

from unittest.mock import patch

import pytest

from urllib3.connectionpool import HTTPConnectionPool
from urllib3.exceptions import (
    LocationParseError,
    MaxRetryError,
    NewConnectionError,
    ProxyError,
)
from urllib3.poolmanager import ProxyManager
from urllib3.response import HTTPResponse
from urllib3.util.request import make_headers
from urllib3.util.retry import Retry
from urllib3.util.url import parse_url

from .port_helpers import find_unused_port


class TestProxyManager:
    @pytest.mark.parametrize(
        "proxy_scheme, scheme",
        [("http", "http"), ("https", "http"), ("https", "https")],
    )
    @pytest.mark.parametrize("zone", ["1", "25", "251", "25ethA", "et%61"])
    @pytest.mark.parametrize("retry_kind", [None, "status", "connection"])
    def test_scoped_ipv6_request_target_matches_host(
        self, proxy_scheme: str, scheme: str, zone: str, retry_kind: str | None
    ) -> None:
        responses: list[HTTPResponse | Exception] = []
        if retry_kind == "status":
            responses.extend([HTTPResponse(status=503), HTTPResponse(status=503)])
        elif retry_kind == "connection":
            responses.extend([OSError("connection reset"), OSError("connection reset")])
        responses.append(HTTPResponse(status=200))

        with ProxyManager(
            f"{proxy_scheme}://proxy:8080", use_forwarding_for_https=True
        ) as manager:
            with patch.object(
                HTTPConnectionPool,
                "_make_request",
                side_effect=responses,
            ) as request:
                response = manager.urlopen(
                    "GET",
                    f"{scheme}://[FE80::1%25{zone}]:8080/path?x=%23#fragment",
                    retries=Retry(total=2, status_forcelist=[503]),
                )

        assert response.status == 200
        assert request.call_count == len(responses)
        for call in request.call_args_list:
            assert call.args[2] == f"{scheme}://[fe80::1%{zone}]:8080/path?x=%23"
            assert call.kwargs["headers"]["Host"] == f"[fe80::1%{zone}]:8080"

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

    @pytest.mark.parametrize("proxy_scheme", ["http", "https"])
    def test_proxy_url_userinfo_becomes_proxy_authorization(
        self, proxy_scheme: str
    ) -> None:
        proxy_url = f"{proxy_scheme}://proxyuser:proxypass@proxy:8080"
        expected = make_headers(proxy_basic_auth="proxyuser:proxypass")[
            "proxy-authorization"
        ]
        with ProxyManager(proxy_url) as manager:
            assert manager.proxy is not None
            # Credentials are removed from the stored proxy URL.
            assert manager.proxy.auth is None
            assert manager.proxy_headers["proxy-authorization"] == expected

            with patch.object(
                HTTPConnectionPool,
                "_make_request",
                side_effect=[HTTPResponse(status=200)],
            ) as request:
                manager.urlopen("GET", "http://example.com/")

            assert request.call_args.args[2] == "http://example.com/"
            assert (
                request.call_args.kwargs["headers"]["proxy-authorization"]
                == expected
            )

    def test_proxy_url_userinfo_conflict_raises(self) -> None:
        with pytest.raises(ValueError, match="proxy-authorization") as exc_info:
            ProxyManager(
                "http://proxyuser:proxypass@proxy:8080",
                proxy_headers={"Proxy-Authorization": "Basic e30="},
            )
        # Credentials must never appear in the error message.
        assert "proxypass" not in str(exc_info.value)

    def test_proxy_url_userinfo_matching_header_accepted(self) -> None:
        expected = make_headers(proxy_basic_auth="proxyuser:proxypass")[
            "proxy-authorization"
        ]
        with ProxyManager(
            "http://proxyuser:proxypass@proxy:8080",
            proxy_headers={"Proxy-Authorization": expected},
        ) as manager:
            # Matching header is kept with its original casing.
            assert manager.proxy_headers == {"Proxy-Authorization": expected}

    def test_proxy_url_without_userinfo_leaves_headers_alone(self) -> None:
        with ProxyManager(
            "http://proxy:8080", proxy_headers={"X-Custom": "1"}
        ) as manager:
            assert manager.proxy_headers == {"X-Custom": "1"}

    def test_request_url_userinfo_forwarding(self) -> None:
        expected_auth = make_headers(basic_auth="user:s3cret")["authorization"]
        with ProxyManager("http://proxy:8080") as manager:
            with patch.object(
                HTTPConnectionPool,
                "_make_request",
                side_effect=[HTTPResponse(status=200)],
            ) as request:
                manager.urlopen(
                    "GET", "http://user:s3cret@example.com:80/path?q=1#fragment"
                )

            # Credentials must not appear in the absolute-form request target.
            assert request.call_args.args[2] == "http://example.com:80/path?q=1"
            headers = request.call_args.kwargs["headers"]
            assert headers["authorization"] == expected_auth
            assert "proxy-authorization" not in {
                k.lower() for k in headers.keys()
            }

    def test_default_port(self) -> None:
        with ProxyManager("http://something") as p:
            assert p.proxy is not None
            assert p.proxy.port == 80
        with ProxyManager("https://something") as p:
            assert p.proxy is not None
            assert p.proxy.port == 443

    def test_proxy_port_zero(self) -> None:
        with ProxyManager("http://proxy:0") as p:
            assert p.proxy is not None
            assert p.proxy.port == 0

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

    @pytest.mark.parametrize(
        "url",
        [
            "https://victim.example\r\nInjected/path",
            "https://[::1%25%0d%0a]/",
        ],
    )
    def test_proxy_connect_rejects_control_characters_in_tunnel_host(
        self, url: str
    ) -> None:
        with ProxyManager("http://proxy:8080") as p:
            with pytest.raises(LocationParseError):
                p.connection_from_url(url)

    @pytest.mark.parametrize("host", ["foo%.example", "foo%zz.example"])
    def test_proxy_connect_rejects_malformed_percent_escapes_in_tunnel_host(
        self, host: str
    ) -> None:
        with ProxyManager("http://proxy:8080") as p:
            with pytest.raises(LocationParseError):
                p.connection_from_host(host, scheme="https")

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
