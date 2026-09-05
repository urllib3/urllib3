from __future__ import annotations

import urllib3


def _check_request_headers_accept_str_and_bytes() -> None:
    headers: dict[str | bytes, str | bytes] = {
        "User-Agent": "urllib3-typing-test",
        b"X-Bytes": b"value",
    }

    urllib3.request("GET", "https://example.com", headers=headers)
    urllib3.PoolManager().request("GET", "https://example.com", headers=headers)
    urllib3.HTTPConnectionPool("example.com").request("GET", "/", headers=headers)
