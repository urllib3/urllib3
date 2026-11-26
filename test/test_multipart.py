from __future__ import annotations

import io

import pytest

from urllib3.fields import RequestField
from urllib3.filepost import encode_multipart_formdata
from urllib3.multipart import MultipartDecoder, MultipartEncoder, Part

BOUNDARY = "!! test boundary !!"
BOUNDARY_BYTES = BOUNDARY.encode()


def read_in_chunks(stream: MultipartEncoder | Part, size: int) -> bytes:
    chunks = []
    while True:
        chunk = stream.read(size)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


class NonSeekableStream(io.RawIOBase):
    """A readable stream that cannot seek and counts the bytes it served."""

    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        data = self._buffer.read(size)
        self.bytes_read += len(data)
        return data

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False


class GeneratingStream(io.RawIOBase):
    """Produces a large body on the fly without storing it in memory."""

    def __init__(self, total: int) -> None:
        self._remaining = total
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        if self._remaining <= 0:
            return b""
        if size is None or size < 0 or size > self._remaining:
            size = self._remaining
        self._remaining -= size
        self.bytes_read += size
        return b"g" * size

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False


class ExplodingSeekableStream(io.RawIOBase):
    """A readable stream whose seekable() raises."""

    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        raise OSError("seekable is broken")


class SeekFailingStream(io.RawIOBase):
    """A stream that claims to be seekable but whose seek() raises."""

    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._buffer.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        raise OSError("seek is broken")


class TestPart:
    def test_read_and_tell(self) -> None:
        part = Part('Content-Disposition: form-data; name="k"\r\n\r\n', b"value")
        assert part.tell() == 0
        assert part.read(10) == b"Content-Di"
        assert part.tell() == 10
        rest = part.read()
        assert rest.endswith(b"value")
        assert part.read() == b""
        assert part.read(1) == b""

    def test_peek_does_not_consume(self) -> None:
        part = Part("X-Test: yes\r\n\r\n", b"abcdef")
        peeked = part.peek(12)
        assert peeked == b"X-Test: yes\r"
        assert part.tell() == 0
        assert part.peek(12) == peeked
        assert part.read(12) == peeked
        # Peeking across the header/data boundary.
        assert part.peek(4) == b"\n\r\na"
        assert part.read() == b"\n\r\nabcdef"

    def test_seek_rewinds(self) -> None:
        part = Part("X-Test: yes\r\n\r\n", b"abcdef")
        expected = part.read()
        part.seek(0, 0)
        assert part.tell() == 0
        assert part.read() == expected

    def test_seek_partial_is_unsupported(self) -> None:
        part = Part("X-Test: yes\r\n\r\n", b"abcdef")
        with pytest.raises(io.UnsupportedOperation):
            part.seek(1, io.SEEK_SET)
        with pytest.raises(io.UnsupportedOperation):
            part.seek(0, io.SEEK_END)

    def test_headers_and_length(self) -> None:
        part = Part(
            'Content-Disposition: form-data; name="k"; filename="f.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n",
            b"hello",
        )
        assert part.headers.endswith(b"\r\n\r\n")
        assert part.header_dict == {
            "Content-Disposition": 'form-data; name="k"; filename="f.txt"',
            "Content-Type": "text/plain",
        }
        assert part.name == "k"
        assert part.filename == "f.txt"
        assert part.length == len(part.headers) + len(b"hello")

    def test_str_and_int_data(self) -> None:
        assert Part("", "héllo").read().endswith("héllo".encode())
        # int data is converted to str for backwards compatibility.
        assert Part("", 42).read().endswith(b"42")

    def test_invalid_data_type(self) -> None:
        with pytest.raises(TypeError):
            Part("", object())  # type: ignore[arg-type]

    def test_file_data_is_streamed_and_rewindable(self) -> None:
        backing = io.BytesIO(b"file-body")
        part = Part('Content-Disposition: form-data; name="f"\r\n\r\n', backing)
        assert part.seekable()
        assert part.length is not None
        expected = part.read()
        assert expected.endswith(b"file-body")
        part.seek(0, 0)
        assert part.read() == expected

    def test_non_seekable_stream_cannot_rewind_after_read(self) -> None:
        stream = NonSeekableStream(b"streamed")
        part = Part('Content-Disposition: form-data; name="f"\r\n\r\n', stream)  # type: ignore[arg-type]
        assert not part.seekable()
        assert part.length is None
        assert part.read().endswith(b"streamed")
        with pytest.raises(io.UnsupportedOperation):
            part.seek(0, 0)

    def test_read_zero_and_peek_variants(self) -> None:
        part = Part('Content-Disposition: form-data; name="k"\r\n\r\n', b"abcdef")
        assert part.read(0) == b""
        assert part.peek(0) == b""
        peeked = part.peek()
        assert peeked.startswith(b"Content-Disposition")
        assert part.readable() is True

    def test_name_and_filename_without_disposition(self) -> None:
        part = Part("X-Test: yes\r\n\r\n", b"data")
        assert part.name is None
        assert part.filename is None

    def test_unquoted_disposition_param(self) -> None:
        part = Part("Content-Disposition: form-data; name=plain\r\n\r\n", b"data")
        assert part.name == "plain"

    def test_stream_with_broken_seekable(self) -> None:
        stream = ExplodingSeekableStream(b"streamed")
        part = Part(
            'Content-Disposition: form-data; name="f"\r\n\r\n',
            stream,  # type: ignore[arg-type]
        )
        assert part.length is None
        assert part.read().endswith(b"streamed")

    def test_stream_with_broken_seek_has_unknown_length(self) -> None:
        stream = SeekFailingStream(b"streamed")
        part = Part(
            'Content-Disposition: form-data; name="f"\r\n\r\n',
            stream,  # type: ignore[arg-type]
        )
        assert part.length is None


class TestMultipartEncoder:
    @pytest.mark.parametrize(
        "fields",
        [
            dict(k="v", k2="v2"),
            [("k", "v"), ("k2", "v2")],
            [("k", b"v"), ("k2", b"v2")],
            [("k", ("somename", b"v"))],
            [("k", ("somefile.txt", b"v", "image/jpeg"))],
            [
                RequestField(
                    "k",
                    b"v",
                    filename="somefile.txt",
                    headers={"Content-Type": "image/jpeg"},
                )
            ],
        ],
    )
    def test_output_matches_encode_multipart_formdata(
        self, fields: list[tuple[str, object]] | dict[str, str]
    ) -> None:
        encoder = MultipartEncoder(fields, boundary=BOUNDARY)  # type: ignore[arg-type]
        expected, content_type = encode_multipart_formdata(
            fields,  # type: ignore[arg-type]
            boundary=BOUNDARY,
        )
        assert encoder.read() == expected
        assert encoder.content_type == content_type
        assert len(encoder) == len(expected)

    def test_wire_format_with_file_field(self) -> None:
        encoder = MultipartEncoder([("k", ("somename", b"v"))], boundary=BOUNDARY)
        expected = (
            b"--" + BOUNDARY_BYTES + b"\r\n"
            b'Content-Disposition: form-data; name="k"; filename="somename"\r\n'
            b"Content-Type: application/octet-stream\r\n"
            b"\r\n"
            b"v\r\n"
            b"--" + BOUNDARY_BYTES + b"--\r\n"
        )
        assert encoder.read() == expected

    @pytest.mark.parametrize("chunk_size", [1, 3, 7, 64, 8192])
    def test_chunked_reads(self, chunk_size: int) -> None:
        fields = [("k", "v"), ("file", ("f.bin", b"x" * 1000))]
        encoder = MultipartEncoder(fields, boundary=BOUNDARY)  # type: ignore[arg-type]
        expected, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)  # type: ignore[arg-type]
        assert read_in_chunks(encoder, chunk_size) == expected

    def test_peek(self) -> None:
        encoder = MultipartEncoder([("k", "v")], boundary=BOUNDARY)
        prefix = b"--" + BOUNDARY_BYTES + b"\r\n"
        assert encoder.peek(len(prefix)) == prefix
        assert encoder.tell() == 0
        assert encoder.read(len(prefix)) == prefix

    def test_complete_rewind(self) -> None:
        fields = [("k", "v"), ("file", ("f.bin", io.BytesIO(b"y" * 500)))]
        encoder = MultipartEncoder(fields, boundary=BOUNDARY)  # type: ignore[arg-type]
        expected, _ = encode_multipart_formdata(
            [("k", "v"), ("file", ("f.bin", b"y" * 500))], boundary=BOUNDARY
        )
        # Rewind mid-stream.
        encoder.read(50)
        encoder.seek(0, 0)
        assert encoder.tell() == 0
        assert encoder.read() == expected
        # Rewind after a complete read: every part is rewound.
        encoder.seek(0, 0)
        assert encoder.read() == expected

    def test_rewind_attempts_all_parts(self) -> None:
        # The first part cannot rewind once read; the encoder must still
        # attempt to rewind the remaining parts before failing.
        backing = io.BytesIO(b"rewindable")
        fields = [
            ("a", ("a.bin", NonSeekableStream(b"one-way"))),
            ("b", ("b.bin", backing)),
        ]
        encoder = MultipartEncoder(fields, boundary=BOUNDARY)  # type: ignore[arg-type]
        encoder.read()
        assert backing.tell() != 0  # The stream was consumed.
        with pytest.raises(io.UnsupportedOperation):
            encoder.seek(0, 0)
        assert backing.tell() == 0  # ...but its rewind was still attempted.

    def test_file_data_is_read_incrementally(self) -> None:
        payload = b"z" * 100_000
        stream = NonSeekableStream(payload)
        encoder = MultipartEncoder([("file", ("big.bin", stream))], boundary=BOUNDARY)  # type: ignore[list-item]
        first = encoder.read(1024)
        assert len(first) == 1024
        # Only a bounded amount of the file has been pulled so far.
        assert stream.bytes_read <= 1024
        rest = encoder.read()
        assert (
            first + rest
            == encode_multipart_formdata(
                [("file", ("big.bin", payload))], boundary=BOUNDARY
            )[0]
        )

    def test_length_unknown_for_non_seekable_part(self) -> None:
        encoder = MultipartEncoder(
            [("file", ("big.bin", NonSeekableStream(b"data")))],  # type: ignore[list-item]
            boundary=BOUNDARY,
        )
        assert encoder.length is None
        with pytest.raises(TypeError):
            len(encoder)
        assert not encoder.seekable()

    @pytest.mark.limit_memory("5 MB", current_thread_only=True)
    def test_streaming_memory_is_bounded(self) -> None:
        # A 32 MiB part produced on the fly: reading the encoder in chunks
        # must not allocate memory proportional to the body size.
        total = 32 * 1024 * 1024
        stream = GeneratingStream(total)
        encoder = MultipartEncoder([("file", ("big.bin", stream))], boundary=BOUNDARY)  # type: ignore[list-item]
        read_total = 0
        while chunk := encoder.read(65536):
            read_total += len(chunk)
        assert stream.bytes_read == total
        assert read_total > total  # Plus boundary and header overhead.

    def test_seek_rewinds_and_readable(self) -> None:
        fields = [("k", "v"), ("file", ("f.bin", b"x" * 100))]
        encoder = MultipartEncoder(fields, boundary=BOUNDARY)  # type: ignore[arg-type]
        expected, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)  # type: ignore[arg-type]
        assert encoder.read(10) == expected[:10]
        assert encoder.seek(0) == 0
        assert encoder.read() == expected
        assert encoder.readable() is True
        with pytest.raises(io.UnsupportedOperation):
            encoder.seek(1)
        with pytest.raises(io.UnsupportedOperation):
            encoder.seek(0, io.SEEK_END)


class TestMultipartDecoder:
    def test_round_trip(self) -> None:
        file_content = b"line1\r\nline2\r\n"
        fields = [
            ("k", "v"),
            ("file", ("notes.txt", file_content)),
            ("bin", ("data.bin", b"\x00\x01\x02\r\n\xff")),
        ]
        encoder = MultipartEncoder(fields, boundary=BOUNDARY)  # type: ignore[arg-type]
        decoder = MultipartDecoder.from_content_type(
            encoder.read(), encoder.content_type
        )
        assert len(decoder) == 3

        text_part, file_part, bin_part = decoder.parts
        assert text_part.name == "k"
        assert text_part.filename is None
        assert text_part.read().endswith(b"v")

        assert file_part.name == "file"
        assert file_part.filename == "notes.txt"
        assert file_part.header_dict["Content-Type"] == "text/plain"
        body = file_part.read()
        assert body[len(file_part.headers) :] == file_content

        assert bin_part.name == "bin"
        assert bin_part.read()[len(bin_part.headers) :] == b"\x00\x01\x02\r\n\xff"

    def test_decoder_accepts_encoder_as_body(self) -> None:
        encoder = MultipartEncoder([("k", "v")], boundary=BOUNDARY)
        decoder = MultipartDecoder(encoder, BOUNDARY)  # type: ignore[arg-type]
        assert [part.name for part in decoder] == ["k"]

    def test_preamble_and_epilogue_are_ignored(self) -> None:
        body = (
            b"preamble\r\n"
            b"--" + BOUNDARY_BYTES + b"\r\n"
            b'Content-Disposition: form-data; name="k"\r\n'
            b"\r\n"
            b"v\r\n"
            b"--" + BOUNDARY_BYTES + b"--\r\n"
            b"epilogue"
        )
        decoder = MultipartDecoder(body, BOUNDARY_BYTES)
        assert len(decoder) == 1
        assert decoder[0].name == "k"
        assert decoder[0].read().endswith(b"v")

    def test_quoted_boundary(self) -> None:
        encoder = MultipartEncoder([("k", "v")], boundary=BOUNDARY)
        decoder = MultipartDecoder.from_content_type(
            encoder.read(),
            f'multipart/form-data; boundary="{BOUNDARY}"',
        )
        assert len(decoder) == 1

    def test_missing_boundary(self) -> None:
        with pytest.raises(ValueError):
            MultipartDecoder.from_content_type(b"", "multipart/form-data")

    def test_lf_only_line_endings(self) -> None:
        body = (
            b"--" + BOUNDARY_BYTES + b"\n"
            b'Content-Disposition: form-data; name="k"\n'
            b"\n"
            b"value\n"
            b"--" + BOUNDARY_BYTES + b"--\n"
        )
        decoder = MultipartDecoder(body, BOUNDARY)
        assert len(decoder.parts) == 1
        assert decoder.parts[0].name == "k"

    def test_garbage_and_headerless_chunks_are_skipped(self) -> None:
        body = (
            b"--" + BOUNDARY_BYTES + b"garbage-without-line-break"
            b"--" + BOUNDARY_BYTES + b"\r\nno header separator here"
            b"--" + BOUNDARY_BYTES + b"\r\n"
            b'Content-Disposition: form-data; name="k"\r\n'
            b"\r\n"
            b"value\r\n"
            b"--" + BOUNDARY_BYTES + b"--\r\n"
        )
        decoder = MultipartDecoder(body, BOUNDARY)
        assert len(decoder.parts) == 1
        assert decoder.parts[0].name == "k"


class TestEncodeMultipartFormdata:
    def test_int_field_value(self) -> None:
        encoded, _ = encode_multipart_formdata([("k", 42)], boundary=BOUNDARY)  # type: ignore[list-item]
        assert b"\r\n42\r\n" in encoded

    def test_file_like_field_value(self) -> None:
        # File-like data used to raise TypeError; it is now streamed
        # through the encoder and included in the returned body.
        encoded, _ = encode_multipart_formdata(
            [("file", ("f.bin", io.BytesIO(b"streamed-bytes")))],  # type: ignore[list-item]
            boundary=BOUNDARY,
        )
        assert b"streamed-bytes" in encoded
