from __future__ import annotations

import logging
import re
import threading
import types
import typing
from dataclasses import dataclass, field
from importlib.metadata import version

import h2.config
import h2.connection
import h2.errors
import h2.events

from .._base_connection import _TYPE_BODY
from .._collections import HTTPHeaderDict
from ..connection import (
    BaseProtocolHelper,
    HTTPConnection,
    HTTPSConnection,
    Stream,
    _get_default_user_agent,
)
from ..exceptions import ConnectionError, IncompleteRead, StreamError
from ..response import HTTPResponse

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


@dataclass
class HTTP2StreamData:
    url: str = field(default="")
    headers: list[tuple[bytes, bytes]] = field(default_factory=list)
    preload_content: bool = field(default=True)
    decode_content: bool = field(default=True)
    enforce_content_length: bool = field(default=True)
    status: int = field(default=0)
    response_headers: HTTPHeaderDict = field(default_factory=HTTPHeaderDict)
    response_buffer: bytes = field(default=b"")
    response_bytes_read: int = field(default=0)
    response_reset: bool = field(default=False)
    response_eof: bool = field(default=False)


class HTTP2ProtocolHelper(BaseProtocolHelper):
    """Protocol helper class for HTTP/2."""

    name: str = "http2"
    version_checked: bool = False

    def __init__(self, conn: HTTPConnection):

        if not HTTP2ProtocolHelper.version_checked:
            # check if h2 version is valid
            h2_version = version("h2")
            if not h2_version.startswith("4."):
                raise ImportError(
                    "urllib3 v2 supports h2 version 4.x.x, currently "
                    f"the 'h2' module is compiled with {h2_version!r}. "
                    "See: https://github.com/urllib3/urllib3/issues/3290"
                )
            HTTP2ProtocolHelper.version_checked = True

        super().__init__(conn)
        self._h2_conn = self._new_h2_conn()
        self._stream_data: dict[Stream | int, HTTP2StreamData] = {}

    def _new_h2_conn(self) -> _LockedObject[h2.connection.H2Connection]:
        config = h2.config.H2Configuration(client_side=True)
        return _LockedObject(h2.connection.H2Connection(config=config))

    def connect(self) -> None:
        with self._h2_conn as h2_conn:
            h2_conn.initiate_connection()
            if data_to_send := h2_conn.data_to_send():
                if self.conn.sock is None:  # Defensive:
                    self.conn.connect()
                self.conn.sock.sendall(data_to_send)

        if self.conn.sock is not None:
            self.conn.sock.settimeout(self.conn.timeout)

    def putrequest(
        self,
        method: str,
        url: str,
        skip_host: bool = False,
        skip_accept_encoding: bool = False,
        stream: Stream | None = None,
    ) -> bool:
        """putrequest
        This deviates from the HTTPConnection method signature since we never need to override
        sending accept-encoding headers or the host header.
        """
        if skip_host:
            raise NotImplementedError("`skip_host` isn't supported")
        if skip_accept_encoding:
            raise NotImplementedError("`skip_accept_encoding` isn't supported")
        if stream is None:
            raise ConnectionError("`stream` cannot be None")
        if stream in self._stream_data:
            raise ConnectionError("`put_request` was already called for this stream")

        self._stream_data[stream] = HTTP2StreamData()
        self._stream_data[stream].url = url or "/"
        self.conn._validate_path(url)  # type: ignore[attr-defined]

        port = self.conn.port if self.conn.port is not None else 443
        if ":" in self.conn.host:
            authority = f"[{self.conn.host}]:{port}"
        else:
            authority = f"{self.conn.host}:{port}"

        self._stream_data[stream].headers.append((b":scheme", b"https"))
        self._stream_data[stream].headers.append((b":method", method.encode()))
        self._stream_data[stream].headers.append((b":authority", authority.encode()))
        self._stream_data[stream].headers.append((b":path", url.encode()))

        return True

    def putheader(
        self, header: str, *values: str, stream: Stream | None = None
    ) -> bool:
        # TODO SKIPPABLE_HEADERS from urllib3 are ignored.
        if stream is None:
            raise ConnectionError("`stream` cannot be None")

        encoded_header = header.encode() if isinstance(header, str) else header
        encoded_header = (
            encoded_header.lower()
        )  # A lot of upstream code uses capitalized headers.
        if not _is_legal_header_name(encoded_header):
            raise ValueError(f"Illegal header name {str(header)}")

        for value in values:
            encoded_value = value.encode() if isinstance(value, str) else value
            if _is_illegal_header_value(encoded_value):
                raise ValueError(f"Illegal header value {str(value)}")
            self._stream_data[stream].headers.append((encoded_header, encoded_value))
        return True

    def endheaders(
        self, message_body: typing.Any = None, stream: Stream | None = None
    ) -> bool:
        if stream is None:
            raise ConnectionError("`stream` cannot be None")

        with self._h2_conn as h2_conn:
            stream.stream_id = h2_conn.get_next_available_stream_id()

            h2_conn.send_headers(
                stream_id=stream.stream_id,
                headers=self._stream_data[stream].headers,
                end_stream=(message_body is None),
            )
            if data_to_send := h2_conn.data_to_send():
                self.conn.sock.sendall(data_to_send)

            # for convenience we associate the stream data also with the h2 stream ID
            self._stream_data[stream.stream_id] = self._stream_data[stream]
        return True

    def request(
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
    ) -> Stream:
        """Send an HTTP/2 request"""
        if chunked:
            # TODO this is often present from upstream.
            # raise NotImplementedError("`chunked` isn't supported with HTTP/2")
            pass

        stream = Stream(self.conn)
        self.putrequest(method, url, stream=stream)

        # store response options in the stream data
        self._stream_data[stream].preload_content = preload_content
        self._stream_data[stream].decode_content = decode_content
        self._stream_data[stream].enforce_content_length = enforce_content_length

        headers = headers or {}
        for k, v in headers.items():
            if k.lower() == "transfer-encoding" and v == "chunked":
                continue
            else:
                self.putheader(k, v, stream=stream)

        if b"user-agent" not in dict(self._stream_data[stream].headers):
            self.putheader("user-agent", _get_default_user_agent(), stream=stream)

        if body:
            self.endheaders(message_body=body, stream=stream)
            self.send(body, stream=stream)
        else:
            self.endheaders(stream=stream)
        return stream

    def _receive(self, until: typing.Callable[[], bool]) -> None:
        """Process events until the ``until`` callable returns True.

        This is a generic event loop that runs until a condition provided by the
        caller triggers. Any data events for any streams that are received are
        cached. A connection that is terminated by the server raises a
        ``ConnectionError``.
        """
        while not until():
            # TODO: Arbitrary read value.
            if received_data := self.conn.sock.recv(65535):
                with self._h2_conn as h2_conn:
                    for event in h2_conn.receive_data(received_data):
                        if isinstance(event, h2.events.ConnectionTerminated):
                            raise ConnectionError("The connection was closed")
                        elif isinstance(event, h2.events.ResponseReceived):
                            if event.stream_id in self._stream_data:
                                status = None
                                headers = HTTPHeaderDict()
                                for header, value in event.headers:
                                    if header == b":status":
                                        status = int(value.decode())
                                    else:
                                        headers.add(
                                            header.decode("ascii"),
                                            value.decode("ascii"),
                                        )
                                if not status:  # Defensive:
                                    raise ConnectionError("Missing response status")
                                self._stream_data[event.stream_id].status = status
                                self._stream_data[event.stream_id].response_headers = (
                                    headers
                                )
                        elif isinstance(event, h2.events.DataReceived):
                            h2_conn.acknowledge_received_data(
                                event.flow_controlled_length, event.stream_id
                            )
                            if event.stream_id in self._stream_data:
                                self._stream_data[
                                    event.stream_id
                                ].response_buffer += event.data
                        elif isinstance(event, h2.events.StreamReset):
                            if event.stream_id in self._stream_data:
                                self._stream_data[event.stream_id].response_reset = True
                        elif isinstance(event, h2.events.StreamEnded):
                            if event.stream_id in self._stream_data:
                                self._stream_data[event.stream_id].response_eof = True
                    if data_to_send := h2_conn.data_to_send():
                        self.conn.sock.sendall(data_to_send)

    def _wait_for_response(self, stream: Stream) -> None:
        """Process events until the given stream returned a response."""
        with self._h2_conn:
            self._receive(
                lambda: (
                    stream.stream_id in self._stream_data
                    and (
                        self._stream_data[stream.stream_id].status > 0
                        or self._stream_data[stream.stream_id].response_eof
                        or self._stream_data[stream.stream_id].response_reset
                    )
                )
            )

    def _wait_for_data(self, stream: Stream) -> None:
        """Process events until the given stream has response data available."""
        with self._h2_conn:
            self._receive(
                lambda: (
                    stream.stream_id in self._stream_data
                    and (
                        len(self._stream_data[stream.stream_id].response_buffer) > 0
                        or self._stream_data[stream.stream_id].response_eof
                        or self._stream_data[stream.stream_id].response_reset
                    )
                )
            )

    def _wait_for_flow_control(self, stream: Stream) -> int:
        """Process events until the given stream's flow control window is
        greater than zero or the stream was reset by the server."""
        if not stream.stream_id:  # Defensive:
            raise ConnectionError("Must call `request` to create a stream")
        with self._h2_conn as h2_conn:
            # here we want to listen to events until one of:
            # - the flow control window is updated and is greater than 0
            # - the server reset the stream
            self._receive(
                lambda: (
                    h2_conn.local_flow_control_window(stream.stream_id) > 0  # type: ignore[arg-type]
                    or (
                        stream.stream_id in self._stream_data
                        and (
                            self._stream_data[stream.stream_id].response_eof
                            or self._stream_data[stream.stream_id].response_reset
                        )
                    )
                )
            )
            return h2_conn.local_flow_control_window(stream.stream_id)

    def getresponse(self, stream: Stream | None = None) -> HTTPResponse:
        if stream is None:
            raise ConnectionError("`stream` cannot be None")
        if not stream.stream_id:
            raise ConnectionError("Must call `request` to create a stream")

        self._wait_for_response(stream)
        stream_data = self._stream_data[stream]

        return HTTP2Response(
            connection=self.conn,
            request_url=stream_data.url,
            status=stream_data.status,
            headers=stream_data.response_headers,
            read_stream=lambda amt: self.read_stream(stream, amt),
            preload_content=stream_data.preload_content,
            decode_content=stream_data.decode_content,
            enforce_content_length=stream_data.enforce_content_length,
        )

    def _write_with_flow_control(self, data: bytes, stream: Stream) -> None:
        if not stream.stream_id:  # Defensive:
            raise ConnectionError("Must call `request` to create a stream")
        while data:
            window_size = self._wait_for_flow_control(stream)
            if window_size == 0:
                raise StreamError("The stream was reset")
            with self._h2_conn as h2_conn:
                chunk = data[:window_size]
                data = data[window_size:]
                h2_conn.send_data(stream.stream_id, chunk, end_stream=False)
                if data_to_send := h2_conn.data_to_send():
                    self.conn.sock.sendall(data_to_send)

    def send(self, data: typing.Any, stream: Stream | None = None) -> bool:
        if stream is None:
            raise ConnectionError("`stream` cannot be None")
        if not stream.stream_id:
            raise ConnectionError("Must call `request` to create a stream")

        with self._h2_conn as h2_conn:
            if data_to_send := h2_conn.data_to_send():
                self.conn.sock.sendall(data_to_send)

        if hasattr(data, "read"):  # file-like objects
            while True:
                chunk = data.read(self.conn.blocksize)
                if not chunk:
                    break
                if isinstance(chunk, str):
                    chunk = chunk.encode()
                self._write_with_flow_control(chunk, stream)
            with self._h2_conn as h2_conn:
                h2_conn.end_stream(stream.stream_id)
                if data_to_send := h2_conn.data_to_send():
                    self.conn.sock.sendall(data_to_send)
            return True

        if isinstance(data, str):  # str -> bytes
            data = data.encode()

        try:
            if isinstance(data, bytes):
                self._write_with_flow_control(data, stream)
                with self._h2_conn as h2_conn:
                    h2_conn.end_stream(stream.stream_id)
                    if data_to_send := h2_conn.data_to_send():
                        self.conn.sock.sendall(data_to_send)
            else:
                for chunk in data:
                    self._write_with_flow_control(chunk, stream)
                with self._h2_conn as h2_conn:
                    h2_conn.end_stream(stream.stream_id)
                    if data_to_send := h2_conn.data_to_send():
                        self.conn.sock.sendall(data_to_send)
        except TypeError:
            raise TypeError(
                "`data` should be str, bytes, iterable, or file. got %r" % type(data)
            )
        return True

    def read_stream(self, stream: Stream, n: int = 0) -> bytes:
        """Read bytes from a stream."""
        stream_data = self._stream_data[stream]
        data = b""
        while not stream_data.response_reset and not stream_data.response_eof:
            if n > 0:
                need = n - len(data)
                data += stream_data.response_buffer[:need]
                stream_data.response_buffer = stream_data.response_buffer[need:]
                if len(data) == n:
                    break  # we have what we need
            else:
                data += stream_data.response_buffer
                stream_data.response_buffer = b""
            self._wait_for_data(stream)
        if n == 0:
            data += stream_data.response_buffer
            stream_data.response_buffer = b""
        if stream_data.response_reset:
            if n == 0 or len(data) < n:
                raise StreamError("The stream was reset")
        if len(stream_data.response_buffer) == 0 and stream_data.response_eof:
            # we just read the last of the response, so we can close the stream
            self.close_stream(stream)
        return data

    def close(self) -> None:
        with self._h2_conn as h2_conn:
            try:
                h2_conn.close_connection()
                if data := h2_conn.data_to_send():
                    self.conn.sock.sendall(data)
            except Exception:
                pass

        # Reset all our HTTP/2 connection state.
        self._h2_conn = self._new_h2_conn()

    def close_stream(self, stream: Stream | None = None) -> None:
        if stream is None:
            raise ConnectionError("`stream` cannot be None")
        if not stream.stream_id:
            raise ConnectionError("Must call `request` to create a stream")

        reset_code = h2.errors.ErrorCodes.NO_ERROR
        if stream in self._stream_data and not self._stream_data[stream].response_eof:
            reset_code = h2.errors.ErrorCodes.CANCEL
        with self._h2_conn as h2_conn:
            try:
                h2_conn.reset_stream(stream.stream_id, error_code=reset_code)
                if data := h2_conn.data_to_send():
                    self.conn.sock.sendall(data)
            except Exception:
                pass

        if stream in self._stream_data:
            del self._stream_data[stream]
        if stream.stream_id in self._stream_data:
            del self._stream_data[stream.stream_id]


class HTTP2Response(HTTPResponse):
    # TODO: This is a woefully incomplete response object, but works for non-streaming.
    def __init__(
        self,
        status: int,
        headers: HTTPHeaderDict,
        request_url: str,
        read_stream: typing.Callable[[int], bytes],
        preload_content: bool = True,
        decode_content: bool = True,
        enforce_content_length: bool = True,
        connection: HTTPConnection | None = None,
    ) -> None:
        self._read_stream = read_stream
        super().__init__(
            status=status,
            headers=headers,
            # Following CPython, we map HTTP versions to major * 10 + minor integers
            version=20,
            version_string="HTTP/2",
            # No reason phrase in HTTP/2
            reason=None,
            preload_content=preload_content,
            decode_content=decode_content,
            enforce_content_length=enforce_content_length,
            connection=connection,
            request_url=request_url,
        )

    def _raw_read(
        self,
        amt: int | None = None,
        *,
        read1: bool = False,
    ) -> bytes:
        data = self._read_stream(amt or 0)
        self._fp_bytes_read += len(data)
        if self.length_remaining is not None:
            self.length_remaining -= len(data)
        if not data:
            # auto-close here?
            if (
                self.enforce_content_length
                and self.length_remaining is not None
                and self.length_remaining != 0
            ):
                raise IncompleteRead(self._fp_bytes_read, self.length_remaining)
        return data

    @property
    def data(self) -> bytes:
        # For backwards-compat with earlier urllib3 0.4 and earlier.
        if self._body:
            return self._body  # type: ignore[return-value]

        return self.read(cache_content=True)

    def close(self) -> None:
        pass
