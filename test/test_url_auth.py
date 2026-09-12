from __future__ import annotations

from unittest.mock import patch

import pytest

from urllib3 import HTTPHeaderDict, HTTPResponse, PoolManager, ProxyManager
from urllib3.connectionpool import HTTPConnectionPool


@pytest.mark.parametrize(
    "userinfo,expected",
    [
        ("user:pass", "Basic dXNlcjpwYXNz"),
        ("user", "Basic dXNlcjo="),
        (":", "Basic Og=="),
        ("user:p%40ss", "Basic dXNlcjpwQHNz"),
        ("user:p%C3%A4ss", "Basic dXNlcjpw5HNz"),
    ],
)
@pytest.mark.parametrize("proxy", [False, True])
def test_request_url_auth(userinfo: str, expected: str, proxy: bool) -> None:
    headers = {"X-Test": "value"}
    manager = ProxyManager("http://proxy.test") if proxy else PoolManager()
    with manager, patch.object(HTTPConnectionPool, "urlopen") as urlopen:
        urlopen.return_value = HTTPResponse(status=200)
        manager.urlopen(
            "GET", f"http://{userinfo}@example.test/path#fragment", headers=headers
        )
        assert urlopen.call_args.args[1] == (
            "http://example.test/path" if proxy else "/path"
        )
        assert urlopen.call_args.kwargs["headers"]["Authorization"] == expected
        assert headers == {"X-Test": "value"}


@pytest.mark.parametrize("header", ["authorization", "Authorization", "AUTHORIZATION"])
@pytest.mark.parametrize("matches", [False, True])
def test_explicit_auth(header: str, matches: bool) -> None:
    headers = {header: "Basic dXNlcjpwYXNz" if matches else "Bearer other"}
    with (
        PoolManager(headers=headers) as manager,
        patch.object(HTTPConnectionPool, "urlopen") as urlopen,
    ):
        urlopen.return_value = HTTPResponse(status=200)
        if matches:
            manager.urlopen("GET", "http://user:pass@example.test/")
            assert len(urlopen.call_args.kwargs["headers"]) == 1
        else:
            with pytest.raises(ValueError, match="Authorization"):
                manager.urlopen("GET", "http://user:pass@example.test/")
            urlopen.assert_not_called()


def test_duplicate_auth_conflict() -> None:
    headers = HTTPHeaderDict()
    headers.add("Authorization", "Basic dXNlcjpwYXNz")
    headers.add("authorization", "Bearer other")
    with PoolManager() as manager, pytest.raises(ValueError, match="Authorization"):
        manager.urlopen("GET", "http://user:pass@example.test/", headers=headers)


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_proxy_url_auth(scheme: str) -> None:
    headers = {"X-Proxy": "value"}
    with ProxyManager(
        f"{scheme}://user:p%40ss@proxy.test", proxy_headers=headers
    ) as manager:
        assert manager.proxy is not None
        assert manager.proxy.auth is None
        assert manager.proxy_headers["Proxy-Authorization"] == "Basic dXNlcjpwQHNz"
        assert headers == {"X-Proxy": "value"}
        pool = manager.connection_from_url("https://example.test/")
        assert pool.proxy_headers == manager.proxy_headers


@pytest.mark.parametrize("matches", [False, True])
def test_explicit_proxy_auth(matches: bool) -> None:
    headers = {
        "proxy-authorization": "Basic dXNlcjpwYXNz" if matches else "Bearer other"
    }
    if matches:
        with ProxyManager(
            "http://user:pass@proxy.test", proxy_headers=headers
        ) as manager:
            assert len(manager.proxy_headers) == 1
    else:
        with pytest.raises(ValueError, match="Proxy-Authorization"):
            ProxyManager("http://user:pass@proxy.test", proxy_headers=headers)


def test_direct_pool_url_auth() -> None:
    with (
        HTTPConnectionPool("example.test") as pool,
        patch.object(pool, "_make_request") as request,
    ):
        request.return_value = HTTPResponse(status=200)
        pool.urlopen("GET", "http://user:pass@example.test/path", retries=False)
        assert request.call_args.args[2] == "http://example.test/path"
        assert (
            request.call_args.kwargs["headers"]["Authorization"] == "Basic dXNlcjpwYXNz"
        )
