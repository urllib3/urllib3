from __future__ import annotations

import io
import sys
import typing
from unittest.mock import patch

import pytest

from urllib3._collections import HTTPHeaderDict
from urllib3._request_methods import RequestMethods
from urllib3.exceptions import UnrewindableBodyError
from urllib3.fields import RequestField
from urllib3.filepost import _TYPE_FIELDS, encode_multipart_formdata
from urllib3.multipart import (
    BodyPart,
    ImproperBodyPartContentError,
    MultipartDecoder,
    MultipartEncoder,
    NonMultipartContentTypeError,
    Part,
)
from urllib3.response import BaseHTTPResponse

BOUNDARY = "!! test boundary !!"


class OneShot:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0
        self.requests: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.requests.append(size)
        if size == -1:
            size = len(self.data) - self.position
        result = self.data[self.position : self.position + size]
        self.position += len(result)
        return result


class GeneratedSource:
    def __init__(self, size: int) -> None:
        self.remaining = size
        self.max_request = 0
        self.read_count = 0
        self.total_read = 0

    def read(self, size: int = -1) -> bytes:
        if size == -1:
            raise AssertionError("MultipartEncoder must request bounded reads")
        self.max_request = max(self.max_request, size)
        self.read_count += 1
        count = min(size, self.remaining)
        self.remaining -= count
        self.total_read += count
        return b"x" * count


def test_encoder_matches_legacy_wire_format() -> None:
    fields: _TYPE_FIELDS = [
        ("name", "café"),
        ("file", ("a.txt", b"body", "text/plain")),
    ]
    expected = (
        b'--!! test boundary !!\r\nContent-Disposition: form-data; name="name"'
        b"\r\n\r\ncaf\xc3\xa9\r\n--!! test boundary !!\r\nContent-Disposition: "
        b'form-data; name="file"; filename="a.txt"\r\nContent-Type: text/plain'
        b"\r\n\r\nbody\r\n--!! test boundary !!--\r\n"
    )
    content_type = 'multipart/form-data; boundary="!! test boundary !!"'
    encoder = MultipartEncoder(fields, boundary=BOUNDARY, blocksize=3)

    assert encoder.content_type == content_type
    assert encoder.content_length == len(expected)
    assert encoder.headers == HTTPHeaderDict(
        {"Content-Type": content_type, "Content-Length": str(len(expected))}
    )
    assert b"".join(encoder) == expected


def test_encoder_preserves_integer_compatibility() -> None:
    assert b"\r\n1\r\n" in MultipartEncoder({"field": 1}, boundary="test").read()


def test_part_reads_headers_and_body_in_chunks() -> None:
    part = Part(
        b"Header: value\r\n\r\n", typing.cast(typing.BinaryIO, OneShot(b"body"))
    )

    assert part.read(0) == b""
    assert part.read(7) == b"Header:"
    assert part.peek(4) == b" val"
    assert part.peek(4) == b" val"
    assert part.read(8) == b" value\r\n"
    assert part.read() == b"\r\nbody"
    assert part.read() == b""
    assert part.peek(-1) == b""


def test_part_peek_buffers_one_shot_bodies_without_advancing() -> None:
    stream = OneShot(b"streamed")
    part = Part(b"", typing.cast(typing.BinaryIO, stream))

    assert part.peek(3) == b"str"
    assert part.read(-2) == b"streamed"
    assert stream.requests and max(stream.requests) <= 16384

    with pytest.raises(TypeError, match="headers"):
        Part(typing.cast(typing.Any, "Header: value"), b"body")


@pytest.mark.limit_memory("10 MB", current_thread_only=True)
def test_part_default_peek_is_bounded() -> None:
    stream = GeneratedSource(32 * 1024 * 1024)
    part = Part(b"", typing.cast(typing.BinaryIO, stream))

    assert len(part.peek()) == 16384
    assert stream.total_read == 16384
    assert part.read(16384) == b"x" * 16384


def test_legacy_helper_delegates_to_encoder() -> None:
    with patch("urllib3.multipart.MultipartEncoder") as encoder_type:
        instance = encoder_type.return_value
        instance.read.return_value = b"body"
        instance.content_type = "multipart/form-data; boundary=test"

        assert encode_multipart_formdata({"field": "value"}, boundary="test") == (
            b"body",
            "multipart/form-data; boundary=test",
        )
        encoder_type.assert_called_once_with({"field": "value"}, boundary="test")


def test_encoder_read_contract_and_iterator() -> None:
    encoder = MultipartEncoder({"field": "value"}, boundary="test", blocksize=4)
    expected = encoder.read(None)
    encoder.seek(0)

    assert encoder.read(0) == b""
    assert encoder.tell() == 0
    assert encoder.read(5) == expected[:5]
    assert b"".join(encoder) == expected[5:]
    with pytest.raises(ValueError):
        encoder.read(-2)
    with pytest.raises(OSError):
        encoder.seek(1)


def test_encoder_rewinds_streams_to_their_initial_position() -> None:
    stream = io.BytesIO(b"prefix-body")
    stream.seek(len(b"prefix-"))
    encoder = MultipartEncoder(
        [("first", ("a", stream)), ("second", ("b", stream))], boundary="test"
    )
    expected = encoder.read()

    assert expected.count(b"body") == 2
    encoder.seek(0)
    assert encoder.read() == expected


def test_encoder_restores_stream_after_a_failed_length_probe() -> None:
    class FailingProbe(io.BytesIO):
        def seek(self, offset: int, whence: int = 0) -> int:
            result = super().seek(offset, whence)
            if whence == 2:
                raise OSError("probe failed")
            return result

    stream = FailingProbe(b"prefix-body")
    stream.seek(len(b"prefix-"))
    encoder = MultipartEncoder([("file", ("a", stream))])

    assert stream.tell() == len(b"prefix-")
    assert encoder.content_length is None


def test_encoder_handles_failed_length_probe_and_tell() -> None:
    class FailingProbeAndTell:
        def __init__(self) -> None:
            self.tell_calls = 0

        def tell(self) -> int:
            self.tell_calls += 1
            if self.tell_calls > 1:
                raise OSError("tell failed")
            return 0

        def seek(self, offset: int, whence: int = 0) -> int:
            if whence == 2:
                raise OSError("probe failed")
            return offset

        def read(self, size: int) -> bytes:
            return b""

    encoder = MultipartEncoder(
        [
            (
                "file",
                ("a", typing.cast(typing.BinaryIO, FailingProbeAndTell())),
            )
        ]
    )

    assert encoder.content_length is None


def test_encoder_rejects_invalid_tell_after_failed_length_probe() -> None:
    class InvalidTellAfterProbe:
        def __init__(self) -> None:
            self.tell_calls = 0

        def tell(self) -> object:
            self.tell_calls += 1
            return 0 if self.tell_calls == 1 else "invalid"

        def seek(self, offset: int, whence: int = 0) -> int:
            if whence == 2:
                raise OSError("probe failed")
            return offset

        def read(self, size: int) -> bytes:
            return b""

    with pytest.raises(TypeError, match="tell"):
        MultipartEncoder(
            [
                (
                    "file",
                    ("a", typing.cast(typing.BinaryIO, InvalidTellAfterProbe())),
                )
            ]
        )


def test_encoder_rejects_streams_it_cannot_restore_after_probing() -> None:
    class FailingRestore(io.BytesIO):
        def seek(self, offset: int, whence: int = 0) -> int:
            if whence == 0:
                raise OSError("restore failed")
            return super().seek(offset, whence)

    with pytest.raises(OSError, match="restore"):
        MultipartEncoder([("file", ("a", FailingRestore(b"body")))])

    class FailingProbeRestore(io.BytesIO):
        def seek(self, offset: int, whence: int = 0) -> int:
            if whence == 2:
                super().seek(offset, whence)
                raise OSError("probe failed")
            if whence == 0:
                raise OSError("restore failed")
            return super().seek(offset, whence)

    with pytest.raises(OSError, match="restore"):
        MultipartEncoder([("file", ("a", FailingProbeRestore(b"body")))])


def test_encoder_rejects_negative_measured_lengths() -> None:
    class BackwardsTell(io.BytesIO):
        def __init__(self) -> None:
            super().__init__(b"body")
            self.calls = 0

        def tell(self) -> int:
            self.calls += 1
            return 4 if self.calls == 1 else 3

    with pytest.raises(ValueError, match="invalid length"):
        MultipartEncoder([("file", ("a", BackwardsTell()))])


def test_encoder_rejects_invalid_stream_tell_values() -> None:
    class InvalidTell:
        def tell(self) -> str:
            return "invalid"

        def seek(self, offset: int, whence: int = 0) -> int:
            return 0

        def read(self, size: int) -> bytes:
            return b""

    with pytest.raises(TypeError, match="tell"):
        MultipartEncoder([("file", ("a", typing.cast(typing.BinaryIO, InvalidTell())))])

    class InvalidEndTell:
        def __init__(self) -> None:
            self.calls = 0

        def tell(self) -> object:
            self.calls += 1
            return 0 if self.calls == 1 else "invalid"

        def seek(self, offset: int, whence: int = 0) -> int:
            return 0

        def read(self, size: int) -> bytes:
            return b""

    with pytest.raises(TypeError, match="tell"):
        MultipartEncoder(
            [("file", ("a", typing.cast(typing.BinaryIO, InvalidEndTell())))]
        )

    class InvalidEndTellRestoreFail:
        def __init__(self) -> None:
            self.calls = 0

        def tell(self) -> object:
            self.calls += 1
            return 0 if self.calls == 1 else "invalid"

        def seek(self, offset: int, whence: int = 0) -> int:
            if whence == 0:
                raise OSError("restore failed")
            return 0

        def read(self, size: int) -> bytes:
            return b""

    with pytest.raises(OSError, match="restore"):
        MultipartEncoder(
            [
                (
                    "file",
                    ("a", typing.cast(typing.BinaryIO, InvalidEndTellRestoreFail())),
                )
            ]
        )


def test_encoder_one_shot_stream_is_chunked_and_not_rewindable() -> None:
    stream = OneShot(b"stream")
    encoder = MultipartEncoder([("file", ("a", typing.cast(typing.BinaryIO, stream)))])

    assert encoder.content_length is None
    assert "Content-Length" not in encoder.headers
    assert b"stream" in encoder.read()
    with pytest.raises(UnrewindableBodyError):
        encoder.seek(0)
    with pytest.raises(ValueError, match="cannot be used twice"):
        MultipartEncoder(
            [
                ("one", ("a", typing.cast(typing.BinaryIO, stream))),
                ("two", ("b", typing.cast(typing.BinaryIO, stream))),
            ]
        )


def test_encoder_accepts_one_shot_stream_with_tell_but_without_seek() -> None:
    class PositionedOneShot(OneShot):
        def tell(self) -> int:
            return self.position

    stream = PositionedOneShot(b"stream")
    encoder = MultipartEncoder(
        [("file", ("a", typing.cast(typing.BinaryIO, stream)))], boundary="test"
    )

    assert encoder.content_length is None
    assert b"stream" in encoder.read()


def test_encoder_rewind_attempts_every_part() -> None:
    class TrackedBytesIO(io.BytesIO):
        def __init__(self, data: bytes) -> None:
            super().__init__(data)
            self.seek_calls = 0

        def seek(self, offset: int, whence: int = 0) -> int:
            self.seek_calls += 1
            return super().seek(offset, whence)

    one_shot = OneShot(b"one shot")
    seekable = TrackedBytesIO(b"seekable")
    encoder = MultipartEncoder(
        [
            ("first", ("a", typing.cast(typing.BinaryIO, one_shot))),
            ("second", ("b", seekable)),
        ]
    )
    seekable.seek_calls = 0

    with pytest.raises(UnrewindableBodyError):
        encoder.seek(0)
    assert seekable.seek_calls == 1


def test_encoder_wraps_stream_rewind_failures() -> None:
    class FailingRewind(io.BytesIO):
        fail = False

        def seek(self, offset: int, whence: int = 0) -> int:
            if self.fail and whence == 0:
                raise OSError("rewind failed")
            return super().seek(offset, whence)

    stream = FailingRewind(b"body")
    encoder = MultipartEncoder([("file", ("a", stream))])
    stream.fail = True

    with pytest.raises(UnrewindableBodyError):
        encoder.seek(0)


def test_encoder_content_length_can_exceed_sys_maxsize() -> None:
    class HugeStream:
        def __init__(self) -> None:
            self.position = 17
            self.end = sys.maxsize + 624

        def tell(self) -> int:
            return self.position

        def seek(self, offset: int, whence: int = 0) -> int:
            if whence == 0:
                self.position = offset
            elif whence == 2:
                self.position = self.end + offset
            else:
                raise OSError("unsupported")
            return self.position

        def read(self, size: int) -> bytes:
            return b""

    encoder = MultipartEncoder(
        [
            (
                "file",
                ("huge", typing.cast(typing.BinaryIO, HugeStream())),
            )
        ],
        boundary="test",
    )

    assert encoder.content_length is not None
    assert encoder.content_length > sys.maxsize
    assert encoder.headers["Content-Length"] == str(encoder.content_length)


@pytest.mark.limit_memory("10 MB", current_thread_only=True)
def test_encoder_bounds_one_shot_reads() -> None:
    stream = GeneratedSource(32 * 1024 * 1024)
    encoder = MultipartEncoder(
        [("file", ("large", typing.cast(typing.BinaryIO, stream)))], blocksize=8192
    )

    total = sum(len(chunk) for chunk in encoder)
    overhead = len(
        MultipartEncoder([("file", ("large", b""))], boundary=encoder.boundary).read()
    )
    assert total == overhead + 32 * 1024 * 1024
    assert stream.total_read == 32 * 1024 * 1024
    assert stream.max_request <= encoder.blocksize
    assert stream.read_count > 1


@pytest.mark.limit_memory("10 MB", current_thread_only=True)
def test_encoder_read_all_does_not_duplicate_chunks() -> None:
    stream = GeneratedSource(6 * 1024 * 1024)
    encoder = MultipartEncoder(
        [("file", ("large", typing.cast(typing.BinaryIO, stream)))], boundary="test"
    )

    body = encoder.read()

    assert len(body) > 6 * 1024 * 1024
    assert stream.total_read == 6 * 1024 * 1024


def test_encoder_rejects_changed_seekable_streams() -> None:
    class ShortReader(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            if size is None:
                size = -1
            return super().read(max(size - 1, 0))

    stream = ShortReader(b"body")
    encoder = MultipartEncoder([("file", ("a", stream))])
    with pytest.raises(OSError, match="ended before"):
        encoder.read()


def test_encoder_rejects_seekable_stream_growth() -> None:
    stream = io.BytesIO(b"body")
    encoder = MultipartEncoder([("file", ("a", stream))])
    stream.seek(0, 2)
    stream.write(b"extra")
    stream.seek(0)

    with pytest.raises(OSError, match="grew"):
        encoder.read()


def test_encoder_rejects_bad_stream_data_and_reads() -> None:
    class BadRead:
        def read(self, size: int) -> str:
            return "body"

    class OverRead:
        def read(self, size: int) -> bytes:
            return b"x" * (size + 1)

    class BadEndRead:
        def __init__(self) -> None:
            self.buffer = io.BytesIO(b"body")
            self.calls = 0

        def tell(self) -> int:
            return self.buffer.tell()

        def seek(self, offset: int, whence: int = 0) -> int:
            return self.buffer.seek(offset, whence)

        def read(self, size: int) -> object:
            self.calls += 1
            if self.calls == 2:
                return "invalid"
            return self.buffer.read(size)

    with pytest.raises(TypeError, match="field data"):
        MultipartEncoder([RequestField("field", typing.cast(typing.Any, object()))])
    with pytest.raises(TypeError, match="return bytes"):
        MultipartEncoder(
            [("file", ("a", typing.cast(typing.BinaryIO, BadRead())))]
        ).read()
    with pytest.raises(OSError, match="more data"):
        MultipartEncoder(
            [("file", ("a", typing.cast(typing.BinaryIO, OverRead())))]
        ).read()
    with pytest.raises(TypeError, match="return bytes"):
        MultipartEncoder(
            [("file", ("a", typing.cast(typing.BinaryIO, BadEndRead())))]
        ).read()


def test_encoder_public_values_are_read_only() -> None:
    encoder = MultipartEncoder([RequestField("field", b"value")], boundary="test")

    assert encoder.boundary == "test"
    assert encoder.blocksize == 16384
    with pytest.raises(AttributeError):
        encoder.boundary = "other"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        encoder.blocksize = 1  # type: ignore[misc]
    with pytest.raises(AttributeError):
        encoder.content_length = 1  # type: ignore[misc]
    with pytest.raises(TypeError, match="integer"):
        MultipartEncoder({"field": "value"}, blocksize=True)
    with pytest.raises(ValueError, match="positive"):
        MultipartEncoder({"field": "value"}, blocksize=0)


def test_request_methods_uses_encoder_headers_without_overwriting_callers() -> None:
    response = typing.cast(BaseHTTPResponse, object())
    with patch.object(
        RequestMethods, "urlopen", autospec=True, return_value=response
    ) as urlopen:
        methods = RequestMethods()
        methods.request("POST", "/", fields={"field": "value"})
        body = typing.cast(MultipartEncoder, urlopen.call_args.kwargs["body"])
        headers = typing.cast(HTTPHeaderDict, urlopen.call_args.kwargs["headers"])
        assert isinstance(body, MultipartEncoder)
        assert headers["Content-Type"].startswith("multipart/form-data;")
        assert headers["Content-Length"] == str(body.content_length)

        methods.request(
            "POST",
            "/",
            fields={"field": "value"},
            headers={"Content-Type": "custom/type", "Content-Length": "1"},
        )
        headers = typing.cast(HTTPHeaderDict, urlopen.call_args.kwargs["headers"])
        assert headers == HTTPHeaderDict(
            {"Content-Type": "custom/type", "Content-Length": "1"}
        )


def test_request_methods_does_not_add_length_with_transfer_encoding() -> None:
    response = typing.cast(BaseHTTPResponse, object())
    with patch.object(
        RequestMethods, "urlopen", autospec=True, return_value=response
    ) as urlopen:
        methods = RequestMethods()
        methods.request("POST", "/", fields={"field": "value"}, chunked=True)
        headers = typing.cast(HTTPHeaderDict, urlopen.call_args.kwargs["headers"])
        assert "Content-Length" not in headers
        assert urlopen.call_args.kwargs["chunked"] is True

        methods.request(
            "POST",
            "/",
            fields={"field": "value"},
            headers={"Transfer-Encoding": "chunked"},
        )
        headers = typing.cast(HTTPHeaderDict, urlopen.call_args.kwargs["headers"])
        assert headers["Transfer-Encoding"] == "chunked"
        assert headers["Content-Type"].startswith("multipart/form-data;")
        assert "Content-Length" not in headers


@pytest.mark.parametrize(
    ("boundary", "parameter"),
    [
        ("simple", "simple"),
        ("with space", '"with space"'),
        ("with'apostrophe", '"with\'apostrophe"'),
        ("with*asterisk", '"with*asterisk"'),
        ("a/b;c?d=e", '"a/b;c?d=e"'),
        ('quote"slash\\', '"quote\\"slash\\\\"'),
    ],
)
def test_encoder_quotes_non_token_boundaries(boundary: str, parameter: str) -> None:
    encoder = MultipartEncoder({"field": "value"}, boundary=boundary)

    assert encoder.content_type == f"multipart/form-data; boundary={parameter}"
    decoder = MultipartDecoder(encoder.read(), content_type=encoder.content_type)
    assert [part.data for part in decoder.parts] == [b"value"]


@pytest.mark.parametrize(
    "boundary", ["", "bad\r", "bad\n", "bad\x00", "bad ", "ñ", "x" * 71]
)
def test_encoder_rejects_invalid_boundaries(boundary: str) -> None:
    with pytest.raises(ValueError):
        MultipartEncoder({"field": "value"}, boundary=boundary)


def test_decoder_parses_mime_forms_and_duplicate_headers() -> None:
    content = (
        b"preamble\r\n--abc\r\nX-Test: one\r\nX-Test: two\r\n"
        b"Content-Type: multipart/mixed\r\n\r\n"
        b"body\r\n--abc\r\nContent-Type: text/plain\r\n\r\n\r\n--abc--\r\nepilogue"
    )
    decoder = MultipartDecoder(content, content_type='multipart/mixed; boundary="abc"')

    assert len(decoder.parts) == 2
    assert decoder.parts[0].data == b"body"
    assert list(decoder.parts[0].headers.iteritems()) == [
        ("X-Test", "one"),
        ("X-Test", "two"),
        ("Content-Type", "multipart/mixed"),
    ]
    assert decoder.parts[1].data == b""


def test_decoder_content_type_uses_structured_header_defects() -> None:
    content = b"--a\\b\r\n\r\nbody\r\n--a\\b--\r\n"
    decoder = MultipartDecoder(
        content, content_type='MULTIPART/mixed; boundary="a\\\\b"'
    )

    assert decoder.parts[0].data == b"body"
    for content_type in (
        'multipart/mixed; boundary="abc',
        "multipart/mixed; boundary=abc trailing",
        "multipart/mixed; boundary=one; boundary=two",
    ):
        with pytest.raises(NonMultipartContentTypeError):
            MultipartDecoder(b"", content_type=content_type)


def test_decoder_rejects_part_header_defects_and_supports_from_response() -> None:
    class Response:
        data = b"--abc\r\n\r\nbody\r\n--abc--\r\n"
        headers = HTTPHeaderDict({"Content-Type": "multipart/mixed; boundary=abc"})

    response = typing.cast(BaseHTTPResponse, Response())
    assert MultipartDecoder.from_response(response).parts[0].data == b"body"
    Response.headers = HTTPHeaderDict()
    with pytest.raises(NonMultipartContentTypeError, match="Missing"):
        MultipartDecoder.from_response(response)
    with pytest.raises(ImproperBodyPartContentError):
        MultipartDecoder(
            b'--abc\r\nContent-Type: text/plain; charset="utf-8\r\n\r\nbody\r\n--abc--\r\n',
            content_type="multipart/mixed; boundary=abc",
        )


def test_decoder_accepts_utf8_headers_emitted_by_encoder() -> None:
    encoder = MultipartEncoder(
        [("café", ("niño.txt", b"body", "text/plain"))], boundary="abc"
    )
    decoder = MultipartDecoder(encoder.read(), content_type=encoder.content_type)

    assert decoder.parts[0].headers["Content-Disposition"] == (
        'form-data; name="café"; filename="niño.txt"'
    )


@pytest.mark.parametrize("value", [b"\xff", b"bad\x00value"])
def test_decoder_rejects_invalid_part_header_bytes(value: bytes) -> None:
    with pytest.raises(ImproperBodyPartContentError):
        MultipartDecoder(
            b"--abc\r\nX-Test: " + value + b"\r\n\r\nbody\r\n--abc--\r\n",
            content_type="multipart/mixed; boundary=abc",
        )


@pytest.mark.parametrize("line_ending", [b"\r", b"\n"])
def test_decoder_rejects_bare_part_header_line_endings(line_ending: bytes) -> None:
    with pytest.raises(ImproperBodyPartContentError, match="line ending"):
        MultipartDecoder(
            b"--abc\r\nX-Test: one"
            + line_ending
            + b"Injected: yes\r\n\r\nbody\r\n--abc--\r\n",
            content_type="multipart/mixed; boundary=abc",
        )


def test_decoder_supports_initial_closing_delimiter_and_transport_padding() -> None:
    assert (
        MultipartDecoder(b"--abc--", content_type="multipart/mixed; boundary=abc").parts
        == ()
    )
    assert (
        MultipartDecoder(
            b"--abc\r\n\r\nbody\r\n--abc-- \t",
            content_type="multipart/mixed; boundary=abc",
        )
        .parts[0]
        .data
        == b"body"
    )


def test_decoder_rejects_invalid_content_type_values() -> None:
    for content_type in (
        typing.cast(str, b"multipart/mixed"),
        "multipart/mixed; boundary=ñ",
    ):
        with pytest.raises(NonMultipartContentTypeError):
            MultipartDecoder(b"", content_type=content_type)

    with pytest.raises(NonMultipartContentTypeError, match="boundary"):
        MultipartDecoder(b"", content_type="multipart/mixed; boundary=" + "x" * 71)

    with pytest.raises(ImproperBodyPartContentError, match="separator"):
        MultipartDecoder(
            b"--abc\r\nheader\r\n--abc--\r\n",
            content_type="multipart/mixed; boundary=abc",
        )


def test_decoder_does_not_split_body_lookalikes() -> None:
    content = b"--abc\r\n\r\nbody --abc\r\nx\r\n--abcX\r\ny\r\n--abc--\r\n"
    assert (
        MultipartDecoder(content, content_type="multipart/form-data; boundary=abc")
        .parts[0]
        .data
        == b"body --abc\r\nx\r\n--abcX\r\ny"
    )


def test_decoder_rejects_invalid_delimiter_lookalikes() -> None:
    with pytest.raises(ImproperBodyPartContentError):
        MultipartDecoder(
            b"--abc trailing\r\n", content_type="multipart/form-data; boundary=abc"
        )


@pytest.mark.parametrize(
    "content_type",
    [
        "text/plain",
        "multipart/form-data",
        "multipart/form-data; boundary=",
        "multipart/form-data\r\nX: y",
    ],
)
def test_decoder_rejects_bad_content_types(content_type: str) -> None:
    with pytest.raises(NonMultipartContentTypeError):
        MultipartDecoder(b"", content_type=content_type)


@pytest.mark.parametrize(
    "content",
    [b"--abc\r\nX: y\r\n", b"--abc\r\nbad\r\n\r\nx\r\n--abc--\r\n", b"--abc\r\n\r\nx"],
)
def test_decoder_rejects_bad_parts(content: bytes) -> None:
    with pytest.raises(ImproperBodyPartContentError):
        MultipartDecoder(content, content_type="multipart/form-data; boundary=abc")


def test_body_part_is_file_like() -> None:
    part = BodyPart(HTTPHeaderDict(), b"abcdef")

    assert part.peek(2) == b"ab"
    assert part.tell() == 0
    assert part.read(2) == b"ab"
    assert part.peek() == b"cdef"
    assert part.seek(-1, 2) == 5
    assert part.read() == b"f"
    with pytest.raises(ValueError):
        part.read(-2)
    with pytest.raises(AttributeError):
        part.headers = HTTPHeaderDict()  # type: ignore[misc]
    with pytest.raises(AttributeError):
        part.data = b"other"  # type: ignore[misc]
