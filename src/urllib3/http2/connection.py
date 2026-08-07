from __future__ import annotations

import logging
import re
import ssl
import threading
import types
import typing
from http.client import CannotSendRequest

import h2.config
import h2.connection
import h2.events
import h2.exceptions

from .._base_connection import _TYPE_BODY
from .._collections import HTTPHeaderDict
from ..connection import HTTPSConnection, _get_default_user_agent
from ..exceptions import ProtocolError
from ..response import BaseHTTPResponse

orig_HTTPSConnection = HTTPSConnection

T = typing.TypeVar("T")

log = logging.getLogger(__name__)

_IDLE_READ_SIZE = 65535
_MAX_IDLE_READS = 16

RE_IS_LEGAL_HEADER_NAME = re.compile(rb"^[!#$%&'*+\-.^_`|~0-9a-z]+$")
RE_IS_ILLEGAL_HEADER_VALUE = re.compile(rb"[\0\x00\x0a\x0d\r\n]|^[ \r\n\t]|[ \r\n\t]$")


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
    def __init__(
        self, host: str, port: int | None = None, **kwargs: typing.Any
    ) -> None:
        self._h2_conn = self._new_h2_conn()
        self._h2_stream: int | None = None
        self._stream_owner: object | None = None
        self._headers: list[tuple[bytes, bytes]] = []
        self._connection_terminated = False
        self._has_completed_response = False

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

        port = self.port if self.port is not None else 443
        if ":" in self.host:
            authority = f"[{self.host}]:{port}"
        else:
            authority = f"{self.host}:{port}"

        self._headers.append((b":scheme", b"https"))
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

        if self.sock is not None:
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

        # Reset all our HTTP/2 connection state.
        self._h2_conn = self._new_h2_conn()
        self._h2_stream = None
        self._stream_owner = None
        self._headers = []
        self._connection_terminated = False
        self._has_completed_response = False

        super().close()


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
