from __future__ import annotations

import typing

import urllib3

if typing.TYPE_CHECKING:

    def check_request_header_types() -> None:
        string_headers: dict[str, str] = {"accept": "application/json"}
        bytes_value_headers: dict[str, bytes] = {"x-token": b"abc"}
        bytes_key_headers: dict[bytes, str] = {b"x-token": "abc"}
        bytes_headers: dict[bytes, bytes] = {b"x-token": b"abc"}
        mixed_headers: dict[str | bytes, str | bytes] = {
            "accept": "application/json",
            b"x-token": b"abc",
        }
        header_dict = urllib3.HTTPHeaderDict({"accept": "application/json"})

        urllib3.request("GET", "https://example.com", headers=string_headers)
        urllib3.request("GET", "https://example.com", headers=bytes_value_headers)
        urllib3.request("GET", "https://example.com", headers=bytes_key_headers)
        urllib3.request("GET", "https://example.com", headers=bytes_headers)
        urllib3.request("GET", "https://example.com", headers=mixed_headers)
        urllib3.request("GET", "https://example.com", headers=header_dict)

        pool = urllib3.PoolManager(headers=string_headers)
        pool.request("GET", "https://example.com", headers=bytes_value_headers)
        pool.request_encode_url("GET", "https://example.com", headers=bytes_key_headers)
        pool.request_encode_body("POST", "https://example.com", headers=bytes_headers)

        connection_pool = urllib3.HTTPConnectionPool(
            "example.com", headers=mixed_headers
        )
        connection_pool.request("GET", "/", headers=header_dict)

        proxy = urllib3.ProxyManager(
            "http://example.com",
            headers=bytes_key_headers,
            proxy_headers=bytes_value_headers,
        )
        proxy.request("GET", "https://example.com", headers=mixed_headers)
