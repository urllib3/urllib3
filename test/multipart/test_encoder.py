from __future__ import annotations

import io
import unittest
from pathlib import Path

import pytest

from urllib3 import filepost
from urllib3.multipart.encoder import MultipartEncoder, Part, _CustomBytesIO

preserve_bytes = {"preserve_exact_body_bytes": True}


def test_file_shortened_after_encoder_creation(tmp_path: Path) -> None:
    path = tmp_path / "changing-file.bin"
    path.write_bytes(b"original content")
    with path.open("rb") as body:
        encoder = MultipartEncoder({"file": ("changing-file.bin", body)})
        path.write_bytes(b"short")
        with pytest.raises(OSError, match="ended before its declared length"):
            encoder.read()


@pytest.mark.limit_memory("2 MB")
def test_streaming_memory(tmp_path: Path) -> None:
    path = tmp_path / "upload.bin"
    with path.open("wb") as output:
        output.truncate(64 * 1024 * 1024)
    with path.open("rb") as body:
        encoder = MultipartEncoder({"file": ("upload.bin", body)}, boundary="test")
        expected_length = len(encoder)
        actual_length = 0
        while chunk := encoder.read(64 * 1024):
            actual_length += len(chunk)
        assert actual_length == expected_length


class LargeFileMock(io.BytesIO):
    def __init__(self) -> None:
        # Let's keep track of how many bytes we've given
        self.bytes_read = 0
        # Our limit (1GB)
        self.bytes_max = 1024 * 1024 * 1024

    def fileno(self) -> int:
        return -1

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
        length = min([length, self.bytes_max - self.bytes_read])

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
        self.instance.read() == b"example text"

    def test_can_read_some_after_writing_to(self) -> None:
        self.instance.write(b"example text")
        self.instance.read(6) == b"exampl"

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
        """Accepts a string with encoded unicode characters."""
        s = b"this is a unicode string: \xc3\xa9 \xc3\xa1 \xc7\xab \xc3\xb3"
        self.instance = _CustomBytesIO(s)
        assert self.instance.read() == s


class TestMultipartEncoder(unittest.TestCase):
    def test_rewind_after_partial_and_complete_read(self) -> None:
        body = io.BytesIO(b"prefix-payload")
        body.seek(7)
        encoder = MultipartEncoder({"file": body}, boundary="test")
        expected = filepost.encode_multipart_formdata({"file": b"payload"}, "test")[0]
        assert len(encoder) == len(expected)
        assert encoder.read(3) == expected[:3]
        assert encoder.tell() == 3
        assert encoder.seek(0, 0) == 0
        assert encoder.tell() == 0
        assert encoder.read() == expected
        assert encoder.tell() == len(expected)
        assert encoder.seek(0, 0) == 0
        assert b"".join(iter(lambda: encoder.read(7), b"")) == expected
        assert len(encoder) == len(expected)

    def test_rewind_attempts_all_parts(self) -> None:
        class CannotRewind(io.BytesIO):
            def seek(self, offset: int, whence: int = 0) -> int:
                raise io.UnsupportedOperation("cannot rewind")

        second = io.BytesIO(b"second")
        encoder = MultipartEncoder({"first": CannotRewind(b"first"), "second": second})
        encoder.read()
        with pytest.raises(io.UnsupportedOperation, match="cannot rewind"):
            encoder.seek(0)
        assert second.tell() == 0

    def test_other_seeks_rejected(self) -> None:
        with pytest.raises(io.UnsupportedOperation):
            self.instance.seek(1)
        with pytest.raises(io.UnsupportedOperation):
            self.instance.seek(0, 1)

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
        parts: dict[str, str | io.BytesIO] = {
            "some field": "value",
            "some file": large_file,
        }
        encoder = MultipartEncoder(parts)
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

        for x in range(30):
            body = open(__file__, "rb")
            self.addCleanup(body.close)
            fields["f%d" % x] = ("test", body)

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
        """Verify that the Encoder handles custom content-types which
        are bytes.

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


class TestPart(unittest.TestCase):
    def test_peek_read_and_rewind_share_position(self) -> None:
        part = Part(b"X-Test: value\r\n\r\n", io.BytesIO(b"payload"))
        expected = b"X-Test: value\r\n\r\npayload"
        assert part.read(0) == b""
        preview = part.peek(1)
        assert preview and expected.startswith(preview)
        assert part.peek(1) == preview
        assert part.read(3) == expected[:3]
        assert part.read() == expected[3:]
        assert part.peek() == b""
        assert part.seek(0) == 0
        assert part.read() == expected


def test_part_reads_file_from_initial_position(tmp_path: Path) -> None:
    path = tmp_path / "part.bin"
    path.write_bytes(b"skip-payload")
    with path.open("rb") as body:
        body.seek(5)
        part = Part(b"Header: value\r\n\r\n", body)
        expected = b"Header: value\r\n\r\npayload"
        assert part.read(4) + part.read() == expected
        assert part.read() == b""
        part.seek(0)
        assert part.read() == expected
        with pytest.raises(io.UnsupportedOperation):
            part.seek(1)


@pytest.mark.parametrize("size", [0, -1])
def test_iteration_requires_positive_chunk_size(size: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        MultipartEncoder({"field": "value"}, default_iter_size=size)


def test_iteration_matches_read() -> None:
    encoder = MultipartEncoder({"field": "value"}, boundary="test", default_iter_size=7)
    chunks = list(encoder)
    assert all(0 < len(chunk) <= 7 for chunk in chunks)
    encoder.seek(0)
    assert b"".join(chunks) == encoder.read()


def test_encoder_metadata_and_consumption() -> None:
    fields = {"field": "value"}
    encoder = MultipartEncoder(fields, boundary="test", default_iter_size=7)
    assert encoder.boundary == "--test"
    assert encoder.boundary_value == "test"
    assert encoder.default_iter_read_size == 7
    assert encoder.encoding == "utf-8"
    assert encoder.fields == fields
    assert "MultipartEncoder" in repr(encoder)
    assert encoder.headers["Content-Type"] == "multipart/form-data; boundary=test"
    assert int(encoder.headers["Content-Length"]) == len(encoder)
    assert not encoder.finished
    assert len(encoder.read(len(encoder) - 1)) == len(encoder) - 1
    assert not encoder.finished
    assert encoder.read() == b"\n"
    assert encoder.finished
    encoder.seek(0)
    assert not encoder.finished


def test_unknown_body_length() -> None:
    with io.BufferedReader(io.BytesIO(b"value")) as body:
        with pytest.raises(ValueError, match="Unable to compute size"):
            Part(b"", body)


def test_custom_buffer_as_field() -> None:
    encoder = MultipartEncoder({"field": _CustomBytesIO(b"value")}, boundary="test")
    assert (
        encoder.read()
        == filepost.encode_multipart_formdata({"field": "value"}, boundary="test")[0]
    )
