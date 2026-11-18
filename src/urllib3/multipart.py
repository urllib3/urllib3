"""
Streaming ``multipart/form-data`` encoding and decoding.

This module provides :class:`MultipartEncoder` and :class:`MultipartDecoder`
along with the :class:`Part` class used to represent a single body part.

Unlike :func:`urllib3.encode_multipart_formdata`, which builds the whole
encoded body in memory before returning it, :class:`MultipartEncoder` is a
readable stream: callers pull the encoded body out in chunks with
:meth:`MultipartEncoder.read`, so encoding a large file only requires enough
memory for a single chunk instead of two (or more) copies of the whole body.
The encoder supports a complete rewind with ``seek(0, 0)``, which attempts to
rewind every body part, so a body can be re-sent on retries and redirects.
"""

from __future__ import annotations

import io
import re
import typing

from .fields import RequestField
from .filepost import _TYPE_FIELDS, choose_boundary, iter_field_objects

__all__ = ["MultipartDecoder", "MultipartEncoder", "Part"]


#: Default size of a single read from an underlying stream and of the
#: data returned by ``peek()`` when no size is requested.
_CHUNK_SIZE = 8192


class _StaticSegment:
    """A segment backed by an in-memory ``bytes`` object."""

    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)
        self.length = len(data)

    def read(self, size: int) -> bytes:
        return self._buffer.read(size)

    def rewind(self) -> None:
        self._buffer.seek(0)

    @property
    def seekable(self) -> bool:
        return True


class _StreamSegment:
    """A segment backed by a caller-provided file-like object.

    The stream is read incrementally and is never loaded into memory in
    full. Rewinding seeks back to the position the stream was in when the
    segment was created; streams that cannot seek can only be rewound
    before anything has been read from them.
    """

    def __init__(self, stream: typing.BinaryIO) -> None:
        self._stream = stream
        self._start: int | None = None
        try:
            if stream.seekable():
                self._start = stream.tell()
        except Exception:
            self._start = None
        self._read_any = False
        self._length: int | None = None
        self._length_known = False

    def read(self, size: int) -> bytes:
        data = self._stream.read(size)
        if data:
            self._read_any = True
        return data

    def rewind(self) -> None:
        if self._start is not None:
            self._stream.seek(self._start)
            self._read_any = False
        elif self._read_any:
            raise io.UnsupportedOperation(
                "cannot rewind a part whose data is a non-seekable stream "
                "that has already been read"
            )

    @property
    def seekable(self) -> bool:
        return self._start is not None

    @property
    def length(self) -> int | None:
        if not self._length_known:
            self._length_known = True
            if self._start is not None:
                try:
                    position = self._stream.tell()
                    end = self._stream.seek(0, io.SEEK_END)
                    self._stream.seek(position, io.SEEK_SET)
                    self._length = end - self._start
                except Exception:
                    self._length = None
        return self._length


_Segment = typing.Union[_StaticSegment, _StreamSegment, "Part"]


def _segment_seekable(segment: _Segment) -> bool:
    """Check seekability across segment types (property or method)."""
    seekable = segment.seekable
    return bool(seekable() if callable(seekable) else seekable)


class _BufferedReader:
    """Buffered reading over a sequence of segments.

    Provides the ``read()``/``peek()``/``tell()`` core shared by
    :class:`Part` and :class:`MultipartEncoder`. Only the bytes that have
    been peeked at (or are about to be returned) are held in memory.
    """

    def __init__(self, segments: list[_Segment]) -> None:
        self._segments = segments
        self._index = 0
        self._buffer = bytearray()
        self._eof = False
        self._pos = 0

    def _fill(self, need: int) -> None:
        """Buffer at least ``need`` bytes, unless EOF is reached first."""
        while len(self._buffer) < need and not self._eof:
            if self._index >= len(self._segments):
                self._eof = True
                break
            segment = self._segments[self._index]
            chunk = segment.read(max(need - len(self._buffer), 1))
            if chunk:
                self._buffer.extend(chunk)
            else:
                self._index += 1

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunks = []
            if self._buffer:
                chunks.append(bytes(self._buffer))
                self._pos += len(self._buffer)
                self._buffer.clear()
            while not self._eof:
                self._fill(_CHUNK_SIZE)
                if self._buffer:
                    chunks.append(bytes(self._buffer))
                    self._pos += len(self._buffer)
                    self._buffer.clear()
            return b"".join(chunks)
        if size == 0:
            return b""
        self._fill(size)
        result = bytes(self._buffer[:size])
        del self._buffer[: len(result)]
        self._pos += len(result)
        return result

    def peek(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = _CHUNK_SIZE
        if size == 0:
            return b""
        self._fill(size)
        return bytes(self._buffer[:size])

    def tell(self) -> int:
        return self._pos

    def rewind(self) -> None:
        """Rewind every segment, attempting all of them even on failure."""
        errors: list[Exception] = []
        for segment in self._segments:
            try:
                segment.rewind()
            except Exception as error:
                errors.append(error)
        if errors:
            raise io.UnsupportedOperation(
                "could not rewind all body parts"
            ) from errors[0]
        self._index = 0
        self._buffer.clear()
        self._eof = False
        self._pos = 0


def _normalize_headers(headers: bytes | str) -> bytes:
    """Normalize a header block so it ends with exactly one blank line."""
    if isinstance(headers, str):
        headers = headers.encode("utf-8")
    return headers.rstrip(b"\r\n") + b"\r\n\r\n"


def _parse_header_block(headers: bytes) -> dict[str, str]:
    """Parse a raw header block into a dictionary of header values."""
    parsed: dict[str, str] = {}
    for line in headers.decode("utf-8", "replace").split("\r\n"):
        name, sep, value = line.partition(":")
        if sep:
            parsed[name.strip()] = value.strip()
    return parsed


def _disposition_param(disposition: str, param: str) -> str | None:
    """Extract a parameter from a ``Content-Disposition`` header value."""
    match = re.search(rf'(?:^|;)\s*{param}="((?:[^"\\]|\\.)*)"', disposition)
    if match is None:
        match = re.search(rf"(?:^|;)\s*{param}=([^;]*)", disposition)
        if match is None:
            return None
        return match.group(1).strip()
    value = match.group(1).replace('\\"', '"').replace("\\\\", "\\")
    # Undo the percent-encoding applied by
    # :func:`urllib3.fields.format_multipart_header_param`.
    return value.replace("%0A", "\n").replace("%0D", "\r").replace("%22", '"')


class Part:
    """
    A single body part of a multipart message: a block of headers followed
    by the part's data.

    A part behaves like a read-only :class:`io.BufferedReader` over its
    content: :meth:`read` returns chunks of the part, :meth:`peek` returns
    upcoming bytes without consuming them, and ``seek(0, 0)`` rewinds the
    part so it can be read again.

    :param headers:
        The part's headers, either as a raw block (``bytes`` or ``str``,
        with or without the trailing blank line), as produced by
        :meth:`urllib3.fields.RequestField.render_headers`.
    :param data:
        The part's data: ``bytes``, ``str``, ``int`` (for backwards
        compatibility, converted to ``str``), or a binary file-like object.
        File-like objects are streamed incrementally and are never loaded
        into memory in full.
    """

    def __init__(
        self,
        headers: bytes | str,
        data: bytes | str | int | typing.BinaryIO,
    ) -> None:
        self._headers = _normalize_headers(headers)
        segments: list[_Segment] = [_StaticSegment(self._headers)]
        if isinstance(data, (bytes, bytearray, memoryview)):
            segments.append(_StaticSegment(bytes(data)))
        elif isinstance(data, str):
            segments.append(_StaticSegment(data.encode("utf-8")))
        elif isinstance(data, int):
            # Backwards compatibility, mirroring encode_multipart_formdata.
            segments.append(_StaticSegment(str(data).encode("utf-8")))
        elif hasattr(data, "read"):
            segments.append(_StreamSegment(data))
        else:
            raise TypeError(
                "Part data must be bytes, str, int, or a binary file-like "
                f"object, not {type(data).__name__!r}"
            )
        self._segments = segments
        self._reader = _BufferedReader(segments)

    @classmethod
    def from_field(cls, field: RequestField) -> Part:
        """
        Create a :class:`Part` from a :class:`~urllib3.fields.RequestField`.
        """
        return cls(field.render_headers(), field.data)

    @property
    def headers(self) -> bytes:
        """The part's raw header block, ending with a blank line."""
        return self._headers

    @property
    def header_dict(self) -> dict[str, str]:
        """The part's headers parsed into a dictionary."""
        return _parse_header_block(self._headers)

    @property
    def name(self) -> str | None:
        """The ``name`` parameter of the part's Content-Disposition."""
        disposition = self.header_dict.get("Content-Disposition")
        if disposition is None:
            return None
        return _disposition_param(disposition, "name")

    @property
    def filename(self) -> str | None:
        """The ``filename`` parameter of the part's Content-Disposition."""
        disposition = self.header_dict.get("Content-Disposition")
        if disposition is None:
            return None
        return _disposition_param(disposition, "filename")

    @property
    def length(self) -> int | None:
        """Total length of the part in bytes, if it can be determined."""
        total = 0
        for segment in self._segments:
            segment_length = segment.length
            if segment_length is None:
                return None
            total += segment_length
        return total

    def read(self, size: int = -1) -> bytes:
        """
        Read and return up to ``size`` bytes of the part, or the whole
        part if ``size`` is negative. Returns ``b""`` at the end of the
        part.
        """
        return self._reader.read(size)

    def peek(self, size: int = -1) -> bytes:
        """
        Return up to ``size`` upcoming bytes of the part without consuming
        them, like :meth:`io.BufferedReader.peek`.
        """
        return self._reader.peek(size)

    def tell(self) -> int:
        """Return the current read position within the part."""
        return self._reader.tell()

    def seek(self, offset: int = 0, whence: int = io.SEEK_SET) -> int:
        """
        Rewind the part with ``seek(0, 0)`` so it can be read again. Any
        other target raises :class:`io.UnsupportedOperation`, as does
        rewinding a part backed by a non-seekable stream that has already
        been read.
        """
        if offset != 0 or whence != io.SEEK_SET:
            raise io.UnsupportedOperation(
                "Part only supports a complete rewind with seek(0, 0)"
            )
        self._reader.rewind()
        return 0

    def rewind(self) -> None:
        """Rewind the part to its beginning; see :meth:`seek`."""
        self.seek(0, io.SEEK_SET)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        """Whether the part can be rewound with :meth:`seek`."""
        return all(_segment_seekable(segment) for segment in self._segments)


class MultipartEncoder:
    """
    A streaming ``multipart/form-data`` encoder.

    The encoder is a readable stream over the encoded body: read it in
    chunks with :meth:`read` to send arbitrarily large bodies without
    loading them into memory. ``seek(0, 0)`` performs a complete rewind,
    attempting to rewind every body part, so the same encoder can be read
    again for retries and redirects.

    :param fields:
        Dictionary of fields or list of (key, value) tuples or
        :class:`~urllib3.fields.RequestField` objects, with the same
        meaning as for :func:`urllib3.encode_multipart_formdata`. Field
        data may additionally be a binary file-like object, which is
        streamed instead of being read into memory.
    :param boundary:
        If not specified, a random boundary is generated using
        :func:`urllib3.filepost.choose_boundary`.
    """

    def __init__(self, fields: _TYPE_FIELDS, boundary: str | None = None) -> None:
        if boundary is None:
            boundary = choose_boundary()
        self.boundary = boundary
        self.parts: list[Part] = [
            Part.from_field(field) for field in iter_field_objects(fields)
        ]

        boundary_bytes = boundary.encode("latin-1")
        segments: list[_Segment] = []
        for part in self.parts:
            segments.append(_StaticSegment(b"--" + boundary_bytes + b"\r\n"))
            segments.append(part)
            segments.append(_StaticSegment(b"\r\n"))
        segments.append(_StaticSegment(b"--" + boundary_bytes + b"--\r\n"))
        self._segments = segments
        self._reader = _BufferedReader(segments)

    @property
    def content_type(self) -> str:
        """The value for the body's ``Content-Type`` header."""
        return f"multipart/form-data; boundary={self.boundary}"

    @property
    def length(self) -> int | None:
        """Total length of the encoded body, if it can be determined."""
        total = 0
        for segment in self._segments:
            segment_length = segment.length
            if segment_length is None:
                return None
            total += segment_length
        return total

    def __len__(self) -> int:
        length = self.length
        if length is None:
            raise TypeError(
                "length of this multipart body cannot be determined because "
                "it contains a part whose length is unknown"
            )
        return length

    def read(self, size: int = -1) -> bytes:
        """
        Read and return up to ``size`` bytes of the encoded body, or the
        whole body if ``size`` is negative. Returns ``b""`` at the end of
        the body.
        """
        return self._reader.read(size)

    def peek(self, size: int = -1) -> bytes:
        """
        Return up to ``size`` upcoming bytes of the encoded body without
        consuming them, like :meth:`io.BufferedReader.peek`.
        """
        return self._reader.peek(size)

    def tell(self) -> int:
        """Return the current read position within the encoded body."""
        return self._reader.tell()

    def seek(self, offset: int = 0, whence: int = io.SEEK_SET) -> int:
        """
        Rewind the whole body with ``seek(0, 0)``, attempting to rewind
        every body part. Any other target raises
        :class:`io.UnsupportedOperation`, as does rewinding a body that
        contains a part backed by a non-seekable stream that has already
        been read.
        """
        if offset != 0 or whence != io.SEEK_SET:
            raise io.UnsupportedOperation(
                "MultipartEncoder only supports a complete rewind with " "seek(0, 0)"
            )
        self._reader.rewind()
        return 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        """Whether the body can be rewound with :meth:`seek`."""
        return all(_segment_seekable(segment) for segment in self._segments)


def _extract_boundary(content_type: str) -> bytes:
    """Extract the boundary from a ``multipart/*`` Content-Type value."""
    for parameter in content_type.split(";")[1:]:
        name, sep, value = parameter.partition("=")
        if sep and name.strip().lower() == "boundary":
            value = value.strip()
            if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            if value:
                return value.encode("latin-1")
    raise ValueError(f"no boundary parameter found in Content-Type: {content_type!r}")


class MultipartDecoder:
    """
    A decoder for ``multipart/form-data`` bodies.

    Parses a body into :class:`Part` objects whose data is held in memory,
    accessible through :attr:`parts`, iteration, and indexing.

    :param body:
        The encoded body as ``bytes``, or a readable stream (such as a
        :class:`MultipartEncoder`) to read the body from.
    :param boundary:
        The multipart boundary, as ``str`` or ``bytes``. Use
        :meth:`from_content_type` to extract it from a ``Content-Type``
        header value instead.
    """

    def __init__(
        self,
        body: bytes | bytearray | memoryview | typing.BinaryIO,
        boundary: str | bytes,
    ) -> None:
        if hasattr(body, "read"):
            body = typing.cast(typing.BinaryIO, body).read()
        data = bytes(body)
        if isinstance(boundary, str):
            boundary = boundary.encode("latin-1")
        self.boundary = boundary
        self.parts: tuple[Part, ...] = tuple(self._parse(data, boundary))

    @classmethod
    def from_content_type(
        cls,
        body: bytes | bytearray | memoryview | typing.BinaryIO,
        content_type: str,
    ) -> MultipartDecoder:
        """
        Create a decoder, extracting the boundary from a ``Content-Type``
        header value such as ``multipart/form-data; boundary=...``.
        """
        return cls(body, _extract_boundary(content_type))

    @staticmethod
    def _parse(data: bytes, boundary: bytes) -> typing.Iterator[Part]:
        delimiter = b"--" + boundary
        # The first split chunk is the preamble, which is ignored. A chunk
        # starting with "--" is the closing delimiter; the rest is the
        # epilogue, which is also ignored.
        for chunk in data.split(delimiter)[1:]:
            if chunk.startswith(b"--"):
                break
            if chunk.startswith(b"\r\n"):
                chunk = chunk[2:]
            elif chunk.startswith(b"\n"):
                chunk = chunk[1:]
            else:
                continue
            # Remove the line break that precedes the next delimiter.
            if chunk.endswith(b"\r\n"):
                chunk = chunk[:-2]
            elif chunk.endswith(b"\n"):
                chunk = chunk[:-1]
            header_block, sep, content = chunk.partition(b"\r\n\r\n")
            if not sep:
                header_block, sep, content = chunk.partition(b"\n\n")
                if not sep:
                    continue
            yield Part(header_block, content)

    def __iter__(self) -> typing.Iterator[Part]:
        return iter(self.parts)

    def __len__(self) -> int:
        return len(self.parts)

    def __getitem__(self, index: int) -> Part:
        return self.parts[index]
