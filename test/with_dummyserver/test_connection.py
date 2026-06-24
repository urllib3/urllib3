from __future__ import annotations

import contextlib
import sys
import typing
from http.client import ResponseNotReady
from unittest import mock

import pytest

from dummyserver.testcase import HypercornDummyServerTestCase as server
from urllib3 import HTTPConnectionPool
from urllib3.response import HTTPResponse

# See https://github.com/python/cpython/issues/146211
# Control character validation in tunnel is missing on:
# - Python 3.11 (all versions)
# - Python 3.12 before 3.12.14
# - Python 3.13 before 3.13.14
# - Python 3.14 before 3.14.5
_MISSING_TUNNEL_CONTROL_CHAR_FIX = (
    sys.version_info[:2] == (3, 11)
    or (sys.version_info[:2] == (3, 12) and sys.version_info[2] < 14)
    or (sys.version_info[:2] == (3, 13) and sys.version_info[2] < 14)
    or (sys.version_info[:2] == (3, 14) and sys.version_info[2] < 5)
)


@pytest.fixture()
def pool() -> typing.Generator[HTTPConnectionPool]:
    server.setup_class()

    with HTTPConnectionPool(server.host, server.port) as pool:
        yield pool

    server.teardown_class()


def test_returns_urllib3_HTTPResponse(pool: HTTPConnectionPool) -> None:
    with contextlib.closing(pool._get_conn()) as conn:
        conn.request("GET", "/")
        response = conn.getresponse()
        assert isinstance(response, HTTPResponse)


@mock.patch("urllib3.connection.sys.audit")
def test_audit_event(audit_mock: mock.Mock, pool: HTTPConnectionPool) -> None:
    with contextlib.closing(pool._get_conn()) as conn:
        conn.request("GET", "/")
        audit_mock.assert_any_call("http.client.connect", conn, conn.host, conn.port)
        # Ensure the event is raised only once.
        connect_events = [
            call
            for call in audit_mock.mock_calls
            if call.args[0] == "http.client.connect"
        ]
        assert len(connect_events) == 1


def test_does_not_release_conn(pool: HTTPConnectionPool) -> None:
    with contextlib.closing(pool._get_conn()) as conn:
        conn.request("GET", "/")
        response = conn.getresponse()

        response.release_conn()
        assert pool.pool.qsize() == 0  # type: ignore[union-attr]


def test_releases_conn(pool: HTTPConnectionPool) -> None:
    with contextlib.closing(pool._get_conn()) as conn:
        conn.request("GET", "/")
        response = conn.getresponse()

        # If these variables are set by the pool
        # then the response can release the connection
        # back into the pool.
        response._pool = pool  # type: ignore[attr-defined]
        response._connection = conn  # type: ignore[attr-defined]

        response.release_conn()
        assert pool.pool.qsize() == 1  # type: ignore[union-attr]


def test_double_getresponse(pool: HTTPConnectionPool) -> None:
    with contextlib.closing(pool._get_conn()) as conn:
        conn.request("GET", "/")
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


@pytest.mark.parametrize(
    "name,value",
    [
        ("Invalid\r\nName", "ValidValue"),
        ("Invalid\rName", "ValidValue"),
        ("Invalid\nName", "ValidValue"),
        ("\r\nInvalidName", "ValidValue"),
        ("\rInvalidName", "ValidValue"),
        ("\nInvalidName", "ValidValue"),
        (" InvalidName", "ValidValue"),
        ("\tInvalidName", "ValidValue"),
        ("Invalid:Name", "ValidValue"),
        (":InvalidName", "ValidValue"),
        ("ValidName", "Invalid\r\nValue"),
        ("ValidName", "Invalid\rValue"),
        ("ValidName", "Invalid\nValue"),
        ("ValidName", "InvalidValue\r\n"),
        ("ValidName", "InvalidValue\r"),
        ("ValidName", "InvalidValue\n"),
    ],
)
@pytest.mark.xfail(
    _MISSING_TUNNEL_CONTROL_CHAR_FIX,
    reason="Control characters in tunnel headers not rejected in older Python versions",
)
def test_invalid_tunnel_headers(
    pool: HTTPConnectionPool, name: str, value: str
) -> None:
    conn = pool._get_conn()
    conn.set_tunnel("tunnel", headers={name: value})
    with pytest.raises(ValueError, match="Invalid header"):
        conn.connect()
    conn.close()


@pytest.mark.parametrize(
    "tunnel_host",
    [
        "invalid\r.host",
        "\ninvalid.host",
        "invalid.host\r\n",
        "invalid.host\x00",
        "invalid host",
    ],
)
@pytest.mark.xfail(
    _MISSING_TUNNEL_CONTROL_CHAR_FIX,
    reason="Control characters in tunnel host not rejected in older Python versions",
)
def test_invalid_tunnel_host(pool: HTTPConnectionPool, tunnel_host: str) -> None:
    conn = pool._get_conn()
    conn.set_tunnel(tunnel_host)
    with pytest.raises(
        ValueError, match="Tunnel host can't contain control characters"
    ):
        conn.connect()
    conn.close()


def test_response_after_drain_conn(pool: HTTPConnectionPool) -> None:
    """
    Test that a connection can be reused after calling `drain_conn` on
    an unread response.
    """
    conn = pool._get_conn()

    conn.request("GET", "/", preload_content=False)
    response = conn.getresponse()
    assert response.status == 200
    response.drain_conn()

    conn.request("GET", "/", preload_content=False)
    response = conn.getresponse()
    assert response.status == 200

    conn.close()
