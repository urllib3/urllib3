from __future__ import annotations

import gzip
import socket
import ssl
import sys
import threading
import time
import typing
import zlib
from http.client import ResponseNotReady
from test import notWindows, onlyBrotli, onlyZstd
from unittest import mock

import h2.config
import h2.connection
import h2.events
import pytest

from urllib3.connection import _get_default_user_agent
from urllib3.exceptions import (
    ConnectionError,
    DecodeError,
    ProtocolError,
    ReadTimeoutError,
)
from urllib3.http2.connection import (
    HTTP2Connection,
    _is_illegal_header_value,
    _is_legal_header_name,
)
from urllib3.util.retry import RequestHistory, Retry

# [1] https://httpwg.org/specs/rfc9113.html#n-field-validity


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

    def test_request_authority_port_zero(self) -> None:
        conn = HTTP2Connection("example.com", port=0)
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(return_value=None),
        )
        conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"foo")  # type: ignore[method-assign]
        send_headers = conn._h2_conn._obj.send_headers = mock.Mock(return_value=None)  # type: ignore[method-assign]
        conn._h2_conn._obj.send_data = mock.Mock(return_value=None)  # type: ignore[method-assign]
        conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)  # type: ignore[method-assign]
        conn._h2_conn._obj.close_connection = mock.Mock(return_value=None)  # type: ignore[method-assign]

        conn.request("GET", "/")
        conn.close()

        send_headers.assert_called_with(
            stream_id=1,
            headers=[
                (b":scheme", b"https"),
                (b":method", b"GET"),
                (b":authority", b"example.com:0"),
                (b":path", b"/"),
                (b"user-agent", _get_default_user_agent().encode()),
            ],
            end_stream=True,
        )

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


class FakeSocket:
    """
    An in-memory socket wired directly to a server-side h2 connection.

    Bytes sent by the client are processed by the server connection
    immediately, so the tests exercise real HTTP/2 wire data in both
    directions. ``recv()`` delivers whatever the server connection has
    pending; when it has nothing, an optional ``pump`` callback gets a
    chance to produce more (used to model responses limited by flow
    control). A ``recv()`` that would block forever raises instead, so
    tests fail loudly if the client reads more than the server sent.
    """

    def __init__(
        self,
        server: h2.connection.H2Connection,
        pump: typing.Callable[[], None] | None = None,
    ) -> None:
        self.server = server
        self.pump = pump
        self.server_events: list[h2.events.Event] = []
        self.server_closed = False
        self.raise_timeout = False
        self.fail_sendall = False
        self.timeout: typing.Any = None
        self._to_client = bytearray()

    def settimeout(self, timeout: typing.Any) -> None:
        self.timeout = timeout

    def sendall(self, data: bytes) -> None:
        if self.fail_sendall:
            raise OSError("Connection reset by peer")
        self.server_events.extend(self.server.receive_data(bytes(data)))

    def recv(self, amt: int) -> bytes:
        if self.raise_timeout:
            raise TimeoutError("Read timed out")
        if not self._to_client:
            self._to_client += self.server.data_to_send()
        if not self._to_client and self.pump is not None:
            self.pump()
            self._to_client += self.server.data_to_send()
        if not self._to_client:
            if self.server_closed:
                return b""
            raise AssertionError(
                "recv() would block forever: the server has no data to send"
            )
        data = bytes(self._to_client[:amt])
        del self._to_client[:amt]
        return data

    def close(self) -> None:
        pass


def _connected_http2_pair(
    pump: typing.Callable[[], None] | None = None,
) -> tuple[HTTP2Connection, h2.connection.H2Connection, FakeSocket]:
    """Create an HTTP2Connection talking to a real server-side h2 connection."""
    server = h2.connection.H2Connection(h2.config.H2Configuration(client_side=False))
    server.initiate_connection()

    conn = HTTP2Connection("example.com")
    sock = FakeSocket(server, pump=pump)
    conn.sock = sock
    with conn._h2_conn as client:
        client.initiate_connection()
        data_to_send = client.data_to_send()
    sock.sendall(data_to_send)
    return conn, server, sock


def _request_stream_id(
    conn: HTTP2Connection, sock: FakeSocket, method: str = "GET", **kwargs: typing.Any
) -> int:
    """Send a request and return the stream id the server saw."""
    conn.request(method, "/", **kwargs)
    stream_id = [
        event.stream_id
        for event in sock.server_events
        if isinstance(event, h2.events.RequestReceived)
    ][-1]
    assert stream_id is not None
    return stream_id


class TestHTTP2ResponseBody:
    """The response body is owned and read on demand by HTTP2Response."""

    def test_getresponse_returns_before_body_is_received(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        # Only the response headers are sent. If getresponse() tried to
        # read the body, FakeSocket.recv() would raise.
        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        assert response.status == 200
        assert not response._stream.is_complete

        server.send_data(stream_id, b"hello world", end_stream=True)
        assert response.read() == b"hello world"
        assert response._stream.is_complete

    def test_read_amt_across_data_frames(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"foo")
        server.send_data(stream_id, b"bar")
        server.send_data(stream_id, b"baz", end_stream=True)

        response = conn.getresponse()
        assert response.read(4) == b"foob"
        assert response.read(4) == b"arba"
        assert response.read(4) == b"z"
        assert response.read(4) == b""
        assert response.read() == b""

    def test_read_all_after_headers_only_batch(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        server.send_data(stream_id, b"first")
        server.send_data(stream_id, b"second", end_stream=True)
        assert response.read() == b"firstsecond"

    def test_preload_content_reads_everything_eagerly(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock)

        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-length", b"3")]
        )
        server.send_data(stream_id, b"foo", end_stream=True)

        response = conn.getresponse()
        assert response._stream.is_complete
        assert response.data == b"foo"
        assert response.length_remaining == 0

    def test_stream_yields_data_frames(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"aaaa")
        server.send_data(stream_id, b"bbbb")
        server.send_data(stream_id, b"cc", end_stream=True)

        response = conn.getresponse()
        assert list(response.stream(4)) == [b"aaaa", b"bbbb", b"cc"]

    def test_read1_returns_available_data_without_waiting(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"first")
        response = conn.getresponse()

        # read1 must return the buffered frame instead of blocking until
        # 100 bytes have accumulated. A blocking read would raise in recv().
        assert response.read1(100) == b"first"

        server.send_data(stream_id, b"second", end_stream=True)
        assert response.read1(100) == b"second"
        assert response.read1(100) == b""

    def test_data_and_headers_in_a_single_recv_batch(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        # Everything arrives in one TCP segment: DATA frames received
        # while waiting for headers must be buffered for later reads.
        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"inline body", end_stream=True)

        response = conn.getresponse()
        assert response.read() == b"inline body"

    def test_flow_control_window_is_acknowledged(self) -> None:
        body = b"x" * 200_000
        state = {"sent": 0, "ended": False}
        stream_id = 0

        def pump() -> None:
            while state["sent"] < len(body):
                window = min(
                    server.local_flow_control_window(stream_id),
                    server.max_outbound_frame_size,
                )
                if window == 0:
                    return
                chunk = body[state["sent"] : state["sent"] + window]
                server.send_data(stream_id, chunk)
                state["sent"] += len(chunk)
            if not state["ended"]:
                server.end_stream(stream_id)
                state["ended"] = True

        conn, server, sock = _connected_http2_pair(pump=pump)
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        # The default flow control window is 65,535 bytes: receiving 200kB
        # only works if the client acknowledges received data. Without
        # acknowledgements the pump stalls and recv() raises.
        assert response.read() == body

    def test_gzip_decoding_preloaded(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock)

        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-encoding", b"gzip")]
        )
        server.send_data(stream_id, gzip.compress(b"hello, world!"), end_stream=True)

        response = conn.getresponse()
        assert response.data == b"hello, world!"

    def test_gzip_decoding_streamed(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        compressed = gzip.compress(b"hello, world!" * 100)
        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-encoding", b"gzip")]
        )
        # Deliver the compressed body across multiple DATA frames.
        third = len(compressed) // 3
        server.send_data(stream_id, compressed[:third])
        server.send_data(stream_id, compressed[third : 2 * third])
        server.send_data(stream_id, compressed[2 * third :], end_stream=True)

        response = conn.getresponse()
        assert b"".join(response.stream(64)) == b"hello, world!" * 100

    def test_deflate_decoding_partial_reads(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-encoding", b"deflate")]
        )
        server.send_data(stream_id, zlib.compress(b"foobarbaz"), end_stream=True)

        response = conn.getresponse()
        assert response.read(3) == b"foo"
        assert response.read(3) == b"bar"
        assert response.read(3) == b"baz"
        assert response.read(3) == b""

    def test_decode_content_false_returns_raw_bytes(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        compressed = gzip.compress(b"hello, world!")
        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-encoding", b"gzip")]
        )
        server.send_data(stream_id, compressed, end_stream=True)

        response = conn.getresponse()
        assert response.read(decode_content=False) == compressed

    def test_read_decode_content_false_after_true_raises(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        compressed = gzip.compress(b"hello, world!" * 100)
        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-encoding", b"gzip")]
        )
        server.send_data(stream_id, compressed, end_stream=True)

        response = conn.getresponse()
        assert response.read(5, decode_content=True) == b"hello"
        with pytest.raises(RuntimeError, match="read\\(decode_content=False\\)"):
            response.read(5, decode_content=False)

    def test_invalid_compressed_data_raises_decode_error(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-encoding", b"gzip")]
        )
        server.send_data(stream_id, b"garbage", end_stream=True)

        response = conn.getresponse()
        with pytest.raises(DecodeError):
            response.read()

    def test_read_amt_accumulates_across_socket_reads(self) -> None:
        chunks = [b"bbbb", b"cccc"]
        state = {"i": 0}
        stream_id = 0

        def pump() -> None:
            if state["i"] < len(chunks):
                server.send_data(
                    stream_id,
                    chunks[state["i"]],
                    end_stream=state["i"] == len(chunks) - 1,
                )
                state["i"] += 1

        conn, server, sock = _connected_http2_pair(pump=pump)
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"aaaa")
        response = conn.getresponse()

        # read(amt) must keep receiving until amt bytes accumulated, not
        # return a short read after the first frame.
        assert response.read(12, decode_content=False) == b"aaaabbbbcccc"

    def test_frames_for_other_streams_are_ignored(self) -> None:
        conn, server, sock = _connected_http2_pair()
        first_stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(first_stream_id, [(b":status", b"200")])
        first_response = conn.getresponse()
        assert first_response.status == 200

        # A second request on the same connection while the first body is
        # unread: late frames for the old stream must not corrupt the new
        # response's body.
        second_stream_id = _request_stream_id(conn, sock, preload_content=False)
        assert second_stream_id != first_stream_id

        server.send_data(first_stream_id, b"stale-data", end_stream=True)
        server.send_headers(second_stream_id, [(b":status", b"200")])
        second_response = conn.getresponse()

        server.send_data(second_stream_id, b"fresh", end_stream=True)
        assert second_response.read() == b"fresh"

    def test_full_read_merges_buffered_decoded_data(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-encoding", b"deflate")]
        )
        server.send_data(stream_id, zlib.compress(b"foobarbaz"), end_stream=True)

        response = conn.getresponse()
        assert response.read(3) == b"foo"
        # Simulate a decoder that does not respect max_length: decoded
        # data ends up buffered before a full read.
        middle_part = response._decode(
            response._raw_read(),
            decode_content=True,
            flush_decoder=False,
            max_length=3,
        )
        assert middle_part == b"bar"
        response._decoded_buffer.put(middle_part)
        assert response.read() == b"barbaz"

    def test_read1_does_not_fake_eof_when_first_chunk_decodes_to_nothing(
        self,
    ) -> None:
        compressed = gzip.compress(b"data" * 100)
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-encoding", b"gzip")]
        )
        # The first frame contains only the gzip header, which decodes to
        # zero bytes: read1 must keep reading instead of returning b"".
        server.send_data(stream_id, compressed[:10])
        response = conn.getresponse()
        server.send_data(stream_id, compressed[10:], end_stream=True)

        body = bytearray(response.read1())
        assert body != b""
        while chunk := response.read1():
            body += chunk
        assert bytes(body) == b"data" * 100

    @onlyZstd()
    def test_truncated_zstd_raises_decode_error(self) -> None:
        if sys.version_info >= (3, 14):
            from compression import zstd
        else:
            from backports import zstd

        compressed = zstd.compress(b"hello, world!" * 64)
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-encoding", b"zstd")]
        )
        server.send_data(stream_id, compressed[:-10], end_stream=True)

        response = conn.getresponse()
        # Truncation is only detectable when the decoder is flushed.
        with pytest.raises(DecodeError):
            response.read()

    @onlyBrotli()
    def test_brotli_decoding_streamed(self) -> None:
        from urllib3.response import brotli  # type: ignore[attr-defined]

        compressed = brotli.compress(b"hello, world!" * 50)
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-encoding", b"br")]
        )
        half = len(compressed) // 2
        server.send_data(stream_id, compressed[:half])
        server.send_data(stream_id, compressed[half:], end_stream=True)

        response = conn.getresponse()
        assert b"".join(response.stream(64)) == b"hello, world!" * 50

    def test_tell_counts_wire_bytes(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"0123456789", end_stream=True)

        response = conn.getresponse()
        assert response.tell() == 0
        assert response.read(4) == b"0123"
        assert response.tell() == 4
        response.read()
        assert response.tell() == 10

    def test_negative_amt_reads_all(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"whole body", end_stream=True)

        response = conn.getresponse()
        assert response.read(-1) == b"whole body"

    def test_data_property_not_cached_after_partial_read(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"0123456789", end_stream=True)

        response = conn.getresponse()
        assert response.read(4) == b"0123"
        # After an uncached partial read the remainder must not be
        # presented as the full cached body.
        assert response.data == b"456789"
        assert response.data == b""

    def test_read_zero_is_noop(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"body", end_stream=True)

        response = conn.getresponse()
        assert response.read(0) == b""
        assert response.read() == b"body"

    def test_zero_length_data_frame_with_end_stream(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"payload")
        response = conn.getresponse()

        server.send_data(stream_id, b"", end_stream=True)
        assert response.read() == b"payload"
        assert response._stream.is_complete

    def test_empty_body_with_content_encoding(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(
            stream_id,
            [(b":status", b"200"), (b"content-encoding", b"gzip")],
            end_stream=True,
        )

        response = conn.getresponse()
        assert response.read() == b""

    def test_stream_amt_none_reads_everything(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"foo")
        server.send_data(stream_id, b"bar", end_stream=True)

        response = conn.getresponse()
        assert list(response.stream(None)) == [b"foobar"]

    def test_latin1_header_values_preserved(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.config.validate_outbound_headers = False
        server.send_headers(
            stream_id,
            [(b":status", b"200"), (b"x-filename", "café".encode("latin-1"))],
            end_stream=True,
        )

        # http.client decodes HTTP/1.1 header bytes as latin-1; HTTP/2
        # responses must parse byte-identical headers identically.
        response = conn.getresponse()
        assert response.headers["x-filename"] == "café"

    def test_invalid_status_value_raises_protocol_error(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.config.validate_outbound_headers = False
        server.send_headers(stream_id, [(b":status", b"abc")], end_stream=True)

        with pytest.raises(ProtocolError, match=":status"):
            conn.getresponse()

    def test_read_cache_content_stores_body(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"cached body", end_stream=True)

        response = conn.getresponse()
        assert response.read(cache_content=True) == b"cached body"
        # The cached body keeps serving after the stream is consumed.
        assert response.data == b"cached body"

    def test_read_amt_decode_content_false_after_true_raises(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-encoding", b"gzip")]
        )
        server.send_data(stream_id, gzip.compress(b"hello, world!"), end_stream=True)

        response = conn.getresponse()
        assert response.read(4) == b"hell"
        with pytest.raises(RuntimeError, match="not supported"):
            response.read(4, decode_content=False)

    def test_read1_negative_amt_reads_all(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"everything", end_stream=True)

        response = conn.getresponse()
        assert response.read1(-3) == b"everything"

    def test_read1_decode_content_false_after_true_raises(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-encoding", b"gzip")]
        )
        server.send_data(stream_id, gzip.compress(b"hello, world!"), end_stream=True)

        response = conn.getresponse()
        assert response.read1(1) == b"h"
        with pytest.raises(RuntimeError, match="not supported"):
            response.read1(1, decode_content=False)

    def test_read1_serves_decoder_tail_before_reading_network(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-encoding", b"gzip")]
        )
        server.send_data(stream_id, gzip.compress(b"hello, world!"), end_stream=True)

        response = conn.getresponse()
        # The whole compressed frame is consumed by the first read1; the
        # remaining decoded bytes must come from the decoder's unconsumed
        # tail without touching the network again.
        assert response.read1(1) == b"h"
        assert response.read1(1) == b"e"
        assert response.read1() == b"llo, world!"

    def test_read1_zero_amt_returns_empty(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"data", end_stream=True)

        response = conn.getresponse()
        assert response.read1(0) == b""

    def test_read1_decode_content_false_returns_raw_bytes(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"raw bytes", end_stream=True)

        response = conn.getresponse()
        assert response.read1(decode_content=False) == b"raw bytes"

    def test_stream_zero_amt_yields_nothing(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"data", end_stream=True)

        response = conn.getresponse()
        assert list(response.stream(0)) == []


class TestHTTP2ResponseLifecycle:
    """Error handling, timeouts and connection lifecycle."""

    def test_getresponse_without_request_raises_response_not_ready(self) -> None:
        conn, server, sock = _connected_http2_pair()
        with pytest.raises(ResponseNotReady):
            conn.getresponse()

    def test_socket_timeout_during_read_raises_read_timeout_error(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        sock.raise_timeout = True
        with pytest.raises(ReadTimeoutError):
            response.read()

    def test_connection_closed_before_headers_raises_protocol_error(self) -> None:
        conn, server, sock = _connected_http2_pair()
        _request_stream_id(conn, sock, preload_content=False)

        sock.server_closed = True
        with pytest.raises(ProtocolError, match="without sending a complete response"):
            conn.getresponse()

    def test_connection_closed_mid_body_raises_protocol_error(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"partial")
        response = conn.getresponse()

        sock.server_closed = True
        with pytest.raises(ProtocolError, match="before the response body"):
            response.read()

    def test_content_length_mismatch_raises_protocol_error(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.config.validate_outbound_headers = False
        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-length", b"100")]
        )
        response = conn.getresponse()

        server.send_data(stream_id, b"short", end_stream=True)
        with pytest.raises(ProtocolError, match="Invalid HTTP/2 data"):
            response.read()

    def test_trailers_are_ignored(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"body")
        server.send_headers(stream_id, [(b"x-trailer", b"value")], end_stream=True)

        response = conn.getresponse()
        assert response.read() == b"body"
        assert "x-trailer" not in response.headers

    def test_informational_responses_are_skipped(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"103")])
        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"final", end_stream=True)

        response = conn.getresponse()
        assert response.status == 200
        assert response.read() == b"final"

    def test_connection_released_to_pool_when_stream_consumed(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"body", end_stream=True)

        response = conn.getresponse()
        pool = mock.MagicMock()
        response._pool = pool
        response._connection = conn

        assert response.read() == b"body"
        pool._put_conn.assert_called_once_with(conn)
        assert response.connection is None

    def test_connection_closed_and_released_on_read_error(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        pool = mock.MagicMock()
        connection = mock.MagicMock()
        response._pool = pool
        response._connection = connection

        sock.server_closed = True
        with pytest.raises(ProtocolError):
            response.read()

        connection.close.assert_called_once_with()
        pool._put_conn.assert_called_once_with(connection)

    def test_drain_conn_consumes_stream(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"x" * 1000, end_stream=True)

        response = conn.getresponse()
        assert not response._stream.is_complete
        response.drain_conn()
        assert response._stream.is_complete

    def test_close_unconsumed_response_closes_connection(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        connection = mock.MagicMock()
        response._connection = connection

        assert not response.closed
        response.close()
        connection.close.assert_called_once_with()
        assert response.closed

    def test_head_response_has_no_body(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, method="HEAD")

        server.send_headers(
            stream_id,
            [(b":status", b"200"), (b"content-length", b"1000")],
            end_stream=True,
        )

        response = conn.getresponse()
        assert response.length_remaining == 0
        assert response.data == b""

    def test_setting_retries_with_history_does_not_crash(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        # The connection pool assigns retries to every response. With a
        # non-empty history the setter assigns the redirect location to
        # response.url, which previously raised NotImplementedError.
        retries = Retry(history=(RequestHistory("GET", "/", None, None, None),))
        response.retries = retries
        assert response.url is None

        response.url = "https://example.com/"
        assert response.url == "https://example.com/"

    def test_json(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock)

        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-type", b"application/json")]
        )
        server.send_data(stream_id, b'{"hello": "world"}', end_stream=True)

        response = conn.getresponse()
        assert response.json() == {"hello": "world"}

    def test_readinto(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"some data", end_stream=True)

        response = conn.getresponse()
        buffer = bytearray(4)
        assert response.readinto(buffer) == 4
        assert bytes(buffer) == b"some"

    def test_stream_reset_raises_protocol_error(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"partial")
        response = conn.getresponse()

        server.reset_stream(stream_id, error_code=8)
        with pytest.raises(ProtocolError, match="reset by the remote peer"):
            response.read()

    def test_goaway_raises_protocol_error(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        server.close_connection(error_code=2)
        with pytest.raises(ProtocolError, match="terminated by the remote peer"):
            response.read()

    def test_goaway_after_stream_end_is_ignored(self) -> None:
        # A graceful shutdown: the server finishes the stream and sends
        # GOAWAY afterwards. The completed response must not error.
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        server.send_data(stream_id, b"graceful", end_stream=True)
        server.close_connection(error_code=0)
        assert response.read() == b"graceful"

    def test_close_then_release_returns_connection_to_pool(self) -> None:
        # requests calls response.close() and then release_conn() when a
        # streamed response is closed before being consumed. The pool slot
        # must be returned in that case.
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        pool = mock.MagicMock()
        connection = mock.MagicMock()
        response._pool = pool
        response._connection = connection

        response.close()
        response.release_conn()

        connection.close.assert_called_once_with()
        pool._put_conn.assert_called_once_with(connection)

    def test_read_and_stream_after_close_return_no_data(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"data")
        response = conn.getresponse()
        assert response.read(2) == b"da"

        response.close()
        assert response.read() == b""
        assert list(response.stream(2)) == []

    def test_auto_close_false_supports_io_wrapper(self) -> None:
        import io

        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"hello world", end_stream=True)

        response = conn.getresponse()
        response.auto_close = False
        reader = io.TextIOWrapper(response)  # type: ignore[type-var]
        assert reader.read() == "hello world"
        assert not response.closed
        assert response.isclosed()

        reader.close()
        assert response.closed

    def test_multiple_content_length_values(self) -> None:
        from urllib3._collections import HTTPHeaderDict
        from urllib3.exceptions import InvalidHeader
        from urllib3.http2.connection import HTTP2Response, HTTP2Stream

        conn, server, sock = _connected_http2_pair()

        def response_with_content_length(value1: str, value2: str) -> HTTP2Response:
            return HTTP2Response(
                status=200,
                headers=HTTPHeaderDict(
                    [("content-length", value1), ("content-length", value2)]
                ),
                request_url="/",
                stream=HTTP2Stream(sock, conn._h2_conn, 1),  # type: ignore[arg-type]
                preload_content=False,
            )

        assert response_with_content_length("42", "42").length_remaining == 42
        with pytest.raises(InvalidHeader):
            response_with_content_length("42", "43")

    def test_read_chunked_raises_response_not_chunked(self) -> None:
        from urllib3.exceptions import ResponseNotChunked

        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        with pytest.raises(ResponseNotChunked):
            response.read_chunked()

    def test_304_reports_zero_length(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        # A 304 may carry the entity's content-length without a body.
        server.send_headers(
            stream_id,
            [(b":status", b"304"), (b"content-length", b"1000")],
            end_stream=True,
        )

        response = conn.getresponse()
        assert response.length_remaining == 0
        assert response.read() == b""

    def test_shutdown_calls_sock_shutdown(self) -> None:
        calls: list[int] = []

        conn, server, sock = _connected_http2_pair()
        sock.shutdown = calls.append  # type: ignore[attr-defined]
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(stream_id, [(b":status", b"200")])

        response = conn.getresponse()
        response._connection = mock.MagicMock()
        response.shutdown()
        assert calls == [socket.SHUT_RD]

    def test_shutdown_after_release_raises(self) -> None:
        conn, server, sock = _connected_http2_pair()
        sock.shutdown = lambda how: None  # type: ignore[attr-defined]
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(stream_id, [(b":status", b"200")])

        response = conn.getresponse()
        with pytest.raises(RuntimeError, match="released"):
            response.shutdown()

    def test_shutdown_after_close_raises(self) -> None:
        conn, server, sock = _connected_http2_pair()
        sock.shutdown = lambda how: None  # type: ignore[attr-defined]
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(stream_id, [(b":status", b"200")])

        response = conn.getresponse()
        response.close()
        with pytest.raises(ValueError):
            response.shutdown()

    def test_closed_after_stream_consumed(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(stream_id, [(b":status", b"200")])
        server.send_data(stream_id, b"body", end_stream=True)

        response = conn.getresponse()
        assert not response.closed
        assert response.read() == b"body"
        assert response.closed
        assert response.isclosed()

    def test_getresponse_applies_updated_timeout(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        # The pool updates conn.timeout to the read timeout after sending
        # the request and before calling getresponse().
        conn.timeout = 0.25
        server.send_headers(stream_id, [(b":status", b"200")])
        conn.getresponse()
        assert sock.timeout == 0.25

    def test_send_failure_after_stream_end_is_ignored(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)
        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        # The PING arrives in the same batch as END_STREAM: failing to
        # send the queued PING ack must not invalidate the received body.
        server.send_data(stream_id, b"done", end_stream=True)
        server.ping(b"12345678")
        sock.fail_sendall = True
        assert response.read() == b"done"

    def test_send_failure_mid_stream_raises(self) -> None:
        body = b"x" * 200_000
        state = {"sent": 0, "ended": False}
        stream_id = 0

        def pump() -> None:
            while state["sent"] < len(body):
                window = min(
                    server.local_flow_control_window(stream_id),
                    server.max_outbound_frame_size,
                )
                if window == 0:
                    return
                chunk = body[state["sent"] : state["sent"] + window]
                server.send_data(stream_id, chunk)
                state["sent"] += len(chunk)
            if not state["ended"]:
                server.end_stream(stream_id)
                state["ended"] = True

        conn, server, sock = _connected_http2_pair(pump=pump)
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        # Failing to send flow control acknowledgements while the body is
        # still incomplete leaves the connection unusable and must raise.
        sock.fail_sendall = True
        with pytest.raises(ProtocolError):
            response.read()

    def test_read_after_close_with_unread_content_length_raises(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-length", b"10")]
        )
        server.send_data(stream_id, b"ab")
        response = conn.getresponse()
        assert response.read(2) == b"ab"

        response.close()
        with pytest.raises(ProtocolError):
            response.read(2)

    def test_ssl_error_during_read_raises_urllib3_ssl_error(self) -> None:
        from urllib3.exceptions import SSLError

        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        def raise_ssl_error(amt: int) -> bytes:
            raise ssl.SSLError("decryption failed or bad record mac")

        sock.recv = raise_ssl_error  # type: ignore[method-assign]
        with pytest.raises(SSLError, match="bad record mac"):
            response.read()

    def test_goaway_send_failure_after_protocol_error_is_ignored(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        # Deliver garbage so h2 raises and queues a GOAWAY for the peer.
        # Sending that GOAWAY fails: the original error must still win.
        sock._to_client += b"\x00" * 24
        sock.fail_sendall = True
        with pytest.raises(ProtocolError, match="Invalid HTTP/2 data"):
            response.read()

    def test_unparseable_content_length_reports_none(self) -> None:
        from urllib3._collections import HTTPHeaderDict
        from urllib3.http2.connection import HTTP2Response, HTTP2Stream

        conn, server, sock = _connected_http2_pair()

        def response_with_content_length(value: str) -> HTTP2Response:
            return HTTP2Response(
                status=200,
                headers=HTTPHeaderDict([("content-length", value)]),
                request_url="/",
                stream=HTTP2Stream(sock, conn._h2_conn, 1),  # type: ignore[arg-type]
                preload_content=False,
            )

        assert response_with_content_length("abc").length_remaining is None
        assert response_with_content_length("-5").length_remaining is None

    def test_drain_conn_swallows_read_errors(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(stream_id, [(b":status", b"200")])
        response = conn.getresponse()

        sock.raise_timeout = True
        # drain_conn is used on a best-effort basis by Retry: read errors
        # while discarding the body must not propagate.
        response.drain_conn()

    def test_drain_conn_resets_decoder_state(self) -> None:
        conn, server, sock = _connected_http2_pair()
        stream_id = _request_stream_id(conn, sock, preload_content=False)

        server.send_headers(
            stream_id, [(b":status", b"200"), (b"content-encoding", b"gzip")]
        )
        server.send_data(stream_id, gzip.compress(b"hello, world!"), end_stream=True)

        response = conn.getresponse()
        assert response.read1(1) == b"h"

        response.drain_conn()
        assert response._decoder is None
        assert len(response._decoded_buffer) == 0

    def _blocked_reader_setup(
        self,
    ) -> tuple[
        HTTP2Connection,
        typing.Any,
        socket.socket,
        socket.socket,
        list[BaseException],
        threading.Thread,
    ]:
        """Start a request over a real socketpair and a daemon thread
        blocked in response.read()."""
        client_sock, server_sock = socket.socketpair()

        server = h2.connection.H2Connection(
            h2.config.H2Configuration(client_side=False)
        )
        server.initiate_connection()

        conn = HTTP2Connection("example.com")
        conn.sock = client_sock
        with conn._h2_conn as client:
            client.initiate_connection()
            client_sock.sendall(client.data_to_send())

        conn.request("GET", "/", preload_content=False)

        stream_id = None
        while stream_id is None:
            events = server.receive_data(server_sock.recv(65536))
            for event in events:
                if isinstance(event, h2.events.RequestReceived):
                    stream_id = event.stream_id
        server.send_headers(stream_id, [(b":status", b"200")])
        server_sock.sendall(server.data_to_send())

        response = conn.getresponse()
        response._connection = conn

        errors: list[BaseException] = []

        def read_body() -> None:
            try:
                response.read()
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        reader = threading.Thread(target=read_body, daemon=True)
        reader.start()
        time.sleep(0.2)  # Let the reader block in recv().
        return conn, response, client_sock, server_sock, errors, reader

    @notWindows()
    @pytest.mark.timeout(10)
    def test_shutdown_unblocks_concurrent_read(self) -> None:
        # On POSIX, shutdown(SHUT_RD) makes a recv() blocked in another
        # thread return b"" immediately. Windows does not interrupt an
        # in-progress recv() for SD_RECEIVE, so this test is POSIX-only,
        # matching the documented HTTPResponse.shutdown() semantics.
        conn, response, client_sock, server_sock, errors, reader = (
            self._blocked_reader_setup()
        )
        try:
            response.shutdown()
            reader.join(timeout=5)

            assert not reader.is_alive()
            assert len(errors) == 1
            assert isinstance(errors[0], ProtocolError)
        finally:
            conn.close()
            server_sock.close()
            client_sock.close()

    @pytest.mark.timeout(10)
    def test_close_does_not_deadlock_with_concurrent_read(self) -> None:
        conn, response, client_sock, server_sock, errors, reader = (
            self._blocked_reader_setup()
        )
        try:
            # Receiving must not hold the h2 lock during the blocking
            # recv(), otherwise this close() would wait for the reader
            # (which never returns) instead of completing promptly. The
            # reader itself is a daemon thread: whether a close() wakes a
            # blocked recv() is platform-dependent, so its outcome is not
            # asserted here (see test_shutdown_unblocks_concurrent_read).
            start = time.monotonic()
            conn.close()
            assert time.monotonic() - start < 2
        finally:
            server_sock.close()
            client_sock.close()
