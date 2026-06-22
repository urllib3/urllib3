from __future__ import annotations

import socket
import threading
import typing
from unittest import mock

import h2.config
import h2.connection
import pytest

import urllib3
import urllib3.http2
from urllib3.connection import HTTPConnection as _HTTPConnection
from urllib3.connection import _get_default_user_agent
from urllib3.exceptions import ConnectionError
from urllib3.http2.connection import (
    HTTP2CleartextConnection,
    HTTP2Connection,
    HTTP2UpgradeConnection,
    _is_illegal_header_value,
    _is_legal_header_name,
)

# [1] https://httpwg.org/specs/rfc9113.html#n-field-validity


def start_h2c_server(
    *,
    upgrade: bool,
    request_count: int = 1,
) -> tuple[
    socket.socket,
    threading.Thread,
    dict[str, typing.Any],
    list[BaseException],
    str,
    int,
]:
    ready = threading.Event()
    result: dict[str, typing.Any] = {"streams": []}
    errors: list[BaseException] = []

    def server(listener: socket.socket) -> None:
        try:
            ready.set()
            conn, _ = listener.accept()
            with conn:
                h2_conn = h2.connection.H2Connection(
                    config=h2.config.H2Configuration(client_side=False)
                )

                responses_sent = 0
                pending_upgrade_response = False
                if upgrade:
                    request = b""
                    while b"\r\n\r\n" not in request:
                        request += conn.recv(4096)
                    result["request"] = request

                    settings = None
                    for line in request.split(b"\r\n"):
                        if line.lower().startswith(b"http2-settings:"):
                            settings = line.split(b":", 1)[1].strip()
                            break
                    assert settings is not None

                    conn.sendall(
                        b"HTTP/1.1 101 Switching Protocols\r\n"
                        b"Connection: Upgrade\r\n"
                        b"Upgrade: h2c\r\n"
                        b"\r\n"
                    )

                    h2_conn.initiate_upgrade_connection(settings)
                    pending_upgrade_response = True
                else:
                    h2_conn.initiate_connection()
                    conn.sendall(h2_conn.data_to_send())

                while responses_sent < request_count:
                    received_data = conn.recv(65535)
                    if not received_data:
                        break
                    events = h2_conn.receive_data(received_data)
                    if pending_upgrade_response:
                        result["streams"].append(1)
                        _send_h2_response(h2_conn, 1, responses_sent)
                        responses_sent += 1
                        pending_upgrade_response = False
                    for event in events:
                        if isinstance(event, h2.events.RequestReceived):
                            result["streams"].append(event.stream_id)
                            _send_h2_response(h2_conn, event.stream_id, responses_sent)
                            responses_sent += 1
                        elif isinstance(event, h2.events.DataReceived):
                            h2_conn.acknowledge_received_data(
                                event.flow_controlled_length, event.stream_id
                            )
                    if data_to_send := h2_conn.data_to_send():
                        conn.sendall(data_to_send)

                _drain_socket(conn)
        except BaseException as e:
            errors.append(e)

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    thread = threading.Thread(target=server, args=(listener,), daemon=True)
    thread.start()
    assert ready.wait(2)

    host, port = listener.getsockname()
    return listener, thread, result, errors, host, port


def start_h2c_upgrade_server() -> tuple[
    socket.socket,
    threading.Thread,
    dict[str, typing.Any],
    list[BaseException],
    str,
    int,
]:
    return start_h2c_server(upgrade=True)


def _send_h2_response(
    h2_conn: h2.connection.H2Connection, stream_id: int, index: int
) -> None:
    body = f"ok{index}".encode()
    h2_conn.send_headers(
        stream_id,
        [(":status", "200"), ("content-length", str(len(body)))],
    )
    h2_conn.send_data(stream_id, body, end_stream=True)


def _drain_socket(conn: socket.socket) -> None:
    conn.settimeout(0.5)
    try:
        conn.recv(65535)
    except OSError:
        pass


class TestHTTP2Connection:
    def test__is_legal_header_name(self) -> None:
        assert _is_legal_header_name(b"foo"), "foo"
        assert _is_legal_header_name(b"foo-bar"), "foo-bar"
        assert _is_legal_header_name(b"foo-bar-baz"), "foo-bar-baz"

        # A field name MUST NOT contain characters in the ranges 0x00-0x20,
        # 0x41-0x5a, or 0x7f-0xff (all ranges inclusive). [1]
        for i in range(0x00, 0x20):
            assert not _is_legal_header_name(
                f"foo{chr(i)}bar".encode()
            ), f"foo\\x{i}bar"
        for i in range(0x41, 0x5A):
            assert not _is_legal_header_name(
                f"foo{chr(i)}bar".encode()
            ), f"foo\\x{i}bar"
        for i in range(0x7F, 0xFF):
            assert not _is_legal_header_name(
                f"foo{chr(i)}bar".encode()
            ), f"foo\\x{i}bar"

        # This specifically excludes all non-visible ASCII characters, ASCII SP
        # (0x20), and uppercase characters ('A' to 'Z', ASCII 0x41 to 0x5a). [1]
        assert not _is_legal_header_name(b"foo bar"), "foo bar"
        assert not _is_legal_header_name(b"foo\x20bar"), "foo\\x20bar"
        assert not _is_legal_header_name(b"Foo-Bar"), "Foo-Bar"

        # With the exception of pseudo-header fields (Section 8.3), which have a
        # name that starts with a single colon, field names MUST NOT include a
        # colon (ASCII COLON, 0x3a). [1]
        assert not _is_legal_header_name(b":foo"), ":foo"
        assert not _is_legal_header_name(b"foo:bar"), "foo:bar"
        assert not _is_legal_header_name(b"foo:"), "foo:"

    def test__is_illegal_header_value(self) -> None:
        assert not _is_illegal_header_value(b"foo"), "foo"
        assert not _is_illegal_header_value(b"foo bar"), "foo bar"
        assert not _is_illegal_header_value(b"foo\tbar"), "foo\\tbar"

        # A field value MUST NOT contain the zero value (ASCII NUL, 0x00), line
        # feed (ASCII LF, 0x0a), or carriage return (ASCII CR, 0x0d) at any
        # position. [1]
        assert _is_illegal_header_value(b"foo\0bar"), "foo\\0bar"
        assert _is_illegal_header_value(b"foo\x00bar"), "foo\\x00bar"
        assert _is_illegal_header_value(b"foo\x0abar"), "foo\\x0abar"
        assert _is_illegal_header_value(b"foo\x0dbar"), "foo\\x0dbar"
        assert _is_illegal_header_value(b"foo\rbar"), "foo\\rbar"
        assert _is_illegal_header_value(b"foo\nbar"), "foo\\nbar"
        assert _is_illegal_header_value(b"foo\r\nbar"), "foo\\r\\nbar"

        # A field value MUST NOT start or end with an ASCII whitespace character
        # (ASCII SP or HTAB, 0x20 or 0x09). [1]
        assert _is_illegal_header_value(b" foo"), " foo"
        assert _is_illegal_header_value(b"foo "), "foo "
        assert _is_illegal_header_value(b"foo\x20"), "foo\\x20"
        assert _is_illegal_header_value(b"\tfoo"), "\\tfoo"
        assert _is_illegal_header_value(b"foo\t"), "foo\\t"
        assert _is_illegal_header_value(b"foo\x09"), "foo\\x09"

    def test_default_socket_options(self) -> None:
        conn = HTTP2Connection("example.com")
        assert conn.socket_options == [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]
        assert conn.port == 443

    def test_cleartext_default_socket_options(self) -> None:
        conn = HTTP2CleartextConnection("example.com")
        assert conn.socket_options == [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]
        assert conn.port == 80

    def test_cleartext_connect_uses_plain_http_connection(self) -> None:
        conn = HTTP2CleartextConnection("example.com")
        with (
            mock.patch.object(
                _HTTPConnection, "connect", autospec=True
            ) as connect_mock,
            mock.patch.object(
                HTTP2CleartextConnection, "_start_http2_connection", autospec=True
            ) as start_mock,
        ):
            conn.connect()

        connect_mock.assert_called_once_with(conn)
        start_mock.assert_called_once_with(conn)

    def test_putheader(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.putheader("foo", "bar")
        assert conn._headers == [(b"foo", b"bar")]

    def test_request_putheader(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(return_value=None),
        )
        conn.putheader = mock.MagicMock(return_value=None)  # type: ignore[method-assign]
        conn.request("GET", "/", headers={"foo": "bar"})
        conn.putheader.assert_has_calls(
            [
                mock.call("foo", "bar"),
                mock.call(b"user-agent", _get_default_user_agent()),
            ]
        )

    def test_putheader_ValueError(self) -> None:
        conn = HTTP2Connection("example.com")
        with pytest.raises(ValueError):
            conn.putheader("foo\0bar", "baz")
        with pytest.raises(ValueError):
            conn.putheader("foo", "foo\r\nbar")

    def test_endheaders_ConnectionError(self) -> None:
        conn = HTTP2Connection("example.com")
        with pytest.raises(ConnectionError):
            conn.endheaders()

    def test_send_ConnectionError(self) -> None:
        conn = HTTP2Connection("example.com")
        with pytest.raises(ConnectionError):
            conn.send(b"foo")

    def test_send_bytes(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(return_value=None),
        )
        conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"bar")  # type: ignore[method-assign]
        conn._h2_conn._obj.send_data = mock.Mock(return_value=None)  # type: ignore[method-assign]
        conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)  # type: ignore[method-assign]

        conn.putrequest("GET", "/")
        conn.endheaders()
        conn.send(b"foo")

        conn._h2_conn._obj.data_to_send.assert_called_with()
        conn.sock.sendall.assert_called_with(b"bar")
        conn._h2_conn._obj.send_data.assert_called_with(1, b"foo", end_stream=True)

    def test_send_str(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(return_value=None),
        )
        conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"bar")  # type: ignore[method-assign]
        conn._h2_conn._obj.send_data = mock.Mock(return_value=None)  # type: ignore[method-assign]
        conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)  # type: ignore[method-assign]

        conn.putrequest("GET", "/")
        conn.endheaders(message_body=b"foo")
        conn.send("foo")

        conn._h2_conn._obj.data_to_send.assert_called_with()
        conn.sock.sendall.assert_called_with(b"bar")
        conn._h2_conn._obj.send_data.assert_called_with(1, b"foo", end_stream=True)

    def test_send_iter(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(return_value=None),
        )
        conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"baz")  # type: ignore[method-assign]
        conn._h2_conn._obj.send_data = mock.Mock(return_value=None)  # type: ignore[method-assign]
        conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)  # type: ignore[method-assign]
        conn._h2_conn._obj.end_stream = mock.Mock(return_value=None)  # type: ignore[method-assign]

        conn.putrequest("GET", "/")
        conn.endheaders(message_body=[b"foo", b"bar"])
        conn.send([b"foo", b"bar"])

        conn._h2_conn._obj.data_to_send.assert_has_calls(
            [
                mock.call(),
                mock.call(),
            ]
        )
        conn.sock.sendall.assert_has_calls(
            [
                mock.call(b"baz"),
                mock.call(b"baz"),
            ]
        )
        conn._h2_conn._obj.send_data.assert_has_calls(
            [
                mock.call(1, b"foo", end_stream=False),
                mock.call(1, b"bar", end_stream=False),
            ]
        )
        conn._h2_conn._obj.end_stream.assert_called_with(1)

    def test_send_file_str(self) -> None:
        conn = HTTP2Connection("example.com")
        mock_open = mock.mock_open(read_data="foo\r\nbar\r\n")
        with mock.patch("builtins.open", mock_open):
            conn.sock = mock.MagicMock(
                sendall=mock.Mock(return_value=None),
            )
            conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"foo")  # type: ignore[method-assign]
            conn._h2_conn._obj.send_data = mock.Mock(return_value=None)  # type: ignore[method-assign]
            conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)  # type: ignore[method-assign]
            conn._h2_conn._obj.end_stream = mock.Mock(return_value=None)  # type: ignore[method-assign]

            with open("foo") as body:
                conn.putrequest("GET", "/")
                conn.endheaders(message_body=body)
                conn.send(body)

                conn._h2_conn._obj.data_to_send.assert_called_with()
                conn.sock.sendall.assert_called_with(b"foo")
                conn._h2_conn._obj.send_data.assert_called_with(
                    1, b"foo\r\nbar\r\n", end_stream=False
                )
                conn._h2_conn._obj.end_stream.assert_called_with(1)

    def test_send_file_bytes(self) -> None:
        conn = HTTP2Connection("example.com")
        mock_open = mock.mock_open(read_data=b"foo\r\nbar\r\n")
        with mock.patch("builtins.open", mock_open):
            conn.sock = mock.MagicMock(
                sendall=mock.Mock(return_value=None),
            )
            conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"foo")  # type: ignore[method-assign]
            conn._h2_conn._obj.send_data = mock.Mock(return_value=None)  # type: ignore[method-assign]
            conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)  # type: ignore[method-assign]
            conn._h2_conn._obj.end_stream = mock.Mock(return_value=None)  # type: ignore[method-assign]

            body = open("foo", "rb")
            conn.putrequest("GET", "/")
            conn.endheaders(message_body=body)
            conn.send(body)

            conn._h2_conn._obj.data_to_send.assert_called_with()
            conn.sock.sendall.assert_called_with(b"foo")
            conn._h2_conn._obj.send_data.assert_called_with(
                1, b"foo\r\nbar\r\n", end_stream=False
            )
            conn._h2_conn._obj.end_stream.assert_called_with(1)

    def test_send_invalid_type(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.putrequest("GET", "/")
        with pytest.raises(TypeError):
            conn.send(1)

    def test_request_GET(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(return_value=None),
        )
        sendall = conn.sock.sendall
        data_to_send = conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"foo")  # type: ignore[method-assign]
        send_headers = conn._h2_conn._obj.send_headers = mock.Mock(return_value=None)  # type: ignore[method-assign]
        conn._h2_conn._obj.send_data = mock.Mock(return_value=None)  # type: ignore[method-assign]
        conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)  # type: ignore[method-assign]
        close_connection = conn._h2_conn._obj.close_connection = mock.Mock(  # type: ignore[method-assign]
            return_value=None
        )

        conn.request("GET", "/")
        conn.close()

        data_to_send.assert_called_with()
        sendall.assert_called_with(b"foo")
        send_headers.assert_called_with(
            stream_id=1,
            headers=[
                (b":scheme", b"https"),
                (b":method", b"GET"),
                (b":authority", b"example.com:443"),
                (b":path", b"/"),
                (b"user-agent", _get_default_user_agent().encode()),
            ],
            end_stream=True,
        )

        close_connection.assert_called_with()

    def test_cleartext_request_GET(self) -> None:
        conn = HTTP2CleartextConnection("example.com")
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(return_value=None),
        )
        sendall = conn.sock.sendall
        data_to_send = conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"foo")  # type: ignore[method-assign]
        send_headers = conn._h2_conn._obj.send_headers = mock.Mock(return_value=None)  # type: ignore[method-assign]
        conn._h2_conn._obj.send_data = mock.Mock(return_value=None)  # type: ignore[method-assign]
        conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)  # type: ignore[method-assign]
        close_connection = conn._h2_conn._obj.close_connection = mock.Mock(  # type: ignore[method-assign]
            return_value=None
        )

        conn.request("GET", "/")
        conn.close()

        data_to_send.assert_called_with()
        sendall.assert_called_with(b"foo")
        send_headers.assert_called_with(
            stream_id=1,
            headers=[
                (b":scheme", b"http"),
                (b":method", b"GET"),
                (b":authority", b"example.com:80"),
                (b":path", b"/"),
                (b"user-agent", _get_default_user_agent().encode()),
            ],
            end_stream=True,
        )

        close_connection.assert_called_with()

    def test_upgrade_request_GET(self) -> None:
        conn = HTTP2UpgradeConnection("example.com")
        conn.sock = mock.MagicMock(sendall=mock.Mock(return_value=None))
        conn._h2_conn._obj.initiate_upgrade_connection = mock.Mock(  # type: ignore[method-assign]
            return_value=b"settings"
        )

        conn.request("GET", "/", headers={"Foo": "bar"})

        sent = b"".join(call.args[0] for call in conn.sock.sendall.call_args_list)
        assert sent.startswith(b"GET / HTTP/1.1\r\n")
        assert b"Host: example.com:80\r\n" in sent
        assert b"Accept-Encoding: identity\r\n" in sent
        assert b"User-Agent: python-urllib3/" in sent
        assert b"Foo: bar\r\n" in sent
        assert b"Connection: Upgrade, HTTP2-Settings\r\n" in sent
        assert b"Upgrade: h2c\r\n" in sent
        assert b"HTTP2-Settings: settings\r\n" in sent
        assert conn._h2_stream == 1
        assert conn._request_url == "/"

    def test_upgrade_connect_uses_plain_http_connection(self) -> None:
        conn = HTTP2UpgradeConnection("example.com")
        with (
            mock.patch.object(
                _HTTPConnection, "connect", autospec=True
            ) as connect_mock,
            mock.patch.object(
                HTTP2UpgradeConnection, "_start_http2_connection", autospec=True
            ) as start_mock,
        ):
            conn.connect()

        connect_mock.assert_called_once_with(conn)
        start_mock.assert_not_called()

    def test_upgrade_request_rejects_body(self) -> None:
        conn = HTTP2UpgradeConnection("example.com")
        with pytest.raises(NotImplementedError):
            conn.request("POST", "/", body=b"body")

    def test_upgrade_request_rejects_chunked_body(self) -> None:
        conn = HTTP2UpgradeConnection("example.com")
        with pytest.raises(NotImplementedError):
            conn.request("POST", "/", chunked=True)

    def test_upgrade_request_overrides_upgrade_headers_case_insensitively(
        self,
    ) -> None:
        conn = HTTP2UpgradeConnection("example.com")
        conn.sock = mock.MagicMock(sendall=mock.Mock(return_value=None))
        conn._h2_conn._obj.initiate_upgrade_connection = mock.Mock(  # type: ignore[method-assign]
            return_value=b"settings"
        )

        conn.request(
            "GET",
            "/",
            headers={
                "connection": "keep-alive",
                "upgrade": "websocket",
                "http2-settings": "old-settings",
                "Host": "custom.example",
                "Accept-Encoding": "gzip",
                "User-Agent": "agent",
            },
        )

        sent = b"".join(call.args[0] for call in conn.sock.sendall.call_args_list)
        assert b"Connection: Upgrade, HTTP2-Settings\r\n" in sent
        assert b"Upgrade: h2c\r\n" in sent
        assert b"HTTP2-Settings: settings\r\n" in sent
        assert b"connection: keep-alive\r\n" not in sent
        assert b"upgrade: websocket\r\n" not in sent
        assert b"http2-settings: old-settings\r\n" not in sent
        assert b"Host: custom.example\r\n" in sent
        assert b"Accept-Encoding: gzip\r\n" in sent
        assert b"User-Agent: agent\r\n" in sent

    def test_upgrade_getresponse_switches_to_http2(self) -> None:
        conn = HTTP2UpgradeConnection("example.com")
        conn.sock = mock.MagicMock()
        conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"preface")  # type: ignore[method-assign]
        h1_response = mock.Mock(status=101)
        h2_response = mock.Mock()

        with (
            mock.patch.object(
                _HTTPConnection, "getresponse", autospec=True, return_value=h1_response
            ) as h1_getresponse,
            mock.patch.object(
                HTTP2CleartextConnection,
                "getresponse",
                autospec=True,
                return_value=h2_response,
            ) as h2_getresponse,
        ):
            response = conn.getresponse()

        assert response is h2_response
        h1_getresponse.assert_called_once_with(conn)
        h2_getresponse.assert_called_once_with(conn)
        conn.sock.sendall.assert_called_once_with(b"preface")
        assert conn._h2_upgrade_complete

    def test_upgrade_getresponse_returns_http1_response_without_101(self) -> None:
        conn = HTTP2UpgradeConnection("example.com")
        conn.sock = mock.MagicMock()
        h1_response = mock.Mock(status=200)
        h2_conn = conn._h2_conn

        with mock.patch.object(
            _HTTPConnection, "getresponse", autospec=True, return_value=h1_response
        ):
            response = conn.getresponse()

        assert response is h1_response
        conn.sock.sendall.assert_not_called()
        assert not conn._h2_upgrade_complete
        assert conn._h2_stream is None
        assert conn._headers == []
        assert conn._h2_conn is not h2_conn

    def test_upgrade_close_resets_upgrade_state(self) -> None:
        conn = HTTP2UpgradeConnection("example.com")
        conn._h2_upgrade_complete = True
        conn.close()

        assert not conn._h2_upgrade_complete

    def test_upgrade_h2c_smoke(self) -> None:
        listener, thread, result, errors, host, port = start_h2c_upgrade_server()
        conn = HTTP2UpgradeConnection(host, port)
        try:
            conn.request("GET", "/")
            response = conn.getresponse()
        finally:
            conn.close()
            listener.close()
            thread.join(2)

        assert not thread.is_alive()
        assert errors == []
        assert response.status == 200
        assert response.data == b"ok0"
        assert result["request"].startswith(b"GET / HTTP/1.1\r\n")
        assert b"Upgrade: h2c\r\n" in result["request"]
        assert b"HTTP2-Settings:" in result["request"]

    def test_upgrade_h2c_pool_smoke(self) -> None:
        listener, thread, result, errors, host, port = start_h2c_upgrade_server()
        try:
            urllib3.http2.inject_into_urllib3(h2c="upgrade")
            pool = urllib3.HTTPConnectionPool(
                host,
                port,
                timeout=urllib3.Timeout(connect=2, read=2),
                retries=False,
            )
            try:
                response = pool.request("GET", "/")
            finally:
                pool.close()
        finally:
            urllib3.http2.extract_from_urllib3()
            listener.close()
            thread.join(2)

        assert not thread.is_alive()
        assert errors == []
        assert response.status == 200
        assert response.data == b"ok0"
        assert result["request"].startswith(b"GET / HTTP/1.1\r\n")
        assert b"Upgrade: h2c\r\n" in result["request"]
        assert b"HTTP2-Settings:" in result["request"]

    def test_cleartext_h2c_pool_reuses_connection(self) -> None:
        listener, thread, result, errors, host, port = start_h2c_server(
            upgrade=False, request_count=2
        )
        try:
            urllib3.http2.inject_into_urllib3(h2c=True)
            pool = urllib3.HTTPConnectionPool(
                host,
                port,
                timeout=urllib3.Timeout(connect=2, read=2),
                retries=False,
            )
            try:
                first = pool.request("GET", "/")
                second = pool.request("GET", "/again")
                num_connections = pool.num_connections
            finally:
                pool.close()
        finally:
            urllib3.http2.extract_from_urllib3()
            listener.close()
            thread.join(2)

        assert not thread.is_alive()
        assert errors == []
        assert first.status == 200
        assert first.data == b"ok0"
        assert second.status == 200
        assert second.data == b"ok1"
        assert num_connections == 1
        assert result["streams"] == [1, 3]

    def test_upgrade_h2c_pool_reuses_connection(self) -> None:
        listener, thread, result, errors, host, port = start_h2c_server(
            upgrade=True, request_count=2
        )
        try:
            urllib3.http2.inject_into_urllib3(h2c="upgrade")
            pool = urllib3.HTTPConnectionPool(
                host,
                port,
                timeout=urllib3.Timeout(connect=2, read=2),
                retries=False,
            )
            try:
                first = pool.request("GET", "/")
                second = pool.request("GET", "/again")
                num_connections = pool.num_connections
            finally:
                pool.close()
        finally:
            urllib3.http2.extract_from_urllib3()
            listener.close()
            thread.join(2)

        assert not thread.is_alive()
        assert errors == []
        assert first.status == 200
        assert first.data == b"ok0"
        assert second.status == 200
        assert second.data == b"ok1"
        assert num_connections == 1
        assert result["streams"] == [1, 3]
        assert result["request"].startswith(b"GET / HTTP/1.1\r\n")
        assert b"Upgrade: h2c\r\n" in result["request"]
        assert b"HTTP2-Settings:" in result["request"]

    def test_request_POST(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(return_value=None),
        )
        sendall = conn.sock.sendall
        data_to_send = conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"foo")  # type: ignore[method-assign]
        send_headers = conn._h2_conn._obj.send_headers = mock.Mock(return_value=None)  # type: ignore[method-assign]
        send_data = conn._h2_conn._obj.send_data = mock.Mock(return_value=None)  # type: ignore[method-assign]
        conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)  # type: ignore[method-assign]
        close_connection = conn._h2_conn._obj.close_connection = mock.Mock(  # type: ignore[method-assign]
            return_value=None
        )

        conn.request("POST", "/", body=b"foo")
        conn.close()

        data_to_send.assert_called_with()
        sendall.assert_called_with(b"foo")
        send_headers.assert_called_with(
            stream_id=1,
            headers=[
                (b":scheme", b"https"),
                (b":method", b"POST"),
                (b":authority", b"example.com:443"),
                (b":path", b"/"),
                (b"user-agent", _get_default_user_agent().encode()),
            ],
            end_stream=False,
        )
        send_data.assert_called_with(1, b"foo", end_stream=True)
        close_connection.assert_called_with()

    def test_close(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(side_effect=Exception("foo")),
        )
        sendall = conn.sock.sendall
        data_to_send = conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"foo")  # type: ignore[method-assign]
        close_connection = conn._h2_conn._obj.close_connection = mock.Mock(  # type: ignore[method-assign]
            return_value=None
        )

        try:
            conn.close()
        except Exception:
            assert False, "Exception was raised"

        close_connection.assert_called_with()
        data_to_send.assert_called_with()
        sendall.assert_called_with(b"foo")
        assert conn._h2_stream is None
        assert conn._headers == []

    def test_request_ignore_chunked(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(return_value=None),
        )
        sendall = conn.sock.sendall
        data_to_send = conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"foo")  # type: ignore[method-assign]
        send_headers = conn._h2_conn._obj.send_headers = mock.Mock(return_value=None)  # type: ignore[method-assign]
        conn._h2_conn._obj.send_data = mock.Mock(return_value=None)  # type: ignore[method-assign]
        conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)  # type: ignore[method-assign]
        close_connection = conn._h2_conn._obj.close_connection = mock.Mock(  # type: ignore[method-assign]
            return_value=None
        )

        conn.request("GET", "/", headers={"Transfer-Encoding": "chunked"}, chunked=True)
        conn.close()

        data_to_send.assert_called_with()
        sendall.assert_called_with(b"foo")
        send_headers.assert_called_with(
            stream_id=1,
            headers=[
                (b":scheme", b"https"),
                (b":method", b"GET"),
                (b":authority", b"example.com:443"),
                (b":path", b"/"),
                (b"user-agent", _get_default_user_agent().encode()),
            ],
            end_stream=True,
        )

        close_connection.assert_called_with()
