from dataclasses import dataclass
from io import IOBase,BytesIO
from itertools import takewhile
import typing

from ...connection import HTTPConnection
from ...response import HTTPResponse
from ...util.retry import Retry

@dataclass
class EmscriptenResponse:
    status_code: int
    headers: dict[str, str]
    body: IOBase | bytes


class EmscriptenHttpResponseWrapper(HTTPResponse):
    def __init__(self, internal_response: EmscriptenResponse, url: str = None, connection=None):
        self._response = internal_response
        self._url = url
        self._connection = connection
        super().__init__(
            headers=internal_response.headers,
            status=internal_response.status_code,
            request_url=url,
            version=0,
            reason="",
            decode_content=True
        )

    @property
    def url(self) -> str | None:
        return self._url

    @url.setter
    def url(self, url: str | None) -> None:
        self._url = url

    @property
    def connection(self) -> HTTPConnection | None:
        return self._connection

    @property
    def retries(self) -> Retry | None:
        return self._retries

    @retries.setter
    def retries(self, retries: Retry | None) -> None:
        # Override the request_url if retries has a redirect location.
        if retries is not None and retries.history:
            self.url = retries.history[-1].redirect_location
        self._retries = retries

    def read(
        self,
        amt: int | None = None,
        decode_content: bool | None = None,
        cache_content: bool = False,
    ) -> bytes:
        if not isinstance(self._response.body,IOBase):
            # wrap body in IOStream
            self._response.body=BytesIO(self._response.body)
        return self._response.body.read(amt)

    def read_chunked(
        self,
        amt: int | None = None,
        decode_content: bool | None = None,
    ) -> typing.Iterator[bytes]:
        return self.read(amt,decode_content)

    def release_conn(self) -> None:
        if not self._pool or not self._connection:
            return None

        self._pool._put_conn(self._connection)
        self._connection = None

    def drain_conn(self) -> None:
        self.close()

    def close(self) -> None:
        if isinstance(self._response.body,IOBase):
            self._response.body.close()

