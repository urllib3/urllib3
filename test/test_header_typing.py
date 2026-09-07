from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    import urllib3
    from urllib3 import HTTPConnectionPool, HTTPSConnectionPool
    from urllib3._collections import HTTPHeaderDict
    from urllib3._request_methods import RequestMethods
    from urllib3.connection import HTTPConnection
    from urllib3.contrib.emscripten.connection import EmscriptenHTTPConnection
    from urllib3.contrib.socks import SOCKSProxyManager
    from urllib3.poolmanager import PoolManager, ProxyManager

    headers_str: typing.Mapping[str, str] = {"X-Header": "value"}
    headers_str_bytes: typing.Mapping[str, bytes] = {"X-Header": b"value"}
    headers_bytes_str: typing.Mapping[bytes, str] = {b"X-Header": "value"}
    headers_bytes: typing.Mapping[bytes, bytes] = {b"X-Header": b"value"}
    headers_mixed: typing.Mapping[str | bytes, str | bytes] = {
        "X-String": b"bytes",
        b"X-Bytes": "string",
    }
    headers_http = HTTPHeaderDict({"X-Header": "value"})
    response = urllib3.HTTPResponse(headers={"X-Response": "value"})
    typing.assert_type(response.headers["X-Response"], str)

    for headers in (
        headers_str,
        headers_str_bytes,
        headers_bytes_str,
        headers_bytes,
        headers_mixed,
        headers_http,
    ):
        urllib3.request("GET", "https://example.com", headers=headers)
        PoolManager(headers=headers).request(
            "GET", "https://example.com", headers=headers
        )
        HTTPConnectionPool("example.com", headers=headers).request(
            "GET", "/", headers=headers
        )

    request_methods = RequestMethods(headers=headers_mixed)
    request_methods.urlopen("GET", "https://example.com", headers=headers_mixed)
    request_methods.request("GET", "https://example.com", headers=headers_mixed)
    request_methods.request_encode_url(
        "GET", "https://example.com", headers=headers_mixed
    )
    request_methods.request_encode_body(
        "POST", "https://example.com", headers=headers_mixed
    )

    HTTPConnection("example.com").request("GET", "/", headers=headers_mixed)
    HTTPConnection("example.com").putheader(b"X-Header", b"value")
    HTTPConnection("example.com").request_chunked("GET", "/", headers=headers_mixed)
    HTTPSConnectionPool("example.com", headers=headers_mixed).request(
        "GET", "/", headers=headers_mixed
    )
    ProxyManager(
        "http://proxy.example.com",
        headers=headers_mixed,
        proxy_headers=headers_mixed,
    )
    SOCKSProxyManager("socks5://proxy.example.com", headers=headers_mixed)
    EmscriptenHTTPConnection("example.com").request("GET", "/", headers=headers_mixed)
