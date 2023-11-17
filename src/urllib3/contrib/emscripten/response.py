from __future__ import annotations

import json as _json
import typing
from dataclasses import dataclass
from io import BytesIO, IOBase

from ...connection import HTTPConnection
from ...response import HTTPResponse
from ...util.retry import Retry
from .request import EmscriptenRequest


@dataclass
class EmscriptenResponse:
    status_code: int
    headers: dict[str, str]
    body: IOBase | bytes
    request: EmscriptenRequest


class EmscriptenHttpResponseWrapper(HTTPResponse):
    def __init__(
        self,
        internal_response: EmscriptenResponse,
        url: str | None = None,
        connection: HTTPConnection | None = None,
    ):
        self._body = None
        self._response = internal_response
        self._url = url
        self._connection = connection
        super().__init__(
            headers=internal_response.headers,
            status=internal_response.status_code,
            request_url=url,
            version=0,
            reason="",
            decode_content=True,
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
        decode_content: bool | None = None,  # ignored because browser decodes always
        cache_content: bool = False,
    ) -> bytes:
        if not isinstance(self._response.body, IOBase):
            # wrap body in IOStream
            self._response.body = BytesIO(self._response.body)
        if amt is not None:
            # don't cache partial content
            cache_content = False
            return typing.cast(bytes, self._response.body.read(amt))
        else:
            data = self._response.body.read(None)
            if cache_content:
                self._body = data
            return typing.cast(bytes, data)

    def read_chunked(
        self,
        amt: int | None = None,
        decode_content: bool | None = None,
    ) -> typing.Generator[bytes, None, None]:
        while True:
            bytes = self.read(amt, decode_content)
            if not bytes:
                break
            yield bytes

    def release_conn(self) -> None:
        if not self._pool or not self._connection:
            return None

        self._pool._put_conn(self._connection)
        self._connection = None

    def drain_conn(self) -> None:
        self.close()

    @property
    def data(self) -> bytes:
        if self._body:
            return self._body  # type: ignore[return-value]
        else:
            return self.read(cache_content=True)

    def json(self) -> typing.Any:
        """
        Parses the body of the HTTP response as JSON.

        To use a custom JSON decoder pass the result of :attr:`HTTPResponse.data` to the decoder.

        This method can raise either `UnicodeDecodeError` or `json.JSONDecodeError`.

        Read more :ref:`here <json>`.
        """
        data = self.data.decode("utf-8")
        return _json.loads(data)

    def close(self) -> None:
        if isinstance(self._response.body, IOBase):
            self._response.body.close()
