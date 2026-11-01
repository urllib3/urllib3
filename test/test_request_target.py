from __future__ import annotations

import io
import socket
from collections.abc import Iterator
from unittest import mock

import pytest

from urllib3 import HTTPConnectionPool, PoolManager, ProxyManager
from urllib3.connection import HTTPConnection


@pytest.fixture
def request_socket() -> Iterator[mock.MagicMock]:
    # Keep request serialization and response parsing real; replace only the
    # transport so no server can normalize the request target before we see it.
    sock = mock.MagicMock(spec=socket.socket)
    with io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n") as response:
        sock.makefile.return_value = response
        with mock.patch.object(HTTPConnection, "_new_conn", return_value=sock):
            yield sock


class TestRequestTarget:
    @pytest.mark.parametrize("client", ["pool", "manager", "proxy"])
    @pytest.mark.parametrize(
        ["target", "expected_target"],
        [
            ("/echo_uri", b"/echo_uri"),
            ("/echo_uri?", b"/echo_uri?"),
            ("/echo_uri?q=1#fragment", b"/echo_uri?q=1"),
            ("/echo_uri?#", b"/echo_uri?"),
            ("/echo_uri#?", b"/echo_uri"),
            ("/echo_uri#?#", b"/echo_uri"),
            ("/echo_uri#!", b"/echo_uri"),
            ("/echo_uri#!#", b"/echo_uri"),
            ("/echo_uri??#", b"/echo_uri??"),
            ("/echo_uri?%3f#", b"/echo_uri?%3F"),
            ("/echo_uri?%3F#", b"/echo_uri?%3F"),
            ("/echo_uri?[]", b"/echo_uri?%5B%5D"),
            ("/a%2fb?q=%23%26%3d", b"/a%2Fb?q=%23%26%3D"),
            ("/a%23b%3fc?q=%23%3f#fragment", b"/a%23b%3Fc?q=%23%3F"),
            ("/a%252Fb?q=%253F", b"/a%252Fb?q=%253F"),
            ("/echo_uri?q=1&q=2&empty=", b"/echo_uri?q=1&q=2&empty="),
            ("/echo_uri?q=a+b%20c", b"/echo_uri?q=a+b%20c"),
            ("/echo_uri?q=/a?b", b"/echo_uri?q=/a?b"),
            ("/echo_params?q=\r&k=\n \n", b"/echo_params?q=%0D&k=%0A%20%0A"),
            ("/a b?q=c d", b"/a%20b?q=c%20d"),
            ("/café?q=雪", b"/caf%C3%A9?q=%E9%9B%AA"),
            ("/a;b:c@d?q=$!,'()*;:@", b"/a;b:c@d?q=$!,'()*;:@"),
        ],
    )
    def test_encoded_target(
        self,
        request_socket: mock.MagicMock,
        client: str,
        target: str,
        expected_target: bytes,
    ) -> None:
        if client == "pool":
            with HTTPConnectionPool("example.com") as pool:
                response = pool.request("GET", target, retries=False)
        else:
            manager = (
                ProxyManager("http://proxy.example:8080")
                if client == "proxy"
                else PoolManager()
            )
            with manager:
                response = manager.request(
                    "GET", "http://example.com" + target, retries=False
                )
            if client == "proxy":
                expected_target = b"http://example.com" + expected_target

        assert response.status == 200
        sent = b"".join(call.args[0] for call in request_socket.sendall.call_args_list)
        assert sent.partition(b"\r\n")[0] == b"GET " + expected_target + b" HTTP/1.1"
        assert sent.count(b"\r\n\r\n") == 1

    def test_pool_preserves_path_dot_segments(
        self, request_socket: mock.MagicMock
    ) -> None:
        with HTTPConnectionPool("example.com") as pool:
            response = pool.request("GET", "/echo_uri/seg0/../seg2", retries=False)

        assert response.status == 200
        sent = b"".join(call.args[0] for call in request_socket.sendall.call_args_list)
        assert sent.partition(b"\r\n")[0] == b"GET /echo_uri/seg0/../seg2 HTTP/1.1"
