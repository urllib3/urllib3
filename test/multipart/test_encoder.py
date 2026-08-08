from __future__ import annotations

import io
import os
import tempfile
import typing
import unittest

import pytest

from urllib3 import filepost
from urllib3.exceptions import UnrewindableBodyError
from urllib3.fields import RequestField
from urllib3.multipart import MultipartDecoder, MultipartEncoder, Part
from urllib3.multipart.encoder import (
    FileWrapper,
    _CustomBytesIO,
    coerce_data,
    encode_with,
    total_len,
)


class LargeFileMock:
    """Simulates a large file-like object without allocating real memory."""

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

    def test_can_read_after_writing_to(self) -> None:
        self.instance.write(b"example text")
        self.instance.seek(0, 0)
        assert self.instance.read() == b"example text"

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

    def test_constructs_from_buffered_io(self) -> None:
        instance = _CustomBytesIO(io.BytesIO(b"buffered"))
        assert instance.read() == b"buffered"

    def test_constructs_from_generic_reader(self) -> None:
        class Reader:
            def read(self) -> bytes:
                return b"generic"

        instance = _CustomBytesIO(Reader())  # type: ignore[arg-type]
        assert instance.read() == b"generic"


class TestFileWrapper:
    def test_peek_seekable_unbuffered_stream_does_not_advance(self) -> None:
        class Stream:
            def __init__(self) -> None:
                self.position = 0

            def __len__(self) -> int:
                return 3

            def tell(self) -> int:
                return self.position

            def seek(self, position: int) -> int:
                self.position = position
                return position

            def read(self, size: int = -1) -> bytes:
                end = 3 if size < 0 else self.position + size
                value = b"abc"[self.position : end]
                self.position += len(value)
                return value

        stream = Stream()
        wrapper = FileWrapper(stream)  # type: ignore[arg-type]
        assert wrapper.peek(2) == b"ab"
        assert stream.tell() == 0

    def test_peek_nonrewindable_stream_returns_empty(self) -> None:
        class Stream:
            def __len__(self) -> int:
                return 1

            def tell(self) -> int:
                return 0

            def read(self, size: int = -1) -> bytes:
                return b"x"

        wrapper = FileWrapper(Stream())  # type: ignore[arg-type]
        assert wrapper.peek() == b""


class TestPart(unittest.TestCase):
    def test_read_streams_headers_then_body(self) -> None:
        part = Part(b"HDR\r\n\r\n", _CustomBytesIO(b"BODY"))
        assert part.read(3) == b"HDR"
        assert part.read(4) == b"\r\n\r\n"
        assert part.read() == b"BODY"
        assert part.read() == b""

    def test_read_zero_does_not_advance(self) -> None:
        part = Part(b"HDR", _CustomBytesIO(b"BODY"))
        assert part.read(0) == b""
        assert part.read() == b"HDRBODY"

    def test_read_all_accepts_any_negative_size_or_none(self) -> None:
        for size in (None, -1, -2):
            part = Part(b"HDR", _CustomBytesIO(b"BODY"))
            assert part.read(size) == b"HDRBODY"

    def test_peek_does_not_advance(self) -> None:
        part = Part(b"ABCDEF", _CustomBytesIO(b"body"))
        assert part.peek(3) == b"ABC"
        assert part.peek() == b"ABCDEF"
        assert part.read(2) == b"AB"
        assert part.peek(2) == b"CD"
        assert part.read() == b"CDEFbody"

    def test_peek_with_negative_size_returns_available_data(self) -> None:
        part = Part(b"ABCDEF", _CustomBytesIO(b"body"))
        assert part.peek(-1) == b"ABCDEF"

    def test_peek_body_after_headers(self) -> None:
        part = Part(b"H", _CustomBytesIO(b"xyz"))
        assert part.read(1) == b"H"
        assert part.peek(2) == b"xy"
        assert part.read() == b"xyz"

    def test_peek_body_with_default_size(self) -> None:
        part = Part(b"H", _CustomBytesIO(b"xyz"))
        part.read(1)
        assert part.peek() == b"xyz"

    def test_peek_unseekable_body_without_peek_returns_empty(self) -> None:
        class Body:
            def __len__(self) -> int:
                return 1

            def read(self, size: int = -1) -> bytes:
                return b"x"

        part = Part(b"", Body())  # type: ignore[arg-type]
        assert part.peek() == b""

    def test_peek_default_size_handles_unknown_remaining_length(self) -> None:
        class Body:
            len = -1

            def __init__(self) -> None:
                self.position = 0

            def tell(self) -> int:
                return self.position

            def seek(self, position: int) -> int:
                self.position = position
                return position

            def read(self, size: int = -1) -> bytes:
                data = b"body"[self.position :]
                self.position += len(data)
                return data

        body = Body()
        part = Part(b"", body)  # type: ignore[arg-type]
        assert part.peek() == b"body"
        assert body.tell() == 0

    def test_peek_open_file_body_without_advancing(self) -> None:
        with open(__file__, "rb") as file_obj:
            part = Part(b"H", FileWrapper(file_obj))
            assert part.read(1) == b"H"
            position = file_obj.tell()
            peeked = part.peek(4)
            assert file_obj.tell() == position
            assert peeked.startswith(part.read(4))

    def test_write_to_uses_read(self) -> None:
        part = Part(b"hdr", _CustomBytesIO(b"data"))
        buf = _CustomBytesIO()
        written = part.write_to(buf, 4)
        assert written == 4
        assert buf.read() == b"hdrd"

    def test_rewind_rejects_file_wrapper_without_seek(self) -> None:
        class Body:
            def __len__(self) -> int:
                return 1

            def tell(self) -> int:
                return 0

            def read(self, size: int = -1) -> bytes:
                return b"x"

        part = Part(b"", FileWrapper(Body()))  # type: ignore[arg-type]
        with pytest.raises(UnrewindableBodyError, match=r"no seek\(\) method"):
            part.rewind()

    def test_rewind_rejects_file_wrapper_reporting_unseekable(self) -> None:
        class Body:
            def __len__(self) -> int:
                return 1

            def tell(self) -> int:
                return 0

            def seekable(self) -> bool:
                return False

            def seek(self, position: int) -> int:
                raise AssertionError("seek must not be called")

            def read(self, size: int = -1) -> bytes:
                return b"x"

        part = Part(b"", FileWrapper(Body()))  # type: ignore[arg-type]
        with pytest.raises(UnrewindableBodyError, match="non-seekable"):
            part.rewind()

    def test_rewind_body_without_seek_only_resets_headers(self) -> None:
        class Body:
            def __len__(self) -> int:
                return 1

            def read(self, size: int = -1) -> bytes:
                return b"x"

        part = Part(b"H", Body())  # type: ignore[arg-type]
        part.read(1)
        part.rewind()
        assert part.read(1) == b"H"

    def test_from_field_converts_integer_for_backwards_compatibility(self) -> None:
        field = RequestField("field", 42)  # type: ignore[arg-type]
        field.make_multipart()
        part = Part.from_field(field, "utf-8")
        assert part.read().endswith(b"42")


class TestMultipartEncoder(unittest.TestCase):
    def setUp(self) -> None:
        self.parts = [("field", "value"), ("other_field", "other_value")]
        self.boundary = "this-is-a-boundary"
        self.instance = MultipartEncoder(self.parts, boundary=self.boundary)

    def test_content_type(self) -> None:
        expected = "multipart/form-data; boundary=this-is-a-boundary"
        assert self.instance.content_type == expected

    def test_public_configuration_properties_and_repr(self) -> None:
        assert self.instance.blocksize == 8192 * 4
        assert self.instance.encoding == "utf-8"
        assert self.instance.fields is self.parts
        assert repr(self.instance) == f"<MultipartEncoder: {self.parts!r}>"

    def test_blocksize_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="greater than zero"):
            MultipartEncoder([], blocksize=0)

    def test_next_returns_chunks_then_stops(self) -> None:
        encoder = MultipartEncoder([("field", "value")], boundary="b", blocksize=2)
        chunks = []
        while True:
            try:
                chunks.append(next(encoder))
            except StopIteration:
                break
        expected = filepost.encode_multipart_formdata(
            [("field", "value")], boundary="b"
        )[0]
        assert b"".join(chunks) == expected

    def test_encodes_data_the_same_as_filepost(self) -> None:
        encoded = filepost.encode_multipart_formdata(self.parts, self.boundary)[0]
        assert encoded == self.instance.read()

    def test_encode_multipart_formdata_uses_encoder(self) -> None:
        encoded, content_type = filepost.encode_multipart_formdata(
            self.parts, self.boundary
        )
        encoder = MultipartEncoder(self.parts, boundary=self.boundary)
        assert encoded == encoder.read()
        assert content_type == encoder.content_type

    def test_streams_its_data(self) -> None:
        large_file = LargeFileMock()
        parts: dict[str, str | LargeFileMock] = {
            "some field": "value",
            "some file": large_file,
        }
        encoder = MultipartEncoder(parts)  # type: ignore[arg-type]
        total_size = encoder.len
        read_size = 1024 * 1024 * 128
        already_read = 0
        while True:
            read = encoder.read(read_size)
            already_read += len(read)
            if not read:
                break

        assert encoder._buffer.tell() <= read_size
        assert already_read == total_size

    def test_does_not_buffer_sized_custom_stream_during_construction(self) -> None:
        class SizedStream:
            def __init__(self, data: bytes) -> None:
                self.data = data
                self.position = 0
                self.read_calls = 0

            def __len__(self) -> int:
                return len(self.data)

            def tell(self) -> int:
                return self.position

            def seek(self, position: int) -> int:
                self.position = position
                return position

            def seekable(self) -> bool:
                return True

            def read(self, size: int = -1) -> bytes:
                self.read_calls += 1
                end = len(self.data) if size < 0 else self.position + size
                chunk = self.data[self.position : end]
                self.position += len(chunk)
                return chunk

        stream = SizedStream(b"x" * (1024 * 1024))
        encoder = MultipartEncoder(
            [("file", ("data.bin", stream, "application/octet-stream"))],  # type: ignore[list-item]
            boundary=self.boundary,
        )

        assert stream.read_calls == 0
        assert len(encoder.read(1024)) == 1024
        assert stream.read_calls == 1

    def test_stream_ending_before_declared_length_raises(self) -> None:
        class TruncatedStream:
            def __init__(self) -> None:
                self.position = 0

            def __len__(self) -> int:
                return 10

            def tell(self) -> int:
                return self.position

            def read(self, size: int = -1) -> bytes:
                if self.position:
                    return b""
                self.position = 3
                return b"abc"

        encoder = MultipartEncoder(
            [("file", ("data.bin", TruncatedStream(), "application/octet-stream"))],  # type: ignore[list-item]
            boundary=self.boundary,
        )
        with pytest.raises(OSError, match="ended before its declared length"):
            encoder.read()

    @pytest.mark.limit_memory("3 MB", current_thread_only=True)
    def test_memory_usage_streaming_large_file(self) -> None:
        """Streaming a 10 MB file should stay under a 3 MB memory limit."""
        file_size_mb = 10
        chunk_size = 8192 * 4
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
            tmp.write(b"x" * (file_size_mb * 1024 * 1024))
            tmp_name = tmp.name
        try:
            with open(tmp_name, "rb") as fd:
                encoder = MultipartEncoder(
                    [
                        ("field", "value"),
                        ("file", ("data.bin", fd, "application/octet-stream")),
                    ],
                    boundary=self.boundary,
                )
                total_size = encoder.len
                read_so_far = 0
                while True:
                    chunk = encoder.read(chunk_size)
                    if not chunk:
                        break
                    read_so_far += len(chunk)
                assert read_so_far == total_size
        finally:
            os.unlink(tmp_name)

    def test_length_is_correct(self) -> None:
        encoded = filepost.encode_multipart_formdata(self.parts, self.boundary)[0]
        assert len(encoded) == self.instance.len

    def test_length_larger_than_platform_ssize_is_supported(self) -> None:
        class HugeStream:
            position = 0

            def __len__(self) -> int:
                return 2**100

            def tell(self) -> int:
                return self.position

            def read(self, size: int = -1) -> bytes:
                return b""

        encoder = MultipartEncoder(
            [("file", ("huge.bin", HugeStream(), "application/octet-stream"))],  # type: ignore[list-item]
            boundary="b",
        )
        assert encoder.len > 2**100
        assert encoder.content_length == str(encoder.len)

    def test_encodes_with_readable_data_without_invented_filename(self) -> None:
        s = io.BytesIO(b"value")
        m = MultipartEncoder([("field", s)], boundary=self.boundary)
        body = m.read()
        assert body == (
            b"--this-is-a-boundary\r\n"
            b'Content-Disposition: form-data; name="field"\r\n\r\n'
            b"value\r\n"
            b"--this-is-a-boundary--\r\n"
        )
        assert b'filename="unknown"' not in body

    def test_bytesio_is_not_copied_during_construction(self) -> None:
        stream = io.BytesIO(b"x" * (1024 * 1024))
        encoder = MultipartEncoder(
            [("file", ("data.bin", stream, "application/octet-stream"))],
            boundary=self.boundary,
        )
        assert isinstance(encoder._parts[0].body, FileWrapper)
        assert encoder._parts[0].body.fd is stream

    def test_reads_open_file_objects(self) -> None:
        with open(__file__, "rb") as fd:
            m = MultipartEncoder([("field", "foo"), ("file", fd)])
            assert m.read() is not None

    def test_file_object_at_nonzero_position_sends_full_content(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"full content")
            tmp_name = tmp.name
        try:
            with open(tmp_name, "rb") as fd:
                fd.read(5)
                m = MultipartEncoder(
                    [("file", ("data.bin", fd, "application/octet-stream"))]
                )
                body = m.read()
            assert b"full content" in body
        finally:
            os.unlink(tmp_name)

    def test_non_seekable_stream_at_nonzero_position_raises(self) -> None:
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
        reader.read(5)
        with pytest.raises(
            ValueError, match="Non-seekable stream is at a non-zero position"
        ):
            MultipartEncoder(
                [("file", ("data.bin", reader, "application/octet-stream"))]
            )

    def test_int_field_value_backwards_compat(self) -> None:
        m = MultipartEncoder([("n", 42)], boundary=self.boundary)
        assert b"42" in m.read()

    def test_filename_hinting_from_file_object(self) -> None:
        with open(__file__, "rb") as fd:
            m = MultipartEncoder([("file", fd)])
            body = m.read().decode("utf-8", errors="replace")
            expected_name = os.path.basename(__file__)
            assert f'filename="{expected_name}"' in body

    def test_filename_hinting_not_applied_to_tuple_values(self) -> None:
        with open(__file__, "rb") as fd:
            m = MultipartEncoder([("file", ("custom.txt", fd, "text/plain"))])
            body = m.read().decode("utf-8", errors="replace")
            assert 'filename="custom.txt"' in body

    def test_accepts_custom_headers(self) -> None:
        fields = [
            (
                "test",
                (
                    "filename",
                    b"filecontent",
                    "application/json",
                    {"X-My-Header": "my-value"},
                ),
            )
        ]
        m = MultipartEncoder(fields=fields)
        output = m.read().decode("utf-8")
        assert output.index("X-My-Header: my-value\r\n") > 0

    def test_accepts_request_field_sequence_items(self) -> None:
        field = RequestField("field", b"value")
        field.make_multipart()
        encoder = MultipartEncoder([field], boundary="b")
        assert encoder.read() == (
            b"--b\r\n"
            b'Content-Disposition: form-data; name="field"\r\n\r\n'
            b"value\r\n--b--\r\n"
        )

    def test_two_item_file_tuple_guesses_content_type(self) -> None:
        encoder = MultipartEncoder(
            [("file", ("example.txt", b"value"))], boundary="b"
        )
        assert b"Content-Type: text/plain\r\n" in encoder.read()

    def test_invalid_file_tuple_length_raises(self) -> None:
        with pytest.raises(ValueError, match="must contain 2, 3, or 4 items"):
            MultipartEncoder(
                [("file", ("name", b"value", "text/plain", {}, "extra"))],  # type: ignore[list-item]
                boundary="b",
            )

    def test_bytes_filename_hint_and_content_type(self) -> None:
        class Stream(io.BytesIO):
            name = b"example.bin"

        encoder = MultipartEncoder(
            [("file", Stream(b"value"))], boundary="b"
        )
        body = encoder.read()
        assert b'filename="example.bin"' in body
        assert b"Content-Type: application/octet-stream\r\n" in body

    def test_pseudo_filename_is_not_used(self) -> None:
        class Stream(io.BytesIO):
            name = "<stdin>"

        encoder = MultipartEncoder(
            [("file", Stream(b"value"))], boundary="b"
        )
        assert b"filename=" not in encoder.read()

    def test_bytes_content_type_is_decoded(self) -> None:
        encoder = MultipartEncoder(
            [("file", ("name", b"value", b"application/example"))],
            boundary="b",
        )
        assert b"Content-Type: application/example\r\n" in encoder.read()

    def test_no_parts(self) -> None:
        fields: list[tuple[str, str]] = []
        boundary = "--90967316f8404798963cce746a4f4ef9"
        m = MultipartEncoder(fields=fields, boundary=boundary)
        output = m.read().decode("utf-8")
        assert output == "----90967316f8404798963cce746a4f4ef9--\r\n"

    def test_empty_boundary_preserves_filepost_behavior(self) -> None:
        encoder = MultipartEncoder([], boundary="")
        assert encoder.read() == b"----\r\n"

    def test_boundary_property_is_unprefixed(self) -> None:
        assert self.instance.boundary == self.boundary

    def test_bytes_like_fields_preserve_filepost_compatibility(self) -> None:
        for value in (bytearray(b"x"), memoryview(b"x")):
            body, content_type = filepost.encode_multipart_formdata(
                [("field", value)], boundary="b"
            )
            assert body == (
                b"--b\r\n"
                b'Content-Disposition: form-data; name="field"\r\n\r\n'
                b"x\r\n"
                b"--b--\r\n"
            )
            assert content_type == "multipart/form-data; boundary=b"

    def test_arbitrary_buffer_protocol_preserves_filepost_compatibility(self) -> None:
        from array import array

        body, _ = filepost.encode_multipart_formdata(
            [("field", array("B", [65, 66]))],  # type: ignore[list-item]
            boundary="b",
        )
        assert body == (
            b"--b\r\n"
            b'Content-Disposition: form-data; name="field"\r\n\r\n'
            b"AB\r\n"
            b"--b--\r\n"
        )

    def test_headers_property(self) -> None:
        headers = self.instance.headers
        assert headers["Content-Type"] == self.instance.content_type
        assert headers["Content-Length"] == self.instance.content_length

    def test_iterable_interface(self) -> None:
        chunks = list(self.instance)
        combined = b"".join(chunks)
        expected = filepost.encode_multipart_formdata(self.parts, self.boundary)[0]
        assert combined == expected

    def test_iterator_drains_buffer_after_closing_boundary_is_generated(self) -> None:
        encoder = MultipartEncoder([("field", b"")], boundary="b", blocksize=1)
        expected = filepost.encode_multipart_formdata([("field", b"")], boundary="b")[0]
        assert b"".join(encoder) == expected

    def test_seek_rewinds_to_start(self) -> None:
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

    def test_seek_rewinds_with_file_parts(self) -> None:
        with open(__file__, "rb") as fd:
            m = MultipartEncoder(
                [("field", "value"), ("file", ("test.py", fd, "text/plain"))],
                boundary=self.boundary,
            )
            first = m.read()
            m.seek(0)
            second = m.read()
        assert first == second

    def test_same_seekable_stream_can_be_used_for_multiple_parts(self) -> None:
        stream = io.BytesIO(b"abc")
        encoder = MultipartEncoder(
            [
                ("one", ("one.bin", stream, "application/octet-stream")),
                ("two", ("two.bin", stream, "application/octet-stream")),
            ],
            boundary="b",
        )
        body = encoder.read()
        decoder = MultipartDecoder(body, content_type=encoder.content_type)

        assert len(body) == encoder.len
        assert [part.data for part in decoder.parts] == [b"abc", b"abc"]

    def test_same_nonseekable_stream_cannot_be_used_for_multiple_parts(self) -> None:
        class Stream:
            def __init__(self) -> None:
                self.position = 0

            def __len__(self) -> int:
                return 3

            def tell(self) -> int:
                return self.position

            def read(self, size: int = -1) -> bytes:
                data = b"abc"[self.position :]
                self.position += len(data)
                return data

        stream = Stream()
        with pytest.raises(ValueError, match="same non-seekable stream"):
            MultipartEncoder(
                [("one", stream), ("two", stream)],  # type: ignore[list-item]
                boundary="b",
            )

    def test_seek_nonzero_raises(self) -> None:
        with pytest.raises(UnrewindableBodyError, match="only supports seek\\(0"):
            self.instance.seek(10, 0)

    def test_seek_with_non_seekable_part_raises_unrewindable(self) -> None:
        class NonSeekableStream:
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
        class NoSeekStream:
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

    def test_seek_method_raising_unsupported_is_unrewindable(self) -> None:
        class FailingSeekStream:
            def __init__(self) -> None:
                self.position = 0

            def __len__(self) -> int:
                return 7

            def tell(self) -> int:
                return self.position

            def seek(self, position: int) -> typing.NoReturn:
                raise io.UnsupportedOperation("not seekable")

            def read(self, size: int = -1) -> bytes:
                data = b"content"[self.position :]
                self.position += len(data)
                return data

        encoder = MultipartEncoder(
            [
                (  # type: ignore[list-item]
                    "file",
                    (
                        "data.bin",
                        FailingSeekStream(),
                        "application/octet-stream",
                    ),
                )
            ],
            boundary=self.boundary,
        )
        assert not encoder.seekable()
        with pytest.raises(UnrewindableBodyError, match="non-seekable stream"):
            encoder.seek(0)

    def test_decoder_round_trip(self) -> None:
        body = self.instance.read()
        decoder = MultipartDecoder(body, content_type=self.instance.content_type)
        assert len(decoder.parts) == 2
        assert decoder.parts[0].data == b"value"
        assert decoder.parts[1].data == b"other_value"

    def test_unsupported_data_type_raises_type_error(self) -> None:
        with pytest.raises(
            TypeError, match="Unsupported data type for multipart encoding"
        ):
            coerce_data(12345, "utf-8")  # type: ignore[arg-type]

    def test_total_len_unsupported_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unable to compute size"):
            total_len(object())  # type: ignore[arg-type]

    def test_encode_with_none_preserves_none(self) -> None:
        assert encode_with(None, "utf-8") is None

    def test_total_len_rejects_negative_dunder_len(self) -> None:
        class NegativeLength:
            def __len__(self) -> int:
                return -1

        with pytest.raises(ValueError, match="should return >= 0"):
            total_len(NegativeLength())

    def test_coerce_data_preserves_custom_bytes_io(self) -> None:
        data = _CustomBytesIO(b"data")
        assert coerce_data(data, "utf-8") is data

    def test_coerce_data_rejects_fileno_stream_without_position(self) -> None:
        class Stream:
            def fileno(self) -> int:
                raise io.UnsupportedOperation

            def read(self, size: int = -1) -> bytes:
                return b"data"

        with pytest.raises(ValueError, match=r"no tell\(\) method"):
            coerce_data(Stream(), "utf-8")  # type: ignore[arg-type]

    def test_coerce_data_rejects_reader_without_position(self) -> None:
        class Stream:
            def read(self, size: int = -1) -> bytes:
                return b"data"

        with pytest.raises(ValueError, match=r"no tell\(\) method"):
            coerce_data(Stream(), "utf-8")  # type: ignore[arg-type]

    def test_read_with_none_size_returns_all_data(self) -> None:
        expected = filepost.encode_multipart_formdata(self.parts, self.boundary)[0]
        result = self.instance.read(None)
        assert result == expected

    def test_read_with_other_negative_size_returns_all_data(self) -> None:
        expected = filepost.encode_multipart_formdata(self.parts, self.boundary)[0]
        assert self.instance.read(-2) == expected

    def test_latin1_boundary_matches_encode_multipart_formdata(self) -> None:
        boundary = "caf\xe9"
        expected = filepost.encode_multipart_formdata(self.parts, boundary)[0]
        encoder = MultipartEncoder(self.parts, boundary=boundary)
        assert encoder.read() == expected
        assert encoder.len == len(expected)
