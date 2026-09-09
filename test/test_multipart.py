from __future__ import annotations

import io
from array import array

import pytest

from urllib3.fields import RequestField
from urllib3.filepost import encode_multipart_formdata
from urllib3.multipart import MultipartDecoder, MultipartEncoder, Part


class ShortReader(io.BytesIO):
    def __init__(self, data: bytes, chunk_size: int = 3) -> None:
        super().__init__(data)
        self.chunk_size = chunk_size
        self.requests: list[int] = []

    def read(self, size: int | None = -1) -> bytes:
        assert size is not None and size >= 0, "Unbounded source read"
        self.requests.append(size)
        return super().read(min(size, self.chunk_size))


def read_chunks(stream: io.BufferedIOBase, size: int) -> bytes:
    chunks = []
    while chunk := stream.read(size):
        assert len(chunk) <= size
        chunks.append(chunk)
    return b"".join(chunks)


class TestPart:
    def test_buffering_original_offset_and_ownership(self) -> None:
        source = ShortReader(b"skipabcdefgh")
        source.seek(4)
        part = Part(source)
        assert part.peek(1).startswith(b"a")
        assert part.tell() == 0
        assert part.read(5) == b"abcde"
        assert part.tell() == 5
        assert part.seek(0) == 0
        assert part.read() == b"abcdefgh"
        part.close()
        assert not source.closed
        assert max(source.requests) <= io.DEFAULT_BUFFER_SIZE

    def test_text(self) -> None:
        assert Part("caf\xe9").read() == b"caf\xc3\xa9"

    def test_nonseekable(self) -> None:
        class Nonseekable(io.BytesIO):
            def tell(self) -> int:
                raise io.UnsupportedOperation

            def seekable(self) -> bool:
                return False

        part = Part(Nonseekable(b"value"))
        assert not part.seekable()
        assert part.read() == b"value"
        with pytest.raises(io.UnsupportedOperation):
            part.seek(0)
        with pytest.raises(io.UnsupportedOperation):
            part.raw.seek(0, 0)


class TestMultipartEncoder:
    @pytest.mark.parametrize("size", [1, 3, 17, 8192])
    def test_exact_wire_and_rewind(self, size: int) -> None:
        source = ShortReader(b"abc\x00def")
        encoder = MultipartEncoder.from_fields(
            [("field", "value"), ("file", ("file.bin", source))], boundary="test"
        )
        expected = (
            b'--test\r\nContent-Disposition: form-data; name="field"\r\n\r\nvalue\r\n'
            b'--test\r\nContent-Disposition: form-data; name="file"; filename="file.bin"\r\n'
            b"Content-Type: application/octet-stream\r\n\r\nabc\x00def\r\n--test--\r\n"
        )
        assert encoder.read(0) == b""
        assert encoder.tell() == 0
        assert read_chunks(encoder, size) == expected
        assert encoder.tell() == len(expected)
        assert encoder.read(3) == b""
        assert encoder.seek(0, 0) == 0
        assert encoder.read() == expected
        assert max(source.requests) <= io.DEFAULT_BUFFER_SIZE
        encoder.close()
        assert not source.closed

    @pytest.mark.parametrize(
        "error_type", [io.UnsupportedOperation, ValueError, RuntimeError]
    )
    def test_rewind_attempts_every_part_after_failure(
        self, error_type: type[Exception]
    ) -> None:
        attempts = []

        class RecordedPart(Part):
            def __init__(self, name: str, fails: bool) -> None:
                super().__init__(b"body")
                self.label = name
                self.fails = fails

            def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
                attempts.append(self.label)
                if self.fails:
                    raise error_type(self.label)
                return super().seek(offset, whence)

        parts = [
            RecordedPart("first", True),
            RecordedPart("second", True),
            RecordedPart("last", False),
        ]
        encoder = MultipartEncoder(parts, "boundary")
        encoder.read(10)
        with pytest.raises(io.UnsupportedOperation):
            encoder.seek(0)
        assert attempts == ["first", "second", "last"]
        with pytest.raises(OSError, match="invalid after a failed rewind"):
            encoder.read(1)
        for part in parts:
            part.fails = False
        assert encoder.seek(0) == 0
        assert encoder.read().endswith(b"--boundary--\r\n")

    def test_readinto_uses_bytes_not_element_count(self) -> None:
        encoder = MultipartEncoder([], "b")
        buffer = array("I", [0, 0])
        count = encoder.readinto(buffer)
        assert count == 7
        assert memoryview(buffer).cast("B")[:count].tobytes() == b"--b--\r\n"

    def test_legacy_helper_accepts_streams(self) -> None:
        source = io.BytesIO(b"contents")
        body, content_type = encode_multipart_formdata(
            {"file": ("file.txt", source)}, boundary="b"
        )
        assert isinstance(body, bytes)
        assert b"\r\n\r\ncontents\r\n" in body
        assert content_type == "multipart/form-data; boundary=b"
        assert not source.closed


class TestMultipartDecoder:
    @pytest.mark.parametrize("size", [1, 2, 3, 7, 8192])
    def test_chunk_boundaries_and_lookalikes(self, size: int) -> None:
        payload = b"binary\x00\xff\r\n--bX\r\n--b--X\r\n--b-\r\nend"
        wire = (
            b'--b\r\nContent-Disposition: form-data; name="x"\r\n\r\n'
            + payload
            + b"\r\n--b--\r\n"
        )
        source = ShortReader(wire, size)
        decoder = MultipartDecoder(source, "b", buffer_size=size)
        part = next(decoder)
        assert part.headers["content-disposition"] == 'form-data; name="x"'
        assert read_chunks(part, 3) == payload
        with pytest.raises(StopIteration):
            next(decoder)
        assert max(source.requests) == size
        part.close()
        assert not source.closed

    def test_skip_unread_part_and_keep_parts_separate(self) -> None:
        wire = b"--b\r\n\r\nfirst\r\n--b\r\n\r\nsecond\r\n--b--\r\n"
        decoder = MultipartDecoder(wire, "b", buffer_size=1)
        first = next(decoder)
        assert first.read(1) == b"f"
        second = next(decoder)
        assert second.read() == b"second"
        assert b"second" not in first.read()
        with pytest.raises(StopIteration):
            next(decoder)

    def test_empty_multipart(self) -> None:
        assert list(MultipartDecoder(b"--b--\r\n", "b")) == []

    def test_headers_and_empty_body(self) -> None:
        wire = b"preamble\r\n--b \t\r\nX: first\r\nX: second\r\n continued\r\n\r\n\r\n--b--\t\r\nepilogue"
        decoder = MultipartDecoder(wire, "b", buffer_size=3)
        part = next(decoder)
        assert part.headers.getlist("x") == ["first", "second continued"]
        assert part.read() == b""
        assert list(decoder) == []

    @pytest.mark.parametrize(
        "wire",
        [b"", b"--b\r\nX: value", b"--b\r\n\r\nbody", b"--b\r\n\r\nbody\r\n--b-"],
    )
    def test_truncated_input(self, wire: bytes) -> None:
        with pytest.raises(ValueError):
            for part in MultipartDecoder(wire, "b", buffer_size=1):
                part.read()

    def test_header_limit(self) -> None:
        with pytest.raises(ValueError, match="too long"):
            next(
                MultipartDecoder(
                    b"--b\r\nX: " + b"x" * 100 + b"\r\n\r\n", "b", max_header_size=32
                )
            )

    def test_round_trip(self) -> None:
        encoder = MultipartEncoder(
            [Part(b"one", {"X-Name": "first"}), Part(b"two")], "b"
        )
        decoder = MultipartDecoder(encoder, "b", buffer_size=2)
        bodies = [(dict(part.headers), part.read()) for part in decoder]
        assert bodies == [({"X-Name": "first"}, b"one"), ({}, b"two")]


class TestMultipartCompatibility:
    @pytest.mark.parametrize("body", [bytearray(b"data"), memoryview(b"data")])
    def test_legacy_buffer_values(self, body: bytearray | memoryview) -> None:
        encoded, _ = encode_multipart_formdata({"x": body}, boundary="b")
        assert (
            encoded
            == b'--b\r\nContent-Disposition: form-data; name="x"\r\n\r\ndata\r\n--b--\r\n'
        )

    def test_legacy_boundary_encoding(self) -> None:
        body, content_type = encode_multipart_formdata([], boundary="caf\xe9")
        assert body == b"--caf\xe9--\r\n"
        assert content_type == "multipart/form-data; boundary=caf\xe9"
        assert list(MultipartDecoder(body, "caf\xe9")) == []

    @pytest.mark.parametrize("decoded", [False, True])
    def test_modified_part_headers_are_encoded(self, decoded: bool) -> None:
        if decoded:
            part = next(
                MultipartDecoder(b"--b\r\nX: old\r\n\r\nbody\r\n--b--\r\n", "b")
            )
        else:
            part = Part.from_field(RequestField("field", b"body", headers={"X": "old"}))
        part.headers["X"] = "new"
        wire = MultipartEncoder([part], "b").read()
        assert b"X: new\r\n" in wire
        assert b"X: old\r\n" not in wire

    @pytest.mark.parametrize(
        "wire",
        [
            b"--b\r\nbad-header\r\n\r\n",
            b"--b\r\n continuation\r\n\r\n",
            b"--b\r\n X: value\r\n\r\n",
            b"--b\r\nX : value\r\n\r\n",
        ],
    )
    def test_malformed_header(self, wire: bytes) -> None:
        with pytest.raises(ValueError):
            next(MultipartDecoder(wire, "b", buffer_size=1))

    def test_closing_boundary_without_final_crlf(self) -> None:
        decoder = MultipartDecoder(b"--b\r\n\r\nx\r\n--b--", "b", buffer_size=1)
        assert next(decoder).read() == b"x"
        assert list(decoder) == []

    def test_encoder_rejects_fractional_read_size(self) -> None:
        with pytest.raises(TypeError):
            MultipartEncoder([], "b").read(1.5)  # type: ignore[arg-type]


class RepeatedBody(io.RawIOBase):
    """Generate a large body without allocating it before profiling starts."""

    def __init__(self, size: int) -> None:
        self.remaining = size

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        assert 0 <= size <= io.DEFAULT_BUFFER_SIZE
        count = min(size, self.remaining)
        self.remaining -= count
        return b"x" * count


@pytest.mark.limit_memory("1 MB")
@pytest.mark.parametrize("size", [1024 * 1024, 16 * 1024 * 1024])
@pytest.mark.parametrize("decode", [False, True])
def test_bounded_streaming_memory(size: int, decode: bool) -> None:
    source = RepeatedBody(size)
    encoder = MultipartEncoder([Part(source)], "b")
    reader: io.BufferedIOBase
    if decode:
        decoder = MultipartDecoder(encoder, "b")
        reader = next(decoder)
    else:
        reader = encoder
    count = 0
    while chunk := reader.read(8192):
        count += len(chunk)
        if decode:
            assert chunk == b"x" * len(chunk)
    assert count == size if decode else count == size + len(b"--b\r\n\r\n\r\n--b--\r\n")
    assert source.remaining == 0
    if decode:
        assert list(decoder) == []


class TestMultipartInvalidInputs:
    @pytest.mark.parametrize("boundary", ["", "bad\rboundary", "bad\nboundary"])
    def test_boundary(self, boundary: str) -> None:
        with pytest.raises(ValueError, match="boundary"):
            MultipartEncoder([], boundary)
        with pytest.raises(ValueError, match="boundary"):
            MultipartDecoder(b"", boundary)

    @pytest.mark.parametrize("name,value", [("Bad:Name", "ok"), ("X", "bad\r\nvalue")])
    def test_encoder_headers(self, name: str, value: str) -> None:
        with pytest.raises(ValueError, match="header"):
            MultipartEncoder([Part(b"body", {name: value})], "b")

    @pytest.mark.parametrize("limit", [0, -1])
    def test_decoder_limits(self, limit: int) -> None:
        with pytest.raises(ValueError, match="positive"):
            MultipartDecoder(b"", "b", buffer_size=limit)
        with pytest.raises(ValueError, match="positive"):
            MultipartDecoder(b"", "b", max_header_size=limit)

    @pytest.mark.parametrize("decode", [False, True])
    @pytest.mark.parametrize("text", [False, True])
    def test_invalid_stream_read(self, decode: bool, text: bool) -> None:
        class InvalidReader(io.BytesIO):
            def read(self, size: int | None = -1) -> bytes:
                return "text" if text else b"x" * (size + 1)  # type: ignore[return-value,operator]

        with pytest.raises(TypeError if text else ValueError):
            if decode:
                next(MultipartDecoder(InvalidReader(), "b"))
            else:
                Part(InvalidReader()).read(1)

    @pytest.mark.parametrize(
        "wire",
        [
            b"--b\r\nX: " + b"x" * 40,
            b"--b\r\n" + b"X: x\r\n" * 8 + b"\r\n",
            b"--b\r\n\r\nx\r\n--b--" + b" " * 40 + b"\r\n",
        ],
    )
    def test_oversized_headers_or_padding(self, wire: bytes) -> None:
        with pytest.raises(ValueError, match="too long"):
            for part in MultipartDecoder(wire, "b", buffer_size=1, max_header_size=32):
                part.read()

    def test_encoder_io_contract(self) -> None:
        # Legacy RequestField rendering accepts integer values at runtime.
        field = RequestField("number", 42)  # type: ignore[arg-type]
        encoder = MultipartEncoder([Part.from_field(field)], "b")
        assert encoder.readable()
        assert encoder.seekable()
        assert b"\r\n\r\n42\r\n" in encoder.read(None)
        with pytest.raises(io.UnsupportedOperation):
            encoder.seek(1)
        with pytest.raises(TypeError, match="writable"):
            encoder.readinto(b"immutable")
        encoder.close()
        with pytest.raises(ValueError):
            encoder.read()
        with pytest.raises(ValueError):
            encoder.seek(0)
        with pytest.raises(ValueError):
            encoder.tell()
