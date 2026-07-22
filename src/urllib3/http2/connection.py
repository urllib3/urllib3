from __future__ import annotations

import io
import logging
import re
import threading
import types
import typing

import h2.config
import h2.connection
import h2.events

from .._base_connection import _TYPE_BODY
from .._collections import HTTPHeaderDict
from ..connection import HTTPSConnection, _get_default_user_agent
from ..exceptions import ConnectionError
from ..response import _READ_CHUNK_SIZE, BaseHTTPResponse, BytesQueueBuffer

if typing.TYPE_CHECKING:
    from .._base_connection import BaseHTTPConnection
    from ..connectionpool import HTTPConnectionPool

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
        self._h2_stream: int | None = None
        self._headers: list[tuple[bytes, bytes]] = []
        self._preload_content = True
        self._decode_content = True

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

        if ":" in self.host:
            authority = f"[{self.host}]:{self.port or 443}"
        else:
            authority = f"{self.host}:{self.port or 443}"

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
        status: int | None = None
        headers: HTTPHeaderDict | None = None
        data_buffer = BytesQueueBuffer()
        stream_ended = False
        if self._h2_stream is None:
            raise ConnectionError("Must call `putrequest` first.")

        with self._h2_conn as conn:
            while headers is None:
                # TODO: Arbitrary read value.
                if received_data := self.sock.recv(65535):
                    events = conn.receive_data(received_data)
                    for event in events:
                        if isinstance(event, h2.events.ResponseReceived):
                            headers = HTTPHeaderDict()
                            for header, value in event.headers:
                                if header == b":status":
                                    status = int(value.decode())
                                else:
                                    headers.add(
                                        header.decode("ascii"), value.decode("ascii")
                                    )

                        elif isinstance(event, h2.events.DataReceived):
                            if event.stream_id == self._h2_stream:
                                data_buffer.put(event.data)
                            conn.acknowledge_received_data(
                                event.flow_controlled_length, event.stream_id
                            )

                        elif isinstance(event, h2.events.StreamEnded):
                            if event.stream_id == self._h2_stream:
                                stream_ended = True
                else:
                    break

                if data_to_send := conn.data_to_send():
                    self.sock.sendall(data_to_send)

        assert status is not None
        assert headers is not None
        return HTTP2Response(
            status=status,
            headers=headers,
            request_url=self._request_url,
            sock=self.sock,
            h2_conn=self._h2_conn,
            stream_id=self._h2_stream,
            data_buffer=data_buffer,
            stream_ended=stream_ended,
            preload_content=self._preload_content,
            decode_content=self._decode_content,
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
        self._preload_content = preload_content
        self._decode_content = decode_content

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
    def __init__(
        self,
        status: int,
        headers: HTTPHeaderDict,
        request_url: str,
        sock: typing.Any,
        h2_conn: _LockedObject[h2.connection.H2Connection],
        stream_id: int,
        data_buffer: BytesQueueBuffer,
        stream_ended: bool,
        preload_content: bool = True,
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
        self._sock = sock
        self._h2_conn = h2_conn
        self._stream_id = stream_id
        self._data_buffer = data_buffer
        self._stream_ended = stream_ended
        self._body: bytes | None = None
        self._decoded_buffer = BytesQueueBuffer()
        self._uncached_read_occurred = False
        self._fp_bytes_read = len(data_buffer)
        self._pool: HTTPConnectionPool | None = None
        self._connection: BaseHTTPConnection | None = None

        content_length = self.headers.get("content-length")
        self.length_remaining = None
        if content_length is not None:
            try:
                self.length_remaining = int(content_length)
            except ValueError:
                pass
            else:
                self.length_remaining -= len(data_buffer)

        if preload_content:
            self._body = self.read(cache_content=True)

    @property
    def data(self) -> bytes:
        if self._body is not None:
            return self._body
        return self.read(cache_content=True)

    @property
    def url(self) -> str | None:
        return self._request_url

    @url.setter
    def url(self, url: str | None) -> None:
        self._request_url = url

    @property
    def connection(self) -> BaseHTTPConnection | None:
        return self._connection

    def get_redirect_location(self) -> None:
        return None

    def _read_next_event(self) -> None:
        if self._stream_ended:
            return

        with self._h2_conn as conn:
            while not self._stream_ended and not self._data_buffer:
                if not (received_data := self._sock.recv(65535)):
                    self._stream_ended = True
                    break

                events = conn.receive_data(received_data)
                for event in events:
                    if isinstance(event, h2.events.DataReceived):
                        if event.stream_id == self._stream_id:
                            self._data_buffer.put(event.data)
                            self._fp_bytes_read += len(event.data)
                            if self.length_remaining is not None:
                                self.length_remaining -= len(event.data)
                        conn.acknowledge_received_data(
                            event.flow_controlled_length, event.stream_id
                        )
                    elif isinstance(event, h2.events.StreamEnded):
                        if event.stream_id == self._stream_id:
                            self._stream_ended = True

                if data_to_send := conn.data_to_send():
                    self._sock.sendall(data_to_send)

    def _raw_read(self, amt: int | None = None) -> bytes:
        if amt == 0:
            return b""

        if amt is None:
            chunks = []
            while self._data_buffer or not self._stream_ended:
                if self._data_buffer:
                    chunks.append(self._data_buffer.get_all())
                else:
                    self._read_next_event()
            return b"".join(chunks)

        while len(self._data_buffer) < amt and not self._stream_ended:
            self._read_next_event()

        if not self._data_buffer:
            return b""
        return self._data_buffer.get(min(amt, len(self._data_buffer)))

    def _release_when_stream_consumed(self) -> None:
        if self._stream_ended and not self._data_buffer:
            self.release_conn()

    def read(
        self,
        amt: int | None = None,
        decode_content: bool | None = None,
        cache_content: bool = False,
    ) -> bytes:
        self._init_decoder()
        if decode_content is None:
            decode_content = self.decode_content

        if amt and amt < 0:
            amt = None
        elif amt == 0:
            return b""

        if amt is None:
            data = self._raw_read()
            if not cache_content:
                self._uncached_read_occurred = True
            data = self._decode(data, decode_content, flush_decoder=True)
            if decode_content and len(self._decoded_buffer) > 0:
                self._decoded_buffer.put(data)
                data = self._decoded_buffer.get_all()
            if cache_content and not self._uncached_read_occurred:
                self._body = data
            self._release_when_stream_consumed()
            return data

        self._uncached_read_occurred = True
        while len(self._decoded_buffer) < amt:
            raw_data = self._raw_read(amt)
            if not raw_data:
                self._decoded_buffer.put(
                    self._decode(raw_data, decode_content, flush_decoder=True)
                )
                break

            if not decode_content:
                if self._has_decoded_content:
                    raise RuntimeError(
                        "Calling read(decode_content=False) is not supported after "
                        "read(decode_content=True) was called."
                    )
                self._release_when_stream_consumed()
                return raw_data

            decoded_data = self._decode(
                raw_data,
                decode_content,
                flush_decoder=False,
                max_length=amt - len(self._decoded_buffer),
            )
            self._decoded_buffer.put(decoded_data)

        if not self._decoded_buffer:
            self._release_when_stream_consumed()
            return b""
        data = self._decoded_buffer.get(min(amt, len(self._decoded_buffer)))
        self._release_when_stream_consumed()
        return data

    def read1(
        self,
        amt: int | None = None,
        decode_content: bool | None = None,
    ) -> bytes:
        return self.read(amt=amt, decode_content=decode_content)

    def stream(
        self, amt: int | None = _READ_CHUNK_SIZE, decode_content: bool | None = None
    ) -> typing.Generator[bytes]:
        if amt == 0:
            return

        while True:
            data = self.read(amt=amt, decode_content=decode_content)
            if not data:
                break
            yield data

    def read_chunked(
        self,
        amt: int | None = None,
        decode_content: bool | None = None,
    ) -> typing.Iterator[bytes]:
        return self.stream(amt=amt, decode_content=decode_content)

    def release_conn(self) -> None:
        if not self._pool or not self._connection:
            return None

        self._pool._put_conn(self._connection)
        self._connection = None
        return None

    def drain_conn(self) -> None:
        self.read()

    def shutdown(self) -> None:
        self.close()

    def close(self) -> None:
        self._stream_ended = True
        if self._connection:
            self._connection.close()
            self._connection = None
        if not self.closed:
            io.IOBase.close(self)

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._fp_bytes_read
