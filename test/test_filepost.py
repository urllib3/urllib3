from __future__ import annotations

import pathlib

import pytest

from urllib3.fields import RequestField
from urllib3.filepost import _TYPE_FIELDS, encode_multipart_formdata

BOUNDARY = "!! test boundary !!"
BOUNDARY_BYTES = BOUNDARY.encode()


class TestMultipartEncoding:
    @pytest.mark.parametrize(
        "fields", [dict(k="v", k2="v2"), [("k", "v"), ("k2", "v2")]]
    )
    def test_input_datastructures(self, fields: _TYPE_FIELDS) -> None:
        encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)
        assert encoded.count(BOUNDARY_BYTES) == 3

    @pytest.mark.parametrize(
        "fields",
        [
            [("k", "v"), ("k2", "v2")],
            [("k", b"v"), ("k2", b"v2")],
            [("k", b"v"), ("k2", "v2")],
        ],
    )
    def test_field_encoding(self, fields: _TYPE_FIELDS) -> None:
        encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)
        expected = (
            b"--" + BOUNDARY_BYTES + b"\r\n"
            b'Content-Disposition: form-data; name="k"\r\n'
            b"\r\n"
            b"v\r\n"
            b"--" + BOUNDARY_BYTES + b"\r\n"
            b'Content-Disposition: form-data; name="k2"\r\n'
            b"\r\n"
            b"v2\r\n"
            b"--" + BOUNDARY_BYTES + b"--\r\n"
        )

        assert encoded == expected

        assert content_type == "multipart/form-data; boundary=" + str(BOUNDARY)

    def test_filename(self) -> None:
        fields = [("k", ("somename", b"v"))]

        encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)
        expected = (
            b"--" + BOUNDARY_BYTES + b"\r\n"
            b'Content-Disposition: form-data; name="k"; filename="somename"\r\n'
            b"Content-Type: application/octet-stream\r\n"
            b"\r\n"
            b"v\r\n"
            b"--" + BOUNDARY_BYTES + b"--\r\n"
        )

        assert encoded == expected

        assert content_type == "multipart/form-data; boundary=" + str(BOUNDARY)

    def test_textplain(self) -> None:
        fields = [("k", ("somefile.txt", b"v"))]

        encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)
        expected = (
            b"--" + BOUNDARY_BYTES + b"\r\n"
            b'Content-Disposition: form-data; name="k"; filename="somefile.txt"\r\n'
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"v\r\n"
            b"--" + BOUNDARY_BYTES + b"--\r\n"
        )

        assert encoded == expected

        assert content_type == "multipart/form-data; boundary=" + str(BOUNDARY)

    def test_explicit(self) -> None:
        fields = [("k", ("somefile.txt", b"v", "image/jpeg"))]

        encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)
        expected = (
            b"--" + BOUNDARY_BYTES + b"\r\n"
            b'Content-Disposition: form-data; name="k"; filename="somefile.txt"\r\n'
            b"Content-Type: image/jpeg\r\n"
            b"\r\n"
            b"v\r\n"
            b"--" + BOUNDARY_BYTES + b"--\r\n"
        )

        assert encoded == expected

        assert content_type == "multipart/form-data; boundary=" + str(BOUNDARY)

    def test_bytesio_at_nonzero_position(self) -> None:
        """Verify encode_multipart_formdata sends the full BytesIO content regardless
        of the current file pointer position (uses getvalue(), not read())."""
        import io

        data = io.BytesIO(b"full content")
        data.read(5)  # Advance position to 5 — simulate partial prior read
        fields = [("k", ("file.bin", data, "application/octet-stream"))]

        encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)
        assert b"full content" in encoded

    def test_buffered_reader_at_nonzero_position(self, tmp_path: pathlib.Path) -> None:
        """Verify encode_multipart_formdata sends the full BufferedReader content
        regardless of the current file pointer position (seeks to 0 before read())."""
        import io

        f = tmp_path / "data.bin"
        f.write_bytes(b"full content")
        with f.open("rb") as raw:
            reader = io.BufferedReader(raw)
            reader.read(5)  # Advance position to 5 — simulate partial prior read
            fields = [("k", ("data.bin", reader, "application/octet-stream"))]
            encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)  # type: ignore[arg-type]
        assert b"full content" in encoded

    def test_non_seekable_stream_at_nonzero_position_raises(self) -> None:
        """Verify that passing a non-seekable stream already past position 0 raises
        ValueError instead of silently encoding partial data."""
        import io

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
        fields = [("k", ("data.bin", reader, "application/octet-stream"))]
        with pytest.raises(
            ValueError, match="Non-seekable stream is at a non-zero position"
        ):
            encode_multipart_formdata(fields, boundary=BOUNDARY)  # type: ignore[arg-type]

    def test_buffered_reader_non_seekable_without_tell_raises(self) -> None:
        """A BufferedReader subclass whose seekable() is False and that has no
        tell() must raise ValueError rather than silently encoding from an
        unknown position."""
        import io

        class NoTellBufferedReader(io.BufferedReader):
            def seekable(self) -> bool:
                return False

            def tell(self) -> int:
                raise io.UnsupportedOperation("tell not supported")

        class NonSeekableRaw(io.RawIOBase):
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

        raw = NonSeekableRaw(b"full content")
        reader = NoTellBufferedReader(raw)  # type: ignore[arg-type]
        fields = [("k", ("data.bin", reader, "application/octet-stream"))]
        with pytest.raises((ValueError, io.UnsupportedOperation)):
            encode_multipart_formdata(fields, boundary=BOUNDARY)

    def test_buffered_reader_non_seekable_no_tell_attribute_raises(self) -> None:
        """A BufferedReader subclass whose seekable() is False and that has no
        tell attribute (hasattr returns False) must raise ValueError."""
        import io

        class NoTellAttrBufferedReader(io.BufferedReader):
            """BufferedReader that hides tell so hasattr(..., 'tell') is False."""

            def seekable(self) -> bool:
                return False

            def __getattribute__(self, name: str) -> object:
                if name == "tell":
                    raise AttributeError("tell")
                return super().__getattribute__(name)

        class NonSeekableRaw(io.RawIOBase):
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

        raw = NonSeekableRaw(b"full content")
        reader = NoTellAttrBufferedReader(raw)  # type: ignore[arg-type]
        fields = [("k", ("data.bin", reader, "application/octet-stream"))]
        with pytest.raises(ValueError, match="has no tell\\(\\) method"):
            encode_multipart_formdata(fields, boundary=BOUNDARY)

    def test_request_fields(self) -> None:
        fields = [
            RequestField(
                "k",
                b"v",
                filename="somefile.txt",
                headers={"Content-Type": "image/jpeg"},
            )
        ]

        encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)
        expected = (
            b"--" + BOUNDARY_BYTES + b"\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"\r\n"
            b"v\r\n"
            b"--" + BOUNDARY_BYTES + b"--\r\n"
        )

        assert encoded == expected
