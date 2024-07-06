from __future__ import annotations

import socket
from unittest import mock

import pytest

from urllib3.connection import _get_default_user_agent
from urllib3.exceptions import ConnectionError
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
        conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"bar")
        conn._h2_conn._obj.send_data = mock.Mock(return_value=None)
        conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)

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
        conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"bar")
        conn._h2_conn._obj.send_data = mock.Mock(return_value=None)
        conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)

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
        conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"baz")
        conn._h2_conn._obj.send_data = mock.Mock(return_value=None)
        conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)
        conn._h2_conn._obj.end_stream = mock.Mock(return_value=None)

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
            conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"foo")
            conn._h2_conn._obj.send_data = mock.Mock(return_value=None)
            conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)
            conn._h2_conn._obj.end_stream = mock.Mock(return_value=None)

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
            conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"foo")
            conn._h2_conn._obj.send_data = mock.Mock(return_value=None)
            conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)
            conn._h2_conn._obj.end_stream = mock.Mock(return_value=None)

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
        data_to_send = conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"foo")
        send_headers = conn._h2_conn._obj.send_headers = mock.Mock(return_value=None)
        conn._h2_conn._obj.send_data = mock.Mock(return_value=None)
        conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)
        close_connection = conn._h2_conn._obj.close_connection = mock.Mock(
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

    def test_request_POST(self) -> None:
        conn = HTTP2Connection("example.com")
        conn.sock = mock.MagicMock(
            sendall=mock.Mock(return_value=None),
        )
        sendall = conn.sock.sendall
        data_to_send = conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"foo")
        send_headers = conn._h2_conn._obj.send_headers = mock.Mock(return_value=None)
        send_data = conn._h2_conn._obj.send_data = mock.Mock(return_value=None)
        conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)
        close_connection = conn._h2_conn._obj.close_connection = mock.Mock(
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
