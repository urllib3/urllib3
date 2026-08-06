from __future__ import annotations

import socket
import ssl
import threading
from unittest import mock

import h2.config
import h2.connection
import h2.events
import pytest

from dummyserver.socketserver import DEFAULT_CA, DEFAULT_CERTS
from urllib3.connection import ProxyConfig, _get_default_user_agent
from urllib3.exceptions import ConnectionError
from urllib3.http2.connection import (
    HTTP2Connection,
    _is_illegal_header_value,
    _is_legal_header_name,
)
from urllib3.util import parse_url
from urllib3.util import ssl_ as urllib3_ssl

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

    def _mock_h2_send(self, conn: HTTP2Connection) -> mock.Mock:
        conn.sock = mock.MagicMock(sendall=mock.Mock(return_value=None))
        conn._h2_conn._obj.data_to_send = mock.Mock(return_value=b"foo")  # type: ignore[method-assign]
        send_headers = conn._h2_conn._obj.send_headers = mock.Mock(return_value=None)  # type: ignore[method-assign]
        conn._h2_conn._obj.send_data = mock.Mock(return_value=None)  # type: ignore[method-assign]
        conn._h2_conn._obj.get_next_available_stream_id = mock.Mock(return_value=1)  # type: ignore[method-assign]
        conn._h2_conn._obj.close_connection = mock.Mock(return_value=None)  # type: ignore[method-assign]
        return send_headers

    def test_forwarding_proxy_construction_is_allowed(self) -> None:
        conn = HTTP2Connection(
            "proxy.example",
            8443,
            proxy=parse_url("https://proxy.example:8443"),
            proxy_config=ProxyConfig(None, True, None, None),
        )
        assert conn.proxy_is_forwarding is True
        assert conn.proxy_is_tunneling is False

    @pytest.mark.parametrize(
        "url, scheme, authority, path",
        (
            (
                "https://target.example:9443/path?query=true",
                b"https",
                b"target.example:9443",
                b"/path?query=true",
            ),
            (
                "http://target.example/path?query=true",
                b"http",
                b"target.example",
                b"/path?query=true",
            ),
            (
                "https://[2001:db8::1]:8443/resource",
                b"https",
                b"[2001:db8::1]:8443",
                b"/resource",
            ),
            (
                # userinfo must not appear in :authority
                "https://user:pass@target.example/secret",
                b"https",
                b"target.example",
                b"/secret",
            ),
        ),
    )
    def test_forwarding_proxy_request_uses_destination_pseudo_headers(
        self, url: str, scheme: bytes, authority: bytes, path: bytes
    ) -> None:
        conn = HTTP2Connection(
            "proxy.example",
            8443,
            proxy=parse_url("https://proxy.example:8443"),
            proxy_config=ProxyConfig(None, True, None, None),
        )
        send_headers = self._mock_h2_send(conn)

        conn.request("GET", url)
        conn.close()

        send_headers.assert_called_with(
            stream_id=1,
            headers=[
                (b":scheme", scheme),
                (b":method", b"GET"),
                (b":authority", authority),
                (b":path", path),
                (b"user-agent", _get_default_user_agent().encode()),
            ],
            end_stream=True,
        )

    def test_forwarding_proxy_rejects_relative_url(self) -> None:
        conn = HTTP2Connection(
            "proxy.example",
            8443,
            proxy=parse_url("https://proxy.example:8443"),
            proxy_config=ProxyConfig(None, True, None, None),
        )
        self._mock_h2_send(conn)

        with pytest.raises(ValueError, match="absolute URL"):
            conn.request("GET", "/relative")

    def test_forwarding_proxy_does_not_use_proxy_as_authority(self) -> None:
        """Without the fix, :authority would be the proxy host:port."""
        conn = HTTP2Connection(
            "proxy.example",
            8443,
            proxy=parse_url("https://proxy.example:8443"),
            proxy_config=ProxyConfig(None, True, None, None),
        )
        send_headers = self._mock_h2_send(conn)

        conn.request("GET", "https://target.example/path")
        headers = dict(send_headers.call_args.kwargs["headers"])
        assert headers[b":authority"] == b"target.example"
        assert headers[b":authority"] != b"proxy.example:8443"
        assert headers[b":scheme"] == b"https"
        assert headers[b":path"] == b"/path"

    def test_http2_omits_host_header_in_favor_of_authority(self) -> None:
        conn = HTTP2Connection(
            "proxy.example",
            8443,
            proxy=parse_url("https://proxy.example:8443"),
            proxy_config=ProxyConfig(None, True, None, None),
        )
        send_headers = self._mock_h2_send(conn)

        conn.request(
            "GET",
            "https://target.example/path",
            headers={"Host": "target.example", "Accept": "*/*"},
        )
        header_names = [name for name, _ in send_headers.call_args.kwargs["headers"]]
        assert b"host" not in header_names
        assert b":authority" in header_names
        assert b"accept" in header_names

    def test_http2_tunneling_via_set_tunnel_remains_unsupported(self) -> None:
        conn = HTTP2Connection(
            "proxy.example",
            8443,
            proxy=parse_url("https://proxy.example:8443"),
            proxy_config=ProxyConfig(None, False, None, None),
        )
        with pytest.raises(NotImplementedError, match="tunnel"):
            conn.set_tunnel("target.example", 443)

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


class TestHTTP2ForwardingWire:
    """Socket-level proof that forwarding pseudo-headers hit the wire."""

    @pytest.mark.parametrize(
        "url, expected",
        (
            (
                "https://target.example:9443/path?q=1",
                {
                    b":scheme": b"https",
                    b":authority": b"target.example:9443",
                    b":path": b"/path?q=1",
                },
            ),
            (
                "http://target.example/path?q=1",
                {
                    b":scheme": b"http",
                    b":authority": b"target.example",
                    b":path": b"/path?q=1",
                },
            ),
            (
                "https://[2001:db8::1]:8443/resource",
                {
                    b":scheme": b"https",
                    b":authority": b"[2001:db8::1]:8443",
                    b":path": b"/resource",
                },
            ),
        ),
    )
    def test_forwarding_pseudo_headers_on_wire(
        self, url: str, expected: dict[bytes, bytes]
    ) -> None:
        received: dict[str, list[tuple[bytes, bytes]]] = {}
        ready = threading.Event()
        done = threading.Event()

        def server() -> None:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(DEFAULT_CERTS["certfile"], DEFAULT_CERTS["keyfile"])
            ctx.set_alpn_protocols(["h2", "http/1.1"])
            sock = socket.socket()
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("localhost", 0))
            sock.listen(5)
            ready.port = sock.getsockname()[1]  # type: ignore[attr-defined]
            ready.set()

            raw, _ = sock.accept()
            tls = ctx.wrap_socket(raw, server_side=True)
            assert tls.selected_alpn_protocol() == "h2"

            config = h2.config.H2Configuration(client_side=False)
            h2_conn = h2.connection.H2Connection(config=config)
            h2_conn.initiate_connection()
            tls.sendall(h2_conn.data_to_send())
            tls.settimeout(5)

            while not done.is_set():
                try:
                    data = tls.recv(65535)
                except TimeoutError:
                    break
                if not data:
                    break
                for event in h2_conn.receive_data(data):
                    if isinstance(event, h2.events.RequestReceived):
                        received["headers"] = [
                            (
                                name if isinstance(name, bytes) else name.encode(),
                                (value if isinstance(value, bytes) else value.encode()),
                            )
                            for name, value in event.headers
                        ]
                        h2_conn.send_headers(
                            event.stream_id,
                            [(b":status", b"200"), (b"content-length", b"0")],
                            end_stream=True,
                        )
                        tls.sendall(h2_conn.data_to_send())
                        done.set()
                        break
                if data_to_send := h2_conn.data_to_send():
                    tls.sendall(data_to_send)

            tls.close()
            sock.close()

        thread = threading.Thread(target=server, daemon=True)
        thread.start()
        assert ready.wait(5)
        port = ready.port  # type: ignore[attr-defined]

        # HTTP2Connection always speaks h2; offer h2 via ALPN like inject_into_urllib3.
        original_alpn = list(urllib3_ssl.ALPN_PROTOCOLS)
        urllib3_ssl.ALPN_PROTOCOLS = ["h2"]
        conn = HTTP2Connection(
            "localhost",
            port,
            proxy=parse_url(f"https://localhost:{port}"),
            proxy_config=ProxyConfig(None, True, None, None),
            ca_certs=DEFAULT_CA,
        )
        try:
            conn.connect()
            assert conn.sock is not None
            assert conn.sock.selected_alpn_protocol() == "h2"
            conn.request("GET", url, headers={"Host": "should-be-omitted"})
            response = conn.getresponse()
            assert response.status == 200
        finally:
            conn.close()
            urllib3_ssl.ALPN_PROTOCOLS = original_alpn
            done.wait(5)
            thread.join(5)

        headers = dict(received["headers"])
        for name, value in expected.items():
            assert headers[name] == value
        assert b"host" not in headers
        assert headers[b":authority"] != f"localhost:{port}".encode()
