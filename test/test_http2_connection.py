from __future__ import annotations

import socket
import typing
from unittest import mock

import h2.config
import h2.connection
import h2.errors
import h2.events
import h2.exceptions
import pytest

from urllib3.connection import _get_default_user_agent
from urllib3.exceptions import ConnectionError, ProtocolError
from urllib3.http2.connection import (
    HTTP2Connection,
    _h2_error_code_name,
    _is_illegal_header_value,
    _is_legal_header_name,
    _raise_for_h2_error_event,
)
from urllib3.util.wait import wait_for_read

# [1] https://httpwg.org/specs/rfc9113.html#n-field-validity


class _H2PeerSocket:
    """
    Selectable socket-like peer that speaks HTTP/2 via an ``h2`` server.

    Uses an OS ``socketpair`` so ``wait_for_read`` works the same as on a real
    TCP socket. ``on_request`` decides how to answer each ``RequestReceived``
    event (response, RST_STREAM, GOAWAY, etc.).
    """

    def __init__(
        self,
        on_request: typing.Callable[
            [h2.connection.H2Connection, h2.events.RequestReceived], None
        ],
    ) -> None:
        self._client, self._peer = socket.socketpair()
        self._server = h2.connection.H2Connection(
            config=h2.config.H2Configuration(client_side=False, header_encoding=None)
        )
        self._server.initiate_connection()
        preface = self._server.data_to_send()
        if preface:
            self._peer.sendall(preface)
        self._on_request = on_request

    def fileno(self) -> int:
        return self._client.fileno()

    def settimeout(self, timeout: float | None) -> None:
        self._client.settimeout(timeout)

    def sendall(self, data: bytes) -> None:
        try:
            events = self._server.receive_data(data)
        except h2.exceptions.H2Error:
            # Client may send GOAWAY/close frames after the peer already
            # terminated the connection; ignore further inbound frames.
            return
        for event in events:
            if isinstance(event, h2.events.RequestReceived):
                self._on_request(self._server, event)
        outbound = self._server.data_to_send()
        if outbound:
            self._peer.sendall(outbound)

    def recv(self, amt: int) -> bytes:
        return self._client.recv(amt)

    def inject_frames(self, data: bytes) -> None:
        """Queue additional frames for a later ``recv`` (e.g. deferred GOAWAY)."""
        if data:
            self._peer.sendall(data)

    def close_writes(self) -> None:
        """Signal EOF to the client side (peer closed the connection)."""
        try:
            self._peer.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    def close(self) -> None:
        for sock in (self._client, self._peer):
            try:
                sock.close()
            except OSError:
                pass

    def __enter__(self) -> _H2PeerSocket:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: typing.Any,
    ) -> None:
        self.close()


def _connect_http2(conn: HTTP2Connection, sock: _H2PeerSocket) -> None:
    """Perform the HTTP/2 connection preface exchange without a real TCP/TLS socket."""
    conn.sock = sock  # type: ignore[assignment,unused-ignore]
    with conn._h2_conn as h2_conn:
        h2_conn.initiate_connection()
        if data := h2_conn.data_to_send():
            sock.sendall(data)


class TestHTTP2ErrorEvents:
    def test_error_code_name_mapping(self) -> None:
        assert _h2_error_code_name(h2.errors.ErrorCodes.CANCEL) == "CANCEL"
        assert _h2_error_code_name(None) == "NO_ERROR"
        assert _h2_error_code_name(0xFF) == "0xff"
        assert _h2_error_code_name("bogus") == "'bogus'"

    def test_raise_for_h2_error_event_rejects_other_events(self) -> None:
        with pytest.raises(
            TypeError, match="Expected StreamReset or ConnectionTerminated"
        ):
            _raise_for_h2_error_event(h2.events.StreamEnded(stream_id=1))

    def test_stream_reset_raises_protocol_error(self) -> None:
        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            server.reset_stream(
                event.stream_id, error_code=h2.errors.ErrorCodes.REFUSED_STREAM
            )

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")
            with pytest.raises(ProtocolError, match="REFUSED_STREAM"):
                conn.getresponse()

    def test_stream_reset_after_partial_body_raises(self) -> None:
        """RST_STREAM after headers+data must not return a truncated body."""

        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            server.send_headers(
                event.stream_id,
                [(b":status", b"200"), (b"content-type", b"text/plain")],
                end_stream=False,
            )
            server.send_data(event.stream_id, b"partial", end_stream=False)
            server.reset_stream(event.stream_id, error_code=h2.errors.ErrorCodes.CANCEL)

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")
            with pytest.raises(ConnectionError, match="CANCEL"):
                conn.getresponse()

    def test_connection_terminated_before_response_raises(self) -> None:
        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            server.close_connection(
                error_code=h2.errors.ErrorCodes.ENHANCE_YOUR_CALM,
                additional_data=b"slow-down",
            )

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")
            with pytest.raises(
                ConnectionError,
                match=(
                    "connection terminated by the peer with error code ENHANCE_YOUR_CALM"
                    r".*last stream id 1.*additional_data=b'slow-down'"
                ),
            ):
                conn.getresponse()

    def test_connection_terminated_after_partial_body_raises(self) -> None:
        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            server.send_headers(
                event.stream_id, [(b":status", b"200")], end_stream=False
            )
            server.send_data(event.stream_id, b"partial", end_stream=False)
            server.close_connection(error_code=h2.errors.ErrorCodes.INTERNAL_ERROR)

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")
            with pytest.raises(ConnectionError, match="INTERNAL_ERROR"):
                conn.getresponse()

    def test_graceful_goaway_after_complete_response_returns_body(self) -> None:
        """GOAWAY in the same flight as StreamEnded must not fail the request."""

        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            server.send_headers(
                event.stream_id, [(b":status", b"200")], end_stream=False
            )
            server.send_data(event.stream_id, b"done", end_stream=True)
            server.close_connection(error_code=h2.errors.ErrorCodes.NO_ERROR)

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")
            response = conn.getresponse()
            assert response.status == 200
            assert response.data == b"done"
            # Connection must not be reused after peer GOAWAY.
            assert conn.sock is None

    def test_deferred_goaway_after_complete_response_closes_connection(self) -> None:
        """GOAWAY in a later recv than StreamEnded must still close the connection."""

        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            server.send_headers(
                event.stream_id, [(b":status", b"200")], end_stream=False
            )
            server.send_data(event.stream_id, b"done", end_stream=True)

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")

            # Produce GOAWAY bytes, but only inject them once StreamEnded has
            # been parsed, so they can only surface in the drain loop's recv.
            sock._server.close_connection(error_code=h2.errors.ErrorCodes.NO_ERROR)
            deferred_goaway = sock._server.data_to_send()
            assert deferred_goaway

            with conn._h2_conn as h2_conn:
                original_receive = h2_conn.receive_data

                def receive_then_inject(data: bytes) -> list[h2.events.Event]:
                    events = list(original_receive(data))
                    if any(isinstance(e, h2.events.StreamEnded) for e in events):
                        sock.inject_frames(deferred_goaway)
                        # Sending on a socketpair is not synchronous on
                        # Windows: block until the injected bytes are
                        # visible to the drain loop's zero-timeout poll.
                        assert wait_for_read(
                            typing.cast(socket.socket, sock), timeout=5.0
                        )
                    return events

                h2_conn.receive_data = receive_then_inject  # type: ignore[method-assign]

            response = conn.getresponse()
            assert response.status == 200
            assert response.data == b"done"
            assert conn.sock is None

    def test_unrelated_stream_reset_is_ignored(self) -> None:
        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            server.send_headers(
                event.stream_id, [(b":status", b"200")], end_stream=False
            )
            server.send_data(event.stream_id, b"ok", end_stream=True)

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")

            with conn._h2_conn as h2_conn:
                original_receive = h2_conn.receive_data

                def receive_with_foreign_reset(data: bytes) -> list[h2.events.Event]:
                    events = list(original_receive(data))
                    events.insert(
                        0,
                        h2.events.StreamReset(
                            stream_id=99,
                            error_code=h2.errors.ErrorCodes.CANCEL,
                            remote_reset=True,
                        ),
                    )
                    return events

                h2_conn.receive_data = receive_with_foreign_reset  # type: ignore[method-assign]

            response = conn.getresponse()
            assert response.status == 200
            assert response.data == b"ok"

    def test_connection_closed_without_goaway_raises(self) -> None:
        """TCP close with an empty recv must raise, not spin forever."""

        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            return None

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")
            # Discard any pending control frames, then EOF the client side.
            while wait_for_read(typing.cast(socket.socket, sock), timeout=0.0):
                if not sock.recv(65535):
                    break
            sock.close_writes()
            with pytest.raises(
                ConnectionError,
                match="Connection closed while reading HTTP/2 response",
            ):
                conn.getresponse()

    def test_successful_response_unaffected(self) -> None:
        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            server.send_headers(
                event.stream_id,
                [(b":status", b"200"), (b"content-type", b"text/plain")],
                end_stream=False,
            )
            server.send_data(event.stream_id, b"hello", end_stream=True)

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")
            response = conn.getresponse()
            assert response.status == 200
            assert response.data == b"hello"
            assert response.headers["content-type"] == "text/plain"

    def test_local_stream_reset_message(self) -> None:
        event = h2.events.StreamReset(
            stream_id=5,
            error_code=h2.errors.ErrorCodes.PROTOCOL_ERROR,
            remote_reset=False,
        )
        with pytest.raises(
            ConnectionError, match="stream 5 was reset with error code PROTOCOL_ERROR"
        ):
            _raise_for_h2_error_event(event)

    def test_wraps_h2_error_from_receive_data(self) -> None:
        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            server.send_headers(
                event.stream_id, [(b":status", b"200")], end_stream=True
            )

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")

            with conn._h2_conn as h2_conn:
                h2_conn.receive_data = mock.Mock(  # type: ignore[method-assign]
                    side_effect=h2.exceptions.ProtocolError("bad frame")
                )

            with pytest.raises(
                ConnectionError, match="HTTP/2 protocol error: bad frame"
            ):
                conn.getresponse()

    def test_unrelated_response_and_data_are_ignored(self) -> None:
        """Headers and body frames for a foreign stream must not leak into ours."""

        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            server.send_headers(
                event.stream_id, [(b":status", b"200")], end_stream=False
            )
            server.send_data(event.stream_id, b"ok", end_stream=True)

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")

            with conn._h2_conn as h2_conn:
                original_receive = h2_conn.receive_data

                def receive_with_foreign_events(data: bytes) -> list[h2.events.Event]:
                    events = list(original_receive(data))
                    # Appended after the real events: without the stream id
                    # guards this response would overwrite the real status
                    # and headers, so the assertions below prove the guards.
                    events.append(
                        h2.events.ResponseReceived(
                            stream_id=99,
                            headers=[(b":status", b"500"), (b"x-foreign", b"1")],
                        )
                    )
                    events.append(
                        h2.events.DataReceived(
                            stream_id=99, data=b"junk", flow_controlled_length=4
                        )
                    )
                    return events

                h2_conn.receive_data = receive_with_foreign_events  # type: ignore[method-assign]

            response = conn.getresponse()
            assert response.status == 200
            assert response.data == b"ok"
            assert "x-foreign" not in response.headers

    def test_connection_close_during_drain_is_tolerated(self) -> None:
        """EOF while draining post-response frames must not fail the request."""

        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            server.send_headers(
                event.stream_id, [(b":status", b"200")], end_stream=False
            )
            server.send_data(event.stream_id, b"done", end_stream=True)

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")

            with conn._h2_conn as h2_conn:
                original_receive = h2_conn.receive_data

                def receive_then_eof(data: bytes) -> list[h2.events.Event]:
                    events = list(original_receive(data))
                    if any(isinstance(e, h2.events.StreamEnded) for e in events):
                        # Peer closes right after the response: the drain
                        # loop sees a readable socket whose recv returns
                        # b"". Block until the EOF is actually visible to
                        # its zero-timeout poll (asynchronous on Windows).
                        sock.close_writes()
                        assert wait_for_read(
                            typing.cast(socket.socket, sock), timeout=5.0
                        )
                    return events

                h2_conn.receive_data = receive_then_eof  # type: ignore[method-assign]

            response = conn.getresponse()
            assert response.status == 200
            assert response.data == b"done"

    def test_late_stream_reset_during_drain_is_ignored(self) -> None:
        """RST_STREAM arriving after StreamEnded must not fail the request."""

        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            server.send_headers(
                event.stream_id, [(b":status", b"200")], end_stream=False
            )
            server.send_data(event.stream_id, b"done", end_stream=True)

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")

            # PING bytes make the drain loop find a readable socket; the client
            # queues a PING ACK so the drain loop also sends data.
            sock._server.ping(b"01234567")
            ping_bytes = sock._server.data_to_send()
            assert ping_bytes

            with conn._h2_conn as h2_conn:
                original_receive = h2_conn.receive_data
                stream_ended = False

                def receive_with_late_reset(data: bytes) -> list[h2.events.Event]:
                    nonlocal stream_ended
                    events = list(original_receive(data))
                    if any(isinstance(e, h2.events.StreamEnded) for e in events):
                        stream_ended = True
                        # Inject only after StreamEnded was parsed, so the
                        # PING can only surface in the drain loop's recv,
                        # and block until it is visible to the drain loop's
                        # zero-timeout poll (asynchronous on Windows).
                        sock.inject_frames(ping_bytes)
                        assert wait_for_read(
                            typing.cast(socket.socket, sock), timeout=5.0
                        )
                    elif stream_ended:
                        # This call is the drain loop's: surface a late reset
                        # of the already-ended stream.
                        events.insert(
                            0,
                            h2.events.StreamReset(
                                stream_id=1,
                                error_code=h2.errors.ErrorCodes.CANCEL,
                                remote_reset=True,
                            ),
                        )
                    return events

                h2_conn.receive_data = receive_with_late_reset  # type: ignore[method-assign]

            response = conn.getresponse()
            assert response.status == 200
            assert response.data == b"done"
            # A late reset of a finished stream is not a connection error.
            assert conn.sock is not None

    def test_h2_error_during_drain_raises(self) -> None:
        """A malformed frame while draining must surface as ConnectionError."""

        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            server.send_headers(
                event.stream_id, [(b":status", b"200")], end_stream=False
            )
            server.send_data(event.stream_id, b"done", end_stream=True)

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")

            sock._server.ping(b"01234567")
            ping_bytes = sock._server.data_to_send()

            with conn._h2_conn as h2_conn:
                original_receive = h2_conn.receive_data
                stream_ended = False

                def receive_then_fail(data: bytes) -> list[h2.events.Event]:
                    nonlocal stream_ended
                    if stream_ended:
                        raise h2.exceptions.ProtocolError("late frame")
                    events = list(original_receive(data))
                    if any(isinstance(e, h2.events.StreamEnded) for e in events):
                        stream_ended = True
                        # Inject only after StreamEnded was parsed and block
                        # until readable, so the drain loop is guaranteed to
                        # pick the PING up and hit the failure path.
                        sock.inject_frames(ping_bytes)
                        assert wait_for_read(
                            typing.cast(socket.socket, sock), timeout=5.0
                        )
                    return events

                h2_conn.receive_data = receive_then_fail  # type: ignore[method-assign]

            with pytest.raises(
                ConnectionError, match="HTTP/2 protocol error: late frame"
            ):
                conn.getresponse()

    def test_stream_ended_without_status_raises(self) -> None:
        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            # Send something so the client has bytes to read; the patched
            # receive_data below turns them into a bare StreamEnded.
            server.ping(b"01234567")

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")

            with conn._h2_conn as h2_conn:
                h2_conn.receive_data = (  # type: ignore[method-assign]
                    lambda data: [h2.events.StreamEnded(stream_id=1)]
                )

            with pytest.raises(
                ConnectionError, match="ended without receiving a status"
            ):
                conn.getresponse()

    def test_close_failure_during_error_cleanup_is_swallowed(self) -> None:
        """A failing close() must not mask the original ConnectionError."""

        def on_request(
            server: h2.connection.H2Connection, event: h2.events.RequestReceived
        ) -> None:
            server.reset_stream(
                event.stream_id, error_code=h2.errors.ErrorCodes.REFUSED_STREAM
            )

        conn = HTTP2Connection("example.com")
        with _H2PeerSocket(on_request) as sock:
            _connect_http2(conn, sock)
            conn.request("GET", "/")
            close_mock = mock.Mock(side_effect=RuntimeError("boom"))
            conn.close = close_mock  # type: ignore[method-assign]
            with pytest.raises(ProtocolError, match="REFUSED_STREAM"):
                conn.getresponse()
            assert close_mock.call_count == 1


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
