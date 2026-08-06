from __future__ import annotations

import logging
import re
import threading
import types
import typing

import h2.config
import h2.connection
import h2.errors
import h2.events
import h2.exceptions

from .._base_connection import _TYPE_BODY
from .._collections import HTTPHeaderDict
from ..connection import HTTPSConnection, _get_default_user_agent
from ..exceptions import ConnectionError
from ..response import BaseHTTPResponse
from ..util.wait import wait_for_read

orig_HTTPSConnection = HTTPSConnection

T = typing.TypeVar("T")

log = logging.getLogger(__name__)

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


def _h2_error_code_name(error_code: object) -> str:
    """Return a human-readable HTTP/2 error code name for exception messages."""
    if error_code is None:
        return "NO_ERROR"
    try:
        return h2.errors.ErrorCodes(error_code).name  # type: ignore[arg-type]
    except ValueError:
        try:
            return f"0x{int(error_code):x}"  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return repr(error_code)


def _raise_for_h2_error_event(event: h2.events.Event) -> typing.NoReturn:
    """
    Translate HTTP/2 error events into urllib3 ``ConnectionError``.

    ``StreamReset`` ends only the affected stream. ``ConnectionTerminated``
    (GOAWAY) means the connection must not be used again. Both surface as
    ``ConnectionError`` (alias of ``ProtocolError``) so connection pools discard
    the connection and may retry on a fresh one.
    """
    if isinstance(event, h2.events.StreamReset):
        code = _h2_error_code_name(event.error_code)
        if event.remote_reset:
            message = (
                f"HTTP/2 stream {event.stream_id} was reset by the peer "
                f"with error code {code}"
            )
        else:
            message = (
                f"HTTP/2 stream {event.stream_id} was reset with error code {code}"
            )
        raise ConnectionError(message)

    if isinstance(event, h2.events.ConnectionTerminated):
        code = _h2_error_code_name(event.error_code)
        message = f"HTTP/2 connection terminated by the peer with error code {code}"
        if event.last_stream_id is not None:
            message += f" (last stream id {event.last_stream_id})"
        if event.additional_data:
            # Cap debug data so oversized GOAWAY payloads cannot inflate
            # exception strings unboundedly.
            debug = event.additional_data[:64]
            message += f" additional_data={debug!r}"
        raise ConnectionError(message)

    raise TypeError(f"Expected StreamReset or ConnectionTerminated, got {event!r}")


def _is_our_stream_event(event: h2.events.Event, stream_id: int | None) -> bool:
    """Return True when a stream-scoped event belongs to ``stream_id``."""
    event_stream_id = getattr(event, "stream_id", None)
    return stream_id is not None and event_stream_id == stream_id


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
        self._headers: list[tuple[bytes, bytes]] = []

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
        with self._h2_conn as conn:
            conn.initiate_connection()
            if data_to_send := conn.data_to_send():
                self.sock.sendall(data_to_send)

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

        with self._h2_conn as conn:
            self._h2_stream = conn.get_next_available_stream_id()

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
            raise ConnectionError("Must call `putrequest` first.")

        with self._h2_conn as conn:
            conn.send_headers(
                stream_id=self._h2_stream,
                headers=self._headers,
                end_stream=(message_body is None),
            )
            if data_to_send := conn.data_to_send():
                self.sock.sendall(data_to_send)
        self._headers = []  # Reset headers for the next request.

    def send(self, data: typing.Any) -> None:
        """Send data to the server.
        `data` can be: `str`, `bytes`, an iterable, or file-like objects
        that support a .read() method.
        """
        if self._h2_stream is None:
            raise ConnectionError("Must call `putrequest` first.")

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
        close_connection = False
        try:
            with self._h2_conn as conn:
                end_stream = False
                while not end_stream:
                    # TODO: Arbitrary read value.
                    received_data = self.sock.recv(65535)
                    if not received_data:
                        raise ConnectionError(
                            "Connection closed while reading HTTP/2 response"
                        )

                    try:
                        events = conn.receive_data(received_data)
                        for event in events:
                            if isinstance(event, h2.events.ConnectionTerminated):
                                # Graceful GOAWAY after our stream has already
                                # ended is not a request failure, but the
                                # connection must not be reused. Abort only when
                                # the active response is incomplete.
                                if end_stream:
                                    close_connection = True
                                else:
                                    _raise_for_h2_error_event(event)

                            elif isinstance(event, h2.events.StreamReset):
                                if not end_stream and _is_our_stream_event(
                                    event, self._h2_stream
                                ):
                                    _raise_for_h2_error_event(event)

                            elif isinstance(event, h2.events.ResponseReceived):
                                if not _is_our_stream_event(event, self._h2_stream):
                                    continue
                                headers = HTTPHeaderDict()
                                for header, value in event.headers:
                                    if header == b":status":
                                        status = int(value.decode())
                                    else:
                                        headers.add(
                                            header.decode("ascii"),
                                            value.decode("ascii"),
                                        )

                            elif isinstance(event, h2.events.DataReceived):
                                if not _is_our_stream_event(event, self._h2_stream):
                                    continue
                                data += event.data
                                conn.acknowledge_received_data(
                                    event.flow_controlled_length, event.stream_id
                                )

                            elif isinstance(event, h2.events.StreamEnded):
                                if _is_our_stream_event(event, self._h2_stream):
                                    end_stream = True

                        if data_to_send := conn.data_to_send():
                            self.sock.sendall(data_to_send)
                    except h2.exceptions.H2Error as e:
                        raise ConnectionError(f"HTTP/2 protocol error: {e}") from e

                # GOAWAY may arrive in a later TCP segment than StreamEnded.
                # Drain immediately-available frames so we close the connection
                # instead of returning it to the pool with a pending GOAWAY.
                while self.sock is not None and wait_for_read(self.sock, timeout=0.0):
                    received_data = self.sock.recv(65535)
                    if not received_data:
                        break
                    try:
                        events = conn.receive_data(received_data)
                        for event in events:
                            if isinstance(event, h2.events.ConnectionTerminated):
                                close_connection = True
                            elif isinstance(event, h2.events.StreamReset):
                                # Active stream already ended; ignore late resets.
                                continue
                        if data_to_send := conn.data_to_send():
                            self.sock.sendall(data_to_send)
                    except h2.exceptions.H2Error as e:
                        raise ConnectionError(f"HTTP/2 protocol error: {e}") from e

            if status is None:
                raise ConnectionError(
                    "HTTP/2 response ended without receiving a status"
                )

            response = HTTP2Response(
                status=status,
                headers=headers,
                request_url=self._request_url,
                data=bytes(data),
            )
            if close_connection:
                # Peer sent GOAWAY after a complete response; discard this connection.
                self.close()
            return response
        except ConnectionError:
            # Ensure direct HTTP2Connection users discard a dirty connection the
            # same way HTTPSConnectionPool does on ProtocolError.
            try:
                self.close()
            except Exception:
                pass
            raise

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
        self._headers = []

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

    def get_redirect_location(self) -> None:
        return None

    def close(self) -> None:
        pass
