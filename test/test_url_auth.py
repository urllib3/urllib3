from __future__ import annotations

from unittest.mock import patch

import pytest

from urllib3 import HTTPConnectionPool, PoolManager, ProxyManager
from urllib3._collections import HTTPHeaderDict
from urllib3.response import HTTPResponse


@pytest.mark.parametrize("use_manager", [False, True])
@pytest.mark.parametrize(
    "userinfo,expected",
    [
        ("user:pass", "Basic dXNlcjpwYXNz"),
        ("user", "Basic dXNlcjo="),
        (":", "Basic Og=="),
        ("user%40example.com:p%3Ass", "Basic dXNlckBleGFtcGxlLmNvbTpwOnNz"),
        ("user:%FF", "Basic dXNlcjr/"),
    ],
)
def test_origin_userinfo(use_manager: bool, userinfo: str, expected: str) -> None:
    client = PoolManager() if use_manager else HTTPConnectionPool("example.com")
    original = {"X-Test": "preserved"}
    with patch.object(
        HTTPConnectionPool, "_make_request", return_value=HTTPResponse()
    ) as request:
        client.urlopen("GET", f"http://{userinfo}@example.com/path", headers=original)
    assert request.call_args.kwargs["headers"]["Authorization"] == expected
    assert "@" not in request.call_args.args[2]
    assert original == {"X-Test": "preserved"}
    client.close() if isinstance(client, HTTPConnectionPool) else client.clear()


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_proxy_userinfo(scheme: str) -> None:
    original = {"X-Proxy": "preserved"}
    manager = ProxyManager(
        f"{scheme}://user:p%3Ass@proxy.example:8080", proxy_headers=original
    )
    assert manager.proxy_headers["Proxy-Authorization"] == "Basic dXNlcjpwOnNz"
    assert manager.proxy is not None
    assert manager.proxy.auth is None
    assert original == {"X-Proxy": "preserved"}
    manager.clear()


@pytest.mark.parametrize("use_manager", [False, True])
def test_conflicting_origin_header(use_manager: bool) -> None:
    client = PoolManager() if use_manager else HTTPConnectionPool("example.com")
    with patch.object(
        HTTPConnectionPool, "_make_request", return_value=HTTPResponse()
    ) as request:
        with pytest.raises(ValueError, match="Authorization") as error:
            client.urlopen(
                "GET",
                "http://user:secret@example.com/",
                headers={"authorization": "Bearer token"},
            )
    request.assert_not_called()
    assert "secret" not in str(error.value)


def test_matching_header_preserves_other_repeated_headers() -> None:
    headers = HTTPHeaderDict({"aUtHoRiZaTiOn": "Basic dXNlcjpwYXNz"})
    headers.add("X-Test", "one")
    headers.add("X-Test", "two")
    with patch.object(
        HTTPConnectionPool, "_make_request", return_value=HTTPResponse()
    ) as request:
        PoolManager().urlopen("GET", "http://user:pass@example.com/", headers=headers)
    assert request.call_args.kwargs["headers"].getlist("X-Test") == ["one", "two"]
    assert headers.getlist("X-Test") == ["one", "two"]


def test_conflicting_proxy_header() -> None:
    with pytest.raises(ValueError, match="Proxy-Authorization"):
        ProxyManager(
            "http://user:pass@proxy.example",
            proxy_headers={"proxy-authorization": "Basic different"},
        )


def test_absolute_form_never_contains_credentials() -> None:
    with patch.object(
        HTTPConnectionPool, "_make_request", return_value=HTTPResponse()
    ) as request:
        ProxyManager("http://proxy:password@proxy.example").urlopen(
            "GET", "http://user:pass@example.com/path"
        )
    assert request.call_args.args[2] == "http://example.com/path"
    headers = request.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Basic dXNlcjpwYXNz"
    assert headers["Proxy-Authorization"] == "Basic cHJveHk6cGFzc3dvcmQ="


def test_conflicting_duplicate_authorization_header() -> None:
    headers = HTTPHeaderDict({"Authorization": "Basic dXNlcjpwYXNz"})
    headers.add("authorization", "Bearer different")
    with pytest.raises(ValueError, match="Authorization"):
        PoolManager().urlopen("GET", "http://user:pass@example.com/", headers=headers)
    assert headers.getlist("Authorization") == [
        "Basic dXNlcjpwYXNz",
        "Bearer different",
    ]


def test_default_headers_not_modified() -> None:
    defaults = {"X-Test": "default"}
    with PoolManager(headers=defaults) as manager:
        with patch.object(
            HTTPConnectionPool, "_make_request", return_value=HTTPResponse()
        ) as request:
            manager.request("GET", "http://user:pass@example.com/")
        assert (
            request.call_args.kwargs["headers"]["Authorization"] == "Basic dXNlcjpwYXNz"
        )
        assert defaults == {"X-Test": "default"}
        assert manager.headers == defaults


def test_matching_proxy_authorization_header() -> None:
    headers = {"pRoXy-AuThOrIzAtIoN": "Basic dXNlcjpwYXNz"}
    with ProxyManager(
        "http://user:pass@proxy.example", proxy_headers=headers
    ) as manager:
        assert manager.proxy_headers["Proxy-Authorization"] == "Basic dXNlcjpwYXNz"
        assert headers == {"pRoXy-AuThOrIzAtIoN": "Basic dXNlcjpwYXNz"}
