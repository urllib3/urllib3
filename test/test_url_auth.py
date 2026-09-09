from __future__ import annotations

import typing
from unittest import mock

import pytest

from urllib3 import HTTPConnectionPool, HTTPSConnectionPool, PoolManager, ProxyManager
from urllib3.response import HTTPResponse
from urllib3.util import make_headers


@pytest.mark.parametrize(
    "userinfo,decoded",
    [
        ("alice:secret", "alice:secret"),
        ("alice", "alice:"),
        ("al%69ce:p%40ss%3Aword", "alice:p@ss:word"),
        ("us%C3%A9r:pass", "usér:pass"),
    ],
)
def test_manager_generates_auth_without_mutating_defaults(
    userinfo: str, decoded: str
) -> None:
    headers = {"X-Trace": "synthetic"}
    with (
        PoolManager(headers=headers) as manager,
        mock.patch.object(
            HTTPConnectionPool, "urlopen", return_value=HTTPResponse(status=200)
        ) as send,
    ):
        manager.urlopen("GET", f"http://{userinfo}@localhost/resource")
    assert send.call_args.args[1] == "/resource"
    assert (
        send.call_args.kwargs["headers"]["Authorization"]
        == make_headers(basic_auth=decoded)["authorization"]
    )
    assert headers == {"X-Trace": "synthetic"}


def test_conflicting_origin_auth_fails_before_io() -> None:
    with (
        PoolManager() as manager,
        mock.patch.object(
            HTTPConnectionPool, "urlopen", return_value=HTTPResponse(status=200)
        ) as send,
    ):
        with pytest.raises(ValueError, match="conflicts"):
            manager.urlopen(
                "GET",
                "http://alice:secret@localhost/",
                headers={"aUtHoRiZaTiOn": "Bearer other"},
            )
    send.assert_not_called()


def test_matching_origin_auth_is_accepted() -> None:
    auth = make_headers(basic_auth="alice:secret")["authorization"]
    with (
        PoolManager() as manager,
        mock.patch.object(
            HTTPConnectionPool, "urlopen", return_value=HTTPResponse(status=200)
        ) as send,
    ):
        manager.urlopen(
            "GET", "http://alice:secret@localhost/", headers={"authorization": auth}
        )
    assert list(send.call_args.kwargs["headers"].values()) == [auth]


def test_proxy_url_is_sanitized_and_auth_is_separate() -> None:
    headers = {"X-Proxy": "synthetic"}
    with ProxyManager(
        "http://proxyuser:proxypass@localhost:8080", proxy_headers=headers
    ) as manager:
        assert manager.proxy is not None
        assert manager.proxy.auth is None
        assert (
            manager.proxy_headers["Proxy-Authorization"]
            == make_headers(proxy_basic_auth="proxyuser:proxypass")[
                "proxy-authorization"
            ]
        )
        assert "proxypass" not in manager.proxy.url
    assert headers == {"X-Proxy": "synthetic"}


def test_conflicting_proxy_auth_fails() -> None:
    with pytest.raises(ValueError, match="conflicts"):
        ProxyManager(
            "http://proxyuser:proxypass@localhost:8080",
            proxy_headers={"proxy-authorization": "Bearer other"},
        )


def test_pool_absolute_target_strips_userinfo() -> None:
    with (
        HTTPConnectionPool("localhost") as pool,
        mock.patch.object(
            pool, "_make_request", return_value=HTTPResponse(status=200)
        ) as send,
    ):
        pool.urlopen("GET", "http://alice:secret@localhost/resource", retries=False)
    assert send.call_args.args[2] == "http://localhost/resource"
    assert (
        send.call_args.kwargs["headers"]["Authorization"]
        == make_headers(basic_auth="alice:secret")["authorization"]
    )


def test_redirect_credentials_are_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    response = HTTPResponse(
        status=302, headers={"Location": "http://bob:newsecret@localhost/next"}
    )
    with (
        PoolManager() as manager,
        mock.patch.object(HTTPConnectionPool, "urlopen", return_value=response),
    ):
        with pytest.raises(ValueError, match="conflicts"):
            manager.urlopen("GET", "http://alice:secret@localhost/", retries=1)
    assert "newsecret" not in caplog.text


def test_forwarded_proxy_auth_conflict_fails_before_io() -> None:
    with (
        ProxyManager("http://proxyuser:proxypass@localhost:8080") as manager,
        mock.patch.object(
            HTTPConnectionPool, "_make_request", return_value=HTTPResponse(status=200)
        ) as send,
    ):
        with pytest.raises(ValueError, match="conflicts"):
            manager.urlopen(
                "GET",
                "http://localhost/",
                headers={"proxy-authorization": "Basic b3RoZXI="},
                retries=False,
            )
    send.assert_not_called()


def test_matching_forwarded_proxy_auth_is_not_duplicated() -> None:
    auth = make_headers(proxy_basic_auth="proxyuser:proxypass")["proxy-authorization"]
    with (
        ProxyManager("http://proxyuser:proxypass@localhost:8080") as manager,
        mock.patch.object(
            HTTPConnectionPool, "_make_request", return_value=HTTPResponse(status=200)
        ) as send,
    ):
        manager.urlopen(
            "GET",
            "http://localhost/",
            headers={"proxy-authorization": auth},
            retries=False,
        )
    values = [
        value
        for key, value in send.call_args.kwargs["headers"].items()
        if key.lower() == "proxy-authorization"
    ]
    assert values == [auth]


def test_unencodable_credentials_have_a_safe_error() -> None:
    with (
        PoolManager() as manager,
        mock.patch.object(HTTPConnectionPool, "urlopen") as send,
    ):
        with pytest.raises(ValueError) as caught:
            manager.urlopen("GET", "http://alice:%E4%B8%ADsecret@localhost/")
    assert "secret" not in str(caught.value)
    send.assert_not_called()


def test_manager_does_not_reuse_url_credentials() -> None:
    with (
        PoolManager() as manager,
        mock.patch.object(
            HTTPConnectionPool, "urlopen", return_value=HTTPResponse(status=200)
        ) as send,
    ):
        manager.urlopen("GET", "http://alice:secret@localhost/")
        manager.urlopen("GET", "http://localhost/")
    assert all(
        key.lower() != "authorization" for key in send.call_args.kwargs["headers"]
    )


def test_matching_byte_auth_header_is_accepted() -> None:
    auth = make_headers(basic_auth="alice:secret")["authorization"].encode()
    headers = typing.cast("typing.Mapping[str, str]", {b"Authorization": auth})
    with (
        PoolManager() as manager,
        mock.patch.object(
            HTTPConnectionPool, "urlopen", return_value=HTTPResponse(status=200)
        ) as send,
    ):
        manager.urlopen("GET", "http://alice:secret@localhost/", headers=headers)
    assert send.call_args.kwargs["headers"] is headers


def test_connect_proxy_auth_conflict_fails_before_connect() -> None:
    with (
        ProxyManager("http://proxyuser:proxypass@localhost:8080") as manager,
        mock.patch.object(HTTPSConnectionPool, "_prepare_proxy") as connect,
        mock.patch.object(
            HTTPConnectionPool, "_make_request", return_value=HTTPResponse(status=200)
        ) as send,
    ):
        with pytest.raises(ValueError, match="conflicts"):
            manager.urlopen(
                "GET",
                "https://localhost/",
                headers={"proxy-authorization": "Basic b3RoZXI="},
                retries=False,
            )
    connect.assert_not_called()
    send.assert_not_called()
