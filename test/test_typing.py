from __future__ import annotations

import typing

import urllib3

if typing.TYPE_CHECKING:

    def check_request_header_types() -> None:
        str_headers: dict[str, str] = {"Accept": "application/json"}
        str_bytes_headers: dict[str, bytes] = {"X-Token": b"abc"}
        bytes_str_headers: dict[bytes, str] = {b"X-Token": "abc"}
        bytes_headers: dict[bytes, bytes] = {b"X-Token": b"abc"}
        mixed_headers: dict[str | bytes, str | bytes] = {
            "Accept": "application/json",
            b"X-Token": b"abc",
        }
        header_dict = urllib3.HTTPHeaderDict({"Accept": "application/json"})

        urllib3.request("GET", "https://example.com", headers=str_headers)
        urllib3.request("GET", "https://example.com", headers=str_bytes_headers)
        urllib3.request("GET", "https://example.com", headers=bytes_str_headers)
        urllib3.request("GET", "https://example.com", headers=bytes_headers)
        urllib3.request("GET", "https://example.com", headers=mixed_headers)
        urllib3.request("GET", "https://example.com", headers=header_dict)

        pool = urllib3.PoolManager(headers=str_headers)
        pool.request("GET", "https://example.com", headers=str_bytes_headers)
        pool.request_encode_url("GET", "https://example.com", headers=bytes_str_headers)
        pool.request_encode_body("POST", "https://example.com", headers=bytes_headers)

        connection_pool = urllib3.HTTPConnectionPool(
            "example.com", headers=mixed_headers
        )
        connection_pool.request("GET", "/", headers=header_dict)

        proxy = urllib3.ProxyManager(
            "http://example.com",
            headers=bytes_str_headers,
            proxy_headers=str_bytes_headers,
        )
        proxy.request("GET", "https://example.com", headers=mixed_headers)
