"""Logic for parsing and decomposing a multipart response body."""
from __future__ import annotations

import email.parser
import typing

from .. import _collections
from .. import response as _response
from .encoder import encode_with


class ImproperBodyPartContentError(Exception):
    pass


class NonMultipartContentTypeError(Exception):
    pass


def _header_parser(headers: bytes, encoding: str) -> typing.Sequence[tuple[str, str]]:
    string = headers.decode(encoding)
    items = email.parser.HeaderParser().parsestr(string).items()
    items = typing.cast(typing.List[typing.Tuple[str, str]], items)
    return items


class BodyPart:
    """This provides an easy way to interact with a single part of the body.

    BodyParts include the headers in the part of the body as well as the body
    content as bytes and optional converted to text based on the provided
    encoding.

    The encoding may be overridden by specifying ``part.encoding = '...'``.
    """

    def __init__(self, content: bytes, encoding: str):
        #: Encoding used for the body part to decode body and headers
        self.encoding = encoding
        headers: dict[str, str] = {}
        # Split into header section (if any) and the content
        headerbytes, separator, bodybytes = content.partition(b"\r\n\r\n")
        if b"\r\n\r\n" != separator:
            raise ImproperBodyPartContentError("content does not contain CR-LF-CR-LF")

        #: The bytes containing the body of this part
        self.content = bodybytes
        if headerbytes != b"":
            headers.update(_header_parser(headerbytes.lstrip(), encoding))
        #: The headers associated with this part
        self.headers = _collections.HTTPHeaderDict(headers)

    @property
    def text(self) -> str:
        """Content of the ``BodyPart`` in unicode."""
        return self.content.decode(self.encoding)


MD = typing.TypeVar("MD", bound="MultipartDecoder")


class MultipartDecoder:
    """This parses the full multipart/form-data payload.

    The ``MultipartDecoder`` object parses the multipart payload of
    a bytestring into a tuple of ``Response``-like ``BodyPart`` objects.

    The basic usage is::

        import requests
        from requests_toolbelt import MultipartDecoder

        response = request.get(url)
        decoder = MultipartDecoder.from_response(response)
        for part in decoder.parts:
            print(part.headers['content-type'])

    If the multipart content is not from a response, basic usage is::

        from requests_toolbelt import MultipartDecoder

        decoder = MultipartDecoder(content, content_type)
        for part in decoder.parts:
            print(part.headers['content-type'])

    For both these usages, there is an optional ``encoding`` parameter. This is
    a string, which is the name of the unicode codec to use (default is
    ``'utf-8'``).
    """

    def __init__(self, content: bytes, content_type: str, encoding: str = "utf-8"):
        #: Original Content-Type header
        self.content_type = content_type
        #: Response body encoding
        self.encoding = encoding
        #: Parsed parts of the multipart response body
        self.parts: tuple[BodyPart, ...] = tuple()
        self._find_boundary()
        self._parse_body(content)

    def _find_boundary(self) -> None:
        ct_info = tuple(x.strip() for x in self.content_type.split(";"))
        mimetype = ct_info[0]
        if mimetype.split("/")[0].lower() != "multipart":
            raise NonMultipartContentTypeError(
                f"Unexpected mimetype in content-type: '{mimetype}'"
            )
        for item in ct_info[1:]:
            attr, _, value = item.partition("=")
            if attr.lower() == "boundary":
                self.boundary = encode_with(value.strip('"'), self.encoding)

    @staticmethod
    def _fix_first_part(part: bytes, boundary_marker: bytes) -> bytes:
        bm_len = len(boundary_marker)
        if boundary_marker == part[:bm_len]:
            return part[bm_len:]
        else:
            return part

    def _parse_body(self, content: bytes) -> None:
        boundary = b"--" + self.boundary

        def body_part(part: bytes) -> BodyPart:
            fixed = MultipartDecoder._fix_first_part(part, boundary)
            return BodyPart(fixed, self.encoding)

        def test_part(part: bytes) -> bool:
            return (
                part != b""
                and part != b"\r\n"
                and part[:4] != b"--\r\n"
                and part != b"--"
            )

        parts = content.split(b"\r\n" + boundary)
        self.parts = tuple(body_part(x) for x in parts if test_part(x))

    @classmethod
    def from_response(
        cls: type[MD],
        response: _response.HTTPResponse,
        encoding: str = "utf-8",
    ) -> MD:
        content = response.data
        content_type = response.headers.get("content-type", None)
        if content_type is None:
            raise ValueError("Cannot determine content-type header from response")
        return cls(content, content_type, encoding)
