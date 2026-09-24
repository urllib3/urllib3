from __future__ import annotations

import socket
import ssl
from threading import Event

from dummyserver.socketserver import DEFAULT_CA, DEFAULT_CERTS
from dummyserver.testcase import SocketDummyServerTestCase
from urllib3 import proxy_from_url


class TestURLAuthOnWire(SocketDummyServerTestCase):
    def test_http_forward_separates_proxy_credential_name(self) -> None:
        captured: dict[str, bytes] = {}
        done = Event()

        def proxy_handler(listener: socket.socket) -> None:
            sock = listener.accept()[0]
            sock.settimeout(5)
            try:
                request = b""
                while not request.endswith(b"\r\n\r\n"):
                    chunk = sock.recv(65536)
                    assert chunk, "connection closed before request headers"
                    request += chunk
                captured["request"] = request
                sock.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
                    b"Connection: close\r\n\r\nOK"
                )
            finally:
                sock.close()
                done.set()

        self._start_server(proxy_handler)
        proxy_url = f"http://proxy-user:proxy-pass@{self.host}:{self.port}"
        origin_url = "http://origin-user:origin-pass@example.com/path"

        with proxy_from_url(proxy_url) as manager:
            response = manager.request("GET", origin_url, timeout=5, retries=False)
            assert response.status == 200

        assert done.wait(5)
        assert b"GET http://example.com/path HTTP/1.1" in captured["request"]
        assert (
            b"Proxy-Authorization: Basic cHJveHktdXNlcjpwcm94eS1wYXNz"
            in captured["request"]
        )
        assert (
            b"Authorization: Basic b3JpZ2luLXVzZXI6b3JpZ2luLXBhc3M="
            in captured["request"]
        )

    def test_connect_separates_proxy_and_origin_credentials(self) -> None:
        captured: dict[str, bytes] = {}
        done = Event()

        def proxy_handler(listener: socket.socket) -> None:
            sock = listener.accept()[0]
            sock.settimeout(5)
            try:
                request = b""
                while not request.endswith(b"\r\n\r\n"):
                    chunk = sock.recv(65536)
                    assert chunk, "connection closed before CONNECT headers"
                    request += chunk
                captured["connect"] = request
                sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")

                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(
                    DEFAULT_CERTS["certfile"], DEFAULT_CERTS["keyfile"]
                )
                tls_sock = context.wrap_socket(sock, server_side=True)
                request = b""
                while not request.endswith(b"\r\n\r\n"):
                    chunk = tls_sock.recv(65536)
                    assert chunk, "connection closed before origin headers"
                    request += chunk
                captured["origin"] = request
                tls_sock.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n"
                    b"Connection: close\r\n\r\nOK"
                )
                tls_sock.close()
            finally:
                done.set()

        self._start_server(proxy_handler)
        proxy_url = f"http://proxy-user:proxy-pass@{self.host}:{self.port}"
        origin_url = f"https://origin-user:origin-pass@{self.host}:443/"

        with proxy_from_url(proxy_url, ca_certs=DEFAULT_CA) as manager:
            response = manager.request("GET", origin_url, timeout=5, retries=False)
            assert response.status == 200

        assert done.wait(5)
        assert (
            b"Proxy-Authorization: Basic cHJveHktdXNlcjpwcm94eS1wYXNz"
            in captured["connect"]
        )
        assert b"\r\nAuthorization:" not in captured["connect"]
        assert (
            b"Authorization: Basic b3JpZ2luLXVzZXI6b3JpZ2luLXBhc3M="
            in captured["origin"]
        )
        assert b"Proxy-Authorization:" not in captured["origin"]
