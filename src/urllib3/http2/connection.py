from __future__ import annotations

import io
import logging
import re
import socket
import threading
import types
import typing
from contextlib import contextmanager
from http.client import HTTPException, ResponseNotReady
from socket import timeout as SocketTimeout

import h2.config
import h2.connection
import h2.events
import h2.exceptions

from .._base_connection import _TYPE_BODY, _ResponseOptions
from .._collections import HTTPHeaderDict
from ..connection import BaseSSLError, HTTPSConnection, _get_default_user_agent
from ..exceptions import (
    ConnectionError,
    HTTPError,
    IncompleteRead,
    InvalidHeader,
    ProtocolError,
    ReadTimeoutError,
    ResponseNotChunked,
    SSLError,
)
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


class HTTP2Stream:
    """
    Owns the read side of a single HTTP/2 stream.

    Instances of this class receive h2 events for the shared HTTP/2
    connection, buffer the DATA frames destined for their stream and
    acknowledge received data to keep the connection's flow control
    window open.

    :meth:`HTTP2Connection.getresponse` uses this object to read the
    response headers and then transfers ownership to
    :class:`HTTP2Response`, which reads the response body through it.
    Keeping all socket reads in one place avoids two competing h2 event
    loops in the connection and the response.
    """

    def __init__(
        self,
        sock: socket.socket,
        h2_conn: _LockedObject[h2.connection.H2Connection],
        stream_id: int,
    ) -> None:
        self._sock = sock
        self._h2_conn = h2_conn
        self.stream_id = stream_id
        self._data_buffer = BytesQueueBuffer()
        self._response: tuple[int, HTTPHeaderDict] | None = None
        self._ended = False

    @property
    def is_complete(self) -> bool:
        """Whether the stream has ended and all buffered data was consumed."""
        return self._ended and not len(self._data_buffer)

    def read_response(self) -> tuple[int, HTTPHeaderDict]:
        """
        Receive events until the response headers for this stream arrive
        and return the status code and headers.

        Informational (1xx) responses are skipped. DATA frames received
        together with the headers are buffered for later reads.
        """
        while self._response is None:
            self._receive_events()
        return self._response

    def read(self, amt: int | None = None, *, read1: bool = False) -> bytes:
        """
        Read up to ``amt`` bytes of the response body, receiving from the
        socket as needed.

        ``amt=None`` reads until the end of the stream. ``read1=True``
        returns as soon as any data is buffered instead of waiting for
        ``amt`` bytes to accumulate. Returns ``b""`` only once the stream
        has ended and all buffered data was consumed.
        """
        if read1 or amt is None:
            while not len(self._data_buffer) and not self._ended:
                self._receive_events()
            if amt is None and not read1:
                while not self._ended:
                    self._receive_events()
        else:
            while len(self._data_buffer) < amt and not self._ended:
                self._receive_events()

        if not len(self._data_buffer):
            return b""
        elif amt is None:
            return self._data_buffer.get_all()
        else:
            return self._data_buffer.get(amt)

    def _receive_events(self) -> None:
        """Read once from the socket and dispatch the resulting h2 events."""
        # recv() deliberately happens outside the h2 lock: if a blocking
        # read held the lock, close() from another thread (which needs the
        # lock) would block until the read returned.
        received_data = self._sock.recv(_READ_CHUNK_SIZE)
        if not received_data:
            if self._response is None:
                msg = "Connection closed without sending a complete response"
            else:
                msg = "Connection closed before the response body was complete"
            raise ProtocolError(msg)

        with self._h2_conn as conn:
            try:
                events = conn.receive_data(received_data)
            except h2.exceptions.ProtocolError as e:
                # h2 queues a GOAWAY frame for the peer when it encounters
                # a protocol error. Try to deliver it, but don't let a send
                # failure mask the actual error.
                try:
                    if data_to_send := conn.data_to_send():
                        self._sock.sendall(data_to_send)
                except OSError:
                    pass
                raise ProtocolError(f"Invalid HTTP/2 data received: {e!r}", e) from e

            for event in events:
                if isinstance(event, h2.events.ResponseReceived):
                    if event.stream_id == self.stream_id:
                        self._response = self._response_from_event(event)
                elif isinstance(event, h2.events.DataReceived):
                    # Open up the flow control window for the peer even if
                    # the data is not for our stream.
                    conn.acknowledge_received_data(
                        event.flow_controlled_length, event.stream_id
                    )
                    if event.stream_id == self.stream_id:
                        self._data_buffer.put(event.data)
                elif isinstance(event, h2.events.StreamEnded):
                    if event.stream_id == self.stream_id:
                        self._ended = True
                elif isinstance(event, h2.events.StreamReset):
                    # Minimal safety net so reads fail instead of blocking
                    # forever. Comprehensive error event handling is
                    # tracked in https://github.com/urllib3/urllib3/issues/3291
                    if event.stream_id == self.stream_id and not self._ended:
                        raise ProtocolError(
                            "Stream was reset by the remote peer "
                            f"(error code {event.error_code})"
                        )
                elif isinstance(event, h2.events.ConnectionTerminated):
                    # Frames that complete this stream before the GOAWAY
                    # already set _ended above. Anything else can never
                    # complete: h2 moves the connection to the CLOSED
                    # state on a received GOAWAY and rejects all frames
                    # after it, so fail fast with a clear error.
                    if not self._ended:
                        raise ProtocolError(
                            "Connection was terminated by the remote peer "
                            f"(error code {event.error_code})"
                        )

            if data_to_send := conn.data_to_send():
                try:
                    self._sock.sendall(data_to_send)
                except OSError:
                    # The stream ended in this batch: failing to deliver
                    # trailing acknowledgements doesn't invalidate the
                    # fully received response.
                    if not self._ended:
                        raise

    def _response_from_event(
        self, event: h2.events.ResponseReceived
    ) -> tuple[int, HTTPHeaderDict]:
        status: int | None = None
        headers = HTTPHeaderDict()
        assert event.headers is not None
        for header, value in event.headers:
            if header == b":status":
                try:
                    status = int(value.decode())
                except ValueError as e:
                    raise ProtocolError(
                        f"Invalid :status pseudo-header value {value!r}"
                    ) from e
            elif not header.startswith(b":"):
                # http.client decodes HTTP/1.1 header bytes as latin-1;
                # match that so byte-identical headers parse identically.
                headers.add(header.decode("latin-1"), value.decode("latin-1"))
        if status is None:  # Defensive: h2 rejects responses without :status.
            raise ProtocolError("Received HTTP/2 response without a :status header")
        return status, headers


class HTTP2Connection(HTTPSConnection):
    def __init__(
        self, host: str, port: int | None = None, **kwargs: typing.Any
    ) -> None:
        self._h2_conn = self._new_h2_conn()
        self._h2_stream: int | None = None
        self._headers: list[tuple[bytes, bytes]] = []
        self._response_options: _ResponseOptions | None = None

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
        """
        Read from the socket until the response headers arrive, then hand
        the body off to :class:`HTTP2Response` via :class:`HTTP2Stream`.

        Raises :class:`http.client.ResponseNotReady` if a request has not
        been sent or a previous response was not handled.
        """
        # Raise the same error as http.client.HTTPConnection
        if self._response_options is None or self._h2_stream is None:
            raise ResponseNotReady()

        # Reset this attribute for being used again.
        resp_options = self._response_options
        self._response_options = None

        # Since the connection's timeout value may have been updated
        # we need to set the timeout on the socket.
        self.sock.settimeout(self.timeout)

        # Transfer ownership of the stream's read side to the response.
        # The response object reads the body from the stream on demand.
        stream = HTTP2Stream(self.sock, self._h2_conn, self._h2_stream)
        self._h2_stream = None

        status, headers = stream.read_response()

        return HTTP2Response(
            status=status,
            headers=headers,
            request_url=resp_options.request_url,
            stream=stream,
            request_method=resp_options.request_method,
            preload_content=resp_options.preload_content,
            decode_content=resp_options.decode_content,
            enforce_content_length=resp_options.enforce_content_length,
            sock_shutdown=getattr(self.sock, "shutdown", None),
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

        # Store these values to be fed into the HTTP2Response object later.
        # We have to store these before we send the request in case we
        # can still salvage a response off the wire even if we aren't able
        # to completely send the request body.
        self._response_options = _ResponseOptions(
            request_method=method,
            request_url=url,
            preload_content=preload_content,
            decode_content=decode_content,
            enforce_content_length=enforce_content_length,
        )

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
        self._response_options = None

        super().close()


class HTTP2Response(BaseHTTPResponse):
    """
    HTTP/2 response.

    The response body is owned by an :class:`HTTP2Stream` handed off by
    :meth:`HTTP2Connection.getresponse` once the response headers were
    received. The body is read from the stream on demand, so responses
    can be streamed with ``preload_content=False`` and decoded based on
    the ``content-encoding`` header just like HTTP/1.1 responses.

    Note that HTTP/2 always enforces that the response body matches the
    ``content-length`` header, as required by RFC 9113 section 8.1.1.
    """

    def __init__(
        self,
        status: int,
        headers: HTTPHeaderDict,
        request_url: str,
        stream: HTTP2Stream,
        request_method: str | None = None,
        preload_content: bool = True,
        decode_content: bool = True,
        enforce_content_length: bool = True,
        auto_close: bool = True,
        sock_shutdown: typing.Callable[[int], None] | None = None,
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
        self._stream = stream
        self._body: bytes | None = None
        self._closed = False
        self._fp_bytes_read = 0
        self._uncached_read_occurred = False
        self._decoded_buffer = BytesQueueBuffer()
        self._sock_shutdown = sock_shutdown

        # h2 enforces on the wire that the received body matches the
        # content-length header. This attribute additionally gates the
        # IncompleteRead check for responses closed before the body was
        # fully read, mirroring HTTPResponse.
        self.enforce_content_length = enforce_content_length
        self.auto_close = auto_close

        # Set by the connection pool after the response is constructed.
        self._pool: HTTPConnectionPool | None = None
        self._connection: BaseHTTPConnection | None = None

        self.length_remaining = self._init_length(request_method)

        # If requested, preload the body.
        if preload_content:
            self._body = self.read(decode_content=decode_content)

    def _init_length(self, request_method: str | None) -> int | None:
        # h2 validates the content-length header on the wire and enforces
        # that the received body matches it, so unlike HTTP/1.1 we only
        # need to parse the value for bookkeeping. The multiple-value
        # handling mirrors HTTPResponse for responses constructed directly.
        length: int | None = None
        content_length = self.headers.get("content-length")
        if content_length is not None:
            try:
                lengths = {int(val) for val in content_length.split(",")}
                if len(lengths) > 1:
                    raise InvalidHeader(
                        "Content-Length contained multiple "
                        "unmatching values (%s)" % content_length
                    )
                length = lengths.pop()
            except ValueError:
                length = None
            else:
                if length < 0:
                    length = None

        # Check for responses that shouldn't include a body
        if (
            self.status in (204, 304)
            or 100 <= self.status < 200
            or request_method == "HEAD"
        ):
            length = 0

        return length

    @contextmanager
    def _error_catcher(self) -> typing.Generator[None]:
        """
        Catch low-level python exceptions, instead re-raising urllib3
        variants, so that low-level exceptions are not leaked in the
        high-level api.

        On exit, release the connection back to the pool if the stream
        was fully consumed, or close it if reading failed part-way.
        """
        clean_exit = False

        try:
            try:
                yield

            except SocketTimeout as e:
                raise ReadTimeoutError(self._pool, None, "Read timed out.") from e  # type: ignore[arg-type]

            except BaseSSLError as e:
                # SSL errors related to framing/MAC get wrapped and reraised here
                raise SSLError(e) from e

            except (HTTPException, OSError) as e:
                raise ProtocolError(f"Connection broken: {e!r}", e) from e

            # If no exception is thrown, we should avoid cleaning up
            # unnecessarily.
            clean_exit = True
        finally:
            # If we didn't terminate cleanly, the connection is in an
            # unknown state and can't be reused: close it.
            if not clean_exit and self._connection:
                self._connection.close()

            # Once the stream is fully consumed (or reading failed) the
            # connection is no longer blocked by this response, so we
            # should return it back to the pool.
            if not clean_exit or self._stream.is_complete:
                self.release_conn()

    def _raw_read(self, amt: int | None = None, *, read1: bool = False) -> bytes:
        """
        Reads `amt` of (still encoded) body bytes from the HTTP/2 stream.
        """
        with self._error_catcher():
            if self._closed:
                data = b""
                if (
                    amt is not None
                    and amt != 0
                    and self.enforce_content_length
                    and self.length_remaining is not None
                    and self.length_remaining != 0
                ):
                    # Mirror HTTPResponse: an amt-read on a closed response
                    # with an unsatisfied Content-Length is an error, not
                    # a silent truncation.
                    raise IncompleteRead(self._fp_bytes_read, self.length_remaining)
            else:
                data = self._stream.read(amt, read1=read1)
                if data:
                    self._fp_bytes_read += len(data)
                    if self.length_remaining is not None:
                        self.length_remaining -= len(data)
        return data

    # read(), read1() and stream() are kept in sync with HTTPResponse; a
    # follow-up can hoist the shared logic into BaseHTTPResponse on top of
    # the common _raw_read() contract.
    def read(
        self,
        amt: int | None = None,
        decode_content: bool | None = None,
        cache_content: bool = False,
    ) -> bytes:
        """
        Similar to :meth:`~urllib3.response.HTTPResponse.read`, but reads
        from the :class:`HTTP2Stream` this response owns.

        :param amt:
            How much of the content to read. If specified, caching is skipped
            because it doesn't make sense to cache partial content as the full
            response.

        :param decode_content:
            If True, will attempt to decode the body based on the
            'content-encoding' header.

        :param cache_content:
            If True, will save the returned data such that the same result is
            returned despite of the state of the underlying file object. This
            is useful if you want the ``.data`` property to continue working
            after having ``.read()`` the file object. (Overridden if ``amt`` is
            set.)
        """
        self._init_decoder()
        if decode_content is None:
            decode_content = self.decode_content

        if amt and amt < 0:
            # Negative numbers and `None` should be treated the same.
            amt = None
        elif amt is not None:
            cache_content = False

            if (
                self._decoder
                and self._decoder.has_unconsumed_tail
                and len(self._decoded_buffer) < amt
            ):
                decoded_data = self._decode(
                    b"",
                    decode_content,
                    flush_decoder=False,
                    max_length=amt - len(self._decoded_buffer),
                )
                self._decoded_buffer.put(decoded_data)
            if len(self._decoded_buffer) >= amt:
                return self._decoded_buffer.get(amt)

        data = self._raw_read(amt)
        if not cache_content:
            self._uncached_read_occurred = True

        flush_decoder = amt is None or (amt != 0 and not data)

        if (
            not data
            and len(self._decoded_buffer) == 0
            and not (self._decoder and self._decoder.has_unconsumed_tail)
        ):
            return data

        if amt is None:
            data = self._decode(data, decode_content, flush_decoder)
            # It's possible that there is buffered decoded data after a
            # partial read.
            if decode_content and len(self._decoded_buffer) > 0:
                self._decoded_buffer.put(data)
                data = self._decoded_buffer.get_all()

            if cache_content and not self._uncached_read_occurred:
                self._body = data
        else:
            # do not waste memory on buffer when not decoding
            if not decode_content:
                if self._has_decoded_content:
                    raise RuntimeError(
                        "Calling read(decode_content=False) is not supported after "
                        "read(decode_content=True) was called."
                    )
                return data

            decoded_data = self._decode(
                data,
                decode_content,
                flush_decoder,
                max_length=amt - len(self._decoded_buffer),
            )
            self._decoded_buffer.put(decoded_data)

            while len(self._decoded_buffer) < amt and data:
                data = self._raw_read(amt)
                decoded_data = self._decode(
                    data,
                    decode_content,
                    flush_decoder,
                    max_length=amt - len(self._decoded_buffer),
                )
                self._decoded_buffer.put(decoded_data)
            data = self._decoded_buffer.get(amt)

        return data

    def read1(
        self,
        amt: int | None = None,
        decode_content: bool | None = None,
    ) -> bytes:
        """
        Similar to ``http.client.HTTPResponse.read1`` and documented
        in :meth:`io.BufferedReader.read1`, but with an additional parameter:
        ``decode_content``.

        :param amt:
            How much of the content to read.

        :param decode_content:
            If True, will attempt to decode the body based on the
            'content-encoding' header.
        """
        if decode_content is None:
            decode_content = self.decode_content
        if amt and amt < 0:
            # Negative numbers and `None` should be treated the same.
            amt = None
        # try and respond without going to the network
        if self._has_decoded_content:
            if not decode_content:
                raise RuntimeError(
                    "Calling read1(decode_content=False) is not supported after "
                    "read1(decode_content=True) was called."
                )
            if (
                self._decoder
                and self._decoder.has_unconsumed_tail
                and (amt is None or len(self._decoded_buffer) < amt)
            ):
                decoded_data = self._decode(
                    b"",
                    decode_content,
                    flush_decoder=False,
                    max_length=(
                        amt - len(self._decoded_buffer) if amt is not None else None
                    ),
                )
                self._decoded_buffer.put(decoded_data)
            if len(self._decoded_buffer) > 0:
                if amt is None:
                    return self._decoded_buffer.get_all()
                return self._decoded_buffer.get(amt)
        if amt == 0:
            return b""

        data = self._raw_read(amt, read1=True)
        self._uncached_read_occurred = True
        if not decode_content:
            return data

        self._init_decoder()
        while True:
            flush_decoder = not data
            decoded_data = self._decode(
                data, decode_content, flush_decoder, max_length=amt
            )
            self._decoded_buffer.put(decoded_data)
            if decoded_data or flush_decoder:
                break
            data = self._raw_read(8192, read1=True)

        if amt is None:
            return self._decoded_buffer.get_all()
        return self._decoded_buffer.get(amt)

    def stream(
        self, amt: int | None = _READ_CHUNK_SIZE, decode_content: bool | None = None
    ) -> typing.Generator[bytes]:
        """
        A generator wrapper for the read() method. A call will block until
        ``amt`` bytes have been read from the connection or until the
        stream has ended.

        :param amt:
            How much of the content to read. The generator will return up to
            much data per iteration, but may return less. This is particularly
            likely when using compressed data. However, the empty string will
            never be returned.

        :param decode_content:
            If True, will attempt to decode the body based on the
            'content-encoding' header.
        """
        if amt == 0:
            return

        while (
            (not self._closed and not self._stream.is_complete)
            or len(self._decoded_buffer) > 0
            or (self._decoder and self._decoder.has_unconsumed_tail)
        ):
            data = self.read(amt=amt, decode_content=decode_content)

            if data:
                yield data

    @property
    def data(self) -> bytes:
        if self._body is not None:
            return self._body
        return self.read(cache_content=True)

    @property
    def url(self) -> str | None:
        """
        Returns the URL that was the source of this response.
        """
        return self._request_url

    @url.setter
    def url(self, url: str | None) -> None:
        self._request_url = url

    @property
    def connection(self) -> BaseHTTPConnection | None:
        return self._connection

    def tell(self) -> int:
        """
        Obtain the number of bytes pulled over the wire so far. May differ
        from the amount of content returned by :meth:`HTTP2Response.read`
        if bytes are encoded on the wire (e.g, compressed).
        """
        return self._fp_bytes_read

    def get_redirect_location(self) -> None:
        return None

    def release_conn(self) -> None:
        if not self._pool or not self._connection:
            return None

        self._pool._put_conn(self._connection)
        self._connection = None

    def drain_conn(self) -> None:
        """
        Read and discard any remaining HTTP response data in the response
        stream.

        Unread data in the HTTP2Response stream blocks the connection from
        being released back to the pool.
        """
        try:
            while self._raw_read(_READ_CHUNK_SIZE):
                pass
        except (HTTPError, OSError, BaseSSLError, HTTPException):
            pass
        if self._has_decoded_content:
            # `_raw_read` skips decompression, so we should clean up the
            # decoder to avoid keeping unnecessary data in memory.
            self._decoded_buffer = BytesQueueBuffer()
            self._decoder = None

    def read_chunked(
        self,
        amt: int | None = None,
        decode_content: bool | None = None,
    ) -> typing.Iterator[bytes]:
        raise ResponseNotChunked(
            "Response is not chunked. "
            "HTTP/2 does not support chunked transfer encoding."
        )

    def readable(self) -> bool:
        return True

    def shutdown(self) -> None:
        if not self._sock_shutdown:
            raise ValueError("Cannot shutdown socket as self._sock_shutdown is not set")
        if self._connection is None:
            raise RuntimeError(
                "Cannot shutdown as connection has already been released to the pool"
            )
        self._sock_shutdown(socket.SHUT_RD)

    def close(self) -> None:
        self._sock_shutdown = None
        self._closed = True

        # Closing the socket does not reliably interrupt a thread that is
        # already blocked in recv(); use shutdown() to unblock a pending
        # read instead.
        if self._connection:
            self._connection.close()

        if not self.auto_close:
            io.IOBase.close(self)

    @property
    def closed(self) -> bool:
        if not self.auto_close:
            return io.IOBase.closed.__get__(self)  # type: ignore[no-any-return]
        return self._closed or self._stream.is_complete

    def isclosed(self) -> bool:
        return self._closed or self._stream.is_complete
