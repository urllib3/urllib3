from __future__ import annotations

import io
import typing

from .._collections import HTTPHeaderDict
from ..exceptions import UnrewindableBodyError
from ..fields import _TYPE_FIELD_BODY, RequestField
from ..filepost import _TYPE_FIELDS, choose_boundary, iter_field_objects

_BOUNDARY_PARAMETER_QUOTE_CHARS = frozenset("'*()<>@,;:\\\"/[]?= ")
_DEFAULT_BLOCKSIZE = 16384


def _validate_boundary(boundary: str) -> None:
    try:
        encoded = boundary.encode("ascii")
    except UnicodeEncodeError as e:
        raise ValueError("Multipart boundary must contain only ASCII characters") from e
    if (
        not encoded
        or len(encoded) > 70
        or encoded[-1:] == b" "
        or any(byte < 32 or byte == 127 for byte in encoded)
    ):
        raise ValueError("Invalid multipart boundary")


def _format_boundary(boundary: str) -> str:
    if not any(char in _BOUNDARY_PARAMETER_QUOTE_CHARS for char in boundary):
        return boundary
    return '"' + boundary.replace("\\", "\\\\").replace('"', '\\"') + '"'


class _Body:
    def __init__(self, data: object) -> None:
        self.data: bytes | typing.BinaryIO
        self.start: int | None = None
        self.length: int | None
        self.position = 0
        self.checked = False

        if isinstance(data, int):
            data = str(data)
        if isinstance(data, str):
            self.data = data.encode("utf-8")
            self.length = len(self.data)
        elif isinstance(data, (bytes, bytearray, memoryview)):
            self.data = bytes(data)
            self.length = len(self.data)
        elif hasattr(data, "read"):
            self.data = typing.cast(typing.BinaryIO, data)
            try:
                start = self.data.tell()
            except (AttributeError, OSError, ValueError):
                self.length = None
            else:
                if not isinstance(start, int):
                    raise TypeError("Multipart stream tell() must return an integer")
                try:
                    self.data.seek(0, 2)
                    end = self.data.tell()
                except (AttributeError, OSError, ValueError):
                    try:
                        current = self.data.tell()
                    except (AttributeError, OSError, ValueError):
                        current = None
                    if current is not None and not isinstance(current, int):
                        _restore_stream(self.data, start)
                        raise TypeError(
                            "Multipart stream tell() must return an integer"
                        )
                    if current != start:
                        _restore_stream(self.data, start)
                    self.length = None
                else:
                    if not isinstance(end, int):
                        _restore_stream(self.data, start)
                        raise TypeError(
                            "Multipart stream tell() must return an integer"
                        )
                    _restore_stream(self.data, start)
                    if end < start:
                        raise ValueError("Multipart stream has an invalid length")
                    self.start = start
                    self.length = end - start
        else:
            raise TypeError(
                "Multipart field data must be bytes, str, int, or a binary stream"
            )

    @property
    def rewindable(self) -> bool:
        return self.start is not None

    def reset(self) -> None:
        if not isinstance(self.data, bytes):
            if self.start is None:
                raise UnrewindableBodyError("Unable to rewind multipart body part")
            try:
                self.data.seek(self.start)
            except (AttributeError, OSError, ValueError) as e:
                raise UnrewindableBodyError(
                    "Unable to rewind multipart body part"
                ) from e
        self.position = 0
        self.checked = False

    def read(self, size: int) -> bytes:
        if isinstance(self.data, bytes):
            result = self.data[self.position : self.position + size]
        else:
            if self.start is not None and self.position == 0:
                self.data.seek(self.start)
            result = self.data.read(size)
            if not isinstance(result, bytes):
                raise TypeError("Multipart streams must return bytes")
            if len(result) > size:
                raise OSError("Multipart stream returned more data than requested")

        if self.length is not None:
            remaining = self.length - self.position
            if not result and remaining:
                raise OSError("Multipart stream ended before its expected length")

        self.position += len(result)
        return result

    def finished(self) -> bool:
        return self.length is not None and self.position == self.length

    def check_end(self) -> None:
        if self.checked or self.length is None or isinstance(self.data, bytes):
            return
        extra = self.data.read(1)
        if not isinstance(extra, bytes):
            raise TypeError("Multipart streams must return bytes")
        if extra:
            raise OSError("Multipart stream grew while it was being read")
        self.checked = True


class Part:
    """A multipart body part with buffered ``read()`` and ``peek()`` methods.

    ``headers`` must include the blank line separating them from ``body``.
    Reads are bounded for streams, including when ``peek()`` is used.
    """

    def __init__(
        self, headers: bytes | bytearray | memoryview, body: _TYPE_FIELD_BODY
    ) -> None:
        if not isinstance(headers, (bytes, bytearray, memoryview)):
            raise TypeError("Multipart part headers must be bytes-like")
        self._headers = bytes(headers)
        self._body = _Body(body)
        self._header_offset = 0
        self._body_finished = False
        self._peeked = bytearray()

    @property
    def content_length(self) -> int | None:
        if self._body.length is None:
            return None
        return len(self._headers) + self._body.length

    def _reset(self) -> None:
        self._body.reset()
        self._header_offset = 0
        self._body_finished = False
        self._peeked.clear()

    def _read_unbuffered(self, size: int) -> bytes:
        result = bytearray()
        if self._header_offset < len(self._headers):
            chunk = self._headers[self._header_offset : self._header_offset + size]
            self._header_offset += len(chunk)
            result.extend(chunk)

        remaining = size - len(result)
        if not self._body_finished and self._body.finished():
            self._body.check_end()
            self._body_finished = True
        elif remaining and not self._body_finished:
            body_size = remaining
            if self._body.length is not None:
                body_size = min(body_size, self._body.length - self._body.position)
            chunk = self._body.read(body_size)
            result.extend(chunk)
            if self._body.finished():
                self._body.check_end()
                self._body_finished = True
            elif not chunk:
                self._body_finished = True
        return bytes(result)

    def read(self, size: int | None = -1) -> bytes:
        if size is None or size < 0:
            buffer = io.BytesIO()
            if self._peeked:
                buffer.write(self._peeked)
                self._peeked.clear()
            while chunk := self._read_unbuffered(_DEFAULT_BLOCKSIZE):
                buffer.write(chunk)
            return buffer.getvalue()
        if size == 0:
            return b""

        result = bytearray(self._peeked[:size])
        del self._peeked[:size]
        while len(result) < size:
            chunk = self._read_unbuffered(size - len(result))
            if not chunk:
                break
            result.extend(chunk)
        return bytes(result)

    def peek(self, size: int = 0) -> bytes:
        if size < 0:
            size = 0
        target = size or _DEFAULT_BLOCKSIZE
        while len(self._peeked) < target:
            chunk = self._read_unbuffered(target - len(self._peeked))
            if not chunk:
                break
            self._peeked.extend(chunk)
        return bytes(self._peeked)


class _EncodedPart:
    def __init__(self, field: RequestField, boundary: bytes) -> None:
        self.prefix = b"--" + boundary + b"\r\n"
        self.part = Part(field.render_headers().encode("utf-8"), field.data)
        self.suffix = b"\r\n"
        self.phase = 0
        self.offset = 0

    @property
    def body(self) -> _Body:
        return self.part._body

    @property
    def content_length(self) -> int | None:
        if self.part.content_length is None:
            return None
        return len(self.prefix) + self.part.content_length + len(self.suffix)

    def reset(self) -> None:
        self.part._reset()
        self.phase = 0
        self.offset = 0

    def read(self, size: int) -> bytes:
        while self.phase < 3:
            if self.phase == 0:
                current = self.prefix
            elif self.phase == 1:
                data = self.part.read(size)
                if not data:
                    self.phase = 2
                    continue
                return data
            else:
                current = self.suffix

            result = current[self.offset : self.offset + size]
            self.offset += len(result)
            if self.offset == len(current):
                self.offset = 0
                self.phase += 1
            return result
        return b""


class MultipartEncoder:
    """Stream fields as a ``multipart/form-data`` request body.

    ``boundary`` and ``blocksize`` control the MIME delimiter and default read size.
    ``content_length`` is ``None`` when a field cannot be measured.
    """

    def __init__(
        self,
        fields: _TYPE_FIELDS,
        *,
        boundary: str | None = None,
        blocksize: int = _DEFAULT_BLOCKSIZE,
    ) -> None:
        if not isinstance(blocksize, int) or isinstance(blocksize, bool):
            raise TypeError("blocksize must be an integer")
        if blocksize <= 0:
            raise ValueError("blocksize must be positive")
        self._boundary = choose_boundary() if boundary is None else boundary
        _validate_boundary(self._boundary)
        self._blocksize = blocksize
        boundary_bytes = self._boundary.encode("ascii")
        self._parts = [
            _EncodedPart(field, boundary_bytes) for field in iter_field_objects(fields)
        ]
        streams: set[int] = set()
        for part in self._parts:
            if not isinstance(part.body.data, bytes):
                identity = id(part.body.data)
                if not part.body.rewindable and identity in streams:
                    raise ValueError(
                        "A non-seekable multipart stream cannot be used twice"
                    )
                streams.add(identity)
        self._closing = b"--" + boundary_bytes + b"--\r\n"
        self._part_index = 0
        self._closing_offset = 0
        self._position = 0
        lengths = [part.content_length for part in self._parts]
        self._content_length = (
            None
            if any(length is None for length in lengths)
            else sum(typing.cast(int, length) for length in lengths)
            + len(self._closing)
        )

    @property
    def boundary(self) -> str:
        return self._boundary

    @property
    def blocksize(self) -> int:
        return self._blocksize

    @property
    def content_length(self) -> int | None:
        return self._content_length

    @property
    def content_type(self) -> str:
        return f"multipart/form-data; boundary={_format_boundary(self._boundary)}"

    @property
    def headers(self) -> HTTPHeaderDict:
        headers = HTTPHeaderDict({"Content-Type": self.content_type})
        if self.content_length is not None:
            headers["Content-Length"] = str(self.content_length)
        return headers

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = 0) -> int:
        if offset != 0 or whence != 0:
            raise OSError("MultipartEncoder only supports seek(0, 0)")
        errors: list[UnrewindableBodyError] = []
        for part in self._parts:
            try:
                part.reset()
            except UnrewindableBodyError as e:
                errors.append(e)
        if errors:
            raise UnrewindableBodyError("Unable to rewind multipart body") from errors[
                0
            ]
        self._part_index = 0
        self._closing_offset = 0
        self._position = 0
        return 0

    def read(self, size: int | None = -1) -> bytes:
        if size is None:
            size = -1
        if size < -1:
            raise ValueError("size must be -1 or a non-negative integer")
        if size == 0:
            return b""
        if size == -1:
            buffer = io.BytesIO()
            while True:
                chunk = self.read(self._blocksize)
                if not chunk:
                    return buffer.getvalue()
                buffer.write(chunk)

        result = bytearray()
        while len(result) < size:
            remaining = size - len(result)
            if self._part_index < len(self._parts):
                chunk = self._parts[self._part_index].read(remaining)
                if not chunk:
                    self._part_index += 1
                    continue
            else:
                chunk = self._closing[
                    self._closing_offset : self._closing_offset + remaining
                ]
                self._closing_offset += len(chunk)
            if not chunk:
                break
            result.extend(chunk)
        self._position += len(result)
        return bytes(result)

    def __iter__(self) -> MultipartEncoder:
        return self

    def __next__(self) -> bytes:
        chunk = self.read(self._blocksize)
        if not chunk:
            raise StopIteration
        return chunk


def _restore_stream(stream: typing.BinaryIO, position: int) -> None:
    try:
        stream.seek(position)
    except (AttributeError, OSError, ValueError) as e:
        raise OSError("Unable to restore multipart stream position") from e
