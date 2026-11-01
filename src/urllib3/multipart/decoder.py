"""Logic for parsing and decomposing a multipart response body."""

from __future__ import annotations

import email.message
import email.parser
import re

from .. import _collections
from .. import response as _response
from ..exceptions import HTTPError


class ImproperBodyPartContentError(HTTPError):
    pass


class NonMultipartContentTypeError(HTTPError):
    pass


class BodyPart:
    """This provides an easy way to interact with a single part of the body.

    BodyParts expose ``headers`` and raw body bytes in ``data``, like
    :class:`~urllib3.response.HTTPResponse`. Decode ``data`` explicitly when
    text is needed. The encoding argument applies only to header values.
    """

    def __init__(self, content: bytes, *, encoding: str = "utf-8"):
        # Split into header section (if any) and the content
        if content.startswith(b"\r\n"):
            headerbytes, bodybytes = b"", content[2:]
        else:
            headerbytes, separator, bodybytes = content.partition(b"\r\n\r\n")
            if not separator:
                raise ImproperBodyPartContentError(
                    "content does not contain CR-LF-CR-LF"
                )

        #: The bytes containing the body of this part
        self.data = bodybytes
        if headerbytes != b"":
            parsed = email.parser.BytesHeaderParser().parsebytes(headerbytes)
            headers = [
                (name, value.encode("ascii", "surrogateescape").decode(encoding))
                for name, value in parsed.raw_items()
            ]
        else:
            headers = []
        #: The headers associated with this part
        self.headers = _collections.HTTPHeaderDict(headers)


class MultipartDecoder:
    """This parses the full multipart/form-data payload.

    The ``MultipartDecoder`` object parses the multipart payload of
    a bytestring into a tuple of ``BodyPart`` objects.

    The basic usage is::

        import urllib3
        from urllib3.multipart import MultipartDecoder

        response = urllib3.request("GET", url)
        decoder = MultipartDecoder.from_response(response)
        for part in decoder.parts:
            print(part.headers['content-type'])

    If the multipart content is not from a response, basic usage is::

        from urllib3.multipart import MultipartDecoder

        decoder = MultipartDecoder(content, content_type=content_type)
        for part in decoder.parts:
            print(part.headers['content-type'])

    For both these usages, there is an optional ``encoding`` parameter. This is
    a string, which is the name of the unicode codec to use (default is
    ``'utf-8'``).
    """

    def __init__(self, content: bytes, *, content_type: str, encoding: str = "utf-8"):
        #: Original Content-Type header
        self.content_type = content_type
        #: Response body encoding
        self.encoding = encoding
        #: Parsed parts of the multipart response body
        self.parts: tuple[BodyPart, ...] = tuple()
        self._find_boundary()
        self._parse_body(content)

    def _find_boundary(self) -> None:
        message = email.message.Message()
        message["Content-Type"] = self.content_type
        if message.get_content_maintype() != "multipart":
            raise NonMultipartContentTypeError(
                f"Unexpected MIME type in Content-Type: {self.content_type!r}"
            )
        boundary = message.get_boundary()
        if not boundary:
            raise ImproperBodyPartContentError("Missing multipart boundary")
        self.boundary = boundary.encode(self.encoding)

    def _parse_body(self, content: bytes) -> None:
        delimiter = re.compile(
            rb"(?:\A|\r\n)--"
            + re.escape(self.boundary)
            + rb"(?P<closing>--)?[ \t]*(?:\r\n|\Z)"
        )
        parts: list[BodyPart] = []
        start = None
        for match in delimiter.finditer(content):
            if start is not None:
                parts.append(
                    BodyPart(content[start : match.start()], encoding=self.encoding)
                )
            if match.group("closing"):
                self.parts = tuple(parts)
                return
            start = match.end()
        raise ImproperBodyPartContentError("Missing closing multipart boundary")

    @classmethod
    def from_response(
        cls,
        response: _response.HTTPResponse,
        *,
        encoding: str = "utf-8",
    ) -> MultipartDecoder:
        content = response.data
        content_type = response.headers.get("content-type", None)
        if content_type is None:
            raise ValueError("Cannot determine content-type header from response")
        return cls(content, content_type=content_type, encoding=encoding)
