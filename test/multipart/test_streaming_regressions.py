from __future__ import annotations

import io
from pathlib import Path

import pytest

from dummyserver.testcase import HypercornDummyServerTestCase
from urllib3 import HTTPConnectionPool
from urllib3.exceptions import UnrewindableBodyError
from urllib3.fields import RequestField
from urllib3.filepost import encode_multipart_formdata
from urllib3.multipart import MultipartDecoder, MultipartEncoder, Part
from urllib3.util.request import rewind_body


@pytest.mark.parametrize("offset", [0, 6, 13, 20])
@pytest.mark.parametrize("blocksize", [1, 7, 64, 65536])
def test_bytesio_starts_at_current_position(offset: int, blocksize: int) -> None:
    payload = b"prefixPAYLOAD"
    stream = io.BytesIO(payload)
    stream.seek(offset)
    encoder = MultipartEncoder({"f": ("f", stream)}, boundary="b", blocksize=blocksize)
    body = b"".join(encoder)
    expected, _ = encode_multipart_formdata(
        {"f": ("f", payload[offset:])}, boundary="b"
    )
    assert body == expected
    assert len(body) == len(encoder)
    assert encoder.tell() == len(body)


@pytest.mark.timeout(2)
@pytest.mark.parametrize("blocksize", [-1, 1, 64, 65536])
def test_truncated_file_fails_instead_of_spinning(
    tmp_path: Path, blocksize: int
) -> None:
    path = tmp_path / "upload"
    path.write_bytes(b"payload")
    with path.open("rb") as stream:
        encoder = MultipartEncoder({"f": ("f", stream)}, boundary="b")
        path.write_bytes(b"")
        with pytest.raises(OSError, match="end of file"):
            while encoder.read(blocksize):
                pass


def test_file_growth_does_not_exceed_content_length(tmp_path: Path) -> None:
    path = tmp_path / "upload"
    path.write_bytes(b"payload")
    with path.open("rb") as stream:
        encoder = MultipartEncoder({"f": ("f", stream)}, boundary="b")
        with path.open("ab") as writer:
            writer.write(b"EXTRA")
        body = encoder.read()
    assert b"EXTRA" not in body
    assert len(body) == len(encoder)


@pytest.mark.parametrize("read_size", [0, 1, 63, 65536, -1])
def test_rewind_restores_initial_positions(tmp_path: Path, read_size: int) -> None:
    path = tmp_path / "upload"
    path.write_bytes(b"prefixFILE")
    with path.open("rb") as file:
        file.seek(6)
        memory = io.BytesIO(b"prefixMEMORY")
        memory.seek(6)
        encoder = MultipartEncoder(
            {"file": ("file", file), "memory": ("memory", memory)}, boundary="b"
        )
        expected, _ = encode_multipart_formdata(
            {"file": ("file", b"FILE"), "memory": ("memory", b"MEMORY")}, boundary="b"
        )
        encoder.read(read_size)
        assert encoder.seek(0, 0) == 0
        assert encoder.tell() == 0
        assert encoder.read() == expected
        rewind_body(encoder, 0)  # type: ignore[arg-type]
        assert b"".join(encoder) == expected
        assert file.tell() == 10
        assert memory.tell() == 12


def test_failed_rewind_attempts_every_part() -> None:
    class FailingRewind(io.BytesIO):
        def seek(self, offset: int, whence: int = 0) -> int:
            raise OSError("not seekable")

    first = FailingRewind(b"first")
    last = io.BytesIO(b"last")
    encoder = MultipartEncoder({"first": first, "last": last}, boundary="b")
    encoder.read()
    with pytest.raises(UnrewindableBodyError):
        rewind_body(encoder, 0)  # type: ignore[arg-type]
    assert last.tell() == 0
    with pytest.raises(OSError, match="rewind"):
        encoder.read()


@pytest.mark.parametrize("offset,whence", [(1, 0), (0, 1), (0, 2)])
def test_unsupported_seek_does_not_change_encoder(offset: int, whence: int) -> None:
    encoder = MultipartEncoder({"f": "value"}, boundary="b")
    prefix = encoder.read(3)
    with pytest.raises(io.UnsupportedOperation):
        encoder.seek(offset, whence)
    assert encoder.tell() == 3
    assert prefix + encoder.read() == encode_multipart_formdata({"f": "value"}, "b")[0]


def test_peek_read_and_rewind_part() -> None:
    field = RequestField.from_tuples("f", ("file", b"payload"))
    part = Part.from_field(field, "utf-8")
    assert part.peek(4) == b"payl"
    assert part.peek(1) == b"payl"
    assert part.read(0) == b""
    assert part.read(2) == b"pa"
    assert part.peek() == b"yl"
    assert part.read() == b"yload"
    assert part.peek() == b""
    part.seek(0)
    assert part.read() == b"payload"


@pytest.mark.parametrize("blocksize", [0, -1])
def test_invalid_blocksize(blocksize: int) -> None:
    with pytest.raises(ValueError, match="blocksize"):
        MultipartEncoder({}, blocksize=blocksize)


@pytest.mark.parametrize("fields", [{}, {"field": "☃"}])
@pytest.mark.parametrize("boundary", ["", "boundary", "bóundary"])
def test_length_and_legacy_boundary_encoding(
    fields: dict[str, str], boundary: str
) -> None:
    encoder = MultipartEncoder(fields, boundary=boundary)
    body = encoder.read(-2)
    assert len(body) == len(encoder)
    assert body.endswith(b"--" + boundary.encode("latin-1") + b"--\r\n")


def test_streaming_never_copies_bytesio() -> None:
    class NoCopyBytesIO(io.BytesIO):
        def getvalue(self) -> bytes:
            raise AssertionError("must not copy the whole input")

        def read(self, size: int | None = -1) -> bytes:
            assert size is not None and 0 <= size <= 65536
            return super().read(min(size, 11))

    encoder = MultipartEncoder({"file": NoCopyBytesIO(b"x" * 100000)})
    assert sum(len(chunk) for chunk in encoder) == len(encoder)


@pytest.mark.limit_memory("2 MB", current_thread_only=True)
def test_large_file_memory_usage(tmp_path: Path) -> None:
    path = tmp_path / "upload"
    file_size = 50 * 1024 * 1024
    with path.open("wb") as file:
        file.seek(file_size - 1)
        file.write(b"x")
    with path.open("rb") as file:
        encoder = MultipartEncoder({"file": ("file", file)}, blocksize=65536)
        length = sum(len(chunk) for chunk in encoder)
        assert length == len(encoder)
        assert length > file_size


def test_duplicate_headers_survive_decoding() -> None:
    content = b"--b\r\nX-Test: one\r\nX-Test: two\r\n\r\ndata\r\n--b--\r\n"
    decoder = MultipartDecoder(content, content_type="multipart/mixed; boundary=b")
    assert decoder.parts[0].headers.getlist("X-Test") == ["one", "two"]


class TestStreamingUpload(HypercornDummyServerTestCase):
    def test_upload_and_redirect_rewind(self, tmp_path: Path) -> None:
        path = tmp_path / "upload"
        path.write_bytes(b"prefix" + b"payload" * 20000)
        with path.open("rb") as file:
            file.seek(6)
            encoder = MultipartEncoder({"file": ("file", file)}, boundary="b")
            expected, _ = encode_multipart_formdata(
                {"file": ("file", b"payload" * 20000)}, "b"
            )
            with HTTPConnectionPool(self.host, self.port, blocksize=4096) as pool:
                response = pool.urlopen(
                    "POST",
                    "/redirect?target=/echo&status=307",
                    body=encoder,
                    headers=encoder.headers,
                )
            assert response.status == 200
            assert response.data == expected
            assert response.retries is not None
            assert len(response.retries.history) == 1
            assert encoder.tell() == len(encoder)


def test_externally_consumed_input_fails_explicitly() -> None:
    stream = io.BytesIO(b"payload")
    encoder = MultipartEncoder({"file": stream})
    stream.read()
    with pytest.raises(OSError, match="end of file"):
        encoder.read()


@pytest.mark.parametrize("blocksize", [1, 2, 5, 65536])
def test_empty_multipart_can_be_streamed_and_rewound(blocksize: int) -> None:
    encoder = MultipartEncoder({}, boundary="b", blocksize=blocksize)
    assert b"".join(encoder) == b"--b--\r\n"
    encoder.seek(0)
    assert b"".join(encoder) == b"--b--\r\n"
