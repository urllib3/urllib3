from __future__ import annotations

import io
import select
import socket
import threading
import typing

import h2.config
import h2.connection
import h2.events
import h2.settings
import pytest

import urllib3.connection
import urllib3.http2
from urllib3.connection import HTTPConnection, ProxyConfig
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.exceptions import ProtocolError
from urllib3.http2.connection import (
    HTTP2CleartextConnection,
    HTTP2UpgradeConnection,
)
from urllib3.util import SKIP_HEADER, parse_url


class H2CServer:
    def __init__(
        self,
        mode: typing.Literal[
            "prior",
            "upgrade-coalesced",
            "upgrade-continue",
            "upgrade-early-hints",
            "upgrade-too-many-continue",
            "upgrade-fragmented",
            "upgrade-invalid-connection",
            "upgrade-invalid-token",
            "fallback",
            "fallback-close",
            "fallback-continue",
            "fallback-early-hints",
            "fallback-malformed",
        ],
        *,
        request_count: int = 1,
        after_first: typing.Literal["none", "control", "goaway", "eof"] = "none",
    ) -> None:
        self.mode = mode
        self.request_count = request_count
        self.after_first = after_first
        self.requests: list[bytes] = []
        self.bodies: list[bytes] = []
        self.streams: list[int] = []
        self.control_acks: list[str] = []
        self.errors: list[BaseException] = []
        self.accept_count = 0
        self.release_after_first = threading.Event()
        self.after_first_sent = threading.Event()
        self.control_acks_received = threading.Event()
        self._ready = threading.Event()
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self.host, self.port = self._listener.getsockname()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> H2CServer:
        self._thread.start()
        assert self._ready.wait(2)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: typing.Any,
    ) -> None:
        self._listener.close()
        self._thread.join(3)
        assert not self._thread.is_alive(), "h2c server did not terminate"
        if exc_type is None:
            assert self.errors == []

    def _run(self) -> None:
        self._ready.set()
        try:
            conn, _ = self._listener.accept()
            self.accept_count += 1
            conn.settimeout(2)
            with conn:
                if self.mode == "prior":
                    self._serve_prior(conn)
                elif self.mode.startswith("fallback"):
                    self._serve_fallback(conn)
                else:
                    self._serve_upgrade(conn)
        except BaseException as e:
            self.errors.append(e)

    def _serve_prior(self, conn: socket.socket) -> None:
        server = h2.connection.H2Connection(
            config=h2.config.H2Configuration(client_side=False)
        )
        server.initiate_connection()
        conn.sendall(server.data_to_send())
        self._receive_h2_requests(conn, server, start_index=0)

    def _serve_upgrade(self, conn: socket.socket) -> None:
        request, body = _read_http1_request(conn)
        self.requests.append(request)
        self.bodies.append(body)

        settings = _header_value(request, b"http2-settings")
        assert settings is not None
        assert (
            sum(
                line.lower().startswith(b"http2-settings:")
                for line in request.split(b"\r\n")
            )
            == 1
        )
        assert b"=" not in settings
        assert _header_value(request, b"upgrade") == b"h2c"
        connection_tokens = {
            token.strip().lower()
            for token in (_header_value(request, b"connection") or b"").split(b",")
        }
        assert {b"upgrade", b"http2-settings"} <= connection_tokens

        if self.mode == "upgrade-invalid-token":
            conn.sendall(
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Connection: Upgrade\r\n"
                b"Upgrade: websocket\r\n\r\n"
            )
            return
        if self.mode == "upgrade-invalid-connection":
            conn.sendall(
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Connection: keep-alive\r\n"
                b"Upgrade: h2c\r\n\r\n"
            )
            return

        if self.mode == "upgrade-too-many-continue":
            conn.sendall(b"HTTP/1.1 100 Continue\r\n\r\n" * 11)
            return

        server = h2.connection.H2Connection(
            config=h2.config.H2Configuration(client_side=False)
        )
        server.initiate_upgrade_connection(settings)
        self.streams.append(1)
        _send_h2_response(server, 1, b"upgraded")
        response = (
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Connection: Upgrade\r\n"
            b"Upgrade: h2c\r\n\r\n" + server.data_to_send()
        )
        if self.mode == "upgrade-continue":
            response = b"HTTP/1.1 100 Continue\r\n\r\n" + response
        if self.mode == "upgrade-early-hints":
            response = (
                b"HTTP/1.1 103 Early Hints\r\nLink: </style.css>; rel=preload\r\n\r\n"
                + response
            )
        if self.mode == "upgrade-fragmented":
            for byte in response:
                conn.sendall(bytes((byte,)))
        else:
            # RFC 7540 permits the server preface and stream-1 response to
            # immediately follow the 101, including in the same TCP packet.
            conn.sendall(response)

        # The client preface is still required even though the response was
        # already available. Parsing it proves the transition completed.
        received = conn.recv(65535)
        server.receive_data(received)
        if not self._run_after_first_action(conn, server):
            return
        if self.request_count > 1:
            self._receive_h2_requests(conn, server, start_index=1)

    def _serve_fallback(self, conn: socket.socket) -> None:
        for index in range(self.request_count):
            request, body = _read_http1_request(conn)
            self.requests.append(request)
            self.bodies.append(body)
            payload = f"fallback-{index}".encode()
            response = (
                b"HTTP/1.1 200 OK\r\n"
                + f"Content-Length: {len(payload)}\r\n".encode()
                + (
                    b"Connection: close\r\n"
                    if self.mode == "fallback-close"
                    else b"Connection: keep-alive\r\n"
                )
            )
            if self.mode == "fallback-malformed":
                response += b"BadHeader\r\n"
            response += b"\r\n" + payload
            if self.mode == "fallback-continue":
                response = b"HTTP/1.1 100 Continue\r\n\r\n" + response
            if self.mode == "fallback-early-hints":
                response = (
                    b"HTTP/1.1 103 Early Hints\r\n"
                    b"Link: </style.css>; rel=preload\r\n\r\n" + response
                )
            conn.sendall(response)

    def _receive_h2_requests(
        self,
        conn: socket.socket,
        server: h2.connection.H2Connection,
        *,
        start_index: int,
    ) -> None:
        responses = 0
        ran_after_first_action = start_index > 0
        while responses < self.request_count - start_index:
            received = conn.recv(65535)
            if not received:
                raise AssertionError("client closed before receiving all responses")
            for event in server.receive_data(received):
                if isinstance(event, h2.events.RequestReceived):
                    headers = dict(event.headers)
                    self.streams.append(event.stream_id)
                    self.requests.append(repr(headers).encode())
                    _send_h2_response(
                        server,
                        event.stream_id,
                        f"prior-{start_index + responses}".encode(),
                    )
                    responses += 1
                elif isinstance(event, h2.events.DataReceived):
                    server.acknowledge_received_data(
                        event.flow_controlled_length, event.stream_id
                    )
                else:
                    self._record_control_ack(event)
            if data := server.data_to_send():
                conn.sendall(data)
            if responses == 1 and not ran_after_first_action:
                ran_after_first_action = True
                if not self._run_after_first_action(conn, server):
                    return
        while self.after_first == "control" and not {
            "ping",
            "settings",
        }.issubset(self.control_acks):
            received = conn.recv(65535)
            if not received:
                raise AssertionError(
                    "client closed before acknowledging control frames"
                )
            for event in server.receive_data(received):
                self._record_control_ack(event)
        if self.after_first == "control":
            self.control_acks_received.set()

    def _record_control_ack(self, event: h2.events.Event) -> None:
        if isinstance(event, h2.events.PingAckReceived):
            self.control_acks.append("ping")
        elif isinstance(event, h2.events.SettingsAcknowledged):
            self.control_acks.append("settings")

    def _run_after_first_action(
        self, conn: socket.socket, server: h2.connection.H2Connection
    ) -> bool:
        if self.after_first == "none":
            return True

        assert self.release_after_first.wait(2), "client didn't consume first response"
        if self.after_first == "control":
            self.control_acks.clear()
            server.ping(b"h2c-ping")
            server.update_settings(
                {h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 10}
            )
            conn.sendall(server.data_to_send())
            self.after_first_sent.set()
            return True
        if self.after_first == "goaway":
            server.close_connection(error_code=0)
            conn.sendall(server.data_to_send())
            self.after_first_sent.set()
            return False

        conn.shutdown(socket.SHUT_RDWR)
        self.after_first_sent.set()
        return False


class _OneByteRecvSocket:
    """Keep a real socket while making response fragmentation deterministic."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    def recv(self, size: int, flags: int = 0) -> bytes:
        return self._sock.recv(min(size, 1), flags)

    def __getattr__(self, name: str) -> typing.Any:
        return getattr(self._sock, name)


class _TrackingHTTP2UpgradeConnection(HTTP2UpgradeConnection):
    def __init__(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        self.receive_owners: list[object | None] = []
        super().__init__(*args, **kwargs)

    def _receive_events(
        self, *, stream_owner: object | None
    ) -> list[h2.events.Event] | None:
        self.receive_owners.append(stream_owner)
        return super()._receive_events(stream_owner=stream_owner)


def _read_http1_request(conn: socket.socket) -> tuple[bytes, bytes]:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            raise AssertionError("client closed during HTTP/1.1 headers")
        data.extend(chunk)
    marker = data.index(b"\r\n\r\n") + 4
    head = bytes(data[:marker])
    body = bytearray(data[marker:])
    if (_header_value(head, b"transfer-encoding") or b"").lower() == b"chunked":
        return head, _read_chunked_body(conn, body)
    content_length = int(_header_value(head, b"content-length") or b"0")
    while len(body) < content_length:
        body.extend(conn.recv(content_length - len(body)))
    return head, bytes(body[:content_length])


def _read_chunked_body(conn: socket.socket, initial: bytearray) -> bytes:
    encoded = initial
    decoded = bytearray()

    def read_line() -> bytes:
        while b"\r\n" not in encoded:
            encoded.extend(conn.recv(4096))
        marker = encoded.index(b"\r\n")
        line = bytes(encoded[:marker])
        del encoded[: marker + 2]
        return line

    while True:
        size = int(read_line().split(b";", 1)[0], 16)
        if size == 0:
            assert read_line() == b""
            return bytes(decoded)
        while len(encoded) < size + 2:
            encoded.extend(conn.recv(4096))
        decoded.extend(encoded[:size])
        assert encoded[size : size + 2] == b"\r\n"
        del encoded[: size + 2]


def _header_value(head: bytes, name: bytes) -> bytes | None:
    for line in head.split(b"\r\n")[1:]:
        if b":" in line:
            field, value = line.split(b":", 1)
            if field.lower() == name:
                return value.strip()
    return None


def _send_h2_response(
    conn: h2.connection.H2Connection, stream_id: int, body: bytes
) -> None:
    conn.send_headers(
        stream_id,
        [(b":status", b"200"), (b"content-length", str(len(body)).encode())],
    )
    conn.send_data(stream_id, body, end_stream=True)


def test_h2c_prior_knowledge_uses_cleartext_preface_and_http_scheme() -> None:
    with H2CServer("prior") as server:
        conn = HTTP2CleartextConnection(server.host, server.port, timeout=1)
        try:
            conn.request("GET", "/resource?q=1")
            response = conn.getresponse()
        finally:
            conn.close()

    assert response.status == 200
    assert response.data == b"prior-0"
    assert server.streams == [1]
    assert b"b':scheme': b'http'" in server.requests[0]
    assert b"b':path': b'/resource?q=1'" in server.requests[0]


def test_h2c_cleartext_connections_default_to_port_80() -> None:
    assert HTTP2CleartextConnection("example.test").port == 80
    assert HTTP2UpgradeConnection("example.test").port == 80


@pytest.mark.parametrize("mode", ["upgrade-coalesced", "upgrade-fragmented"])
def test_h2c_upgrade_preserves_immediate_or_fragmented_http2_bytes(
    mode: typing.Literal["upgrade-coalesced", "upgrade-fragmented"],
) -> None:
    with H2CServer(mode) as server:
        conn = _TrackingHTTP2UpgradeConnection(server.host, server.port, timeout=1)
        try:
            conn.request("GET", "/upgrade")
            if mode == "upgrade-fragmented":
                conn.sock = typing.cast(typing.Any, _OneByteRecvSocket(conn.sock))
            response = conn.getresponse()
            assert conn.receive_owners
            assert all(owner is conn for owner in conn.receive_owners)
            assert conn._h2_received_data == bytearray()
            assert conn._stream_owner is None
            assert conn._h2_stream is None
            assert conn._has_completed_response
        finally:
            conn.close()

    assert response.status == 200
    assert response.data == b"upgraded"
    assert server.streams == [1]


def test_h2c_upgrade_accepts_100_before_switching_protocols() -> None:
    with H2CServer("upgrade-continue") as server:
        conn = HTTP2UpgradeConnection(server.host, server.port, timeout=1)
        try:
            conn.request("POST", "/upgrade", body=b"body")
            response = conn.getresponse()
        finally:
            conn.close()

    assert response.data == b"upgraded"
    assert server.bodies == [b"body"]


def test_h2c_upgrade_accepts_103_before_switching_protocols() -> None:
    with H2CServer("upgrade-early-hints") as server:
        conn = HTTP2UpgradeConnection(server.host, server.port, timeout=1)
        try:
            conn.request("GET", "/upgrade")
            response = conn.getresponse()
        finally:
            conn.close()

    assert response.data == b"upgraded"
    assert server.streams == [1]


def test_h2c_upgrade_discards_103_before_http1_fallback() -> None:
    with H2CServer("fallback-early-hints") as server:
        conn = HTTP2UpgradeConnection(server.host, server.port, timeout=1)
        try:
            conn.request("GET", "/fallback")
            response = conn.getresponse()
        finally:
            conn.close()

    assert response.status == 200
    assert response.data == b"fallback-0"


def test_h2c_upgrade_bounds_informational_responses() -> None:
    with H2CServer("upgrade-too-many-continue") as server:
        conn = HTTP2UpgradeConnection(server.host, server.port, timeout=1)
        try:
            conn.request("GET", "/upgrade")
            with pytest.raises(ProtocolError, match="Too many informational"):
                conn.getresponse()
        finally:
            conn.close()


@pytest.mark.parametrize(
    "mode", ["upgrade-invalid-connection", "upgrade-invalid-token"]
)
def test_h2c_upgrade_validates_response_upgrade_tokens(
    mode: typing.Literal["upgrade-invalid-connection", "upgrade-invalid-token"],
) -> None:
    with H2CServer(mode) as server:
        conn = HTTP2UpgradeConnection(server.host, server.port, timeout=1)
        try:
            conn.request("GET", "/")
            with pytest.raises(ProtocolError, match="Upgrade"):
                conn.getresponse()
        finally:
            conn.close()


def test_h2c_upgrade_sends_fixed_length_body_before_switching() -> None:
    with H2CServer("upgrade-coalesced") as server:
        conn = HTTP2UpgradeConnection(server.host, server.port, timeout=1)
        try:
            conn.request("POST", "/submit", body=b"request-body")
            response = conn.getresponse()
        finally:
            conn.close()

    assert response.data == b"upgraded"
    assert server.bodies == [b"request-body"]
    assert _header_value(server.requests[0], b"content-length") == b"12"


@pytest.mark.parametrize(
    ("body", "headers", "expected"),
    [
        (b"chunked-body", {"Transfer-Encoding": "chunked"}, b"chunked-body"),
        ([b"iterable-", b"body"], None, b"iterable-body"),
        (io.BytesIO(b"file-body"), None, b"file-body"),
    ],
)
def test_h2c_upgrade_sends_chunked_bodies_before_switching(
    body: typing.Any,
    headers: dict[str, str] | None,
    expected: bytes,
) -> None:
    with H2CServer("upgrade-coalesced") as server:
        conn = HTTP2UpgradeConnection(server.host, server.port, timeout=1)
        try:
            conn.request("POST", "/submit", body=body, headers=headers)
            response = conn.getresponse()
        finally:
            conn.close()

    assert response.data == b"upgraded"
    assert server.bodies == [expected]
    assert _header_value(server.requests[0], b"transfer-encoding") == b"chunked"


def test_h2c_upgrade_honors_skippable_headers() -> None:
    with H2CServer("upgrade-coalesced") as server:
        conn = HTTP2UpgradeConnection(server.host, server.port, timeout=1)
        try:
            conn.request(
                "GET",
                "/upgrade",
                headers={
                    "Accept-Encoding": SKIP_HEADER,
                    "User-Agent": SKIP_HEADER,
                },
            )
            response = conn.getresponse()
        finally:
            conn.close()

    assert response.data == b"upgraded"
    assert _header_value(server.requests[0], b"accept-encoding") is None
    assert _header_value(server.requests[0], b"user-agent") is None


def test_h2c_upgrade_rejects_skip_header_for_unsupported_fields() -> None:
    client, server = socket.socketpair()
    conn = HTTP2UpgradeConnection("example.test", timeout=1)
    conn.sock = client
    try:
        with pytest.raises(ValueError, match="SKIP_HEADER only supports"):
            conn.request("GET", "/", headers={"X-Custom": SKIP_HEADER})
        server.settimeout(0.01)
        with pytest.raises(TimeoutError):
            server.recv(1)
    finally:
        conn.close()
        server.close()


def test_h2c_upgrade_non_101_falls_back_and_reuses_http1_connection() -> None:
    with H2CServer("fallback", request_count=2) as server:
        conn = HTTP2UpgradeConnection(server.host, server.port, timeout=1)
        try:
            conn.request("GET", "/first", preload_content=False)
            first = conn.getresponse()
            assert first.data == b"fallback-0"
            conn.request("GET", "/second")
            second = conn.getresponse()
        finally:
            conn.close()

    assert first.version == 11
    assert first.data == b"fallback-0"
    assert second.data == b"fallback-1"
    assert server.accept_count == 1
    assert len(server.requests) == 2


def test_h2c_upgrade_fallback_detaches_connection_close_response() -> None:
    with H2CServer("fallback-close") as server:
        conn = HTTP2UpgradeConnection(server.host, server.port, timeout=1)
        try:
            conn.request("GET", "/fallback", preload_content=False)
            response = conn.getresponse()

            # The response owns the closing socket, matching http.client's
            # lifecycle, while its unread body remains available to callers.
            assert conn.sock is None
            assert response.data == b"fallback-0"
        finally:
            conn.close()

    assert server.accept_count == 1


@pytest.mark.parametrize("mode", ["fallback-continue", "fallback-malformed"])
def test_h2c_upgrade_fallback_preserves_http1_parser_behavior(
    mode: typing.Literal["fallback-continue", "fallback-malformed"],
) -> None:
    with H2CServer(mode) as server:
        conn = HTTP2UpgradeConnection(server.host, server.port, timeout=1)
        try:
            conn.request("GET", "/fallback")
            response = conn.getresponse()
        finally:
            conn.close()

    assert response.status == 200
    assert response.data == b"fallback-0"


@pytest.mark.parametrize(
    "connection_class", [HTTP2CleartextConnection, HTTP2UpgradeConnection]
)
def test_h2c_mode_preserves_http1_proxy_connections(
    connection_class: type[HTTP2CleartextConnection],
) -> None:
    with H2CServer("fallback") as server:
        conn = connection_class(
            server.host,
            server.port,
            timeout=1,
            proxy=parse_url(f"http://{server.host}:{server.port}"),
            proxy_config=ProxyConfig(None, False, None, None),
        )
        try:
            conn.request("GET", "http://example.test/resource")
            response = conn.getresponse()
        finally:
            conn.close()

    assert response.status == 200
    assert response.data == b"fallback-0"
    assert server.requests[0].startswith(
        b"GET http://example.test/resource HTTP/1.1\r\n"
    )
    assert _header_value(server.requests[0], b"upgrade") is None


@pytest.mark.parametrize("mode", ["prior_knowledge", "upgrade"])
def test_h2c_mode_preserves_proxy_manager_http1_connections(
    mode: typing.Literal["prior_knowledge", "upgrade"],
) -> None:
    with H2CServer("fallback") as server:
        try:
            urllib3.http2.inject_into_urllib3(h2c=mode)
            with urllib3.ProxyManager(
                f"http://{server.host}:{server.port}", timeout=1
            ) as proxy:
                response = proxy.request(
                    "GET", "http://example.test/resource", retries=False
                )
        finally:
            urllib3.http2.extract_from_urllib3()

    assert response.status == 200
    assert response.data == b"fallback-0"
    assert server.requests[0].startswith(
        b"GET http://example.test/resource HTTP/1.1\r\n"
    )
    assert _header_value(server.requests[0], b"upgrade") is None


@pytest.mark.parametrize(
    ("mode", "server_mode"),
    [
        ("prior_knowledge", "prior"),
        ("upgrade", "upgrade-coalesced"),
    ],
)
def test_h2c_modes_work_through_http_connection_pool(
    mode: typing.Literal["prior_knowledge", "upgrade"],
    server_mode: typing.Literal["prior", "upgrade-coalesced"],
) -> None:
    with H2CServer(server_mode) as server:
        try:
            urllib3.http2.inject_into_urllib3(h2c=mode)
            with HTTPConnectionPool(server.host, server.port, timeout=1) as pool:
                response = pool.request("GET", "/pool", retries=False)
        finally:
            urllib3.http2.extract_from_urllib3()

    assert response.status == 200
    expected = b"prior-0" if mode == "prior_knowledge" else b"upgraded"
    assert response.data == expected


@pytest.mark.parametrize(
    ("mode", "server_mode"),
    [
        ("prior_knowledge", "prior"),
        ("upgrade", "upgrade-coalesced"),
    ],
)
def test_h2c_pool_reuses_one_connection_for_sequential_streams(
    mode: typing.Literal["prior_knowledge", "upgrade"],
    server_mode: typing.Literal["prior", "upgrade-coalesced"],
) -> None:
    with H2CServer(server_mode, request_count=2) as server:
        try:
            urllib3.http2.inject_into_urllib3(h2c=mode)
            with HTTPConnectionPool(server.host, server.port, timeout=1) as pool:
                first = pool.request("GET", "/first", retries=False)
                second = pool.request("GET", "/second", retries=False)
                assert pool.num_connections == 1
        finally:
            urllib3.http2.extract_from_urllib3()

    assert first.data == (b"prior-0" if mode == "prior_knowledge" else b"upgraded")
    assert second.data == b"prior-1"
    assert server.accept_count == 1
    assert server.streams == [1, 3]


@pytest.mark.parametrize(
    ("mode", "server_mode"),
    [
        ("prior_knowledge", "prior"),
        ("upgrade", "upgrade-coalesced"),
    ],
)
def test_h2c_pool_processes_idle_controls_before_reusing_connection(
    mode: typing.Literal["prior_knowledge", "upgrade"],
    server_mode: typing.Literal["prior", "upgrade-coalesced"],
) -> None:
    with H2CServer(server_mode, request_count=2, after_first="control") as server:
        try:
            urllib3.http2.inject_into_urllib3(h2c=mode)
            with HTTPConnectionPool(server.host, server.port, timeout=1) as pool:
                first = pool.request("GET", "/first", retries=False)
                server.release_after_first.set()
                assert server.after_first_sent.wait(1)
                second = pool.request("GET", "/second", retries=False)
                assert server.control_acks_received.wait(1)
                assert pool.num_connections == 1
        finally:
            urllib3.http2.extract_from_urllib3()

    assert first.status == second.status == 200
    assert server.accept_count == 1
    assert server.streams == [1, 3]
    assert {"ping", "settings"} <= set(server.control_acks)


@pytest.mark.parametrize(
    ("connection_class", "server_mode"),
    [
        (HTTP2CleartextConnection, "prior"),
        (HTTP2UpgradeConnection, "upgrade-coalesced"),
    ],
)
@pytest.mark.parametrize("after_first", ["goaway", "eof"])
def test_h2c_connection_is_not_reusable_after_peer_shutdown(
    connection_class: type[HTTP2CleartextConnection],
    server_mode: typing.Literal["prior", "upgrade-coalesced"],
    after_first: typing.Literal["goaway", "eof"],
) -> None:
    with H2CServer(server_mode, after_first=after_first) as server:
        conn = connection_class(server.host, server.port, timeout=1)
        try:
            conn.request("GET", "/first")
            response = conn.getresponse()
            server.release_after_first.set()
            assert server.after_first_sent.wait(1)
            assert conn.sock is not None
            readable, _, _ = select.select([conn.sock], [], [], 1)
            assert readable
            assert not conn.is_connected
        finally:
            conn.close()

    assert response.status == 200
    assert server.streams == [1]


def test_h2c_injection_modes_restore_http_connection() -> None:
    original = HTTPConnectionPool.ConnectionCls
    try:
        urllib3.http2.inject_into_urllib3(h2c="prior_knowledge")
        assert HTTPConnectionPool.ConnectionCls is HTTP2CleartextConnection
        urllib3.http2.inject_into_urllib3(h2c="upgrade")
        assert HTTPConnectionPool.ConnectionCls is HTTP2UpgradeConnection
        urllib3.http2.inject_into_urllib3(h2c=False)
        assert HTTPConnectionPool.ConnectionCls is original
    finally:
        urllib3.http2.extract_from_urllib3()

    assert HTTPConnectionPool.ConnectionCls is original


def test_h2c_injection_preserves_distinct_custom_http_connection_classes() -> None:
    module_original = urllib3.connection.HTTPConnection
    pool_original = HTTPConnectionPool.ConnectionCls

    class CustomModuleHTTPConnection(HTTPConnection):
        pass

    class CustomPoolHTTPConnection(HTTPConnection):
        pass

    setattr(urllib3.connection, "HTTPConnection", CustomModuleHTTPConnection)
    setattr(HTTPConnectionPool, "ConnectionCls", CustomPoolHTTPConnection)
    try:
        urllib3.http2.inject_into_urllib3()
        assert urllib3.connection.HTTPConnection is CustomModuleHTTPConnection
        assert HTTPConnectionPool.ConnectionCls is CustomPoolHTTPConnection

        urllib3.http2.inject_into_urllib3(h2c="upgrade")
        assert urllib3.connection.HTTPConnection is HTTP2UpgradeConnection
        assert getattr(HTTPConnectionPool, "ConnectionCls") is HTTP2UpgradeConnection

        urllib3.http2.extract_from_urllib3()
        assert urllib3.connection.HTTPConnection is CustomModuleHTTPConnection
        assert HTTPConnectionPool.ConnectionCls is CustomPoolHTTPConnection
    finally:
        urllib3.http2.extract_from_urllib3()
        setattr(urllib3.connection, "HTTPConnection", module_original)
        setattr(HTTPConnectionPool, "ConnectionCls", pool_original)
