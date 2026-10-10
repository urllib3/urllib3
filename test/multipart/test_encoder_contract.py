from __future__ import annotations

import io
import typing

import pytest

from urllib3.fields import RequestField
from urllib3.filepost import encode_multipart_formdata
from urllib3.multipart import MultipartEncoder, Part
from urllib3.multipart.encoder import (
    FileWrapper,
    _CustomBytesIO,
    coerce_data,
    total_len,
)


def test_next_preserves_wire_body_and_exhaustion() -> None:
    fields = {"name": "value"}
    encoder = MultipartEncoder(fields, boundary="boundary", blocksize=7)
    assert encoder.boundary == "--boundary"
    assert encoder.boundary_value == "boundary"
    assert encoder.default_iter_read_size == 7
    assert encoder.encoding == "utf-8"
    assert encoder.fields == fields
    assert not encoder.finished
    assert "MultipartEncoder" in repr(encoder)
    chunks = []
    while True:
        try:
            chunks.append(next(encoder))
        except StopIteration:
            break
    assert b"".join(chunks) == encode_multipart_formdata(fields, "boundary")[0]
    assert all(0 < len(chunk) <= 7 for chunk in chunks)
    assert encoder.finished
    with pytest.raises(StopIteration):
        next(encoder)


def test_part_invalid_seek_preserves_buffer() -> None:
    part = Part.from_field(RequestField("f", b"payload"))
    assert part.peek(3) == b"pay"
    with pytest.raises(io.UnsupportedOperation):
        part.seek(1)
    assert part.read() == b"payload"


def test_wrapper_read_all_respects_initial_end() -> None:
    stream = io.BytesIO(b"prefixpayload")
    stream.seek(6)
    wrapper = FileWrapper(stream)
    stream.seek(0, 2)
    stream.write(b"extra")
    stream.seek(6)
    assert wrapper.read() == b"payload"
    assert wrapper.read() == b""


def test_size_fallback_and_unsupported_stream() -> None:
    assert total_len(io.StringIO("hello")) == 5
    with pytest.raises(ValueError, match="Unable to compute size"):
        total_len(typing.cast(typing.BinaryIO, io.RawIOBase()))


def test_existing_buffer_preserves_position() -> None:
    stream = _CustomBytesIO(b"prefixpayload")
    stream.seek(6)
    assert typing.cast(object, coerce_data(stream, "utf-8")) is stream
    part = Part(b"", stream)
    assert part.read() == b"payload"
    part.seek(0)
    assert part.read() == b"payload"
