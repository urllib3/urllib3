from __future__ import annotations

import io
import operator
import typing

from ._collections import HTTPHeaderDict
from .fields import RequestField


class _BodyReader(io.RawIOBase):
    """Adapt a caller-owned binary stream without taking ownership of it."""

    def __init__(
        self, stream: typing.BinaryIO | io.BufferedIOBase | io.RawIOBase
    ) -> None:
        super().__init__()
        self.stream = stream
        self.start: int | None
        try:
            self.start = stream.tell()
        except (OSError, AttributeError):
            self.start = None

    def readable(self) -> bool:
        return self.stream.readable()

    def seekable(self) -> bool:
        return self.start is not None and self.stream.seekable()

    def tell(self) -> int:
        if self.start is None:
            raise io.UnsupportedOperation("Body position is unavailable")
        return self.stream.tell() - self.start

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if self.start is None:
            raise io.UnsupportedOperation("Body cannot be rewound")
        if whence == io.SEEK_SET:
            offset += self.start
        return self.stream.seek(offset, whence) - self.start

    def readinto(self, buffer: typing.Any) -> int:
        data = self.stream.read(len(buffer))
        if not isinstance(data, bytes):
            raise TypeError("Multipart body streams must return bytes")
        if len(data) > len(buffer):
            raise ValueError("Multipart body returned more bytes than requested")
        buffer[: len(data)] = data
        return len(data)


class Part(io.BufferedReader):
    """A buffered multipart body with headers, leaving its input stream open.

    ``read()`` and ``peek()`` follow :class:`io.BufferedReader`. Seeking to zero
    returns to the position the input stream had when the part was created.
    A nonseekable input remains nonseekable.
    """

    def __init__(
        self,
        body: (
            bytes
            | bytearray
            | memoryview
            | str
            | typing.BinaryIO
            | io.BufferedIOBase
            | io.RawIOBase
        ),
        headers: typing.Mapping[str, str] | None = None,
        *,
        buffer_size: int = io.DEFAULT_BUFFER_SIZE,
    ) -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        if isinstance(body, (bytes, bytearray, memoryview)):
            body = io.BytesIO(body)
        super().__init__(_BodyReader(body), buffer_size=buffer_size)
        self.headers = HTTPHeaderDict(headers)
        self._encoded_headers: bytes | None = None
        self._header_snapshot: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_field(cls, field: RequestField) -> Part:
        """Wrap a request field body and preserve its formatted headers."""
        data = field.data
        if isinstance(data, int):
            data = str(data)
        part = cls(data)
        part._encoded_headers = field.render_headers().encode("utf-8")
        part.headers = HTTPHeaderDict(
            (name, value) for name, value in field.headers.items() if value
        )
        part._header_snapshot = tuple(part.headers.items())
        return part

    def _render_headers(self) -> bytes:
        if (
            self._encoded_headers is not None
            and tuple(self.headers.items()) == self._header_snapshot
        ):
            return self._encoded_headers
        lines = []
        for name, value in self.headers.items():
            if not name or any(c in name for c in "\r\n:"):
                raise ValueError("Invalid multipart header name")
            if "\r" in value or "\n" in value:
                raise ValueError("Invalid multipart header value")
            lines.append(f"{name}: {value}\r\n".encode("utf-8"))
        return b"".join(lines) + b"\r\n"


class MultipartEncoder(io.BufferedIOBase):
    """Read a sequence of parts as a multipart/form-data body in bounded chunks.

    Caller-owned parts and their underlying streams stay open when the encoder
    closes. ``seek(0, 0)`` attempts to rewind every part; other seek positions
    are unsupported. A failed rewind invalidates reading until a rewind succeeds.
    """

    def __init__(
        self, parts: typing.Iterable[Part], boundary: str | None = None
    ) -> None:
        super().__init__()
        # Import locally so the legacy filepost helper can use this class.
        from .filepost import choose_boundary

        self.boundary = choose_boundary() if boundary is None else boundary
        if not self.boundary or "\r" in self.boundary or "\n" in self.boundary:
            raise ValueError("Invalid multipart boundary")
        self._boundary = self.boundary.encode("latin-1")
        self.parts = tuple(parts)
        self.content_type = f"multipart/form-data; boundary={self.boundary}"
        self._segments: list[typing.BinaryIO] = []
        for part in self.parts:
            self._segments.extend(
                (
                    io.BytesIO(
                        b"--" + self._boundary + b"\r\n" + part._render_headers()
                    ),
                    part,
                    io.BytesIO(b"\r\n"),
                )
            )
        self._segments.append(io.BytesIO(b"--" + self._boundary + b"--\r\n"))
        self._index = 0
        self._position = 0
        self._valid = True

    @classmethod
    def from_fields(
        cls, fields: _TYPE_FIELDS, boundary: str | None = None
    ) -> MultipartEncoder:
        """Build an encoder from the fields accepted by the legacy helper."""
        from .filepost import iter_field_objects

        return cls(
            (Part.from_field(field) for field in iter_field_objects(fields)), boundary
        )

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return all(part.seekable() for part in self.parts)

    def tell(self) -> int:
        """Return the number of bytes read since creation or the last rewind."""
        self._checkClosed()
        return self._position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        """Rewind every part with ``seek(0, 0)`` or raise after all attempts."""
        self._checkClosed()
        if offset != 0 or whence != io.SEEK_SET:
            raise io.UnsupportedOperation("MultipartEncoder only supports seek(0, 0)")
        error: Exception | None = None
        for segment in self._segments:
            try:
                segment.seek(0)
            except Exception as exc:
                # A custom part may raise errors other than OSError. Rewinding
                # later parts must still be attempted before reporting failure.
                if error is None:
                    error = exc
        self._valid = error is None
        if error is not None:
            raise io.UnsupportedOperation(
                "One or more multipart bodies cannot rewind"
            ) from error
        self._index = 0
        self._position = 0
        return 0

    def read(self, size: int | None = -1) -> bytes:
        """Read at most ``size`` bytes, or all remaining bytes for a negative size.

        ``None`` also reads all remaining bytes. Bounded positive sizes keep
        body data buffered independently of the total length of each part.
        """
        self._checkClosed()
        if not self._valid:
            raise OSError("Multipart body is invalid after a failed rewind")
        if size is not None:
            size = operator.index(size)
        if size == 0:
            return b""
        unlimited = size is None or size < 0
        remaining = io.DEFAULT_BUFFER_SIZE if unlimited else size
        assert remaining is not None
        output = bytearray()
        while self._index < len(self._segments):
            data = self._segments[self._index].read(remaining)
            if not data:
                self._index += 1
                continue
            output.extend(data)
            self._position += len(data)
            if not unlimited:
                remaining -= len(data)
                if remaining == 0:
                    break
        return bytes(output)

    def readinto(self, buffer: typing.Any) -> int:
        """Fill a writable bytes-like buffer and return the byte count."""
        view = memoryview(buffer).cast("B")
        if view.readonly:
            raise TypeError("readinto() requires a writable buffer")
        data = self.read(len(view))
        view[: len(data)] = data
        return len(data)


class _DecodedBody(io.RawIOBase):
    def __init__(self, decoder: MultipartDecoder) -> None:
        super().__init__()
        self.decoder = decoder
        self.done = False

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: typing.Any) -> int:
        if self.done:
            return 0
        data = self.decoder._read_body(len(buffer))
        if not data:
            self.done = True
        buffer[: len(data)] = data
        return len(data)


class MultipartDecoder(typing.Iterator[Part]):
    """Iterate over multipart bodies without buffering entire parts.

    Consume each returned :class:`Part` before requesting the next one. Moving
    to the next part discards unread bytes of the previous part. Decoded parts
    are forward-only; the caller's input stream is never closed by the decoder.
    Header blocks are limited to ``max_header_size`` bytes.
    """

    def __init__(
        self,
        body: bytes | typing.BinaryIO | io.BufferedIOBase | io.RawIOBase,
        boundary: str,
        *,
        buffer_size: int = io.DEFAULT_BUFFER_SIZE,
        max_header_size: int = 65536,
    ) -> None:
        if not boundary or "\r" in boundary or "\n" in boundary:
            raise ValueError("Invalid multipart boundary")
        if buffer_size <= 0 or max_header_size <= 0:
            raise ValueError("Multipart buffer and header limits must be positive")
        self._stream = io.BytesIO(body) if isinstance(body, bytes) else body
        self._delimiter = b"--" + boundary.encode("latin-1")
        self._marker = b"\r\n" + self._delimiter
        self._buffer_size = buffer_size
        self._max_header_size = max_header_size
        self._buffer = bytearray()
        self._eof = False
        self._started = False
        self._finished = False
        self._part_ended = False
        self._current: Part | None = None
        self._current_raw: _DecodedBody | None = None

    def _fill(self) -> None:
        data = self._stream.read(self._buffer_size)
        if not isinstance(data, bytes):
            raise TypeError("Multipart body streams must return bytes")
        if len(data) > self._buffer_size:
            raise ValueError("Multipart body returned more bytes than requested")
        self._buffer.extend(data)
        self._eof = not data

    def _readline(self) -> bytes:
        while True:
            end = self._buffer.find(b"\r\n")
            if end >= 0:
                if end + 2 > self._max_header_size:
                    raise ValueError("Multipart header line is too long")
                line = bytes(self._buffer[: end + 2])
                del self._buffer[: end + 2]
                return line
            if len(self._buffer) > self._max_header_size:
                raise ValueError("Multipart header line is too long")
            if self._eof:
                line = bytes(self._buffer)
                self._buffer.clear()
                return line
            self._fill()

    def __next__(self) -> Part:
        if self._current is not None:
            # The previous Part may already have buffered bytes. They belong to
            # that old Part, while this drains the remainder from the source.
            while self._read_body(self._buffer_size):
                pass
            assert self._current_raw is not None
            self._current_raw.done = True
            self._current = None
        if not self._started:
            while True:
                line = self._readline()
                if not line:
                    raise ValueError("Multipart opening boundary was not found")
                marker = line.removesuffix(b"\r\n").rstrip(b" \t")
                if marker == self._delimiter:
                    break
                if marker == self._delimiter + b"--":
                    self._finished = True
                    break
            self._started = True
        if self._finished:
            raise StopIteration

        headers = HTTPHeaderDict()
        encoded_headers = bytearray()
        current_name: str | None = None
        current_value = ""
        while True:
            line = self._readline()
            if not line.endswith(b"\r\n"):
                raise ValueError("Truncated multipart headers")
            encoded_headers.extend(line)
            if len(encoded_headers) > self._max_header_size:
                raise ValueError("Multipart header block is too long")
            if line == b"\r\n":
                if current_name is not None:
                    headers.add(current_name, current_value)
                break
            if line[:1] in (b" ", b"\t"):
                if current_name is None:
                    raise ValueError("Multipart header continuation has no field")
                current_value += " " + line.strip().decode("latin-1")
                continue
            if current_name is not None:
                headers.add(current_name, current_value)
            name, separator, value = line[:-2].partition(b":")
            if not separator or not name or name.strip() != name:
                raise ValueError("Invalid multipart header")
            current_name = name.decode("latin-1")
            current_value = value.strip().decode("latin-1")

        self._part_ended = False
        raw = _DecodedBody(self)
        part = Part(typing.cast("typing.BinaryIO", raw), headers)
        part._encoded_headers = bytes(encoded_headers)
        part._header_snapshot = tuple(part.headers.items())
        self._current_raw = raw
        self._current = part
        return part

    def _read_body(self, size: int) -> bytes:
        if self._part_ended or size == 0:
            return b""
        while True:
            index = self._buffer.find(self._marker)
            if index >= 0:
                after = index + len(self._marker)
                while len(self._buffer) < after + 2 and not self._eof:
                    self._fill()
                closing = self._buffer[after : after + 2] == b"--"
                if closing:
                    after += 2
                padding_start = after
                while True:
                    while after < len(self._buffer) and self._buffer[after] in (32, 9):
                        after += 1
                    if after - padding_start > self._max_header_size:
                        raise ValueError("Multipart boundary padding is too long")
                    if len(self._buffer) >= after + 2 or self._eof:
                        break
                    self._fill()
                terminated = self._buffer[after : after + 2] == b"\r\n"
                if terminated or (closing and self._eof and after == len(self._buffer)):
                    if index:
                        count = min(index, size)
                        data = bytes(self._buffer[:count])
                        del self._buffer[:count]
                        return data
                    del self._buffer[: after + (2 if terminated else 0)]
                    self._part_ended = True
                    self._finished = closing
                    return b""
                # A boundary prefix followed by other body bytes is ordinary
                # data. Return the leading CRLF and look for the next candidate.
                count = min(index + 2, size)
                data = bytes(self._buffer[:count])
                del self._buffer[:count]
                return data

            available = len(self._buffer) - len(self._marker) - 2
            if available > 0:
                count = min(available, size)
                data = bytes(self._buffer[:count])
                del self._buffer[:count]
                return data
            if self._eof:
                raise ValueError(
                    "Truncated multipart body: closing boundary is missing"
                )
            self._fill()


if typing.TYPE_CHECKING:
    from .filepost import _TYPE_FIELDS
