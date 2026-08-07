from __future__ import annotations

import typing

import pytest

import urllib3.http2
from dummyserver.socketserver import DEFAULT_CA
from dummyserver.testcase import HTTPSHypercornDummyServerTestCase
from urllib3 import HTTPSConnectionPool
from urllib3.exceptions import DecodeError, ReadTimeoutError
from urllib3.http2.connection import HTTP2Response
from urllib3.util.timeout import Timeout


@pytest.fixture(autouse=True)
def inject_http2() -> typing.Generator[None]:
    urllib3.http2.inject_into_urllib3()
    try:
        yield
    finally:
        urllib3.http2.extract_from_urllib3()


class TestHTTP2ResponseBody(HTTPSHypercornDummyServerTestCase):
    def _pool(self, **kwargs: typing.Any) -> HTTPSConnectionPool:
        return HTTPSConnectionPool(self.host, self.port, ca_certs=DEFAULT_CA, **kwargs)

    def test_preloaded_response(self) -> None:
        with self._pool() as pool:
            r = pool.request("GET", "/")

        assert isinstance(r, HTTP2Response)
        assert r.status == 200
        assert r.version == 20
        assert r.version_string == "HTTP/2"
        assert r.headers["server"] == "hypercorn-h2"
        assert r.data == b"Dummy server!"

    def test_streamed_response(self) -> None:
        with self._pool() as pool:
            r = pool.request("GET", "/chunked", preload_content=False)
            assert isinstance(r, HTTP2Response)
            assert list(r.stream(4)) == [b"1231", b"2312", b"3123"]

    def test_partial_reads(self) -> None:
        with self._pool() as pool:
            r = pool.request("GET", "/", preload_content=False)
            assert r.read(5) == b"Dummy"
            assert r.read(1) == b" "
            assert r.read() == b"server!"
            assert r.read() == b""

    @pytest.mark.parametrize("encoding", ["gzip", "deflate"])
    def test_decodes_compressed_response(self, encoding: str) -> None:
        with self._pool() as pool:
            r = pool.request(
                "GET", "/encodingrequest", headers={"Accept-Encoding": encoding}
            )
            assert r.headers["content-encoding"] == encoding
            assert r.data == b"hello, world!"

    def test_decodes_compressed_response_streamed(self) -> None:
        with self._pool() as pool:
            r = pool.request(
                "GET",
                "/encodingrequest",
                headers={"Accept-Encoding": "gzip"},
                preload_content=False,
            )
            assert b"".join(r.stream(3)) == b"hello, world!"

    def test_decode_content_false_returns_compressed_bytes(self) -> None:
        with self._pool() as pool:
            r = pool.request(
                "GET",
                "/encodingrequest",
                headers={"Accept-Encoding": "gzip"},
                decode_content=False,
            )
            # gzip magic number proves the body was left compressed.
            assert r.data[:2] == b"\x1f\x8b"

    def test_invalid_compressed_body_raises_decode_error(self) -> None:
        with self._pool() as pool:
            with pytest.raises(DecodeError):
                pool.request(
                    "GET",
                    "/encodingrequest",
                    headers={"Accept-Encoding": "garbage-gzip"},
                    retries=False,
                )

    def test_response_larger_than_flow_control_window(self) -> None:
        # 300kB is several times the default 64kB flow control window, so
        # this only completes if HTTP2Response acknowledges received data
        # while streaming.
        with self._pool() as pool:
            r = pool.request(
                "GET",
                "/large_response?size=300000",
                preload_content=False,
                retries=False,
            )
            received = sum(len(chunk) for chunk in r.stream(16384))
            assert received == 300000

    def test_connection_released_to_pool_after_body_consumed(self) -> None:
        # Connection reuse across sequential requests is not new behavior;
        # this proves the release path: with preload_content=False the
        # connection must return to the pool once the body is consumed.
        with self._pool() as pool:
            r1 = pool.request("GET", "/", preload_content=False)
            assert r1.read() == b"Dummy server!"
            r2 = pool.request("GET", "/")
            assert r2.data == b"Dummy server!"
            assert pool.num_connections == 1

    def test_read_timeout_is_respected(self) -> None:
        with self._pool(retries=False) as pool:
            with pytest.raises(ReadTimeoutError):
                pool.request(
                    "GET",
                    "/slow",
                    timeout=Timeout(connect=5, read=0.25),
                )

    def test_json(self) -> None:
        with self._pool() as pool:
            r = pool.request(
                "POST",
                "/echo_json",
                body=b'{"hello": "world"}',
                headers={"Content-Type": "application/json"},
            )
            assert r.json() == {"hello": "world"}

    def test_head_response_has_no_body(self) -> None:
        with self._pool() as pool:
            r = pool.request("HEAD", "/", preload_content=False)
            assert r.status == 200
            assert r.read() == b""
