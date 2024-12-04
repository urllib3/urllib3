from __future__ import annotations

import logging
import re
import threading
import types
import typing
from enum import Enum
from io import BytesIO

import h2.config  # type: ignore[import-untyped]
import h2.connection  # type: ignore[import-untyped]
import h2.events  # type: ignore[import-untyped]

from .._base_connection import _TYPE_BODY
from .._collections import HTTPHeaderDict
from ..connection import HTTPSConnection, _get_default_user_agent
from ..exceptions import ConnectionError
from ..response import BaseHTTPResponse, BytesQueueBuffer

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


class HTTP2Connection(HTTPSConnection):
    def __init__(
        self, host: str, port: int | None = None, **kwargs: typing.Any
    ) -> None:
        self._h2_conn = self._new_h2_conn()
        self._h2_streams: dict[int, HTTP2Stream] = dict()
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

    def _putrequest(
        self,
        stream_id: int,
        method: str,
        url: str,
        **kwargs: typing.Any,
    ) -> None:
        """_putrequest
        This deviates from the HTTPConnection method signature since we never need to override
        sending accept-encoding headers or the host header.
        """
        if "skip_host" in kwargs:
            raise NotImplementedError("`skip_host` isn't supported")
        if "skip_accept_encoding" in kwargs:
            raise NotImplementedError("`skip_accept_encoding` isn't supported")

        self._request_url = url or "/"
        self._validate_path(url)  # type: ignore[attr-defined]

        if ":" in self.host:
            authority = f"[{self.host}]:{self.port or 443}"
        else:
            authority = f"{self.host}:{self.port or 443}"

        self._headers.append((b":scheme", b"https"))
        self._headers.append((b":method", method.encode()))
        self._headers.append((b":authority", authority.encode()))
        self._headers.append((b":path", url.encode()))

    def putheader(self, header: str | bytes, *values: str | bytes) -> None:
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

    def _endheaders(self, stream_id: int, message_body: typing.Any = None) -> None:
        with self._h2_conn as conn:
            conn.send_headers(
                stream_id=stream_id,
                headers=self._headers,
                end_stream=(message_body is None),
            )
            if data_to_send := conn.data_to_send():
                self.sock.sendall(data_to_send)
        self._headers = []  # Reset headers for the next request.

    def _send_stream(self, stream_id: int, data: typing.Any) -> None:
        """Send data across a stream to the server
        `stream_id`: `int`, id corresponding to the stream
        `data`: `str`, `bytes`, an iterable, or file-like objects
        that support a .read() method.
        """
        with self._h2_conn as conn:
            if data_to_send := conn.data_to_send():
                self.sock.sendall(data_to_send)

            if hasattr(data, "read"):  # file-like objects
                while True:
                    chunk = data.read(self.blocksize)
                    if not chunk:
                        break
                    if isinstance(chunk, str):
                        chunk = chunk.encode()  # pragma: no cover
                    conn.send_data(stream_id, chunk, end_stream=False)
                    if data_to_send := conn.data_to_send():
                        self.sock.sendall(data_to_send)
                conn.end_stream(stream_id)
                return

            if isinstance(data, str):  # str -> bytes
                data = data.encode()

            try:
                if isinstance(data, bytes):
                    conn.send_data(stream_id, data, end_stream=True)
                    if data_to_send := conn.data_to_send():
                        self.sock.sendall(data_to_send)
                else:
                    for chunk in data:
                        conn.send_data(stream_id, chunk, end_stream=False)
                        if data_to_send := conn.data_to_send():
                            self.sock.sendall(data_to_send)
                    conn.end_stream(stream_id)
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

    def _read_stream(
        self,
        stream_id: int,
        get_response_headers: bool = False,
        end_stream: bool = False,
    ) -> None:
        if not get_response_headers and not end_stream:
            raise RuntimeError(
                "One of 'get_response_headers' or 'end_stream' should be set"
            )

        if get_response_headers and end_stream:
            raise RuntimeError(
                "Only one of 'get_response_headers' and 'end_stream' " "should be set."
            )

        with self._h2_conn as conn:
            stop_reading = False
            while not stop_reading:
                # breakpoint()
                if not (received_data := self.sock.recv(65535)):
                    # connection is lost
                    break

                events = conn.receive_data(received_data)
                for event in events:
                    print(event)
                    if isinstance(event, h2.events.ResponseReceived):
                        _headers = HTTPHeaderDict()
                        for header, value in event.headers:
                            if header == b":status":
                                _status = int(value.decode())
                            else:
                                _headers.add(
                                    header.decode("ascii"), value.decode("ascii")
                                )

                        self._h2_streams[event.stream_id].open_stream(_status, _headers)
                        if get_response_headers and stream_id == event.stream_id:
                            stop_reading = True

                    elif isinstance(event, h2.events.DataReceived):
                        self._h2_streams[event.stream_id].push_data(event.data)
                        conn.acknowledge_received_data(
                            event.flow_controlled_length, event.stream_id
                        )
                    elif isinstance(event, h2.events.StreamEnded):
                        self._h2_streams[event.stream_id].end_stream()
                        if end_stream and event.stream_id == stream_id:
                            stop_reading = True

                if data_to_send := conn.data_to_send():
                    self.sock.sendall(data_to_send)
        if get_response_headers and not stop_reading:
            raise ConnectionError(
                f"Could not get Response Headers for stream {stream_id}"
            )
        if end_stream and not stop_reading:
            raise ConnectionError(
                f"Expected StreamEnded event for stream id {stream_id}."
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
    ) -> HTTP2Stream:
        """Send an HTTP/2 request"""
        if "chunked" in kwargs:
            # TODO this is often present from upstream.
            # raise NotImplementedError("`chunked` isn't supported with HTTP/2")
            pass

        if self.sock is not None:
            self.sock.settimeout(self.timeout)

        stream_id = None
        with self._h2_conn as conn:
            stream_id = conn.get_next_available_stream_id()

        if stream_id is None:
            raise ConnectionError("Could not allocate stream id.")

        self._putrequest(stream_id, method, url)

        headers = headers or {}
        for k, v in headers.items():
            if k.lower() == "transfer-encoding" and v == "chunked":
                continue
            else:
                self.putheader(k, v)

        if b"user-agent" not in dict(self._headers):
            self.putheader(b"user-agent", _get_default_user_agent())

        if body:
            self._endheaders(stream_id=stream_id, message_body=body)
            self._send_stream(stream_id=stream_id, data=body)
        else:
            self._endheaders(stream_id=stream_id)

        stream = HTTP2Stream(stream_id=stream_id, connection=self)
        self._h2_streams[stream_id] = stream

        return stream

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


# These states have different meaning than the HTTP/2 RFC9113. They mean -
# IDLE = Response Headers have not being received
# OPEN = Response Headers Received, also can received data.
# CLOSED = END_STREAM received and also send back
StreamState = Enum("StreamState", ["IDLE", "OPEN", "CLOSED"])


class HTTP2Stream:
    def __init__(self, stream_id: int, connection: HTTP2Connection) -> None:
        self.stream_id = stream_id
        self.state = StreamState.IDLE
        self.connection = connection
        self.response: HTTP2Response | None = None
        self._data = BytesIO()

    def getresponse(self) -> HTTP2Response:
        if self.state == StreamState.IDLE:
            self.connection._read_stream(self.stream_id, get_response_headers=True)

        assert self.response is not None
        return self.response

    def open_stream(self, status: int, headers: HTTPHeaderDict) -> None:
        assert self.state == StreamState.IDLE
        res = HTTP2Response(
            status=status,
            headers=headers,
            request_url=self.connection._request_url,
            data=bytearray(),
            stream=self,
        )
        self.response = res
        self.state = StreamState.OPEN

    def read(self, amt: int = -1) -> bytes:
        if self.state == StreamState.OPEN:
            self.connection._read_stream(self.stream_id, end_stream=True)

        assert self.state == StreamState.CLOSED
        return self._data.read(amt)

    def push_data(self, data: bytes) -> None:
        assert self.state == StreamState.OPEN
        self._data.write(data)

    def end_stream(self) -> None:
        assert self.state != StreamState.CLOSED
        self._data.seek(0)
        self.state = StreamState.CLOSED


class HTTP2Response(BaseHTTPResponse):
    # TODO: This is a woefully incomplete response object, but works for non-streaming.
    def __init__(
        self,
        status: int,
        headers: HTTPHeaderDict,
        request_url: str,
        data: bytes,
        stream: HTTP2Stream,
        decode_content: bool = True,
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
        self._stream = stream
        # self.length_remaining = self._init_length()

        self._decoded_buffer = BytesQueueBuffer()

    def read(
        self,
        amt: int | None = None,
        decode_content: bool | None = None,
        cache_content: bool = False,
    ) -> bytes:
        self._init_decoder()
        if decode_content is None:
            decode_content = self.decode_content

        if not decode_content:
            if self._has_decoded_content:
                raise RuntimeError(
                    "Calling read(decode_content=False) is not supported after "
                    "read(decode_content=True) was called."
                )

        if amt and amt < 0:
            amt = None

        if amt is None:
            # read all the data
            data = self._stream.read()
            decode_content, flush_decoder = True, True
            data = self._decode(data, decode_content, flush_decoder)
            if cache_content:
                self._data = data
        else:
            if len(self._decoded_buffer) >= amt:
                return self._decoded_buffer.get(amt)

            data = self._stream.read(amt)

            if decode_content:
                flush_decoder = amt != 0 and not data
                decoded_data = self._decode(data, decode_content, flush_decoder)
                self._decoded_buffer.put(decoded_data)
                data = self._decoded_buffer.get(amt)

        return data

    @property
    def data(self) -> bytes:
        if self._data:
            return self._data

        self.read(cache_content=True)
        return self._data

    def get_redirect_location(self) -> None:
        return None

    def close(self) -> None:
        pass
