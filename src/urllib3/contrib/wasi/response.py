from __future__ import annotations

import logging
import typing
from dataclasses import dataclass

from ...exceptions import IncompleteRead, InvalidHeader
from ...response import BaseHTTPResponse, BytesQueueBuffer
from .request import WasiRequest

if typing.TYPE_CHECKING:
    from ..._base_connection import BaseHTTPConnection, BaseHTTPSConnection

log = logging.getLogger(__name__)


@typing.runtime_checkable
class ResponseBody(typing.Protocol):
    def read(self, amt: int | None) -> bytes: ...
    def closed(self) -> bool: ...
    def close(self) -> None: ...


class BytesResponseBody(ResponseBody):
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def read(self, amt: int | None) -> bytes:
        if amt is not None:
            result = self.data[self.offset : self.offset + amt]
        else:
            result = self.data[self.offset :]
        self.offset += len(result)
        return result

    def closed(self) -> bool:
        return False

    def close(self) -> None:
        pass


@dataclass
class WasiResponse:
    status_code: int
    headers: dict[str, str]
    body: ResponseBody
    request: WasiRequest


class WasiHttpResponseWrapper(BaseHTTPResponse):
    def __init__(
        self,
        internal_response: WasiResponse,
        preload_content: bool = True,
        decode_content: bool = True,
        enforce_content_length: bool = True,
        connection: BaseHTTPConnection | BaseHTTPSConnection | None = None,
    ):
        self._pool = None  # set by pool class
        self._body = None
        self._response = internal_response
        self._connection = connection
        self._url = internal_response.request.url
        self._decoded_buffer = BytesQueueBuffer()
        super().__init__(
            headers=internal_response.headers,
            status=internal_response.status_code,
            request_url=self._url,
            version=0,
            version_string="HTTP/?",
            reason="",
            decode_content=True,
        )
        self.enforce_content_length = enforce_content_length
        self.length_remaining = self._init_length(internal_response.request.method)

        # If requested, preload the body.
        if preload_content:
            self._body = self.read(decode_content=decode_content)

    @property
    def data(self) -> bytes:
        if self._body:
            return self._body
        else:
            return self.read(cache_content=True)

    @property
    def url(self) -> str | None:
        return self._url

    @url.setter
    def url(self, url: str | None) -> None:
        if url is not None:
            self._url = url

    @property
    def connection(self) -> BaseHTTPConnection | None:
        return self._connection

    def stream(
        self, amt: int | None = 2**16, decode_content: bool | None = None
    ) -> typing.Iterator[bytes]:
        if self._body:
            yield self._body
        else:
            while True:
                data = self.read(amt=amt, decode_content=decode_content)
                if len(data) != 0:
                    yield data
                else:
                    break

    def read(
        self,
        amt: int | None = None,
        decode_content: bool | None = None,
        cache_content: bool = False,
    ) -> bytes:
        if self.closed or self._response.body.closed():
            return b""

        self._init_decoder()
        if decode_content is None:
            decode_content = self.decode_content

        if amt is not None and amt < 0:
            amt = None

        if amt is None:
            data = self._raw_read(None)
            data = self._decode(data, decode_content, True)
            if cache_content:
                self._body = data
            return data
        else:
            # caching is unsupported with partial reads
            cache_content = False

            done = len(self._decoded_buffer) >= amt
            while not done:
                data = self._raw_read(8192)
                body_finished = len(data) == 0
                decoded_data = self._decode(data, decode_content, body_finished)
                self._decoded_buffer.put(decoded_data)
                done = len(self._decoded_buffer) >= amt or body_finished
            return self._decoded_buffer.get(amt)

    def read1(
        self,
        amt: int | None = None,
        decode_content: bool | None = None,
    ) -> bytes:
        return self.read(amt, decode_content)

    def read_chunked(
        self,
        amt: int | None = None,
        decode_content: bool | None = None,
    ) -> typing.Iterator[bytes]:
        return self.stream(amt, decode_content)

    def release_conn(self) -> None:
        if not self._pool or not self._connection:
            return None

        self.drain_conn()
        self._pool._put_conn(self._connection)
        self._connection = None

    def drain_conn(self) -> None:
        self.shutdown()

    def shutdown(self) -> None:
        self._response.body.close()

    def close(self) -> None:
        if not self.closed:
            self.shutdown()
            if self._connection:
                self._connection.close()
                self._connection = None
            self._closed = True

    def _init_length(self, request_method: str | None) -> int | None:
        length: int | None
        content_length: str | None = self.headers.get("content-length")

        if content_length is not None:
            try:
                # RFC 7230 section 3.3.2 specifies multiple content lengths can
                # be sent in a single Content-Length header
                # (e.g. Content-Length: 42, 42). This line ensures the values
                # are all valid ints and that as long as the `set` length is 1,
                # all values are the same. Otherwise, the header is invalid.
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

        else:  # if content_length is None
            length = None

        # Check for responses that shouldn't include a body
        if (
            self.status in (204, 304)
            or 100 <= self.status < 200
            or request_method == "HEAD"
        ):
            length = 0

        return length

    def _raw_read(self, amt: int | None) -> bytes:
        assert amt != 0

        try:
            data = self._response.body.read(amt)
        except Exception as e:
            self.release_conn()
            raise e

        if (
            len(data) == 0
            and self.enforce_content_length
            and self.length_remaining is not None
            and self.length_remaining != 0
        ):
            raise IncompleteRead(0, self.length_remaining)

        if self.length_remaining is not None:
            self.length_remaining -= len(data)

        return data
