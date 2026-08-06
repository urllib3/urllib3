from __future__ import annotations

from hypercorn.typing import HTTPScope

from dummyserver.asgi_proxy import _upstream_url_from_scope


def _scope(**kwargs: object) -> HTTPScope:
    base: dict[str, object] = {
        "type": "http",
        "asgi": {"spec_version": "2.3", "version": "3.0"},
        "http_version": "2",
        "method": "GET",
        "scheme": "https",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": None,
        "server": ("localhost", 443),
        "state": {},
        "extensions": {},
    }
    base.update(kwargs)
    return base  # type: ignore[return-value]


def test_upstream_url_keeps_http11_absolute_form() -> None:
    scope = _scope(
        http_version="1.1",
        path="http://target.example:8080/path",
        query_string=b"q=1",
        headers=[(b"host", b"target.example:8080")],
    )
    assert _upstream_url_from_scope(scope) == "http://target.example:8080/path?q=1"


def test_upstream_url_rebuilds_http2_origin_form_from_host() -> None:
    scope = _scope(
        path="/path",
        raw_path=b"/path",
        query_string=b"q=1",
        headers=[(b"host", b"target.example:9443")],
    )
    assert _upstream_url_from_scope(scope) == "https://target.example:9443/path?q=1"
