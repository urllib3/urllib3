"""Logic for parsing and decomposing a multipart response body."""

from __future__ import annotations

import email.parser
import re
import typing

from .. import _collections
from .. import response as _response
from ..exceptions import HTTPError
from ..util.util import to_bytes


class ImproperBodyPartContentError(HTTPError):
    """Raised when a body part does not contain a header/body separator."""


class NonMultipartContentTypeError(HTTPError):
    """Raised when Content-Type is not a multipart media type."""


def _header_parser(headers: bytes) -> typing.Sequence[tuple[str, str]]:
    parser = email.parser.BytesHeaderParser()
    message = parser.parsebytes(headers + b"\r\n\r\n")
    return list(message.raw_items())


class BodyPart:
    """This provides an easy way to interact with a single part of the body.

    Body parts expose their headers and raw body bytes, similarly to
    :class:`urllib3.response.HTTPResponse`.
    """

    def __init__(self, content: bytes, *, encoding: str = "utf-8"):
        # Split into header section (if any) and the content
        headerbytes, separator, bodybytes = content.partition(b"\r\n\r\n")
        if b"\r\n\r\n" != separator:
            raise ImproperBodyPartContentError("content does not contain CR-LF-CR-LF")

        #: The bytes containing the body of this part.
        self.data = bodybytes
        if headerbytes != b"":
            headers = _header_parser(headerbytes.lstrip())
        else:
            headers = []
        #: The headers associated with this part
        self.headers = _collections.HTTPHeaderDict(headers)


class MultipartDecoder:
    """This parses the full multipart/form-data payload.

    The ``MultipartDecoder`` object parses the multipart payload of
    a bytestring into a tuple of ``Response``-like ``BodyPart`` objects.

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

    ``content_type`` and ``encoding`` are keyword-only arguments.
    """

    def __init__(self, content: bytes, *, content_type: str, encoding: str = "utf-8"):
        #: Original Content-Type header
        self.content_type = content_type
        #: Response body encoding
        self.encoding = encoding
        #: Parsed parts of the multipart response body
        self.parts: tuple[BodyPart, ...] = ()
        self.boundary: bytes
        self._find_boundary()
        self._parse_body(content)

    def _find_boundary(self) -> None:
        if not self.content_type.strip():
            raise NonMultipartContentTypeError("Content-Type must not be empty")

        boundary_parameter = re.search(
            r"(?:^|;)\s*boundary\s*=\s*", self.content_type, flags=re.IGNORECASE
        )
        if boundary_parameter is not None:
            raw_value = self.content_type[boundary_parameter.end() :]
            if (
                raw_value.startswith('"')
                and re.match(r'^"(?:[^"\\]|\\.)*"', raw_value) is None
            ):
                raise NonMultipartContentTypeError(
                    f"Unterminated boundary parameter in Content-Type: "
                    f"{self.content_type!r}"
                )

        parser = email.parser.HeaderParser()
        message = parser.parsestr(f"Content-Type: {self.content_type}\n\n")
        mime_type = message.get_content_type()
        if mime_type.split("/", 1)[0].lower() != "multipart":
            raise NonMultipartContentTypeError(
                f"Unexpected MIME type in Content-Type: {mime_type!r}"
            )
        boundary = message.get_param("boundary", header="Content-Type")
        if isinstance(boundary, str) and boundary:
            self.boundary = to_bytes(boundary, self.encoding)
            return
        raise NonMultipartContentTypeError(
            f"No boundary parameter found in Content-Type: {self.content_type!r}"
        )

    def _parse_body(self, content: bytes) -> None:
        delimiter = re.compile(
            rb"(?:^|\r\n)--"
            + re.escape(self.boundary)
            + rb"(?P<close>--)?[ \t]*(?:\r\n|$)"
        )
        matches = list(delimiter.finditer(content))
        parts: list[BodyPart] = []
        for index, match in enumerate(matches):
            if match.group("close") is not None:
                break
            if index + 1 >= len(matches):
                break
            next_match = matches[index + 1]
            part_data = content[match.end() : next_match.start()]
            parts.append(BodyPart(part_data, encoding=self.encoding))
        self.parts = tuple(parts)

    @classmethod
    def from_response(
        cls,
        response: _response.HTTPResponse,
        encoding: str = "utf-8",
    ) -> MultipartDecoder:
        content = response.data
        content_type = response.headers.get("content-type", None)
        if content_type is None:
            raise ValueError("Cannot determine Content-Type header from response")
        return cls(content, content_type=content_type, encoding=encoding)
