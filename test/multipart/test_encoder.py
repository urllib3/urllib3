from __future__ import annotations

import io
import unittest

import pytest

from urllib3 import filepost
from urllib3.multipart.encoder import MultipartEncoder, _CustomBytesIO

preserve_bytes = {"preserve_exact_body_bytes": True}


class LargeFileMock:
    """Simulates a large (1 GB) file-like object without allocating real memory.

    This is intentionally NOT a BytesIO subclass so that coerce_data wraps it
    in a FileWrapper (via the fileno duck-type check) instead of calling
    getvalue() on an uninitialized BytesIO.
    """

    def __init__(self) -> None:
        self.bytes_read = 0
        self.bytes_max = 1024 * 1024 * 1024  # 1 GB

    def fileno(self) -> int:
        raise io.UnsupportedOperation("mock file has no real fd")

    @property
    def name(self) -> str:
        return "fake_name.py"

    def __len__(self) -> int:
        return self.bytes_max

    def read(self, size: int | None = None) -> bytes:
        if self.bytes_read >= self.bytes_max:
            return b""

        if size is None:
            length = self.bytes_max - self.bytes_read
        else:
            length = size

        length = int(length)
        length = min(length, self.bytes_max - self.bytes_read)

        self.bytes_read += length

        return b"a" * length

    def tell(self) -> int:
        return self.bytes_read


class TestCustomBytesIO(unittest.TestCase):
    def setUp(self) -> None:
        self.instance = _CustomBytesIO()

    def test_writable(self) -> None:
        assert hasattr(self.instance, "write")
        assert self.instance.write(b"example") == 7

    def test_readable(self) -> None:
        assert hasattr(self.instance, "read")
        assert self.instance.read() == b""
        assert self.instance.read(10) == b""

    def test_can_read_after_writing_to(self) -> None:
        self.instance.write(b"example text")
        self.instance.seek(0, 0)
        assert self.instance.read() == b"example text"

    def test_can_read_some_after_writing_to(self) -> None:
        self.instance.write(b"example text")
        self.instance.seek(0, 0)
        assert self.instance.read(6) == b"exampl"

    def test_can_get_length(self) -> None:
        self.instance.write(b"example")
        self.instance.seek(0, 0)
        assert self.instance.len == 7

    def test_truncates_intelligently(self) -> None:
        self.instance.write(b"abcdefghijklmnopqrstuvwxyzabcd")  # 30 bytes
        assert self.instance.tell() == 30
        self.instance.seek(-10, 2)
        self.instance.smart_truncate()
        assert self.instance.len == 10
        assert self.instance.read() == b"uvwxyzabcd"
        assert self.instance.tell() == 10

    def test_accepts_encoded_strings_with_unicode(self) -> None:
        s = b"this is a unicode string: \xc3\xa9 \xc3\xa1 \xc7\xab \xc3\xb3"
        self.instance = _CustomBytesIO(s)
        assert self.instance.read() == s


class TestMultipartEncoder(unittest.TestCase):
    def setUp(self) -> None:
        self.parts = [("field", "value"), ("other_field", "other_value")]
        self.boundary = "this-is-a-boundary"
        self.instance = MultipartEncoder(self.parts, boundary=self.boundary)

    def test_content_type(self) -> None:
        expected = "multipart/form-data; boundary=this-is-a-boundary"
        assert self.instance.content_type == expected

    def test_content_length(self) -> None:
        assert self.instance.content_length == str(len(self.instance))

    def test_encodes_data_the_same(self) -> None:
        encoded = filepost.encode_multipart_formdata(self.parts, self.boundary)[0]
        assert encoded == self.instance.read()

    def test_streams_its_data(self) -> None:
        large_file = LargeFileMock()
        parts: dict[str, str | LargeFileMock] = {
            "some field": "value",
            "some file": large_file,
        }
        encoder = MultipartEncoder(parts)  # type: ignore[arg-type]
        total_size = len(encoder)
        read_size = 1024 * 1024 * 128
        already_read = 0
        while True:
            read = encoder.read(read_size)
            already_read += len(read)
            if not read:
                break

        assert encoder._buffer.tell() <= read_size
        assert already_read == total_size

    def test_length_is_correct(self) -> None:
        encoded = filepost.encode_multipart_formdata(self.parts, self.boundary)[0]
        assert len(encoded) == len(self.instance)

    def test_encodes_with_readable_data(self) -> None:
        s = io.BytesIO(b"value")
        m = MultipartEncoder([("field", s)], boundary=self.boundary)
        assert m.read() == (
            b"--this-is-a-boundary\r\n"
            b'Content-Disposition: form-data; name="field"\r\n\r\n'
            b"value\r\n"
            b"--this-is-a-boundary--\r\n"
        )

    def test_reads_open_file_objects(self) -> None:
        with open(__file__, "rb") as fd:
            m = MultipartEncoder([("field", "foo"), ("file", fd)])
            assert m.read() is not None

    def test_reads_open_file_objects_with_a_specified_filename(self) -> None:
        with open(__file__, "rb") as fd:
            m = MultipartEncoder(
                [("field", "foo"), ("file", ("filename", fd, "text/plain"))]
            )
            assert m.read() is not None

    def test_file_object_at_nonzero_position_sends_full_content(self) -> None:
        """Verify that MultipartEncoder seeks to 0 before reading a seekable
        file-like object, so partial prior reads don't silently drop bytes."""
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"full content")
            tmp_name = tmp.name

        try:
            with open(tmp_name, "rb") as fd:
                fd.read(5)  # Advance position to 5 — simulate partial prior read
                m = MultipartEncoder(
                    [("file", ("data.bin", fd, "application/octet-stream"))]
                )
                body = m.read()
            assert b"full content" in body
        finally:
            import os

            os.unlink(tmp_name)

    def test_non_seekable_stream_at_nonzero_position_raises(self) -> None:
        """Verify that MultipartEncoder raises ValueError for a non-seekable stream
        already past position 0 instead of silently encoding partial data."""

        class NonSeekableReader(io.RawIOBase):
            def __init__(self, data: bytes) -> None:
                self._data = memoryview(data)
                self._pos = 0

            def readinto(self, b: bytearray) -> int:  # type: ignore[override]
                n = len(b)
                chunk = bytes(self._data[self._pos : self._pos + n])
                b[: len(chunk)] = chunk
                self._pos += len(chunk)
                return len(chunk)

            def readable(self) -> bool:
                return True

            def seekable(self) -> bool:
                return False

            def tell(self) -> int:
                return self._pos

        raw = NonSeekableReader(b"full content")
        reader = io.BufferedReader(raw)  # type: ignore[type-var]
        reader.read(5)  # Advance position — cannot seek back
        with pytest.raises(
            ValueError, match="Non-seekable stream is at a non-zero position"
        ):
            MultipartEncoder(
                [("file", ("data.bin", reader, "application/octet-stream"))]  # type: ignore[list-item]
            )

    def test_custom_binary_io_without_fileno_reads_into_memory(self) -> None:
        """A BinaryIO object that has read() and tell() but no fileno() should
        be read into memory rather than falling through to an incorrect cast."""

        class CustomStream:
            def __init__(self, data: bytes) -> None:
                self._buf = io.BytesIO(data)

            def tell(self) -> int:
                return self._buf.tell()

            def read(self, size: int = -1) -> bytes:
                return self._buf.read(size)

        stream = CustomStream(b"custom stream content")
        m = MultipartEncoder([("file", ("data.bin", stream, "application/octet-stream"))])  # type: ignore[list-item]
        body = m.read()
        assert b"custom stream content" in body

    def test_custom_stream_seekable_at_nonzero_position_seeks_to_start(self) -> None:
        """A seekable custom stream advanced before passing should be rewound to 0
        and encode the full content, not just the remaining bytes."""

        class SeekableCustomStream:
            def __init__(self, data: bytes) -> None:
                self._buf = io.BytesIO(data)

            def seekable(self) -> bool:
                return True

            def seek(self, pos: int, whence: int = 0) -> int:
                return self._buf.seek(pos, whence)

            def tell(self) -> int:
                return self._buf.tell()

            def read(self, size: int = -1) -> bytes:
                return self._buf.read(size)

        stream = SeekableCustomStream(b"full content")
        stream.read(5)  # Advance position — simulate partial prior read
        m = MultipartEncoder([("file", ("data.bin", stream, "application/octet-stream"))])  # type: ignore[list-item]
        body = m.read()
        assert b"full content" in body

    def test_custom_stream_non_seekable_at_nonzero_position_raises(self) -> None:
        """A non-seekable custom stream already past position 0 must raise
        ValueError instead of silently encoding partial data."""

        class NonSeekableCustomStream:
            def __init__(self, data: bytes) -> None:
                self._buf = io.BytesIO(data)
                self._pos = 0

            def seekable(self) -> bool:
                return False

            def tell(self) -> int:
                return self._pos

            def read(self, size: int = -1) -> bytes:
                chunk = self._buf.read(size)
                self._pos += len(chunk)
                return chunk

        stream = NonSeekableCustomStream(b"full content")
        stream.read(5)  # Advance position — cannot seek back
        with pytest.raises(
            ValueError, match="Non-seekable stream is at a non-zero position"
        ):
            MultipartEncoder([("file", ("data.bin", stream, "application/octet-stream"))])  # type: ignore[list-item]

    def test_fileno_stream_non_seekable_without_tell_raises(self) -> None:
        """A fileno-bearing stream whose seekable() is False and that has no
        tell() must raise ValueError rather than silently encoding from an
        unknown position."""

        class NoTellFilenoStream:
            """Has fileno (duck-type), seekable() returns False, no tell()."""

            def __init__(self, data: bytes) -> None:
                self._data = data

            def fileno(self) -> int:
                raise io.UnsupportedOperation("no real fd")

            def __len__(self) -> int:
                return len(self._data)

            def seekable(self) -> bool:
                return False

            def read(self, size: int = -1) -> bytes:
                return self._data

        stream = NoTellFilenoStream(b"content")
        with pytest.raises(ValueError, match="Stream has no tell\\(\\) method"):
            MultipartEncoder([("file", ("data.bin", stream, "application/octet-stream"))])  # type: ignore[list-item]

    def test_read_only_stream_non_seekable_without_tell_raises(self) -> None:
        """A read()-only stream (no fileno) whose seekable() is False and that
        has no tell() must raise ValueError rather than silently encoding from
        an unknown position."""

        class NoTellReadStream:
            """Has read() but no fileno(), seekable() returns False, no tell()."""

            def __init__(self, data: bytes) -> None:
                self._data = data

            def seekable(self) -> bool:
                return False

            def read(self, size: int = -1) -> bytes:
                return self._data

        stream = NoTellReadStream(b"content")
        with pytest.raises(ValueError, match="Stream has no tell\\(\\) method"):
            MultipartEncoder([("file", ("data.bin", stream, "application/octet-stream"))])  # type: ignore[list-item]

    def test_fileno_stream_no_seekable_no_tell_raises(self) -> None:
        """A fileno-bearing stream with neither seekable() nor tell() must raise
        ValueError rather than silently encoding from an unknown position."""

        class BareFilenoStream:
            """Has fileno (duck-type), no seekable(), no tell()."""

            def __init__(self, data: bytes) -> None:
                self._data = data

            def fileno(self) -> int:
                raise io.UnsupportedOperation("no real fd")

            def __len__(self) -> int:
                return len(self._data)

            def read(self, size: int = -1) -> bytes:
                return self._data

        stream = BareFilenoStream(b"content")
        with pytest.raises(ValueError, match="Stream has no tell\\(\\) method"):
            MultipartEncoder([("file", ("data.bin", stream, "application/octet-stream"))])  # type: ignore[list-item]

    def test_read_only_stream_no_seekable_no_tell_raises(self) -> None:
        """A read()-only stream (no fileno) with neither seekable() nor tell()
        must raise ValueError rather than silently encoding from an unknown
        position."""

        class BareReadStream:
            """Has read() but no fileno(), no seekable(), no tell()."""

            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self, size: int = -1) -> bytes:
                return self._data

        stream = BareReadStream(b"content")
        with pytest.raises(ValueError, match="Stream has no tell\\(\\) method"):
            MultipartEncoder([("file", ("data.bin", stream, "application/octet-stream"))])  # type: ignore[list-item]

    def test_unsupported_data_type_raises_type_error(self) -> None:
        """A data value that is none of the supported types should raise
        TypeError immediately rather than silently returning an incorrect cast."""
        from urllib3.multipart.encoder import coerce_data

        with pytest.raises(
            TypeError, match="Unsupported data type for multipart encoding"
        ):
            coerce_data(12345, "utf-8")  # type: ignore[call-overload]

    def test_handles_encoded_unicode_strings(self) -> None:
        m = MultipartEncoder(
            [
                (
                    "field",
                    b"this is a unicode string: \xc3\xa9 \xc3\xa1 \xc7\xab \xc3\xb3",
                )
            ]
        )
        assert m.read() is not None

    def test_handles_unicode_strings(self) -> None:
        s = b"this is a unicode string: \xc3\xa9 \xc3\xa1 \xc7\xab \xc3\xb3"
        m = MultipartEncoder([("field", s.decode("utf-8"))])
        assert m.read() is not None

    def test_regression_1(self) -> None:
        """
        Ensure https://github.com/requests/toolbelt/issues/31 doesn't
        ever happen again.
        """
        fields: dict[str, str | tuple[str, io.BufferedReader]] = {"test": "t" * 100}
        opened_files: list[io.BufferedReader] = []

        try:
            for x in range(30):
                f = open(__file__, "rb")
                opened_files.append(f)
                fields[f"f{x}"] = ("test", f)

            m = MultipartEncoder(fields=fields)
            total_size = len(m)

            blocksize = 8192
            read_so_far = 0

            while True:
                data = m.read(blocksize)
                if not data:
                    break
                read_so_far += len(data)

            assert read_so_far == total_size
        finally:
            for f in opened_files:
                f.close()

    def test_regression_2(self) -> None:
        """Ensure issue #31 doesn't ever happen again."""
        fields = {"test": "t" * 8100}

        m = MultipartEncoder(fields=fields)
        total_size = len(m)

        blocksize = 8192
        read_so_far = 0

        while True:
            data = m.read(blocksize)
            if not data:
                break
            read_so_far += len(data)

        assert read_so_far == total_size

    def test_handles_empty_unicode_values(self) -> None:
        """Verify that the Encoder can handle empty unicode strings.

        See https://github.com/requests/toolbelt/issues/46 for
        more context.
        """
        fields = [(b"test".decode("utf-8"), b"".decode("utf-8"))]
        m = MultipartEncoder(fields=fields)
        assert len(m.read()) > 0

    def test_accepts_custom_content_type(self) -> None:
        """Verify that the Encoder handles custom content-types.

        See https://github.com/requests/toolbelt/issues/52
        """
        fields = [
            (
                b"test".decode("utf-8"),
                (
                    b"filename".decode("utf-8"),
                    b"filecontent",
                    b"application/json".decode("utf-8"),
                ),
            )
        ]
        m = MultipartEncoder(fields=fields)
        output = m.read().decode("utf-8")
        assert output.index("Content-Type: application/json\r\n") > 0

    def test_accepts_custom_content_type_as_bytes(self) -> None:
        """Verify that the Encoder handles custom content-types which are bytes.

        See https://github.com/requests/toolbelt/issues/52
        """
        fields = [
            (
                b"test".decode("utf-8"),
                (
                    b"filename".decode("utf-8"),
                    b"filecontent",
                    b"application/json",
                ),
            )
        ]
        m = MultipartEncoder(fields=fields)
        output = m.read().decode("utf-8")
        assert output.index("Content-Type: application/json\r\n") > 0

    def test_accepts_custom_headers(self) -> None:
        """Verify that the Encoder handles custom headers.

        See https://github.com/requests/toolbelt/issues/52
        """
        fields = [
            (
                b"test".decode("utf-8"),
                (
                    b"filename".decode("utf-8"),
                    b"filecontent",
                    b"application/json".decode("utf-8"),
                    {"X-My-Header": "my-value"},
                ),
            )
        ]
        m = MultipartEncoder(fields=fields)
        output = m.read().decode("utf-8")
        assert output.index("X-My-Header: my-value\r\n") > 0

    def test_no_parts(self) -> None:
        fields: list[tuple[str, str]] = []
        boundary = "--90967316f8404798963cce746a4f4ef9"
        m = MultipartEncoder(fields=fields, boundary=boundary)
        output = m.read().decode("utf-8")
        assert output == "----90967316f8404798963cce746a4f4ef9--\r\n"

    def test_boundary_value_property(self) -> None:
        assert self.instance.boundary_value == self.boundary

    def test_boundary_property(self) -> None:
        assert self.instance.boundary == f"--{self.boundary}"

    def test_encoding_property(self) -> None:
        assert self.instance.encoding == "utf-8"

    def test_fields_property(self) -> None:
        assert self.instance.fields == self.parts

    def test_finished_before_read(self) -> None:
        assert not self.instance.finished

    def test_finished_after_read(self) -> None:
        self.instance.read()
        assert self.instance.finished

    def test_read_with_none_size_returns_all_data(self) -> None:
        """Passing size=None to read() must not crash with TypeError.

        Previously, size=None left bytes_to_load as None which was passed to
        _load(), where `None > 0` raised TypeError.
        """
        expected = filepost.encode_multipart_formdata(self.parts, self.boundary)[0]
        result = self.instance.read(None)
        assert result == expected

    def test_read_with_none_size_on_finished_encoder(self) -> None:
        """read(None) must also work when the encoder is already finished."""
        self.instance.read()  # consume everything
        assert self.instance.finished
        result = self.instance.read(None)
        assert result == b""

    def test_repr(self) -> None:
        assert "MultipartEncoder" in repr(self.instance)

    def test_default_iter_read_size(self) -> None:
        assert self.instance.default_iter_read_size == 8192 * 4

    def test_iterable_interface(self) -> None:
        chunks = list(self.instance)
        combined = b"".join(chunks)
        expected = filepost.encode_multipart_formdata(self.parts, self.boundary)[0]
        assert combined == expected

    def test_headers_property(self) -> None:
        headers = self.instance.headers
        assert "Content-Type" in headers
        assert "Content-Length" in headers
        assert headers["Content-Type"] == self.instance.content_type
        assert headers["Content-Length"] == self.instance.content_length

    def test_next_returns_data_when_not_finished(self) -> None:
        assert not self.instance.finished
        data = next(self.instance)
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_next_raises_stop_iteration_when_finished(self) -> None:
        self.instance.read()
        assert self.instance.finished
        with pytest.raises(StopIteration):
            next(self.instance)

    def test_filename_hinting_from_file_object(self) -> None:
        """When a bare file object is passed as a field value, the encoder
        should guess the filename from the .name attribute (per
        requests-toolbelt PR #316)."""
        with open(__file__, "rb") as fd:
            m = MultipartEncoder([("file", fd)])
            body = m.read().decode("utf-8", errors="replace")
            import os

            expected_name = os.path.basename(__file__)
            assert f'filename="{expected_name}"' in body

    def test_filename_hinting_not_applied_to_tuple_values(self) -> None:
        """When a file is passed as part of a tuple, the explicitly provided
        filename should be used, not the .name attribute."""
        with open(__file__, "rb") as fd:
            m = MultipartEncoder([("file", ("custom.txt", fd, "text/plain"))])
            body = m.read().decode("utf-8", errors="replace")
            assert 'filename="custom.txt"' in body

    def test_coerce_data_passthrough_for_custom_bytes_io(self) -> None:
        """coerce_data should return a _CustomBytesIO unchanged."""
        from urllib3.multipart.encoder import coerce_data

        custom = _CustomBytesIO(b"hello")
        result = coerce_data(custom, "utf-8")
        assert result is custom  # type: ignore[comparison-overlap]

    def test_total_len_unsupported_type_raises(self) -> None:
        """total_len raises ValueError for objects whose size cannot be determined."""
        from urllib3.multipart.encoder import total_len

        with pytest.raises(ValueError, match="Unable to compute size"):
            total_len(object())  # type: ignore[call-overload]

    def test_total_len_with_fileno_unsupported_operation(self) -> None:
        """total_len falls through to getvalue when fileno raises UnsupportedOperation."""
        from urllib3.multipart.encoder import total_len

        class FakeStream:
            def fileno(self) -> int:
                raise io.UnsupportedOperation("not supported")

            def getvalue(self) -> bytes:
                return b"hello world"

        assert total_len(FakeStream()) == 11  # type: ignore[call-overload]

    def test_custom_bytes_io_with_binary_io_buffer(self) -> None:
        """_CustomBytesIO should accept a BinaryIO (BufferedIOBase) buffer."""
        buf = io.BytesIO(b"binary io content")
        custom = _CustomBytesIO(buf)
        assert custom.read() == b"binary io content"

    def test_seek_rewinds_to_start(self) -> None:
        """seek(0, 0) rewinds the encoder for retries and redirects."""
        expected = filepost.encode_multipart_formdata(self.parts, self.boundary)[0]
        first_read = self.instance.read()
        assert first_read == expected
        assert self.instance.finished
        assert self.instance.tell() == len(expected)

        self.instance.seek(0, 0)
        assert not self.instance.finished
        assert self.instance.tell() == 0
        second_read = self.instance.read()
        assert second_read == expected

    def test_tell_returns_bytes_read(self) -> None:
        """tell() returns the number of bytes read so far."""
        assert self.instance.tell() == 0
        chunk = self.instance.read(10)
        assert self.instance.tell() == len(chunk)
        self.instance.read()
        assert self.instance.tell() == len(self.instance)

    def test_seek_nonzero_raises(self) -> None:
        """seek(pos) for pos != 0 raises UnrewindableBodyError."""
        from urllib3.exceptions import UnrewindableBodyError

        with pytest.raises(UnrewindableBodyError, match="only supports seek\\(0"):
            self.instance.seek(10, 0)

    def test_seek_rewinds_with_file_parts(self) -> None:
        """seek(0) works when encoder contains file-like parts."""
        with open(__file__, "rb") as fd:
            m = MultipartEncoder(
                [("field", "value"), ("file", ("test.py", fd, "text/plain"))],
                boundary=self.boundary,
            )
            first = m.read()
            m.seek(0)
            second = m.read()
        assert first == second

    def test_non_seekable_stream_encodes_one_shot(self) -> None:
        """A non-seekable stream at position 0 is accepted and encodes correctly
        when no seek(0, 0) is called (one-shot use, no retries)."""
        from urllib3.multipart.encoder import FileWrapper

        class NonSeekableStream:
            """Duck-typed non-seekable stream: fileno raises, has __len__/tell/read."""

            def __init__(self, data: bytes) -> None:
                self._data = data
                self._pos = 0

            def fileno(self) -> int:
                raise io.UnsupportedOperation("no real fd")

            def seekable(self) -> bool:
                return False

            def tell(self) -> int:
                return self._pos

            def __len__(self) -> int:
                return len(self._data)

            def read(self, size: int = -1) -> bytes:
                if size == -1:
                    chunk = self._data[self._pos :]
                    self._pos = len(self._data)
                else:
                    chunk = self._data[self._pos : self._pos + size]
                    self._pos += len(chunk)
                return chunk

        stream = NonSeekableStream(b"streaming content")
        m = MultipartEncoder(
            [("file", ("data.bin", stream, "application/octet-stream"))],  # type: ignore[list-item]
            boundary=self.boundary,
        )
        body = m.read()
        assert b"streaming content" in body
        part = m._parts[0]
        assert isinstance(part.body, FileWrapper)

    def test_seek_with_non_seekable_part_raises_unrewindable(self) -> None:
        """seek(0, 0) on an encoder whose FileWrapper body has seek() but
        seekable() returns False raises UnrewindableBodyError (not
        io.UnsupportedOperation).  This mirrors io.BufferedReader wrapping a
        non-seekable raw stream, which exposes seek() but reports seekable=False."""
        from urllib3.exceptions import UnrewindableBodyError

        class NonSeekableStream:
            """Duck-typed non-seekable stream: seekable()=False, seek() raises."""

            def __init__(self, data: bytes) -> None:
                self._data = data
                self._pos = 0

            def fileno(self) -> int:
                raise io.UnsupportedOperation("no real fd")

            def seekable(self) -> bool:
                return False

            def seek(self, pos: int, whence: int = 0) -> int:
                raise io.UnsupportedOperation("underlying stream is not seekable")

            def tell(self) -> int:
                return self._pos

            def __len__(self) -> int:
                return len(self._data)

            def read(self, size: int = -1) -> bytes:
                if size == -1:
                    chunk = self._data[self._pos :]
                    self._pos = len(self._data)
                else:
                    chunk = self._data[self._pos : self._pos + size]
                    self._pos += len(chunk)
                return chunk

        stream = NonSeekableStream(b"streaming content")
        m = MultipartEncoder(
            [("file", ("data.bin", stream, "application/octet-stream"))],  # type: ignore[list-item]
            boundary=self.boundary,
        )
        m.read()
        with pytest.raises(UnrewindableBodyError, match="non-seekable stream"):
            m.seek(0, 0)

    def test_seek_with_no_seek_method_raises_unrewindable(self) -> None:
        """seek(0, 0) on an encoder whose FileWrapper body has no seek() method
        raises UnrewindableBodyError (not AttributeError), even when the stream
        also lacks seekable()."""
        from urllib3.exceptions import UnrewindableBodyError

        class NoSeekStream:
            """Has fileno (raises), tell, __len__, read — but NO seek or seekable."""

            def __init__(self, data: bytes) -> None:
                self._data = data
                self._pos = 0

            def fileno(self) -> int:
                raise io.UnsupportedOperation("no real fd")

            def tell(self) -> int:
                return self._pos

            def __len__(self) -> int:
                return len(self._data)

            def read(self, size: int = -1) -> bytes:
                if size == -1:
                    chunk = self._data[self._pos :]
                    self._pos = len(self._data)
                else:
                    chunk = self._data[self._pos : self._pos + size]
                    self._pos += len(chunk)
                return chunk

        stream = NoSeekStream(b"content")
        m = MultipartEncoder(
            [("file", ("data.bin", stream, "application/octet-stream"))],  # type: ignore[list-item]
            boundary=self.boundary,
        )
        m.read()
        with pytest.raises(UnrewindableBodyError, match="no seek\\(\\) method"):
            m.seek(0, 0)

    def test_custom_bytes_io_with_non_base_binary_io(self) -> None:
        """_CustomBytesIO should handle BinaryIO-like objects that are not
        subclasses of RawIOBase or BufferedIOBase (the else branch)."""

        class DuckTypeBinaryIO:
            def __init__(self, data: bytes) -> None:
                self._buf = io.BytesIO(data)

            def read(self, n: int = -1) -> bytes:
                return self._buf.read(n)

        custom = _CustomBytesIO(DuckTypeBinaryIO(b"duck typed"))  # type: ignore[arg-type]
        assert custom.read() == b"duck typed"
