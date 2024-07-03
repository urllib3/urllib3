from __future__ import annotations

import socket
from unittest import mock

from urllib3.connection import _get_default_user_agent
from urllib3.http2 import (
    HTTP2Connection,
    _is_illegal_header_value,
    _is_legal_header_name,
)


class TestHTTP2Connection:
    def test__is_legal_header_name(self) -> None:
        assert _is_legal_header_name(b":foo")
        assert _is_legal_header_name(b"foo")
        assert _is_legal_header_name(b"foo-bar")
        assert not _is_legal_header_name(b"foo bar")
        assert not _is_legal_header_name(b"foo:bar")
        assert not _is_legal_header_name(b"foo\nbar")
        assert not _is_legal_header_name(b"foo\tbar")

    def test__is_illegal_header_value(self) -> None:
        assert not _is_illegal_header_value(b"foo")
        assert not _is_illegal_header_value(b"foo bar")
        assert not _is_illegal_header_value(b"foo\tbar")
        assert _is_illegal_header_value(b"foo\0bar")  # null byte
        assert _is_illegal_header_value(b"foo\x00bar")  # null byte
        assert _is_illegal_header_value(b"foo\x0bbar")  # vertical tab
        assert _is_illegal_header_value(b"foo\x0cbar")  # form feed
        assert _is_illegal_header_value(b"foo\rbar")
        assert _is_illegal_header_value(b"foo\nbar")

    def test_default_socket_options(self) -> None:
        conn = HTTP2Connection("example.com")
        assert conn.socket_options == [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]
        assert conn.port == 443

    def test_putheader(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.putheader("foo", "bar")
        assert conn._headers == [(b"foo", b"bar")]

    def test_send_bytes(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(return_value=None),
        )
        conn.conn._obj.send_data = mock.Mock(return_value=None)
        conn.conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)
        conn.conn._obj.end_stream = mock.Mock(return_value=None)

        conn.putrequest("GET", "/")
        conn.endheaders()
        conn.send(b"foo")

        conn.conn._obj.send_data.assert_called_with(1, b"foo", end_stream=True)

    def test_send_str(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(return_value=None),
        )
        conn.conn._obj.send_data = mock.Mock(return_value=None)
        conn.conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)
        conn.conn._obj.end_stream = mock.Mock(return_value=None)

        conn.putrequest("GET", "/")
        conn.endheaders(message_body=b"foo")
        conn.send("foo")

        conn.conn._obj.send_data.assert_called_with(1, b"foo", end_stream=True)

    def test_send_iter(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(return_value=None),
        )
        conn.conn._obj.send_data = mock.Mock(return_value=None)
        conn.conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)
        conn.conn._obj.end_stream = mock.Mock(return_value=None)

        conn.putrequest("GET", "/")
        conn.endheaders(message_body=[b"foo", b"bar"])
        conn.send([b"foo", b"bar"])

        conn.conn._obj.send_data.assert_has_calls(
            [
                mock.call(1, b"foo", end_stream=False),
                mock.call(1, b"bar", end_stream=False),
            ]
        )
        conn.conn._obj.end_stream.assert_called_with(1)

    def test_send_file(self) -> None:
        conn = HTTP2Connection("example.com")
        mock_open = mock.mock_open(read_data=b"foo\r\nbar\r\n")
        with mock.patch("builtins.open", mock_open):
            conn.sock = mock.MagicMock(
                sendall=mock.Mock(return_value=None),
            )
            conn.conn._obj.send_data = mock.Mock(return_value=None)
            conn.conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)
            conn.conn._obj.end_stream = mock.Mock(return_value=None)

            body = open("test.txt", "rb")
            conn.putrequest("GET", "/")
            conn.endheaders(message_body=body)
            conn.send(body)

            conn.conn._obj.send_data.assert_called_with(
                1, b"foo\r\nbar\r\n", end_stream=False
            )
            conn.conn._obj.end_stream.assert_called_with(1)

    def test__has_header(self) -> None:
        conn = HTTP2Connection("example.com")
        conn._headers = [(b"foo", b"bar")]
        assert conn._has_header("foo")
        assert not conn._has_header("bar")

    def test_request_GET(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(return_value=None),
        )
        conn.conn._obj.send_headers = send_headers = mock.Mock(return_value=None)
        conn.conn._obj.send_data = mock.Mock(return_value=None)
        conn.conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)
        conn.conn._obj.close_connection = close_connection = mock.Mock(
            return_value=None
        )

        conn.request("GET", "/")
        conn.close()

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

    def test_request_POST(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(return_value=None),
        )
        conn.conn._obj.send_headers = send_headers = mock.Mock(return_value=None)
        conn.conn._obj.send_data = send_data = mock.Mock(return_value=None)
        conn.conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)
        conn.conn._obj.close_connection = close_connection = mock.Mock(
            return_value=None
        )

        conn.request("POST", "/", body=b"foo")
        conn.close()

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
