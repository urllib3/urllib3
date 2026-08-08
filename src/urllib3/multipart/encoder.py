"""Streaming multipart/form-data encoder."""

from __future__ import annotations

import contextlib
import io
import operator
import os
import typing

from .. import _collections, fields, filepost
from ..exceptions import UnrewindableBodyError
from ..fields import RequestField
from ..util.util import to_bytes

P = typing.TypeVar("P", bound="Part")


class Part:
    """A single multipart body part (headers + body stream).

    Provides :meth:`read` and :meth:`peek` similar to
    :class:`io.BufferedReader`, streaming headers then body without buffering
    the entire part.
    """

    def __init__(
        self,
        headers: bytes,
        body: io.BytesIO | io.BufferedReader | FileWrapper | _CustomBytesIO,
    ) -> None:
        self.headers = headers
        self.body = body
        self._header_pos = 0
        self.len = len(self.headers) + total_len(self.body)

    def rewind(self) -> None:
        """Reset part state for reuse. Seeks body to start if seekable.

        :raises UnrewindableBodyError: If the body stream cannot be rewound.
        """
        self._header_pos = 0
        body = self.body
        if isinstance(body, FileWrapper):
            fd = body.fd
            if not hasattr(fd, "seek"):
                raise UnrewindableBodyError(
                    "Cannot rewind MultipartEncoder: part body stream has no "
                    "seek() method. Use a seekable stream (such as an open file) "
                    "to enable request retries and redirects."
                )
            if hasattr(fd, "seekable") and not fd.seekable():
                raise UnrewindableBodyError(
                    "Cannot rewind MultipartEncoder: part body is a non-seekable "
                    "stream. Use a seekable stream (such as an open file) to enable "
                    "request retries and redirects."
                )
            fd.seek(0)
        elif hasattr(body, "seek"):
            body.seek(0)

    @classmethod
    def from_field(cls: type[P], field: fields.RequestField, encoding: str) -> P:
        """Create a part from a :class:`~urllib3.fields.RequestField`."""
        headers = typing.cast(bytes, encode_with(field.render_headers(), encoding))
        data: typing.Any = field.data
        if isinstance(data, int):
            data = str(data)  # Backwards compatibility
        body = coerce_data(data, encoding)
        return cls(headers, body)

    def bytes_left_to_write(self) -> int:
        """Return the number of unread bytes in this part."""
        return (len(self.headers) - self._header_pos) + total_len(self.body)

    def read(self, size: int | None = -1) -> bytes:
        """Read up to ``size`` bytes from headers, then the body."""
        if size is None or size < 0:
            size = -1
        if size == 0:
            return b""

        chunks: list[bytes] = []
        remaining = size

        if self._header_pos < len(self.headers):
            header_left = self.headers[self._header_pos :]
            if size == -1:
                chunks.append(header_left)
                self._header_pos = len(self.headers)
            else:
                take = header_left[:remaining]
                chunks.append(take)
                self._header_pos += len(take)
                remaining -= len(take)
                if remaining == 0:
                    return b"".join(chunks)

        if size == -1:
            chunks.append(self.body.read(-1) or b"")
        else:
            chunks.append(self.body.read(remaining) or b"")

        return b"".join(chunks)

    def peek(self, size: int = 0) -> bytes:
        """Return bytes without advancing the read position."""
        if size < 0:
            size = 0
        header_left = self.headers[self._header_pos :]
        if header_left:
            if size == 0:
                return header_left
            return header_left[:size]

        body = self.body
        if hasattr(body, "peek"):
            peeked = body.peek(size)
            return peeked if peeked is not None else b""

        if hasattr(body, "tell") and hasattr(body, "seek"):
            pos = body.tell()
            try:
                if size == 0:
                    peek_amount = 4096
                    body_len = total_len(body)
                    if body_len >= 0:
                        peek_amount = min(peek_amount, body_len)
                    return body.read(peek_amount) or b""
                return body.read(size) or b""
            finally:
                body.seek(pos)

        return b""

    def write_to(self, buffer: _CustomBytesIO, size: int) -> int:
        """Thin helper over :meth:`read` for the encoder buffer."""
        return buffer.append(self.read(size))


class _CustomBytesIO(io.BytesIO):
    def __init__(
        self,
        buffer: typing.BinaryIO | str | bytes | None = None,
        encoding: str = "utf-8",
    ) -> None:
        if buffer is None:
            buffer = b""
        if isinstance(buffer, (io.RawIOBase, io.BufferedIOBase)):
            bufferbytes = buffer.read() or b""
        elif isinstance(buffer, (str, bytes)):
            bufferbytes = encode_with(buffer, encoding)
        else:
            bufferbytes = buffer.read()
        super().__init__(bufferbytes)

    def _get_end(self) -> int:
        current_pos = self.tell()
        self.seek(0, 2)
        length = self.tell()
        self.seek(current_pos, 0)
        return length

    @property
    def len(self) -> int:
        length = self._get_end()
        return length - self.tell()

    def append(self, data: bytes) -> int:
        with reset(self):
            written = self.write(data)
        return written

    def smart_truncate(self) -> None:
        to_be_read = total_len(self)
        already_read = self._get_end() - to_be_read

        if already_read >= to_be_read:
            old_bytes = self.read()
            self.seek(0, 0)
            self.truncate()
            self.write(old_bytes)
            self.seek(0, 0)


class FileWrapper:
    def __init__(self, file_object: typing.BinaryIO):
        self.fd = file_object
        self._total_len = total_len(self.fd)

    @property
    def len(self) -> int:
        return self._total_len - self.fd.tell()

    def read(self, length: int = -1) -> bytes:
        return self.fd.read(length)

    def peek(self, size: int = 0) -> bytes:
        if hasattr(self.fd, "peek"):
            return typing.cast(bytes, self.fd.peek(size))
        if not self.rewindable():
            return b""
        position = self.fd.tell()
        try:
            return self.fd.read(size or 4096)
        finally:
            self.fd.seek(position)

    def rewindable(self) -> bool:
        if not hasattr(self.fd, "seek"):
            return False
        if hasattr(self.fd, "seekable") and not self.fd.seekable():
            return False
        try:
            position = self.fd.tell()
            self.fd.seek(position)
        except (OSError, ValueError):
            return False
        return True


BytesLike: typing.TypeAlias = bytes | bytearray | memoryview

PartTuples = typing.Union[
    tuple[str, typing.Union[BytesLike, str, typing.BinaryIO]],
    tuple[
        str,
        typing.Union[BytesLike, str, typing.BinaryIO],
        typing.Union[bytes, str],
    ],
    tuple[
        str,
        typing.Union[BytesLike, str, typing.BinaryIO],
        typing.Union[bytes, str],
        typing.Mapping[str, str],
    ],
]

FieldValue: typing.TypeAlias = typing.Union[
    BytesLike, str, int, PartTuples, typing.BinaryIO
]

Fields = typing.Union[
    typing.Mapping[str, FieldValue],
    typing.Sequence[tuple[str, FieldValue] | RequestField],
]


class MultipartEncoder:
    """A memory-efficient way of streaming large files in multipart/form-data format.

    The basic usage is:

    .. code-block:: python

        import urllib3
        from urllib3.multipart import MultipartEncoder

        pm = urllib3.PoolManager()
        encoder = MultipartEncoder({'field': 'value',
                                    'other_field': 'other_value'})
        r = pm.urlopen(
            method='POST',
            url='https://httpbin.org/post',
            body=encoder,
            headers=encoder.headers,
        )

    If you do not need to take advantage of streaming the post body, you can
    also do:

    .. code-block:: python

        import urllib3
        from urllib3.multipart import MultipartEncoder

        pm = urllib3.PoolManager()
        encoder = MultipartEncoder({'field': 'value',
                                    'other_field': 'other_value'})
        r = pm.urlopen(
            method='POST',
            url='https://httpbin.org/post',
            body=encoder.read(),
            headers=encoder.headers,
        )

    If you want the encoder to use a specific order, you can use an
    :class:`~urllib3.HTTPHeaderDict` or a list of tuples:

    .. code-block:: python

        encoder = MultipartEncoder([('field', 'value'),
                                    ('other_field', 'other_value')])

    You can also provide tuples as part values in the same formats as are
    supported by :meth:`~urllib3.fields.RequestField.from_tuples`

    .. code-block:: python

        encoder = MultipartEncoder({
            'field': ('file_name', b'{"a": "b"}', 'application/json',
                      {'X-My-Header': 'my-value'})
        })

    Bare file-like objects with a ``.name`` attribute use
    ``os.path.basename(name)`` as the filename; objects without ``.name``
    (for example :class:`io.BytesIO`) omit a filename.

    Finally, you can also optionally specify the boundary string to use.

    The encoder supports :meth:`seek` (0, 0) to rewind to the start, enabling
    request retries and redirects. Use :meth:`tell` to get the current read
    position.
    """

    def __init__(
        self,
        fields: Fields,
        *,
        boundary: str | None = None,
        encoding: str = "utf-8",
        blocksize: int = 8192 * 4,
    ):
        self._boundary_value: str = (
            boundary if boundary is not None else filepost.choose_boundary()
        )
        self._boundary: str = f"--{self._boundary_value}"
        self._enc: str = encoding
        # Keep compatibility with encode_multipart_formdata(), which has always
        # encoded boundary delimiters as latin-1 independently of field data.
        self._encoded_boundary = to_bytes(self._boundary + "\r\n", "latin-1")
        self._fields = fields
        if blocksize <= 0:
            raise ValueError("blocksize must be greater than zero")
        self._blocksize = blocksize
        self._finished: bool = False
        self._current_part: Part | None = None
        self._len: int | None = None
        self._bytes_read: int = 0
        self._buffer = _CustomBytesIO(encoding=encoding)
        self._parts, self._iter_parts = self._prepare_parts()
        self._write_boundary()

    @property
    def boundary(self) -> str:
        """Boundary value either passed in by the user or generated."""
        return self._boundary_value

    @property
    def blocksize(self) -> int:
        """Number of bytes read per iteration."""
        return self._blocksize

    @property
    def encoding(self) -> str:
        """Encoding of the data being passed in."""
        return self._enc

    @property
    def fields(self) -> Fields:
        """Fields provided by the user."""
        return self._fields

    @property
    def finished(self) -> bool:
        """Whether the encoder has been consumed."""
        return self._finished

    def __iter__(self) -> typing.Iterator[bytes]:
        while chunk := self.read(self._blocksize):
            yield chunk

    def __next__(self) -> bytes:
        chunk = self.read(self._blocksize)
        if not chunk:
            raise StopIteration()
        return chunk

    @property
    def len(self) -> int:
        """Length of the multipart/form-data body.

        This is a property instead of ``__len__`` so bodies larger than
        :data:`sys.maxsize` remain representable on all Python platforms.
        """
        return self._len if self._len is not None else self._calculate_length()

    def __repr__(self) -> str:
        return f"<MultipartEncoder: {self._fields!r}>"

    def _calculate_length(self) -> int:
        """
        This uses the parts to calculate the length of the body.

        This returns the calculated length so :attr:`len` can be lazy.
        """
        boundarycrnl_len = len(to_bytes(self._boundary, "latin-1")) + len(b"\r\n\r\n")
        self._len = sum(total_len(p) for p in self._parts) + (
            boundarycrnl_len * (len(self._parts) + 1)
        )
        return self._len

    def _calculate_load_amount(self, read_size: int) -> int:
        """This calculates how many bytes need to be added to the buffer.

        When a consumer reads ``x`` from the buffer, there are two cases to
        satisfy:

            1. Enough data in the buffer to return the requested amount
            2. Not enough data

        This function uses the amount of unread bytes in the buffer and
        determines how much the Encoder has to load before it can return the
        requested amount of bytes.

        :param int read_size: the number of bytes the consumer requests
        :returns: int -- the number of bytes that must be loaded into the
            buffer before the read can be satisfied. This will be strictly
            non-negative
        """
        amount = read_size - total_len(self._buffer)
        return amount if amount > 0 else 0

    def _load(self, amount: int) -> None:
        """Load ``amount`` number of bytes into the buffer."""
        self._buffer.smart_truncate()
        part = self._current_part or self._next_part()
        while amount == -1 or amount > 0:
            written = 0
            if part and not part.bytes_left_to_write():
                written += self._write(b"\r\n")
                written += self._write_boundary()
                part = self._next_part()

            if not part:
                written += self._write_closing_boundary()
                self._finished = True
                break

            part_written = part.write_to(self._buffer, amount)
            if part_written == 0 and part.bytes_left_to_write():
                raise OSError("Multipart body stream ended before its declared length")
            written += part_written

            if amount != -1:
                amount -= written

    def _next_part(self) -> Part | None:
        try:
            p = self._current_part = next(self._iter_parts)
            if isinstance(p.body, FileWrapper) and p.body.rewindable():
                p.body.fd.seek(0)
            return p
        except StopIteration:
            return None

    def _iter_fields(self) -> typing.Iterator[RequestField]:
        for item in to_list(self._fields):
            if isinstance(item, RequestField):
                yield item
                continue

            name, v = item
            filename: str | None = None
            content_type: str | bytes | None = None
            headers: typing.Mapping[str, str] | None = None
            if isinstance(v, (list, tuple)):
                if len(v) == 2:
                    filename, data = typing.cast(tuple[str, typing.Any], v)
                    content_type = fields.guess_content_type(filename)
                elif len(v) == 3:
                    filename, data, content_type = typing.cast(
                        tuple[str, typing.Any, str | bytes], v
                    )
                elif len(v) == 4:
                    filename, data, content_type, headers = typing.cast(
                        tuple[
                            str,
                            typing.Any,
                            str | bytes,
                            typing.Mapping[str, str],
                        ],
                        v,
                    )
                else:
                    raise ValueError(
                        "multipart field tuples must contain 2, 3, or 4 items"
                    )
            else:
                data = v
                if (
                    filename is None
                    and hasattr(data, "read")
                    and not isinstance(data, (str, bytes, int))
                ):
                    # Bare file-like: use basename of .name when present.
                    # Do not invent a filename for objects like BytesIO.
                    name_attr = getattr(data, "name", None)
                    if isinstance(name_attr, (str, bytes)) and name_attr:
                        if isinstance(name_attr, bytes):
                            name_attr = name_attr.decode("utf-8", errors="replace")
                        if not name_attr.startswith("<") and name_attr not in (
                            "stdin",
                            "stdout",
                            "stderr",
                        ):
                            filename = os.path.basename(name_attr)
                            content_type = fields.guess_content_type(filename)

            if isinstance(data, int):
                data = str(data)  # Backwards compatibility

            field = fields.RequestField(
                name=name, data=data, filename=filename, headers=headers
            )
            if isinstance(content_type, bytes):
                content_type = content_type.decode("utf-8")
            field.make_multipart(content_type=content_type)
            yield field

    def _prepare_parts(self) -> tuple[list[Part], typing.Iterator[Part]]:
        """This uses the fields provided by the user and creates Part objects.

        It returns the new value for the `parts` attribute and creates a
        generator for iteration.
        """
        enc = self._enc
        parts = [Part.from_field(f, enc) for f in self._iter_fields()]
        seen_streams: set[int] = set()
        for part in parts:
            if not isinstance(part.body, FileWrapper):
                continue
            stream_id = id(part.body.fd)
            if stream_id in seen_streams and not part.body.rewindable():
                raise ValueError(
                    "The same non-seekable stream cannot be used for multiple "
                    "multipart fields"
                )
            seen_streams.add(stream_id)
        return parts, iter(parts)

    def _write(self, bytes_to_write: bytes | bytearray) -> int:
        """Write the bytes to the end of the buffer.

        :param bytes bytes_to_write: byte-string (or bytearray) to append to
            the buffer
        :returns: int -- the number of bytes written
        """
        return self._buffer.append(bytes_to_write)

    def _write_boundary(self) -> int:
        """Write the boundary to the end of the buffer."""
        return self._write(self._encoded_boundary)

    def _write_closing_boundary(self) -> int:
        """Write the bytes necessary to finish a multipart/form-data body.

        This overwrites the trailing ``\\r\\n`` of the last boundary with
        ``--\\r\\n``, converting it into a closing boundary.  Four bytes are
        written in total, but two of them replace bytes that already existed in
        the buffer, so the net growth of the readable buffer is 2.  That net
        figure is what callers use to update their ``amount`` counter; it is
        returned here for consistency even though :meth:`_load` always breaks
        immediately after this call and never reads the return value.
        """
        with reset(self._buffer):
            self._buffer.seek(-2, 2)
            self._buffer.write(b"--\r\n")
        return 2  # net bytes added (4 written − 2 overwritten)

    @property
    def content_type(self) -> str:
        return f"multipart/form-data; boundary={self._boundary_value}"

    @property
    def content_length(self) -> str:
        return str(self.len)

    @property
    def headers(self) -> _collections.HTTPHeaderDict:
        return _collections.HTTPHeaderDict(
            {
                "Content-Type": self.content_type,
                "Content-Length": self.content_length,
            }
        )

    def read(self, size: int | None = -1) -> bytes:
        """Read data from the streaming encoder.

        :param int size: (optional), If provided, ``read`` will return exactly
            that many bytes. If ``-1`` or ``None``, it will return all
            remaining bytes.
        :returns: bytes
        """
        if size is None or size < 0:
            size = -1

        if self._finished:
            data = self._buffer.read(size)
            self._bytes_read += len(data)
            return data

        if size == -1:
            bytes_to_load: int = -1
        else:
            bytes_to_load = self._calculate_load_amount(size)

        self._load(bytes_to_load)
        data = self._buffer.read(size)
        self._bytes_read += len(data)
        return data

    def tell(self) -> int:
        """Return the number of bytes read so far."""
        return self._bytes_read

    def seek(self, pos: int, whence: int = 0) -> int:
        """Seek to a position in the stream.

        Only ``seek(0, 0)`` (rewind to start) is supported. This allows
        request retries and redirects to work correctly.

        :param int pos: Position to seek to.
        :param int whence: Seek mode (0=start, 1=current, 2=end).
        :returns: The new position.
        :raises UnrewindableBodyError: If any part uses a non-seekable stream.
        :raises ValueError: If seeking to a non-zero position.
        """
        if whence != 0 or pos != 0:
            raise UnrewindableBodyError(
                "MultipartEncoder only supports seek(0, 0) to rewind to the start. "
                "Use seek(0) for retries and redirects."
            )
        if any(
            isinstance(part.body, FileWrapper) and not hasattr(part.body.fd, "seek")
            for part in self._parts
        ):
            raise UnrewindableBodyError(
                "Cannot rewind MultipartEncoder: at least one part body stream "
                "has no seek() method. Use seekable streams to enable request "
                "retries and redirects."
            )
        if any(
            isinstance(part.body, FileWrapper) and not part.body.rewindable()
            for part in self._parts
        ):
            raise UnrewindableBodyError(
                "Cannot rewind MultipartEncoder: at least one part body is a "
                "non-seekable stream. Use seekable streams to enable request "
                "retries and redirects."
            )
        for part in self._parts:
            part.rewind()
        self._finished = False
        self._current_part = None
        self._iter_parts = iter(self._parts)
        self._bytes_read = 0
        self._buffer.truncate(0)
        self._buffer.seek(0)
        self._write_boundary()
        return 0

    def seekable(self) -> bool:
        """Return whether all multipart body streams can be rewound."""
        return all(
            not isinstance(part.body, FileWrapper) or part.body.rewindable()
            for part in self._parts
        )


def encode_with(string: str | bytes | None, encoding: str) -> bytes | None:
    """Encode ``string`` with ``encoding`` if necessary.

    :param str string: If string is a bytes object, it will not encode it.
        Otherwise, this function will encode it with the provided encoding.
    :param str encoding: The encoding with which to encode string.
    :returns: encoded bytes object
    """
    if string is None:
        return None
    return to_bytes(string, encoding)


def total_len(
    o: (
        Part
        | FileWrapper
        | typing.AnyStr
        | typing.TextIO
        | typing.BinaryIO
        | typing.Sized
    ),
) -> int:
    if hasattr(o, "__len__"):
        o = typing.cast(typing.Union[typing.Sized, typing.AnyStr], o)
        length = operator.index(o.__len__())
        if length < 0:
            raise ValueError("__len__() should return >= 0")
        return length

    if hasattr(o, "len"):
        o = typing.cast(typing.Union[Part, FileWrapper, _CustomBytesIO], o)
        return o.len

    if hasattr(o, "fileno"):
        try:
            fileno = o.fileno()
        except io.UnsupportedOperation:
            pass
        else:
            return os.fstat(fileno).st_size

    if hasattr(o, "getvalue"):
        o = typing.cast(typing.Union[io.BytesIO, io.StringIO], o)
        return len(o.getvalue())

    raise ValueError("Unable to compute size", o)


@contextlib.contextmanager
def reset(buffer: typing.BinaryIO) -> typing.Iterator[None]:
    """Keep track of the buffer's current position and write to the end.

    This is a context manager meant to be used when adding data to the buffer.
    It eliminates the need for every function to be concerned with the
    position of the cursor in the buffer.
    """
    original_position = buffer.tell()
    buffer.seek(0, 2)
    yield
    buffer.seek(original_position, 0)


def coerce_data(
    data: _CustomBytesIO | io.BytesIO | typing.BinaryIO | str | BytesLike,
    encoding: str,
) -> _CustomBytesIO | FileWrapper:
    """Ensure that every object's __len__ behaves uniformly."""
    if not isinstance(data, _CustomBytesIO):
        if isinstance(data, io.BytesIO):
            data.seek(0)
            return FileWrapper(data)

        if isinstance(data, (bytes, bytearray, memoryview)):
            return _CustomBytesIO(bytes(data), encoding)

        if isinstance(data, str):
            return _CustomBytesIO(data, encoding)

        try:
            buffer = memoryview(typing.cast(typing.Any, data))
        except TypeError:
            pass
        else:
            return _CustomBytesIO(bytes(buffer), encoding)

        if hasattr(data, "fileno"):
            if hasattr(data, "seekable") and data.seekable():
                data.seek(0)
            elif hasattr(data, "tell"):
                if data.tell() != 0:
                    raise ValueError(
                        "Non-seekable stream is at a non-zero position; "
                        "cannot encode partial data. Seek to position 0 before passing "
                        "this stream, or use a seekable stream."
                    )
            else:
                raise ValueError(
                    "Stream has no tell() method; cannot verify it is at position 0. "
                    "Use a seekable stream, or provide a stream with a tell() method."
                )
            return FileWrapper(data)

        # Sized, file-like objects can be streamed without a file descriptor.
        if hasattr(data, "read"):
            if hasattr(data, "seekable") and data.seekable():
                data.seek(0)
            elif hasattr(data, "tell"):
                if data.tell() != 0:
                    raise ValueError(
                        "Non-seekable stream is at a non-zero position; "
                        "cannot encode partial data. Seek to position 0 before passing "
                        "this stream, or use a seekable stream."
                    )
            else:
                raise ValueError(
                    "Stream has no tell() method; cannot verify it is at position 0. "
                    "Use a seekable stream, or provide a stream with a tell() method."
                )
            total_len(data)
            return FileWrapper(data)

        raise TypeError(
            f"Unsupported data type for multipart encoding: {type(data)!r}. "
            "Expected str, bytes, io.BytesIO, or a file-like object with a "
            "fileno() method."
        )

    return data


def to_list(
    fields: Fields,
) -> list[tuple[str, FieldValue] | RequestField]:
    if isinstance(fields, typing.Mapping):
        return list(fields.items())

    result: list[tuple[str, FieldValue] | RequestField] = []
    for item in fields:
        result.append(item)
    return result
