from __future__ import annotations

import socket
import threading
from http.client import CannotSendRequest
from unittest import mock

import h2.config
import h2.connection
import h2.events
import h2.exceptions
import h2.settings
import pytest

from urllib3 import HTTPSConnectionPool
from urllib3._collections import HTTPHeaderDict
from urllib3.connection import _get_default_user_agent
from urllib3.exceptions import ConnectionError
from urllib3.http2.connection import (
    HTTP2Connection,
    HTTP2Response,
    _is_illegal_header_value,
    _is_legal_header_name,
)

# [1] https://httpwg.org/specs/rfc9113.html#n-field-validity


class TestHTTP2Connection:
    @staticmethod
    def _connected_h2_pair(
        connection_class: type[HTTP2Connection] = HTTP2Connection,
    ) -> tuple[HTTP2Connection, socket.socket, h2.connection.H2Connection]:
        client_sock, server_sock = socket.socketpair()
        server_h2 = h2.connection.H2Connection(
            config=h2.config.H2Configuration(client_side=False)
        )
        conn = connection_class("example.com")
        conn.sock = client_sock

        with conn._h2_conn as client_h2:
            client_h2.initiate_connection()
            client_sock.sendall(client_h2.data_to_send())

        server_h2.initiate_connection()
        server_h2.receive_data(server_sock.recv(65535))
        server_sock.sendall(server_h2.data_to_send())
        return conn, server_sock, server_h2

    @staticmethod
    def _send_response(
        conn: HTTP2Connection,
        server_sock: socket.socket,
        server_h2: h2.connection.H2Connection,
        path: str,
        body: bytes,
    ) -> int:
        conn.request("GET", path)
        events = server_h2.receive_data(server_sock.recv(65535))
        stream_id = next(
            event.stream_id
            for event in events
            if isinstance(event, h2.events.RequestReceived)
        )
        server_h2.send_headers(
            stream_id,
            [(":status", "200"), ("content-length", str(len(body)))],
        )
        server_h2.send_data(stream_id, body, end_stream=True)
        server_sock.sendall(server_h2.data_to_send())
        assert conn.getresponse().data == body
        return stream_id

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

    def test_response_url_can_be_updated_for_retry_history(self) -> None:
        response = HTTP2Response(200, HTTPHeaderDict(), "/original", b"")

        assert response.url == "/original"
        response.url = "/retried"
        assert response.url == "/retried"

    def test_pool_reuses_connection_after_processing_idle_ping(self) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()
        pool = HTTPSConnectionPool("example.com", maxsize=1)

        class RecordingSocket:
            def __init__(self, wrapped: socket.socket) -> None:
                self.wrapped = wrapped
                self.send_timeouts: list[float | None] = []

            def __getattr__(self, name: str) -> object:
                return getattr(self.wrapped, name)

            def sendall(self, data: bytes) -> None:
                self.send_timeouts.append(self.wrapped.gettimeout())
                self.wrapped.sendall(data)

        try:
            first_stream_id = self._send_response(
                conn, server_sock, server_h2, "/", b"first"
            )

            server_h2.ping(b"12345678")
            server_sock.sendall(server_h2.data_to_send())

            original_timeout = 12.5
            assert conn.sock is not None
            recording_sock = RecordingSocket(conn.sock)
            conn.sock = recording_sock
            recording_sock.wrapped.settimeout(original_timeout)
            assert conn.is_connected
            assert recording_sock.wrapped.gettimeout() == original_timeout
            assert recording_sock.send_timeouts == [original_timeout]

            events = server_h2.receive_data(server_sock.recv(65535))
            assert any(isinstance(event, h2.events.PingAckReceived) for event in events)

            assert pool.pool is not None
            pool.pool.get(block=False)
            pool._put_conn(conn)
            reused = pool._get_conn()
            assert reused is conn
            assert reused.sock is not None

            second_stream_id = self._send_response(
                reused, server_sock, server_h2, "/again", b"second"
            )
            assert second_stream_id > first_stream_id
        finally:
            conn.close()
            pool.close()
            server_sock.close()

    def test_idle_eof_is_not_reusable(self) -> None:
        conn, server_sock, _ = self._connected_h2_pair()
        try:
            server_sock.close()
            assert not conn.is_connected
        finally:
            conn.close()

    def test_idle_goaway_is_not_reusable(self) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()
        try:
            stream_id = self._send_response(
                conn, server_sock, server_h2, "/", b"complete"
            )
            server_h2.close_connection(error_code=0, last_stream_id=stream_id)
            server_sock.sendall(server_h2.data_to_send())

            assert not conn.is_connected
        finally:
            conn.close()
            server_sock.close()

    def test_request_rechecks_for_goaway_after_pool_probe(self) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()
        try:
            stream_id = self._send_response(
                conn, server_sock, server_h2, "/", b"complete"
            )
            assert conn.is_connected

            server_h2.close_connection(error_code=0, last_stream_id=stream_id)
            server_sock.sendall(server_h2.data_to_send())

            with pytest.raises(ConnectionError, match="no longer reusable"):
                conn.request("GET", "/must-not-be-sent")
        finally:
            conn.close()
            server_sock.close()

    def test_pool_retries_on_goaway_between_health_check_and_request(self) -> None:
        class GoawayAfterProbeConnection(HTTP2Connection):
            server_sock: socket.socket
            server_h2: h2.connection.H2Connection
            sent_goaway = False

            def _probe_idle_connection(self) -> bool:
                reusable = super()._probe_idle_connection()
                if self._has_completed_response and reusable and not self.sent_goaway:
                    self.server_h2.close_connection(
                        error_code=0,
                        last_stream_id=self.server_h2.highest_inbound_stream_id,
                    )
                    self.server_sock.sendall(self.server_h2.data_to_send())
                    self.sent_goaway = True
                return reusable

        first_conn, first_server_sock, first_server_h2 = self._connected_h2_pair(
            GoawayAfterProbeConnection
        )
        assert isinstance(first_conn, GoawayAfterProbeConnection)
        first_conn.server_sock = first_server_sock
        first_conn.server_h2 = first_server_h2
        first_conn.is_verified = True
        second_conn, second_server_sock, second_server_h2 = self._connected_h2_pair()
        second_conn.is_verified = True

        class TwoConnectionPool(HTTPSConnectionPool):
            def __init__(self) -> None:
                super().__init__("example.com", maxsize=1)
                self.available_connections = [first_conn, second_conn]

            def _new_conn(self) -> HTTP2Connection:
                self.num_connections += 1
                return self.available_connections.pop(0)

        def serve_one_response(
            server_sock: socket.socket,
            server_h2: h2.connection.H2Connection,
            body: bytes,
        ) -> None:
            events = server_h2.receive_data(server_sock.recv(65535))
            stream_id = next(
                event.stream_id
                for event in events
                if isinstance(event, h2.events.RequestReceived)
            )
            server_h2.send_headers(
                stream_id,
                [(":status", "200"), ("content-length", str(len(body)))],
            )
            server_h2.send_data(stream_id, body, end_stream=True)
            server_sock.sendall(server_h2.data_to_send())

        pool = TwoConnectionPool()
        first_server = threading.Thread(
            target=serve_one_response,
            args=(first_server_sock, first_server_h2, b"first"),
        )
        first_server.start()
        try:
            first_response = pool.request("GET", "/first", retries=1)
            first_server.join(timeout=1)
            assert not first_server.is_alive()
            assert first_response.data == b"first"

            second_server = threading.Thread(
                target=serve_one_response,
                args=(second_server_sock, second_server_h2, b"second"),
            )
            second_server.start()
            second_response = pool.request("GET", "/second", retries=1)
            second_server.join(timeout=1)
            assert not second_server.is_alive()

            assert second_response.data == b"second"
            assert first_conn.sent_goaway
            assert first_conn.sock is None
            assert pool.num_connections == 2
        finally:
            pool.close()
            first_conn.close()
            second_conn.close()
            first_server_sock.close()
            second_server_sock.close()

    def test_pool_retries_when_peer_disables_new_streams(self) -> None:
        first_conn, first_server_sock, first_server_h2 = self._connected_h2_pair()
        second_conn, second_server_sock, second_server_h2 = self._connected_h2_pair()
        first_conn.is_verified = True
        second_conn.is_verified = True

        class TwoConnectionPool(HTTPSConnectionPool):
            def __init__(self) -> None:
                super().__init__("example.com", maxsize=1)
                self.available_connections = [first_conn, second_conn]

            def _new_conn(self) -> HTTP2Connection:
                self.num_connections += 1
                return self.available_connections.pop(0)

        def serve_one_response(
            server_sock: socket.socket,
            server_h2: h2.connection.H2Connection,
            body: bytes,
        ) -> None:
            events = server_h2.receive_data(server_sock.recv(65535))
            stream_id = next(
                event.stream_id
                for event in events
                if isinstance(event, h2.events.RequestReceived)
            )
            server_h2.send_headers(
                stream_id,
                [(":status", "200"), ("content-length", str(len(body)))],
            )
            server_h2.send_data(stream_id, body, end_stream=True)
            server_sock.sendall(server_h2.data_to_send())

        pool = TwoConnectionPool()
        first_server = threading.Thread(
            target=serve_one_response,
            args=(first_server_sock, first_server_h2, b"first"),
        )
        first_server.start()
        try:
            first_response = pool.request("GET", "/first", retries=1)
            first_server.join(timeout=1)
            assert not first_server.is_alive()
            assert first_response.data == b"first"

            first_server_h2.update_settings(
                {h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 0}
            )
            first_server_sock.sendall(first_server_h2.data_to_send())

            second_server = threading.Thread(
                target=serve_one_response,
                args=(second_server_sock, second_server_h2, b"second"),
            )
            second_server.start()
            second_response = pool.request("GET", "/second", retries=1)
            second_server.join(timeout=1)
            assert not second_server.is_alive()

            assert second_response.data == b"second"
            assert first_conn.sock is None
            assert pool.num_connections == 2
        finally:
            pool.close()
            first_conn.close()
            second_conn.close()
            first_server_sock.close()
            second_server_sock.close()

    def test_idle_settings_are_processed_and_acknowledged(self) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()
        try:
            self._send_response(conn, server_sock, server_h2, "/", b"complete")
            server_h2.update_settings(
                {h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 1}
            )
            server_sock.sendall(server_h2.data_to_send())

            assert conn.is_connected
            events = server_h2.receive_data(server_sock.recv(65535))
            assert any(
                isinstance(event, h2.events.SettingsAcknowledged) for event in events
            )
        finally:
            conn.close()
            server_sock.close()

    def test_zero_max_concurrent_streams_is_explicit_and_can_be_restored(
        self,
    ) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()
        try:
            self._send_response(conn, server_sock, server_h2, "/", b"first")

            server_h2.update_settings(
                {h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 0}
            )
            server_sock.sendall(server_h2.data_to_send())
            assert conn.is_connected
            server_h2.receive_data(server_sock.recv(65535))

            with pytest.raises(ConnectionError, match="does not currently allow"):
                conn.request("GET", "/blocked")

            server_h2.update_settings(
                {h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 1}
            )
            server_sock.sendall(server_h2.data_to_send())
            assert conn.is_connected
            server_h2.receive_data(server_sock.recv(65535))

            self._send_response(conn, server_sock, server_h2, "/restored", b"second")
        finally:
            conn.close()
            server_sock.close()

    def test_stream_owner_prevents_idle_probe_from_consuming_response(self) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()
        response_owner = object()
        try:
            conn.request("GET", "/")
            events = server_h2.receive_data(server_sock.recv(65535))
            stream_id = next(
                event.stream_id
                for event in events
                if isinstance(event, h2.events.RequestReceived)
            )
            server_h2.send_headers(stream_id, [(":status", "200")])
            server_h2.send_data(stream_id, b"owned", end_stream=True)
            server_sock.sendall(server_h2.data_to_send())

            conn._transfer_stream_owner(conn, response_owner)
            original_stream_id = conn._h2_stream
            original_request_url = conn._request_url
            with pytest.raises(CannotSendRequest, match="response stream is active"):
                conn.request("GET", "/must-not-overwrite-owner")
            assert conn._stream_owner is response_owner
            assert conn._h2_stream == original_stream_id
            assert conn._request_url == original_request_url
            assert conn._headers == []

            assert conn.is_connected
            with pytest.raises(RuntimeError, match="different owner"):
                conn._receive_events(stream_owner=conn)

            response_events = conn._receive_events(stream_owner=response_owner)
            assert response_events is not None
            assert any(
                isinstance(event, h2.events.DataReceived) and event.data == b"owned"
                for event in response_events
            )
            assert any(
                isinstance(event, h2.events.StreamEnded) for event in response_events
            )
            conn._release_stream_owner(response_owner)
            with pytest.raises(RuntimeError, match="different owner"):
                conn._receive_events(stream_owner=response_owner)
        finally:
            conn.close()
            server_sock.close()

    def test_active_stream_reset_fails_immediately(self) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()
        try:
            conn.request("GET", "/")
            events = server_h2.receive_data(server_sock.recv(65535))
            stream_id = next(
                event.stream_id
                for event in events
                if isinstance(event, h2.events.RequestReceived)
            )
            server_h2.reset_stream(stream_id, error_code=8)
            server_sock.sendall(server_h2.data_to_send())

            with pytest.raises(ConnectionError, match="stream was reset.*8"):
                conn.getresponse()
        finally:
            conn.close()
            server_sock.close()

    def test_active_goaway_fails_immediately(self) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()
        try:
            conn.request("GET", "/")
            server_h2.receive_data(server_sock.recv(65535))
            server_h2.close_connection(error_code=0, last_stream_id=0)
            server_sock.sendall(server_h2.data_to_send())

            with pytest.raises(ConnectionError, match="connection was terminated.*0"):
                conn.getresponse()
        finally:
            conn.close()
            server_sock.close()

    def test_idle_probe_is_bounded_under_continuous_control_frames(self) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()

        class OneFrameSocket:
            def __init__(self, wrapped: socket.socket) -> None:
                self.wrapped = wrapped
                self.recv_calls = 0

            def __getattr__(self, name: str) -> object:
                return getattr(self.wrapped, name)

            def recv(self, size: int) -> bytes:
                self.recv_calls += 1
                return self.wrapped.recv(17)

        try:
            self._send_response(conn, server_sock, server_h2, "/", b"complete")
            for ping_id in range(17):
                server_h2.ping(ping_id.to_bytes(8, "big"))
            server_sock.sendall(server_h2.data_to_send())

            assert conn.sock is not None
            one_frame_sock = OneFrameSocket(conn.sock)
            conn.sock = one_frame_sock
            assert not conn.is_connected
            assert one_frame_sock.recv_calls == 16
        finally:
            conn.close()
            server_sock.close()

    def test_idle_probe_timeout_accessor_failure_is_not_reusable(self) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()

        class BrokenTimeoutSocket:
            def __init__(self, wrapped: socket.socket) -> None:
                self.wrapped = wrapped

            def __getattr__(self, name: str) -> object:
                return getattr(self.wrapped, name)

            def gettimeout(self) -> float | None:
                raise OSError("socket unavailable")

        try:
            self._send_response(conn, server_sock, server_h2, "/", b"complete")
            assert conn.sock is not None
            conn.sock = BrokenTimeoutSocket(conn.sock)
            assert not conn.is_connected
        finally:
            conn.close()
            server_sock.close()

    def test_idle_probe_treats_zero_timeout_as_no_pending_data(self) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()

        class TimeoutSocket:
            def __init__(self, wrapped: socket.socket) -> None:
                self.wrapped = wrapped

            def __getattr__(self, name: str) -> object:
                return getattr(self.wrapped, name)

            def recv(self, size: int) -> bytes:
                if self.wrapped.gettimeout() == 0:
                    raise TimeoutError("non-blocking read would block")
                return self.wrapped.recv(size)

        try:
            self._send_response(conn, server_sock, server_h2, "/", b"complete")
            assert conn.sock is not None
            timeout_sock = TimeoutSocket(conn.sock)
            conn.sock = timeout_sock
            timeout_sock.wrapped.settimeout(7.5)

            assert conn.is_connected
            assert timeout_sock.wrapped.gettimeout() == 7.5
        finally:
            conn.close()
            server_sock.close()

    def test_failed_idle_control_frame_ack_makes_connection_unusable(self) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()

        class AckFailingSocket:
            def __init__(self, wrapped: socket.socket) -> None:
                self.wrapped = wrapped
                self.send_timeouts: list[float | None] = []

            def __getattr__(self, name: str) -> object:
                return getattr(self.wrapped, name)

            def sendall(self, data: bytes) -> None:
                self.send_timeouts.append(self.wrapped.gettimeout())
                raise BlockingIOError

        try:
            self._send_response(conn, server_sock, server_h2, "/", b"complete")
            server_h2.ping(b"12345678")
            server_sock.sendall(server_h2.data_to_send())

            assert conn.sock is not None
            failing_sock = AckFailingSocket(conn.sock)
            conn.sock = failing_sock
            failing_sock.wrapped.settimeout(9.5)

            assert not conn.is_connected
            assert failing_sock.wrapped.gettimeout() == 9.5
            assert failing_sock.send_timeouts == [9.5]
        finally:
            conn.close()
            server_sock.close()

    def test_response_completed_before_goaway_is_returned_but_not_reused(
        self,
    ) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()
        try:
            conn.request("GET", "/")
            events = server_h2.receive_data(server_sock.recv(65535))
            stream_id = next(
                event.stream_id
                for event in events
                if isinstance(event, h2.events.RequestReceived)
            )
            server_h2.send_headers(
                stream_id,
                [(":status", "200"), ("content-length", "8")],
            )
            server_h2.send_data(stream_id, b"complete", end_stream=True)
            server_h2.close_connection(error_code=0, last_stream_id=stream_id)
            server_sock.sendall(server_h2.data_to_send())

            assert conn.getresponse().data == b"complete"
            assert not conn.is_connected
        finally:
            conn.close()
            server_sock.close()

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

    def test_transfer_stream_owner_with_wrong_current_owner(self) -> None:
        conn = HTTP2Connection("example.com")
        owner_a = object()
        owner_b = object()
        conn._stream_owner = owner_a
        with pytest.raises(RuntimeError, match="different owner"):
            conn._transfer_stream_owner(owner_b, object())
        assert conn._stream_owner is owner_a

    def test_getresponse_eof_raises_protocol_error(self) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()
        try:
            conn.request("GET", "/")
            server_h2.receive_data(server_sock.recv(65535))

            # Replace socket with one that returns EOF immediately.
            original_sock = conn.sock
            conn.sock = mock.MagicMock(recv=mock.Mock(return_value=b""))
            assert original_sock is not None
            original_sock.close()

            with pytest.raises(ConnectionError, match="closed before the response"):
                conn.getresponse()
            assert conn._connection_terminated
        finally:
            conn.close()
            server_sock.close()

    def test_idle_probe_set_nonblocking_oserror_is_not_reusable(self) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()

        class SetNonblockingFailingSocket:
            def __init__(self, wrapped: socket.socket) -> None:
                self.wrapped = wrapped

            def __getattr__(self, name: str) -> object:
                return getattr(self.wrapped, name)

            def settimeout(self, timeout: float | None) -> None:
                if timeout == 0.0:
                    raise OSError("cannot set non-blocking")
                self.wrapped.settimeout(timeout)

        try:
            self._send_response(conn, server_sock, server_h2, "/", b"complete")
            assert conn.sock is not None
            failing_sock = SetNonblockingFailingSocket(conn.sock)
            failing_sock.wrapped.settimeout(5.0)
            conn.sock = failing_sock
            assert not conn.is_connected
        finally:
            conn.close()
            server_sock.close()

    def test_idle_probe_restore_timeout_oserror_is_not_reusable(self) -> None:
        conn, server_sock, server_h2 = self._connected_h2_pair()

        class RestoreTimeoutFailingSocket:
            def __init__(self, wrapped: socket.socket) -> None:
                self.wrapped = wrapped
                self._settimeout_count = 0

            def __getattr__(self, name: str) -> object:
                return getattr(self.wrapped, name)

            def settimeout(self, timeout: float | None) -> None:
                self._settimeout_count += 1
                if self._settimeout_count >= 2:
                    raise OSError("cannot restore timeout")
                self.wrapped.settimeout(timeout)

        try:
            self._send_response(conn, server_sock, server_h2, "/", b"complete")
            assert conn.sock is not None
            failing_sock = RestoreTimeoutFailingSocket(conn.sock)
            failing_sock.wrapped.settimeout(5.0)
            conn.sock = failing_sock
            assert not conn.is_connected
        finally:
            conn.close()
            server_sock.close()

    def test_endheaders_too_many_streams_cleans_up(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.sock = mock.MagicMock(sendall=mock.Mock(return_value=None))
        conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"foo")  # type: ignore[method-assign]
        conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)  # type: ignore[method-assign]
        conn._h2_conn._obj.send_headers = mock.Mock(  # type: ignore[method-assign]
            side_effect=h2.exceptions.TooManyStreamsError
        )

        conn.putrequest("GET", "/")
        assert conn._stream_owner is conn
        with pytest.raises(ConnectionError, match="does not currently allow"):
            conn.endheaders()

        assert conn._headers == []
        assert conn._stream_owner is None
        assert conn._h2_stream is None

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
