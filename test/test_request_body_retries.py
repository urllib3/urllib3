from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest

import urllib3
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.exceptions import UnrewindableBodyError
from urllib3.response import BaseHTTPResponse
from urllib3.util.request import _wrap_iterator_body


@contextmanager
def server_with_retry_response(
    first_status: int = 503,
) -> Iterator[tuple[str, list[bytes]]]:
    received_bodies: list[bytes] = []

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self) -> None:
            if self.headers.get("Transfer-Encoding") == "chunked":
                chunks: list[bytes] = []
                while True:
                    size = int(self.rfile.readline().split(b";", 1)[0].strip(), 16)
                    if size == 0:
                        self.rfile.readline()
                        break
                    chunks.append(self.rfile.read(size))
                    self.rfile.readline()
                body = b"".join(chunks)
            else:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))

            received_bodies.append(body)
            if len(received_bodies) == 1:
                self.send_response(first_status)
                if first_status == 503:
                    self.send_header("Retry-After", "0")
                elif first_status in (301, 302, 307, 308):
                    self.send_header("Location", "/redirected")
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/upload", received_bodies
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


@pytest.mark.parametrize(
    "body_factory",
    [
        pytest.param(
            lambda: (part for part in (b"PAYLOAD-1", b"PAYLOAD-2")),
            id="generator",
        ),
        pytest.param(lambda: iter([b"PAYLOAD-1", b"PAYLOAD-2"]), id="list-iterator"),
        pytest.param(
            lambda: map(lambda part: part, (b"PAYLOAD-1", b"PAYLOAD-2")),
            id="map",
        ),
    ],
)
@pytest.mark.parametrize("first_status", [503, 307], ids=["status-retry", "redirect"])
def test_retry_does_not_silently_resend_an_exhausted_iterator(
    body_factory: Callable[[], Iterator[bytes]], first_status: int
) -> None:
    with server_with_retry_response(first_status) as (url, received_bodies):
        with pytest.raises(UnrewindableBodyError):
            urllib3.request(
                "PUT",
                url,
                body=body_factory(),
                retries=urllib3.Retry(1, backoff_factor=0),
            )

    assert received_bodies == [b"PAYLOAD-1PAYLOAD-2"]


def test_connection_pool_request_rejects_reusing_consumed_iterator() -> None:
    with server_with_retry_response() as (url, received_bodies):
        parsed_url = urlsplit(url)
        assert parsed_url.hostname is not None
        assert parsed_url.port is not None
        with HTTPConnectionPool(parsed_url.hostname, parsed_url.port) as pool:
            with pytest.raises(UnrewindableBodyError):
                pool.request(
                    "PUT",
                    parsed_url.path,
                    body=iter([b"PAYLOAD-1", b"PAYLOAD-2"]),
                    retries=urllib3.Retry(1, backoff_factor=0),
                )

    assert received_bodies == [b"PAYLOAD-1PAYLOAD-2"]


def test_connect_error_before_body_consumption_can_be_retried() -> None:
    with server_with_retry_response(first_status=200) as (url, received_bodies):
        parsed_url = urlsplit(url)
        assert parsed_url.hostname is not None
        assert parsed_url.port is not None
        with HTTPConnectionPool(parsed_url.hostname, parsed_url.port) as pool:
            original_make_request = pool._make_request
            attempts = 0

            def fail_once(*args: Any, **kwargs: Any) -> BaseHTTPResponse:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise OSError("simulated connection failure")
                return original_make_request(*args, **kwargs)

            with patch.object(pool, "_make_request", side_effect=fail_once):
                response = pool.request(
                    "PUT",
                    parsed_url.path,
                    body=iter([b"PAYLOAD-1", b"PAYLOAD-2"]),
                    retries=urllib3.Retry(1, backoff_factor=0),
                )

    assert response.status == 200
    assert attempts == 2
    assert received_bodies == [b"PAYLOAD-1PAYLOAD-2"]


def test_reiterable_body_can_still_be_retried() -> None:
    payload = [b"PAYLOAD-1", b"PAYLOAD-2"]
    with server_with_retry_response() as (url, received_bodies):
        response = urllib3.request(
            "PUT",
            url,
            body=payload,
            retries=urllib3.Retry(1, backoff_factor=0),
        )

    assert response.status == 200
    assert received_bodies == [b"PAYLOAD-1PAYLOAD-2", b"PAYLOAD-1PAYLOAD-2"]


def test_iterator_can_be_reused_if_no_chunk_was_consumed() -> None:
    body = _wrap_iterator_body(iter([b"payload"]))
    assert body is not None
    iter(body)

    assert list(body) == [b"payload"]


def test_iterator_exception_makes_body_unrewindable() -> None:
    class FailingIterator:
        def __iter__(self) -> FailingIterator:
            return self

        def __next__(self) -> bytes:
            raise OSError("failed while reading body")

    body = _wrap_iterator_body(FailingIterator())
    assert body is not None
    with pytest.raises(OSError, match="failed while reading body"):
        next(iter(body))

    with pytest.raises(UnrewindableBodyError):
        iter(body)
