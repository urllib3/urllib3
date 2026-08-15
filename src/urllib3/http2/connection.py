from __future__ import annotations

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
from ..connection import (
    BaseProtocolHelper,
    HTTPConnection,
    HTTPSConnection,
    _get_default_user_agent,
)
from ..exceptions import ConnectionError
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


class HTTP2ProtocolHelper(BaseProtocolHelper):
    """Protocol helper class for HTTP/2."""

    name = "http2"

    def __init__(self, conn: HTTPConnection):
        super().__init__(conn)
        self._h2_conn = self._new_h2_conn()
        self._h2_stream: int | None = None
        self._headers: list[tuple[bytes, bytes]] = []

    def _new_h2_conn(self) -> _LockedObject[h2.connection.H2Connection]:
        config = h2.config.H2Configuration(client_side=True)
        return _LockedObject(h2.connection.H2Connection(config=config))

    def putrequest(
        self,
        method: str,
        url: str,
        skip_host: bool = False,
        skip_accept_encoding: bool = False,
    ) -> bool:
        """putrequest
        This deviates from the HTTPConnection method signature since we never need to override
        sending accept-encoding headers or the host header.
        """
        if skip_host:
            raise NotImplementedError("`skip_host` isn't supported")
        if skip_accept_encoding:
            raise NotImplementedError("`skip_accept_encoding` isn't supported")

        self._request_url = url or "/"
        self.conn._validate_path(url)  # type: ignore[attr-defined]

        port = self.conn.port if self.conn.port is not None else 443
        if ":" in self.conn.host:
            authority = f"[{self.conn.host}]:{port}"
        else:
            authority = f"{self.conn.host}:{port}"

        self._headers.append((b":scheme", b"https"))
        self._headers.append((b":method", method.encode()))
        self._headers.append((b":authority", authority.encode()))
        self._headers.append((b":path", url.encode()))

        with self._h2_conn as conn:
            self._h2_stream = conn.get_next_available_stream_id()
        return True

    def putheader(self, header: str, *values: str) -> bool:
        # TODO SKIPPABLE_HEADERS from urllib3 are ignored.
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
            self._headers.append((encoded_header, encoded_value))
        return True

    def endheaders(self, message_body: typing.Any = None) -> bool:
        if self._h2_stream is None:
            raise ConnectionError("Must call `putrequest` first.")

        with self._h2_conn as h2_conn:
            h2_conn.send_headers(
                stream_id=self._h2_stream,
                headers=self._headers,
                end_stream=(message_body is None),
            )
            if data_to_send := h2_conn.data_to_send():
                self.conn.sock.sendall(data_to_send)
        self._headers = []  # Reset headers for the next request.
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
    ) -> None:
        """Send an HTTP/2 request"""
        if chunked:
            # TODO this is often present from upstream.
            # raise NotImplementedError("`chunked` isn't supported with HTTP/2")
            pass

        with self._h2_conn as h2_conn:
            h2_conn.initiate_connection()
            if data_to_send := h2_conn.data_to_send():
                if self.conn.sock is None:
                    self.conn.connect()
                self.conn.sock.sendall(data_to_send)

        if self.conn.sock is not None:
            self.conn.sock.settimeout(self.conn.timeout)

        self.putrequest(method, url)

        headers = headers or {}
        for k, v in headers.items():
            if k.lower() == "transfer-encoding" and v == "chunked":
                continue
            else:
                self.putheader(k, v)

        if b"user-agent" not in dict(self._headers):
            self.putheader("user-agent", _get_default_user_agent())

        if body:
            self.endheaders(message_body=body)
            self.send(body)
        else:
            self.endheaders()

    def getresponse(self) -> HTTPResponse:
        status = None
        data = bytearray()
        with self._h2_conn as h2_conn:
            end_stream = False
            while not end_stream:
                # TODO: Arbitrary read value.
                if received_data := self.conn.sock.recv(65535):
                    events = h2_conn.receive_data(received_data)
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
                            data += event.data
                            h2_conn.acknowledge_received_data(
                                event.flow_controlled_length, event.stream_id
                            )

                        elif isinstance(event, h2.events.StreamEnded):
                            end_stream = True

                if data_to_send := h2_conn.data_to_send():
                    self.conn.sock.sendall(data_to_send)

        assert status is not None
        return HTTP2Response(
            status=status,
            headers=headers,
            request_url=self._request_url,
            data=bytes(data),
            connection=self.conn,
        )

    def send(self, data: typing.Any) -> bool:
        if self._h2_stream is None:
            raise ConnectionError("Must call `putrequest` first.")

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
                    h2_conn.send_data(self._h2_stream, chunk, end_stream=False)
                    if data_to_send := h2_conn.data_to_send():
                        self.conn.sock.sendall(data_to_send)
                h2_conn.end_stream(self._h2_stream)
                return True

            if isinstance(data, str):  # str -> bytes
                data = data.encode()

            try:
                if isinstance(data, bytes):
                    h2_conn.send_data(self._h2_stream, data, end_stream=True)
                    if data_to_send := h2_conn.data_to_send():
                        self.conn.sock.sendall(data_to_send)
                else:
                    for chunk in data:
                        h2_conn.send_data(self._h2_stream, chunk, end_stream=False)
                        if data_to_send := h2_conn.data_to_send():
                            self.conn.sock.sendall(data_to_send)
                    h2_conn.end_stream(self._h2_stream)
            except TypeError:
                raise TypeError(
                    "`data` should be str, bytes, iterable, or file. got %r"
                    % type(data)
                )
        return True

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
        self._h2_stream = None
        self._headers = []


class HTTP2Connection(HTTPSConnection):
    _protocol_helper: HTTP2ProtocolHelper

    def __init__(
        self, host: str, port: int | None = None, **kwargs: typing.Any
    ) -> None:
        super().__init__(host, port, **kwargs)


class HTTP2Response(HTTPResponse):
    # TODO: This is a woefully incomplete response object, but works for non-streaming.
    def __init__(
        self,
        status: int,
        headers: HTTPHeaderDict,
        request_url: str,
        data: bytes,
        decode_content: bool = False,  # TODO: support decoding
        connection: HTTPConnection | None = None,
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
            connection=connection,
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
