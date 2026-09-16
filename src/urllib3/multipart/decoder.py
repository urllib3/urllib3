"""Logic for parsing and decomposing a multipart response body."""

from __future__ import annotations

import email.message
import email.parser
import re

from .. import _collections
from .. import response as _response
from ..exceptions import HTTPError


class ImproperBodyPartContentError(HTTPError):
    """A multipart body or part is malformed."""


class NonMultipartContentTypeError(HTTPError):
    """The Content-Type does not specify multipart data and a boundary."""


class BodyPart:
    """A decoded part, with raw body bytes in ``data`` and an HTTPHeaderDict.

    Duplicate headers are retained. Decode ``data`` explicitly if the part's
    media type and character encoding are known.
    """

    def __init__(self, content: bytes) -> None:
        if content.startswith(b"\r\n"):
            headerbytes, bodybytes = b"", content[2:]
        else:
            headerbytes, separator, bodybytes = content.partition(b"\r\n\r\n")
            if not separator:
                raise ImproperBodyPartContentError(
                    "content does not contain CR-LF-CR-LF"
                )
        self.data = bodybytes
        parsed = email.parser.BytesHeaderParser().parsebytes(headerbytes)
        self.headers = _collections.HTTPHeaderDict()
        for name, value in parsed.raw_items():
            # Match HTTPResponse's lossless Latin-1 decoding of header bytes.
            value = value.encode("ascii", "surrogateescape").decode("latin-1")
            self.headers.add(name, value)


class MultipartDecoder:
    """Parse a complete multipart response into a tuple of :class:`~urllib3.multipart.decoder.BodyPart`.

    .. code-block:: python

        response = urllib3.request("GET", url)
        decoder = MultipartDecoder.from_response(response)
        for part in decoder.parts:
            print(part.headers.get("Content-Type"), part.data)

    To parse bytes directly, use ``MultipartDecoder(content,
    content_type="multipart/mixed; boundary=example")``. Unlike the encoder,
    the decoder buffers the complete response.
    """

    def __init__(self, content: bytes, *, content_type: str) -> None:
        self.content_type = content_type
        self.boundary = self._find_boundary()
        self.parts = self._parse_body(content)

    def _find_boundary(self) -> bytes:
        mime_type = self.content_type.partition(";")[0].strip()
        if not re.fullmatch(r"multipart/[!#$%&'*+.^_`|~0-9a-z-]+", mime_type, re.I):
            raise NonMultipartContentTypeError(
                f"Unexpected MIME type in Content-Type: {mime_type!r}"
            )
        message = email.message.Message()
        message["Content-Type"] = self.content_type
        boundary = message.get_boundary()
        if not boundary or "\r" in boundary or "\n" in boundary:
            raise NonMultipartContentTypeError("Missing or invalid multipart boundary")
        try:
            return boundary.encode("ascii")
        except UnicodeEncodeError as exc:
            raise NonMultipartContentTypeError(
                "Multipart boundary must be ASCII"
            ) from exc

    def _parse_body(self, content: bytes) -> tuple[BodyPart, ...]:
        # A boundary prefix in the body is not a delimiter. Only complete
        # delimiter lines count; preamble and epilogue are ignored.
        delimiter = re.compile(
            rb"(?:\A|\r\n)--" + re.escape(self.boundary) + rb"(--)?[ \t]*(?:\r\n|\Z)"
        )
        parts: list[BodyPart] = []
        start = None
        for match in delimiter.finditer(content):
            if start is not None:
                parts.append(BodyPart(content[start : match.start()]))
            if match.group(1):
                return tuple(parts)
            start = match.end()
        raise ImproperBodyPartContentError("Multipart body has no closing boundary")

    @classmethod
    def from_response(cls, response: _response.HTTPResponse) -> MultipartDecoder:
        content_type = response.headers.get("Content-Type")
        if content_type is None:
            raise ValueError("Cannot determine Content-Type header from response")
        return cls(response.data, content_type=content_type)
