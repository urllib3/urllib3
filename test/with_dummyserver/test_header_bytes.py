from __future__ import annotations

import socket

import pytest

from dummyserver.testcase import SocketDummyServerTestCase
from urllib3 import HTTPConnectionPool
from urllib3._collections import HTTPHeaderDict
from urllib3.connection import HTTPConnection


class TestBinaryHeaderWire(SocketDummyServerTestCase):
    def test_connect_preserves_duplicate_binary_proxy_headers(self) -> None:
        received: list[bytes] = []

        def accept_tunnel(listener: socket.socket) -> None:
            with listener.accept()[0] as sock:
                sock.settimeout(5)
                request = b""
                while not request.endswith(b"\r\n\r\n"):
                    chunk = sock.recv(65536)
                    if not chunk:
                        raise RuntimeError("Client closed before CONNECT headers")
                    request += chunk
                received.append(request)
                sock.sendall(b"HTTP/1.1 200 OK\r\n\r\n")

        self._start_server(accept_tunnel)
        headers = HTTPHeaderDict({"X-Raw": b"\x80"})
        headers.add("X-Raw", b"\xff")
        connection = HTTPConnection(self.host, self.port)
        connection.set_tunnel("example.com", 443, headers=headers)
        try:
            connection.connect()
        finally:
            connection.close()
        assert b"X-Raw: \x80\r\nX-Raw: \xff\r\n" in received[0]
        assert headers.getlist("X-Raw") == [b"\x80", b"\xff"]

    @pytest.mark.parametrize("value", [b"", b"Sch\xf6nefeld/1.18.0", b"\x80\xff"])
    def test_combined_bytes_are_sent_without_transcoding(self, value: bytes) -> None:
        def echo_raw_request(listener: socket.socket) -> None:
            with listener.accept()[0] as sock:
                sock.settimeout(5)
                request = b""
                while not request.endswith(b"\r\n\r\n"):
                    chunk = sock.recv(65536)
                    if not chunk:
                        raise RuntimeError(
                            "Client closed before sending request headers"
                        )
                    request += chunk
                sock.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: "
                    + str(len(request)).encode("ascii")
                    + b"\r\nConnection: close\r\n\r\n"
                    + request
                )

        self._start_server(echo_raw_request)
        headers = HTTPHeaderDict({"X-Raw": value})
        headers.add("X-Raw", b"next", combine=True)
        headers["X-Text"] = "unchanged"
        with HTTPConnectionPool(self.host, self.port) as pool:
            response = pool.request("GET", "/", headers=headers, retries=0)
        # Echo bytes in the response body so http.client cannot decode them.
        assert b"X-Raw: " + value + b", next\r\n" in response.data
        assert b"X-Text: unchanged\r\n" in response.data
