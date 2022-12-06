from __future__ import annotations

import typing
from http.client import ResponseNotReady

import pytest

from dummyserver.testcase import HTTPDummyServerTestCase as server
from urllib3 import HTTPConnectionPool
from urllib3.response import HTTPResponse


@pytest.fixture()
def pool() -> typing.Generator[HTTPConnectionPool, None, None]:
    server.setup_class()

    with HTTPConnectionPool(server.host, server.port) as pool:
        yield pool

    server.teardown_class()


def test_returns_urllib3_HTTPResponse(pool: HTTPConnectionPool) -> None:
    conn = pool._get_conn()

    method = "GET"
    path = "/"

    conn.request(method, path)

    response = conn.getresponse()

    assert isinstance(response, HTTPResponse)


def test_does_not_release_conn(pool: HTTPConnectionPool) -> None:
    conn = pool._get_conn()

    method = "GET"
    path = "/"

    conn.request(method, path)

    response = conn.getresponse()

    response.release_conn()
    assert pool.pool.qsize() == 0  # type: ignore[union-attr]


def test_releases_conn(pool: HTTPConnectionPool) -> None:
    conn = pool._get_conn()
    assert conn is not None

    method = "GET"
    path = "/"

    conn.request(method, path)

    response = conn.getresponse()
    # If these variables are set by the pool
    # then the response can release the connection
    # back into the pool.
    response._pool = pool  # type: ignore[attr-defined]
    response._connection = conn  # type: ignore[attr-defined]

    response.release_conn()
    assert pool.pool.qsize() == 1  # type: ignore[union-attr]


def test_double_getresponse(pool: HTTPConnectionPool) -> None:
    conn = pool._get_conn()

    method = "GET"
    path = "/"

    conn.request(method, path)

    _ = conn.getresponse()

    # Calling getrepsonse() twice should cause an error
    with pytest.raises(ResponseNotReady):
        conn.getresponse()


def test_connection_state_properties(pool: HTTPConnectionPool) -> None:
    conn = pool._get_conn()

    assert conn.is_closed is True
    assert conn.is_connected is False
    assert conn.has_connected_to_proxy is False
    assert conn.is_verified is False
    assert conn.proxy_is_verified is None

    conn.connect()

    assert conn.is_closed is False
    assert conn.is_connected is True
    assert conn.has_connected_to_proxy is False
    assert conn.is_verified is False
    assert conn.proxy_is_verified is None

    conn.request("GET", "/")
    resp = conn.getresponse()
    assert resp.status == 200

    conn.close()

    assert conn.is_closed is True
    assert conn.is_connected is False
    assert conn.has_connected_to_proxy is False
    assert conn.is_verified is False
    assert conn.proxy_is_verified is None


def test_set_tunnel_is_reset(pool: HTTPConnectionPool) -> None:
    conn = pool._get_conn()

    assert conn.is_closed is True
    assert conn.is_connected is False
    assert conn.has_connected_to_proxy is False
    assert conn.is_verified is False
    assert conn.proxy_is_verified is None

    conn.set_tunnel(host="host", port=8080, scheme="http")

    assert conn._tunnel_host == "host"  # type: ignore[attr-defined]
    assert conn._tunnel_port == 8080  # type: ignore[attr-defined]
    assert conn._tunnel_scheme == "http"  # type: ignore[attr-defined]

    conn.close()

    assert conn._tunnel_host is None  # type: ignore[attr-defined]
    assert conn._tunnel_port is None  # type: ignore[attr-defined]
    assert conn._tunnel_scheme is None  # type: ignore[attr-defined]


def test_invalid_tunnel_scheme(pool: HTTPConnectionPool) -> None:
    conn = pool._get_conn()

    with pytest.raises(ValueError) as e:
        conn.set_tunnel(host="host", port=8080, scheme="socks")
    assert (
        str(e.value)
        == "Invalid proxy scheme for tunneling: 'socks', must be either 'http' or 'https'"
    )
