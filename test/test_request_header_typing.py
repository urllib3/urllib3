from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    import urllib3
    from urllib3.connection import HTTPConnection

    def _request_headers_accept_str_and_bytes(
        str_headers: typing.Mapping[str, str],
        bytes_headers: typing.Mapping[bytes, bytes],
        mixed_headers: typing.Mapping[str | bytes, str | bytes],
    ) -> None:
        urllib3.request("GET", "https://example.com", headers=str_headers)
        urllib3.request("GET", "https://example.com", headers=bytes_headers)
        urllib3.request("GET", "https://example.com", headers=mixed_headers)

        pool = urllib3.HTTPConnectionPool("example.com", headers=bytes_headers)
        pool.request("GET", "/", headers=mixed_headers)

        manager = urllib3.PoolManager(headers=mixed_headers)
        manager.request("GET", "https://example.com", headers=bytes_headers)

        proxy = urllib3.ProxyManager(
            "http://proxy.example.com",
            headers=str_headers,
            proxy_headers=bytes_headers,
        )
        proxy.request("GET", "https://example.com", headers=mixed_headers)

        connection = HTTPConnection("example.com")
        connection.set_tunnel("example.com", headers=bytes_headers)
        connection.request("GET", "/", headers=mixed_headers)
