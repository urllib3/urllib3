from __future__ import annotations

import typing

import urllib3
from urllib3 import HTTPConnectionPool, HTTPSConnectionPool
from urllib3._collections import _TYPE_HEADER_MAPPING, HTTPHeaderDict
from urllib3._request_methods import RequestMethods
from urllib3.connection import HTTPConnection
from urllib3.fields import RequestField
from urllib3.poolmanager import PoolManager, ProxyManager

try:
    from urllib3.contrib.socks import SOCKSProxyManager
except (ImportError, urllib3.exceptions.DependencyWarning):
    SOCKSProxyManager = None  # type: ignore[assignment,misc]

# Test all mapping variants
headers_str: dict[str, str] = {"X-Header": "value"}
headers_str_bytes: dict[str, bytes] = {"X-Header": b"value"}
headers_bytes_str: dict[bytes, str] = {b"X-Header": "value"}
headers_bytes: dict[bytes, bytes] = {b"X-Header": b"value"}
headers_mixed: dict[str | bytes, str | bytes] = {
    "X-String": b"bytes",
    b"X-Bytes": "string",
}
headers_mapping_str: typing.Mapping[str, str] = {"X-Header": "value"}
headers_mapping_bytes: typing.Mapping[bytes, bytes] = {b"X-Header": b"value"}
headers_mapping_mixed: typing.Mapping[str | bytes, str | bytes] = {
    "X-String": b"bytes",
    b"X-Bytes": "string",
}
headers_http = HTTPHeaderDict({"X-Header": "value"})

all_header_variants: list[_TYPE_HEADER_MAPPING] = [
    headers_str,
    headers_str_bytes,
    headers_bytes_str,
    headers_bytes,
    headers_mixed,
    headers_mapping_str,
    headers_mapping_bytes,
    headers_mapping_mixed,
    headers_http,
]


def test_type_header_mapping_assignment() -> None:
    for h in all_header_variants:
        assigned: _TYPE_HEADER_MAPPING = h
        assert assigned is not None


def test_typing_functions_accept_header_variants() -> None:
    for h in all_header_variants:
        pm = PoolManager(headers=h)
        assert pm is not None

        proxy_pm = ProxyManager("http://proxy:8080", headers=h, proxy_headers=h)
        assert proxy_pm is not None

        cp = HTTPConnectionPool("localhost", headers=h)
        assert cp is not None

        https_cp = HTTPSConnectionPool("localhost", headers=h)
        assert https_cp is not None

        field = RequestField(name="field", data=b"data", headers=h)
        assert field is not None

        rm = RequestMethods(headers=h)
        assert rm is not None

        if SOCKSProxyManager is not None:
            socks = SOCKSProxyManager("socks5://localhost:1080", headers=h)
            assert socks is not None


def test_putheader_accepts_bytes_and_str() -> None:
    conn = HTTPConnection("localhost")
    conn.putrequest("GET", "/")
    # Verify putheader type signature allows both str and bytes
    conn.putheader("X-Custom", "val")
    conn.putheader(b"X-Custom-Bytes", b"val")
    conn.putheader(b"X-Custom-Mixed", "val")
    conn.putheader("X-Custom-Mixed2", b"val")


def test_set_tunnel_accepts_bytes_headers() -> None:
    conn = HTTPConnection("localhost")
    headers: dict[str | bytes, str | bytes] = {
        b"Proxy-Authorization": b"basic",
        "X-Custom": "val",
    }
    conn.set_tunnel(
        "example.com",
        443,
        headers=headers,
    )
    tunnel_headers = getattr(conn, "_tunnel_headers", {})
    assert tunnel_headers["Proxy-Authorization"] == "basic"
    assert tunnel_headers["X-Custom"] == "val"
