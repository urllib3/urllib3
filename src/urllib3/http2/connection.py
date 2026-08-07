from __future__ import annotations

import http.client
import io
import logging
import re
import socket
import ssl
import threading
import types
import typing
from http.client import CannotSendRequest

import h2.config
import h2.connection
import h2.events
import h2.exceptions

from .._base_connection import _TYPE_BODY, _ResponseOptions
from .._collections import HTTPHeaderDict
from ..connection import (
    HTTPConnection,
    HTTPSConnection,
    _get_default_user_agent,
    _normalize_header_values,
)
from ..exceptions import HeaderParsingError, ProtocolError
from ..response import BaseHTTPResponse, HTTPResponse
from ..util import SKIP_HEADER, SKIPPABLE_HEADERS
from ..util.request import body_to_chunks
from ..util.response import assert_header_parsing

orig_HTTPSConnection = HTTPSConnection

T = typing.TypeVar("T")

log = logging.getLogger(__name__)

_IDLE_READ_SIZE = 65535
_MAX_IDLE_READS = 16

RE_IS_LEGAL_HEADER_NAME = re.compile(rb"^[!#$%&'*+\-.^_`|~0-9a-z]+$")
RE_IS_ILLEGAL_HEADER_VALUE = re.compile(rb"[\0\x00\x0a\x0d\r\n]|^[ \r\n\t]|[ \r\n\t]$")
RE_IS_LEGAL_HTTP1_HEADER_NAME = re.compile(rb"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
RE_IS_ILLEGAL_HTTP1_HEADER_VALUE = re.compile(rb"[\x00\r\n]")
RE_HTTP1_STATUS_LINE = re.compile(
    rb"^HTTP/(?P<major>[0-9]+)\.(?P<minor>[0-9]+) "
    rb"(?P<status>[0-9]{3})(?: (?P<reason>[^\r\n]*))?$"
)


class _SocketReader(io.RawIOBase):
    """Expose prefetched bytes and then a socket as an unbuffered reader.

    The reader deliberately doesn't own the socket. ``http.client`` closes its
    response file after a fixed-length body, while the connection keeps the
    underlying socket available for another request.
    """

    def __init__(self, sock: typing.Any, prefetched: bytes) -> None:
        self._sock = sock
        self._prefetched = bytearray(prefetched)
        self._owns_socket = False

    def take_socket_ownership(self) -> None:
        """Close the socket with this reader after connection-close responses."""
        self._owns_socket = True
        if self.closed:
            self._sock.close()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: typing.Any) -> int:
        if self._prefetched:
            size = min(len(buffer), len(self._prefetched))
            buffer[:size] = self._prefetched[:size]
            del self._prefetched[:size]
            return size
        return typing.cast(int, self._sock.recv_into(buffer))

    def close(self) -> None:
        try:
            if self._owns_socket:
                self._sock.close()
        finally:
            super().close()


class _PrefetchedSocket:
    """Socket facade used to hand an already-read response to http.client."""

    def __init__(self, sock: typing.Any, prefetched: bytes) -> None:
        self._sock = sock
        self._prefetched = prefetched
        self._reader: _SocketReader | None = None

    def makefile(self, mode: str, buffering: int | None = None) -> io.BufferedReader:
        assert mode == "rb"
        self._reader = _SocketReader(self._sock, self._prefetched)
        return io.BufferedReader(self._reader)

    def transfer_socket_to_response(self) -> None:
        assert self._reader is not None
        self._reader.take_socket_ownership()


def _read_http1_response_head(
    sock: typing.Any, prefetched: bytes = b""
) -> tuple[bytes, bytes]:
    data = bytearray(prefetched)
    while b"\r\n\r\n" not in data:
        received = sock.recv(65535)
        if not received:
            raise ProtocolError("Connection closed while reading h2c upgrade response")
        data.extend(received)
        if len(data) > 65536:
            raise ProtocolError("h2c upgrade response headers are too large")
    marker = data.index(b"\r\n\r\n") + 4
    if marker > 65536:
        raise ProtocolError("h2c upgrade response headers are too large")
    return bytes(data[:marker]), bytes(data[marker:])


def _parse_http1_response_head(
    head: bytes,
) -> tuple[int, int, HTTPHeaderDict, http.client.HTTPMessage]:
    status_line, separator, header_lines = head.partition(b"\r\n")
    if not separator or (match := RE_HTTP1_STATUS_LINE.fullmatch(status_line)) is None:
        raise ProtocolError(f"Invalid h2c upgrade status line: {status_line!r}")

    try:
        message = http.client.parse_headers(io.BytesIO(header_lines))
    except http.client.HTTPException as e:
        raise ProtocolError("Invalid h2c upgrade response headers", e) from e

    version = int(match.group("major")) * 10 + int(match.group("minor"))
    return (
        version,
        int(match.group("status")),
        HTTPHeaderDict(message.items()),
        message,
    )


def _header_has_token(headers: HTTPHeaderDict, name: str, token: str) -> bool:
    return token.lower() in {
        item.strip().lower() for item in headers.get(name, "").split(",")
    }


def _encode_http1_header(name: str, value: str) -> bytes:
    encoded_name = name.encode("ascii")
    encoded_value = value.encode("latin-1")
    if not RE_IS_LEGAL_HTTP1_HEADER_NAME.fullmatch(encoded_name):
        raise ValueError(f"Illegal header name {name!r}")
    if RE_IS_ILLEGAL_HTTP1_HEADER_VALUE.search(encoded_value):
        raise ValueError(f"Illegal header value {value!r}")
    return encoded_name + b": " + encoded_value + b"\r\n"


def _is_legal_header_name(name: bytes) -> bool:
    """
    "An implementation that validates fields according to the definitions in Sections
    5.1 and 5.5 of [HTTP] only needs an additional check that field names do not
    include uppercase characters." (https://httpwg.org/specs/rfc9113.html#n-field-validity)

    `http.client._is_legal_header_name` does not validate the field name according to the
    HTTP 1.1 spec, so we do that here, in addition to checking for uppercase characters.

    This does not allow for the `:` character in the header name, so should not
    be used to validate pseudo-headers.
    """
    return bool(RE_IS_LEGAL_HEADER_NAME.match(name))


def _is_illegal_header_value(value: bytes) -> bool:
    """
    "A field value MUST NOT contain the zero value (ASCII NUL, 0x00), line feed
    (ASCII LF, 0x0a), or carriage return (ASCII CR, 0x0d) at any position. A field
    value MUST NOT start or end with an ASCII whitespace character (ASCII SP or HTAB,
    0x20 or 0x09)." (https://httpwg.org/specs/rfc9113.html#n-field-validity)
    """
    return bool(RE_IS_ILLEGAL_HEADER_VALUE.search(value))


class _LockedObject(typing.Generic[T]):
    """
    A wrapper class that hides a specific object behind a lock.
    The goal here is to provide a simple way to protect access to an object
    that cannot safely be simultaneously accessed from multiple threads. The
    intended use of this class is simple: take hold of it with a context
    manager, which returns the protected object.
    """

    __slots__ = (
        "lock",
        "_obj",
    )

    def __init__(self, obj: T):
        self.lock = threading.RLock()
        self._obj = obj

    def __enter__(self) -> T:
        self.lock.acquire()
        return self._obj

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        self.lock.release()


class HTTP2Connection(HTTPSConnection):
    _http2_scheme: typing.ClassVar[bytes] = b"https"
    _http2_default_port: typing.ClassVar[int] = 443

    def __init__(
        self, host: str, port: int | None = None, **kwargs: typing.Any
    ) -> None:
        self._h2_conn = self._new_h2_conn()
        self._h2_stream: int | None = None
        self._stream_owner: object | None = None
        self._headers: list[tuple[bytes, bytes]] = []
        self._connection_terminated = False
        self._has_completed_response = False
        self._h2_received_data = bytearray()

        if "proxy" in kwargs or "proxy_config" in kwargs:  # Defensive:
            raise NotImplementedError("Proxies aren't supported with HTTP/2")

        super().__init__(host, port, **kwargs)

        if self._tunnel_host is not None:
            raise NotImplementedError("Tunneling isn't supported with HTTP/2")

    def _new_h2_conn(self) -> _LockedObject[h2.connection.H2Connection]:
        config = h2.config.H2Configuration(client_side=True)
        return _LockedObject(h2.connection.H2Connection(config=config))

    def connect(self) -> None:
        super().connect()
        self._start_http2_connection()

    def _start_http2_connection(self) -> None:
        self._connection_terminated = False
        with self._h2_conn as conn:
            conn.initiate_connection()
            if data_to_send := conn.data_to_send():
                self.sock.sendall(data_to_send)

    def _assert_stream_owner(self, stream_owner: object | None) -> None:
        if self._stream_owner is not stream_owner:
            raise RuntimeError("HTTP/2 stream events have a different owner")

    def _transfer_stream_owner(self, current_owner: object, new_owner: object) -> None:
        """Transfer the right to receive events for the active stream."""
        if self._stream_owner is not current_owner:
            raise RuntimeError("HTTP/2 stream events have a different owner")
        self._stream_owner = new_owner

    def _release_stream_owner(self, stream_owner: object) -> None:
        """Release an active stream after its response has completed."""
        self._assert_stream_owner(stream_owner)
        self._stream_owner = None
        self._h2_stream = None

    def _process_received_data(
        self, received_data: bytes, *, stream_owner: object | None
    ) -> list[h2.events.Event]:
        """Process HTTP/2 bytes and flush protocol-generated output."""
        self._assert_stream_owner(stream_owner)
        with self._h2_conn as conn:
            events = conn.receive_data(received_data)
            for event in events:
                if isinstance(event, h2.events.DataReceived):
                    conn.acknowledge_received_data(
                        event.flow_controlled_length, event.stream_id
                    )
                elif isinstance(event, h2.events.ConnectionTerminated):
                    self._connection_terminated = True

            if data_to_send := conn.data_to_send():
                self.sock.sendall(data_to_send)

        return events

    def _receive_events(
        self, *, stream_owner: object | None
    ) -> list[h2.events.Event] | None:
        """Receive and process one batch of HTTP/2 events.

        ``None`` means the peer reached EOF. Flow-controlled data is always
        acknowledged and protocol-generated output (for example PING and
        SETTINGS acknowledgements) is flushed before returning.
        """
        self._assert_stream_owner(stream_owner)
        assert self.sock is not None
        if self._h2_received_data:
            received_data = bytes(self._h2_received_data)
            self._h2_received_data.clear()
        else:
            received_data = self.sock.recv(65535)
        if not received_data:
            self._connection_terminated = True
            return None
        return self._process_received_data(received_data, stream_owner=stream_owner)

    def _probe_idle_connection(self) -> bool:
        """Process pending control frames and determine idle connection health."""
        sock = self.sock
        if sock is None or self._connection_terminated:
            return False

        # Never consume response events behind the response reader's back.
        if self._stream_owner is not None:
            return True

        try:
            previous_timeout = sock.gettimeout()
        except OSError:
            self._connection_terminated = True
            return False

        for _ in range(_MAX_IDLE_READS):
            received_data: bytes | None = None
            receive_failed = False
            try:
                sock.settimeout(0.0)
                try:
                    received_data = sock.recv(_IDLE_READ_SIZE)
                except (BlockingIOError, TimeoutError, ssl.SSLWantReadError):
                    pass
                except OSError:
                    receive_failed = True
            except OSError:
                receive_failed = True
            finally:
                # Only recv() is non-blocking. Restore the caller's timeout
                # before parsing because hyper-h2 can generate output which
                # must be delivered with sendall().
                if self.sock is sock:
                    try:
                        sock.settimeout(previous_timeout)
                    except OSError:
                        receive_failed = True

            if receive_failed or received_data == b"":
                self._connection_terminated = True
                return False
            if received_data is None:
                return True

            try:
                self._process_received_data(received_data, stream_owner=None)
            except (OSError, h2.exceptions.ProtocolError):
                # If generated protocol output can't be sent then this
                # connection is no longer safe to reuse. The pool will close
                # it instead of losing bytes and continuing the session.
                self._connection_terminated = True
                return False
            if self._connection_terminated:
                return False

        # A peer that can keep the socket continuously readable can otherwise
        # starve the pool indefinitely. Conservatively discard the connection.
        self._connection_terminated = True
        return False

    @property
    def is_connected(self) -> bool:
        return self._probe_idle_connection()

    def putrequest(  # type: ignore[override]
        self,
        method: str,
        url: str,
        **kwargs: typing.Any,
    ) -> None:
        """putrequest
        This deviates from the HTTPConnection method signature since we never need to override
        sending accept-encoding headers or the host header.
        """
        if "skip_host" in kwargs:
            raise NotImplementedError("`skip_host` isn't supported")
        if "skip_accept_encoding" in kwargs:
            raise NotImplementedError("`skip_accept_encoding` isn't supported")

        if self._stream_owner is not None:
            raise CannotSendRequest(
                "Cannot send a new HTTP/2 request while a response stream is active"
            )

        if self._has_completed_response and not self._probe_idle_connection():
            raise ProtocolError("HTTP/2 connection is no longer reusable")

        with self._h2_conn as conn:
            if conn.remote_settings.max_concurrent_streams == 0:
                raise ProtocolError("HTTP/2 peer does not currently allow new streams")
            stream_id = conn.get_next_available_stream_id()

        self._request_url = url or "/"
        self._validate_path(url)  # type: ignore[attr-defined]

        port = self.port if self.port is not None else self._http2_default_port
        if ":" in self.host:
            authority = f"[{self.host}]:{port}"
        else:
            authority = f"{self.host}:{port}"

        self._headers.append((b":scheme", self._http2_scheme))
        self._headers.append((b":method", method.encode()))
        self._headers.append((b":authority", authority.encode()))
        self._headers.append((b":path", url.encode()))

        self._h2_stream = stream_id
        self._stream_owner = self

    def putheader(self, header: str | bytes, *values: str | bytes) -> None:  # type: ignore[override]
        # TODO SKIPPABLE_HEADERS from urllib3 are ignored.
        header = header.encode() if isinstance(header, str) else header
        header = header.lower()  # A lot of upstream code uses capitalized headers.
        if not _is_legal_header_name(header):
            raise ValueError(f"Illegal header name {str(header)}")

        for value in values:
            value = value.encode() if isinstance(value, str) else value
            if _is_illegal_header_value(value):
                raise ValueError(f"Illegal header value {str(value)}")
            self._headers.append((header, value))

    def endheaders(self, message_body: typing.Any = None) -> None:  # type: ignore[override]
        if self._h2_stream is None:
            raise ProtocolError("Must call `putrequest` first.")

        with self._h2_conn as conn:
            try:
                conn.send_headers(
                    stream_id=self._h2_stream,
                    headers=self._headers,
                    end_stream=(message_body is None),
                )
            except h2.exceptions.TooManyStreamsError as e:
                self._headers = []
                self._release_stream_owner(self)
                raise ProtocolError(
                    "HTTP/2 peer does not currently allow new streams"
                ) from e
            if data_to_send := conn.data_to_send():
                self.sock.sendall(data_to_send)
        self._headers = []  # Reset headers for the next request.

    def send(self, data: typing.Any) -> None:
        """Send data to the server.
        `data` can be: `str`, `bytes`, an iterable, or file-like objects
        that support a .read() method.
        """
        if self._h2_stream is None:
            raise ProtocolError("Must call `putrequest` first.")

        with self._h2_conn as conn:
            if data_to_send := conn.data_to_send():
                self.sock.sendall(data_to_send)

            if hasattr(data, "read"):  # file-like objects
                while True:
                    chunk = data.read(self.blocksize)
                    if not chunk:
                        break
                    if isinstance(chunk, str):
                        chunk = chunk.encode()
                    conn.send_data(self._h2_stream, chunk, end_stream=False)
                    if data_to_send := conn.data_to_send():
                        self.sock.sendall(data_to_send)
                conn.end_stream(self._h2_stream)
                return

            if isinstance(data, str):  # str -> bytes
                data = data.encode()

            try:
                if isinstance(data, bytes):
                    conn.send_data(self._h2_stream, data, end_stream=True)
                    if data_to_send := conn.data_to_send():
                        self.sock.sendall(data_to_send)
                else:
                    for chunk in data:
                        conn.send_data(self._h2_stream, chunk, end_stream=False)
                        if data_to_send := conn.data_to_send():
                            self.sock.sendall(data_to_send)
                    conn.end_stream(self._h2_stream)
            except TypeError:
                raise TypeError(
                    "`data` should be str, bytes, iterable, or file. got %r"
                    % type(data)
                )

    def set_tunnel(
        self,
        host: str,
        port: int | None = None,
        headers: typing.Mapping[str, str] | None = None,
        scheme: str = "http",
    ) -> None:
        raise NotImplementedError(
            "HTTP/2 does not support setting up a tunnel through a proxy"
        )

    def getresponse(  # type: ignore[override]
        self,
    ) -> HTTP2Response:
        status = None
        headers = HTTPHeaderDict()
        data = bytearray()
        stream_id = self._h2_stream
        end_stream = False
        while not end_stream:
            events = self._receive_events(stream_owner=self)
            if events is None:
                raise ProtocolError(
                    "HTTP/2 connection closed before the response completed"
                )

            for event in events:
                if (
                    isinstance(event, h2.events.ResponseReceived)
                    and event.stream_id == stream_id
                ):
                    headers = HTTPHeaderDict()
                    for header, value in event.headers:
                        if header == b":status":
                            status = int(value.decode())
                        else:
                            headers.add(header.decode("ascii"), value.decode("ascii"))

                elif (
                    isinstance(event, h2.events.DataReceived)
                    and event.stream_id == stream_id
                ):
                    data += event.data

                elif (
                    isinstance(event, h2.events.StreamEnded)
                    and event.stream_id == stream_id
                ):
                    end_stream = True

                elif (
                    isinstance(event, h2.events.StreamReset)
                    and event.stream_id == stream_id
                ):
                    raise ProtocolError(
                        "HTTP/2 stream was reset by the peer "
                        f"(error code {event.error_code})"
                    )

                elif isinstance(event, h2.events.ConnectionTerminated):
                    if not end_stream:
                        raise ProtocolError(
                            "HTTP/2 connection was terminated by the peer "
                            f"(error code {event.error_code})"
                        )

        assert status is not None
        self._release_stream_owner(self)
        self._has_completed_response = True
        return HTTP2Response(
            status=status,
            headers=headers,
            request_url=self._request_url,
            data=bytes(data),
        )

    def request(  # type: ignore[override]
        self,
        method: str,
        url: str,
        body: _TYPE_BODY | None = None,
        headers: typing.Mapping[str, str] | None = None,
        *,
        preload_content: bool = True,
        decode_content: bool = True,
        enforce_content_length: bool = True,
        **kwargs: typing.Any,
    ) -> None:
        """Send an HTTP/2 request"""
        if "chunked" in kwargs:
            # TODO this is often present from upstream.
            # raise NotImplementedError("`chunked` isn't supported with HTTP/2")
            pass

        if self.sock is None:
            self.connect()
        else:
            self.sock.settimeout(self.timeout)

        self.putrequest(method, url)

        headers = headers or {}
        for k, v in headers.items():
            if k.lower() == "transfer-encoding" and v == "chunked":
                continue
            else:
                self.putheader(k, v)

        if b"user-agent" not in dict(self._headers):
            self.putheader(b"user-agent", _get_default_user_agent())

        if body:
            self.endheaders(message_body=body)
            self.send(body)
        else:
            self.endheaders()

    def close(self) -> None:
        with self._h2_conn as conn:
            try:
                conn.close_connection()
                if data := conn.data_to_send():
                    self.sock.sendall(data)
            except Exception:
                pass

        self._reset_http2_state()

        super().close()

    def _reset_http2_state(self) -> None:
        self._h2_conn = self._new_h2_conn()
        self._h2_stream = None
        self._stream_owner = None
        self._headers = []
        self._connection_terminated = False
        self._has_completed_response = False
        self._h2_received_data.clear()


class HTTP2CleartextConnection(HTTP2Connection):
    """HTTP/2 over a cleartext TCP connection using prior knowledge."""

    _http2_scheme = b"http"
    _http2_default_port = 80

    def __init__(
        self, host: str, port: int | None = None, **kwargs: typing.Any
    ) -> None:
        # HTTP proxies keep their existing HTTP/1.1 behavior. h2c configuration
        # describes the origin connection, not an implicit capability of every
        # intermediary on the route.
        self._h2c_http1_fallback = bool(
            kwargs.get("proxy") is not None or kwargs.get("proxy_config") is not None
        )
        if self._h2c_http1_fallback:
            self._h2_conn = self._new_h2_conn()
            self._h2_stream = None
            self._stream_owner = None
            self._headers = []
            self._connection_terminated = False
            self._has_completed_response = False
            self._h2_received_data = bytearray()
            HTTPConnection.__init__(
                self,
                host,
                port=self._http2_default_port if port is None else port,
                **kwargs,
            )
        else:
            super().__init__(
                host,
                port=self._http2_default_port if port is None else port,
                **kwargs,
            )

    def connect(self) -> None:
        HTTPConnection.connect(self)
        if not self._h2c_http1_fallback:
            self._start_http2_connection()

    def request(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        if self._h2c_http1_fallback:
            HTTPConnection.request(self, *args, **kwargs)
        else:
            super().request(*args, **kwargs)

    def putrequest(  # type: ignore[override]
        self, method: str, url: str, **kwargs: typing.Any
    ) -> None:
        if self._h2c_http1_fallback:
            HTTPConnection.putrequest(self, method, url, **kwargs)
        else:
            super().putrequest(method, url, **kwargs)

    def putheader(  # type: ignore[override]
        self, header: str | bytes, *values: str | bytes
    ) -> None:
        if self._h2c_http1_fallback:
            HTTPConnection.putheader(self, header, *values)  # type: ignore[arg-type]
        else:
            super().putheader(header, *values)

    def endheaders(  # type: ignore[override]
        self, message_body: typing.Any = None
    ) -> None:
        if self._h2c_http1_fallback:
            HTTPConnection.endheaders(self, message_body)
        else:
            super().endheaders(message_body)

    def send(self, data: typing.Any) -> None:
        if self._h2c_http1_fallback:
            HTTPConnection.send(self, data)
        else:
            super().send(data)

    def getresponse(self) -> BaseHTTPResponse:  # type: ignore[override]
        if self._h2c_http1_fallback:
            return HTTPConnection.getresponse(self)
        return super().getresponse()

    def close(self) -> None:
        if self._h2c_http1_fallback:
            self._reset_http2_state()
            HTTPConnection.close(self)
        else:
            super().close()


class HTTP2UpgradeConnection(HTTP2CleartextConnection):
    """Cleartext HTTP/2 negotiated with the legacy HTTP/1.1 Upgrade path."""

    def __init__(
        self, host: str, port: int | None = None, **kwargs: typing.Any
    ) -> None:
        self._h2c_upgrade_complete = False
        self._h2c_request_method: str | None = None
        super().__init__(host, port=port, **kwargs)

    def connect(self) -> None:
        HTTPConnection.connect(self)

    def request(  # type: ignore[override]
        self,
        method: str,
        url: str,
        body: _TYPE_BODY | None = None,
        headers: typing.Mapping[str, str] | None = None,
        *,
        chunked: bool = False,
        preload_content: bool = True,
        decode_content: bool = True,
        enforce_content_length: bool = True,
        **kwargs: typing.Any,
    ) -> None:
        if self._h2c_http1_fallback:
            HTTPConnection.request(
                self,
                method,
                url,
                body=body,
                headers=headers,
                chunked=chunked,
                preload_content=preload_content,
                decode_content=decode_content,
                enforce_content_length=enforce_content_length,
            )
            return
        if self._h2c_upgrade_complete:
            HTTP2Connection.request(
                self,
                method,
                url,
                body=body,
                headers=headers,
                preload_content=preload_content,
                decode_content=decode_content,
                enforce_content_length=enforce_content_length,
                chunked=chunked,
                **kwargs,
            )
            return

        if kwargs:
            unknown = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected request arguments for h2c upgrade: {unknown}")
        if self.sock is None:
            self.connect()
        else:
            self.sock.settimeout(self.timeout)

        self._validate_method(method)  # type: ignore[attr-defined]
        self._validate_path(url)  # type: ignore[attr-defined]
        self._response_options = _ResponseOptions(
            request_method=method,
            request_url=url,
            preload_content=preload_content,
            decode_content=decode_content,
            enforce_content_length=enforce_content_length,
        )
        self._h2c_request_method = method
        self._request_url = url or "/"

        with self._h2_conn as conn:
            settings_header = conn.initiate_upgrade_connection()
        assert settings_header is not None
        self._h2_stream = 1
        self._stream_owner = self

        request_headers = HTTPHeaderDict(headers or {})
        skipped_headers: set[str] = set()
        for name, value in (headers or {}).items():
            if value == SKIP_HEADER:
                lower_name = name.lower()
                if lower_name not in SKIPPABLE_HEADERS:
                    skippable = "', '".join(
                        name.title() for name in sorted(SKIPPABLE_HEADERS)
                    )
                    raise ValueError(
                        f"urllib3.util.SKIP_HEADER only supports '{skippable}'"
                    )
                skipped_headers.add(lower_name)
                request_headers.discard(name)
        request_headers["Connection"] = "Upgrade, HTTP2-Settings"
        request_headers["Upgrade"] = "h2c"
        request_headers["HTTP2-Settings"] = settings_header.decode("ascii")

        chunks_and_length = body_to_chunks(
            body, method=method, blocksize=self.blocksize
        )
        chunks = chunks_and_length.chunks
        content_length = chunks_and_length.content_length
        header_names = {name.lower() for name in request_headers}
        if "host" not in header_names and "host" not in skipped_headers:
            request_headers["Host"] = self._http2_authority()
        if (
            "accept-encoding" not in header_names
            and "accept-encoding" not in skipped_headers
        ):
            request_headers["Accept-Encoding"] = "identity"
        if "user-agent" not in header_names and "user-agent" not in skipped_headers:
            request_headers["User-Agent"] = _get_default_user_agent()

        if chunked:
            if "transfer-encoding" not in header_names:
                request_headers["Transfer-Encoding"] = "chunked"
        elif "content-length" in header_names:
            chunked = False
        elif "transfer-encoding" in header_names:
            chunked = True
        else:
            if content_length is None:
                if chunks is not None:
                    chunked = True
                    request_headers["Transfer-Encoding"] = "chunked"
            else:
                request_headers["Content-Length"] = str(content_length)

        try:
            request_head = bytearray(
                f"{method} {url or '/'} HTTP/1.1\r\n".encode("ascii")
            )
            for name, value in request_headers.iteritems():
                request_head.extend(_encode_http1_header(name, value))
            request_head.extend(b"\r\n")
            self.sock.sendall(request_head)
            if chunks is not None:
                for chunk in chunks:
                    if not chunk:
                        continue
                    encoded_chunk = chunk.encode() if isinstance(chunk, str) else chunk
                    if chunked:
                        self.sock.sendall(
                            b"%x\r\n%b\r\n" % (len(encoded_chunk), encoded_chunk)
                        )
                    else:
                        self.sock.sendall(encoded_chunk)
            if chunked:
                self.sock.sendall(b"0\r\n\r\n")
        except BaseException:
            self.close()
            raise

    def _http2_authority(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        if self.port in (None, self._http2_default_port):
            return host
        return f"{host}:{self.port}"

    def getresponse(self) -> BaseHTTPResponse:  # type: ignore[override]
        if self._h2c_http1_fallback:
            return HTTPConnection.getresponse(self)
        if self._h2c_upgrade_complete:
            return HTTP2Connection.getresponse(self)
        if self._response_options is None or self._h2c_request_method is None:
            raise http.client.ResponseNotReady()

        prefetched = b""
        response_prefix = bytearray()
        response_head_bytes = 0
        informational_responses = 0
        while True:
            head, prefetched = _read_http1_response_head(self.sock, prefetched)
            response_head_bytes += len(head)
            if response_head_bytes > 65536:
                raise ProtocolError("Too many informational h2c upgrade responses")
            version, status, response_headers, response_message = (
                _parse_http1_response_head(head)
            )
            if status == 101 or not 100 <= status < 200:
                response_prefix.extend(head)
                break
            informational_responses += 1
            if informational_responses > 10:
                raise ProtocolError("Too many informational h2c upgrade responses")

        if status != 101:
            response_prefix.extend(prefetched)
            response = self._fallback_response(bytes(response_prefix))
            self._reset_http2_state()
            self._response_options = None
            self._h2c_request_method = None
            return response

        if version != 11:
            raise ProtocolError("Invalid h2c Upgrade response: 101 requires HTTP/1.1")
        try:
            assert_header_parsing(response_message)
        except (HeaderParsingError, TypeError) as e:
            raise ProtocolError("Invalid h2c Upgrade response headers", e) from e
        if not _header_has_token(response_headers, "connection", "upgrade"):
            raise ProtocolError(
                "Invalid h2c Upgrade response: Connection header lacks Upgrade"
            )
        if not _header_has_token(response_headers, "upgrade", "h2c"):
            raise ProtocolError(
                "Invalid h2c Upgrade response: Upgrade header lacks h2c"
            )

        self._h2_received_data.extend(prefetched)
        with self._h2_conn as conn:
            if data_to_send := conn.data_to_send():
                self.sock.sendall(data_to_send)
        self._h2c_upgrade_complete = True
        h2_response = HTTP2Connection.getresponse(self)
        self._response_options = None
        self._h2c_request_method = None
        return h2_response

    def _fallback_response(self, prefetched: bytes) -> HTTPResponse:
        assert self._response_options is not None
        response_options = self._response_options
        prefetched_socket = _PrefetchedSocket(self.sock, prefetched)
        original_response = http.client.HTTPResponse(
            typing.cast(socket.socket, prefetched_socket),
            method=self._h2c_request_method,
        )
        original_response.begin()
        if original_response.will_close:
            # Match http.client.HTTPConnection.getresponse(): detach a closing
            # socket from the connection while leaving the response able to
            # consume its body. The response reader closes the socket later.
            prefetched_socket.transfer_socket_to_response()
            self.sock = None
        try:
            assert_header_parsing(original_response.msg)
        except (HeaderParsingError, TypeError) as e:
            log.warning("Failed to parse h2c fallback headers: %s", e, exc_info=True)
        headers = HTTPHeaderDict(_normalize_header_values(original_response.msg))
        return HTTPResponse(
            body=original_response,
            headers=headers,
            status=original_response.status,
            version=original_response.version,
            version_string=f"HTTP/{original_response.version // 10}.{original_response.version % 10}",
            reason=original_response.reason,
            preload_content=response_options.preload_content,
            decode_content=response_options.decode_content,
            original_response=original_response,
            enforce_content_length=response_options.enforce_content_length,
            request_method=response_options.request_method,
            request_url=response_options.request_url,
            sock_shutdown=getattr(self.sock, "shutdown", None),
        )

    def close(self) -> None:
        was_upgraded = self._h2c_upgrade_complete
        self._h2c_upgrade_complete = False
        self._response_options = None
        self._h2c_request_method = None
        if was_upgraded:
            HTTP2Connection.close(self)
        else:
            self._reset_http2_state()
            HTTPConnection.close(self)


class HTTP2Response(BaseHTTPResponse):
    # TODO: This is a woefully incomplete response object, but works for non-streaming.
    def __init__(
        self,
        status: int,
        headers: HTTPHeaderDict,
        request_url: str,
        data: bytes,
        decode_content: bool = False,  # TODO: support decoding
    ) -> None:
        super().__init__(
            status=status,
            headers=headers,
            # Following CPython, we map HTTP versions to major * 10 + minor integers
            version=20,
            version_string="HTTP/2",
            # No reason phrase in HTTP/2
            reason=None,
            decode_content=decode_content,
            request_url=request_url,
        )
        self._data = data
        self.length_remaining = 0

    @property
    def data(self) -> bytes:
        return self._data

    @property
    def url(self) -> str | None:
        return self._request_url

    @url.setter
    def url(self, url: str | None) -> None:
        self._request_url = url

    def get_redirect_location(self) -> None:
        return None

    def close(self) -> None:
        pass
