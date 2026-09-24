from __future__ import annotations

import io
import typing
from email import policy
from email.errors import MultipartInvariantViolationDefect, UndecodableBytesDefect
from email.parser import BytesHeaderParser

from .._collections import HTTPHeaderDict
from ..exceptions import HTTPError

if typing.TYPE_CHECKING:
    from ..response import BaseHTTPResponse


class ImproperBodyPartContentError(HTTPError):
    """A multipart body part could not be parsed."""


class NonMultipartContentTypeError(HTTPError):
    """The response Content-Type is not multipart."""


def _validate_boundary(boundary: str) -> bytes:
    encoded = boundary.encode("ascii")
    if (
        not encoded
        or len(encoded) > 70
        or encoded[-1:] == b" "
        or any(byte < 32 or byte == 127 for byte in encoded)
    ):
        raise NonMultipartContentTypeError("Invalid multipart boundary")
    return encoded


class BodyPart:
    """A decoded multipart body part with a file-like read cursor.

    :ivar headers: Read-only part headers. The returned ``HTTPHeaderDict`` is mutable.
    :ivar data: Read-only complete part body.
    """

    def __init__(self, headers: HTTPHeaderDict, data: bytes) -> None:
        self._headers = headers
        self._buffer = io.BytesIO(bytes(data))

    @property
    def headers(self) -> HTTPHeaderDict:
        return self._headers

    @property
    def data(self) -> bytes:
        return self._buffer.getvalue()

    def read(self, size: int | None = -1) -> bytes:
        if size is not None and size < -1:
            raise ValueError("size must be -1 or a non-negative integer")
        return self._buffer.read(size)

    def peek(self, size: int | None = -1) -> bytes:
        position = self._buffer.tell()
        try:
            return self.read(size)
        finally:
            self._buffer.seek(position)

    def tell(self) -> int:
        return self._buffer.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._buffer.seek(offset, whence)


class MultipartDecoder:
    """Decode a ``multipart/*`` response body into :class:`BodyPart` objects."""

    def __init__(
        self, content: bytes | bytearray | memoryview, *, content_type: str
    ) -> None:
        self.parts: tuple[BodyPart, ...] = tuple(
            self._parse(bytes(content), content_type)
        )

    @classmethod
    def from_response(cls, response: BaseHTTPResponse) -> MultipartDecoder:
        content_type = response.headers.get("Content-Type")
        if content_type is None:
            raise NonMultipartContentTypeError("Missing Content-Type header")
        return cls(response.data, content_type=content_type)

    @staticmethod
    def _content_type_boundary(content_type: str) -> bytes:
        if not isinstance(content_type, str):
            raise NonMultipartContentTypeError("Invalid multipart Content-Type")
        if any(char in content_type for char in "\r\n\x00"):
            raise NonMultipartContentTypeError("Invalid multipart Content-Type")
        try:
            raw = content_type.encode("ascii")
        except UnicodeEncodeError as e:
            raise NonMultipartContentTypeError(
                "Multipart Content-Type must contain only ASCII characters"
            ) from e
        message = BytesHeaderParser(policy=policy.default).parsebytes(
            b"Content-Type: " + raw + b"\r\n\r\n"
        )
        header = message["Content-Type"]
        if (
            set(map(type, message.defects)) - {MultipartInvariantViolationDefect}
            or header is None
            or header.defects
        ):
            raise NonMultipartContentTypeError("Malformed multipart Content-Type")
        if message.get_content_maintype() != "multipart":
            raise NonMultipartContentTypeError("Content-Type is not multipart")
        boundary = header.params.get("boundary")
        if not isinstance(boundary, str):
            raise NonMultipartContentTypeError("Missing multipart boundary")
        return _validate_boundary(boundary)

    @classmethod
    def _parse(cls, content: bytes, content_type: str) -> list[BodyPart]:
        boundary = cls._content_type_boundary(content_type)
        marker = b"--" + boundary
        delimiter = _find_delimiter(content, marker, 0)
        if delimiter is None:
            raise ImproperBodyPartContentError("Missing multipart boundary delimiter")
        _, after, closing = delimiter
        if closing:
            return []

        parts = []
        while True:
            delimiter = _find_delimiter(content, marker, after)
            if delimiter is None:
                raise ImproperBodyPartContentError("Missing closing multipart boundary")
            next_start, next_after, closing = delimiter
            if content[after : after + 2] == b"\r\n":
                header_bytes = b""
                body_start = after + 2
            else:
                header_end = content.find(b"\r\n\r\n", after, next_start)
                if header_end == -1:
                    raise ImproperBodyPartContentError(
                        "Missing multipart part header separator"
                    )
                header_bytes = content[after:header_end]
                body_start = header_end + 4
            header_lines = header_bytes.replace(b"\r\n", b"")
            if b"\r" in header_lines or b"\n" in header_lines:
                raise ImproperBodyPartContentError(
                    "Malformed multipart part header line ending"
                )
            message = BytesHeaderParser(policy=policy.default).parsebytes(
                header_bytes + b"\r\n\r\n"
            )
            if set(map(type, message.defects)) - {
                MultipartInvariantViolationDefect
            } or any(
                not isinstance(defect, UndecodableBytesDefect)
                for header in message.values()
                for defect in header.defects
            ):
                raise ImproperBodyPartContentError("Malformed multipart part headers")
            for _, raw_value in message.raw_items():
                try:
                    raw_value.encode("ascii", "surrogateescape").decode("utf-8")
                except UnicodeError as e:
                    raise ImproperBodyPartContentError(
                        "Multipart part headers must contain valid UTF-8"
                    ) from e
            headers = HTTPHeaderDict()
            for name, value in message.items():
                parsed_value = str(value)
                if any(
                    (ord(char) < 32 and char != "\t") or ord(char) == 127
                    for char in parsed_value
                ):
                    raise ImproperBodyPartContentError(
                        "Multipart part headers contain invalid control characters"
                    )
                headers.add(name, parsed_value)
            parts.append(BodyPart(headers, content[body_start : next_start - 2]))
            if closing:
                return parts
            after = next_after


def _find_delimiter(
    content: bytes, marker: bytes, start: int
) -> tuple[int, int, bool] | None:
    position = start
    while True:
        position = content.find(marker, position)
        if position == -1:
            return None
        if position and content[position - 2 : position] != b"\r\n":
            position += 1
            continue
        after = position + len(marker)
        closing = content[after : after + 2] == b"--"
        if closing:
            after += 2
        whitespace_end = after
        while whitespace_end < len(content) and content[whitespace_end] in b" \t":
            whitespace_end += 1
        if whitespace_end == len(content) and closing:
            return position, whitespace_end, True
        if content[whitespace_end : whitespace_end + 2] == b"\r\n":
            return position, whitespace_end + 2, closing
        position += 1
