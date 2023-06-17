from __future__ import annotations

import pytest
import ssl

from urllib3.exceptions import MaxRetryError, NewConnectionError, ProxyError
from urllib3.poolmanager import ProxyManager
from urllib3.util.retry import Retry
from urllib3.util.url import parse_url
import urllib3.util.ssl_
from dummyserver.server import DEFAULT_CA

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

    def test_proxy_ssl_context_and_proxy_ssl_context(self) -> None:
        """When both proxy_ssl_context and ssl_context are set when using
        use_forwarding_for_https, raise a value error"""

        proxy_ssl_context = urllib3.util.ssl_.create_urllib3_context()
        proxy_ssl_context.load_verify_locations(DEFAULT_CA)
        ctx = ssl.create_default_context()
        with pytest.raises(ValueError) as exc_info:
            ProxyManager(
                "https://proxy:8080",
                use_forwarding_for_https=True,
                proxy_ssl_context=proxy_ssl_context,
                ssl_context=ctx,
            )
        assert (
            "ssl_context and proxy_ssl_context are both defined"
            in exc_info.value.args[0]
        )

    def test_proxy_ssl_context_only(self) -> None:
        """When only ssl_context is set when using use_forwarding_for_https
        in urllib3 2.x, raise a deprecation error"""

        ctx = ssl.create_default_context()
        with pytest.raises(ValueError) as exc_info:
            ProxyManager(
                "https://proxy:8080", use_forwarding_for_https=True, ssl_context=ctx
            )
        assert "proxy_ssl_context should be used" in exc_info.value.args[0]

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
