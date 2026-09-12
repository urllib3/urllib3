from __future__ import annotations

import socket
import ssl

import pytest
import trustme

from dummyserver.socketserver import SocketServerThread
from dummyserver.testcase import SocketDummyServerTestCase
from urllib3 import HTTPConnectionPool, PoolManager, ProxyManager
from urllib3.util import make_headers


def read_request(sock: socket.socket) -> bytes:
    sock.settimeout(5)
    request = b""
    while not request.endswith(b"\r\n\r\n"):
        chunk = sock.recv(65536)
        if not chunk:
            raise RuntimeError("Incomplete request")
        request += chunk
    return request


class TestURLAuthWire(SocketDummyServerTestCase):
    @pytest.mark.parametrize("mode", ["pool", "manager", "proxy"])
    def test_wire_headers_and_target(
        self, mode: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        requests: list[bytes] = []

        def serve(listener: socket.socket) -> None:
            listener.settimeout(5)
            with listener.accept()[0] as sock:
                requests.append(read_request(sock))
                sock.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

        self._start_server(serve)
        client = (
            ProxyManager(f"http://proxyuser:proxypass@{self.host}:{self.port}")
            if mode == "proxy"
            else (
                PoolManager()
                if mode == "manager"
                else HTTPConnectionPool(self.host, self.port)
            )
        )
        with client:
            response = client.request(
                "GET",
                f"http://alice:s%65cret@{self.host}:{self.port}/resource",
                retries=False,
                timeout=2,
            )
            assert response.data == b"ok"
        raw = requests[0]
        assert b"@" not in raw.split(b"\r\n", 1)[0]
        assert (
            b"Authorization: "
            + make_headers(basic_auth="alice:secret")["authorization"].encode()
            + b"\r\n"
            in raw
        )
        proxy_header = (
            b"Proxy-Authorization: "
            + make_headers(proxy_basic_auth="proxyuser:proxypass")[
                "proxy-authorization"
            ].encode()
            + b"\r\n"
        )
        assert (proxy_header in raw) is (mode == "proxy")
        assert "secret" not in caplog.text
        assert "proxypass" not in caplog.text

    @pytest.mark.parametrize("cross_host", [False, True])
    @pytest.mark.parametrize("proxy", [False, True])
    def test_redirect_does_not_reintroduce_url_credentials(
        self, cross_host: bool, proxy: bool
    ) -> None:
        requests: list[bytes] = []
        origin_host = "origin.invalid" if proxy else self.host
        target_host = (
            (
                "other.invalid"
                if proxy
                else "[::1]" if SocketServerThread.USE_IPV6 else "127.0.0.1"
            )
            if cross_host
            else origin_host
        )

        def serve(listener: socket.socket) -> None:
            listener.settimeout(5)
            for index in range(2):
                with listener.accept()[0] as sock:
                    requests.append(read_request(sock))
                    if index == 0:
                        response = f"HTTP/1.1 302 Found\r\nLocation: http://{target_host}:{self.port}/next\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode()
                    else:
                        response = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
                    sock.sendall(response)

        self._start_server(serve)
        with (
            ProxyManager(f"http://{self.host}:{self.port}") if proxy else PoolManager()
        ) as client:
            response = client.request(
                "GET",
                f"http://alice:secret@{origin_host}:{self.port}/first",
                retries=1,
                timeout=2,
            )
            assert response.data == b"ok"
        assert b"Authorization:" in requests[0]
        assert (b"Authorization:" in requests[1]) is not cross_host
        assert all(b"@" not in request.split(b"\r\n", 1)[0] for request in requests)

    @pytest.mark.parametrize("request_proxy_auth", [False, True])
    def test_connect_keeps_proxy_credentials_out_of_origin_request(
        self, request_proxy_auth: bool
    ) -> None:
        ca = trustme.CA()
        certificate = ca.issue_cert("localhost")
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        certificate.configure_cert(server_context)
        client_context = ssl.create_default_context()
        ca.configure_trust(client_context)
        requests: list[bytes] = []

        def serve(listener: socket.socket) -> None:
            listener.settimeout(5)
            with listener.accept()[0] as sock:
                requests.append(read_request(sock))
                sock.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                with server_context.wrap_socket(sock, server_side=True) as tls:
                    requests.append(read_request(tls))
                    tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")

        self._start_server(serve)
        with ProxyManager(
            f"http://proxyuser:proxypass@{self.host}:{self.port}",
            ssl_context=client_context,
        ) as client:
            response = client.request(
                "GET",
                "https://alice:secret@localhost:443/resource",
                headers=(
                    make_headers(proxy_basic_auth="proxyuser:proxypass")
                    if request_proxy_auth
                    else {}
                ),
                retries=False,
                timeout=2,
            )
            assert response.data == b"ok"
        assert requests[0].startswith(b"CONNECT localhost:443 ")
        assert (
            b"Proxy-Authorization: "
            + make_headers(proxy_basic_auth="proxyuser:proxypass")[
                "proxy-authorization"
            ].encode()
            + b"\r\n"
            in requests[0]
        )
        assert (
            b"Authorization: "
            + make_headers(basic_auth="alice:secret")["authorization"].encode()
            + b"\r\n"
            not in requests[0]
        )
        assert requests[1].startswith(b"GET /resource ")
        assert b"proxy-authorization:" not in requests[1].lower()
        assert (
            b"Authorization: "
            + make_headers(basic_auth="alice:secret")["authorization"].encode()
            + b"\r\n"
            in requests[1]
        )
