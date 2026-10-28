from __future__ import annotations

import io
import typing
import unittest
from unittest import mock

import pytest

import urllib3.response
from urllib3.multipart.decoder import (
    BodyPart,
    ImproperBodyPartContentError,
    MultipartDecoder,
    NonMultipartContentTypeError,
)
from urllib3.multipart.encoder import MultipartEncoder, encode_with


@pytest.mark.parametrize("content_type", ["", "text/plain", "application/json"])
def test_non_multipart_content_type(content_type: str) -> None:
    with pytest.raises(NonMultipartContentTypeError):
        MultipartDecoder(b"", content_type=content_type)


@pytest.mark.parametrize(
    "content_type", ["multipart/mixed", 'multipart/mixed; boundary=""']
)
def test_missing_boundary(content_type: str) -> None:
    with pytest.raises(
        ImproperBodyPartContentError, match="Missing multipart boundary"
    ):
        MultipartDecoder(b"", content_type=content_type)


def test_boundary_lines_preserve_body_bytes() -> None:
    body = b"binary\x00\xff\r\n--a:b-extra\r\ninline --a:b marker"
    content = (
        b"preamble\r\n--a:b\t \r\nX-Test: value\r\n\r\n"
        + body
        + b"\r\n--a:b--\r\nepilogue"
    )
    decoder = MultipartDecoder(
        content, content_type='Multipart/Mixed; charset=utf-8; boundary="a:b"'
    )
    assert len(decoder.parts) == 1
    assert decoder.parts[0].data == body


def test_missing_closing_boundary() -> None:
    with pytest.raises(ImproperBodyPartContentError, match="Missing closing"):
        MultipartDecoder(
            b"--test\r\n\r\nbody", content_type="multipart/mixed; boundary=test"
        )


def test_empty_multipart() -> None:
    decoder = MultipartDecoder(
        b"--test--\r\n", content_type="multipart/mixed; boundary=test"
    )
    assert decoder.parts == ()


class TestBodyPart(unittest.TestCase):
    @staticmethod
    def bodypart_bytes_from_headers_and_values(
        headers: typing.Sequence[tuple[str, str]], value: str, encoding: str
    ) -> bytes:
        if not headers:
            return b"\r\n" + value.encode(encoding)
        return b"\r\n\r\n".join(
            [
                b"\r\n".join(
                    [b": ".join([encode_with(i, encoding) for i in h]) for h in headers]
                ),
                encode_with(value, encoding),
            ]
        )

    def setUp(self) -> None:
        self.header_1 = ("Snowman", "☃")
        self.value_1 = "©"
        self.part_1 = BodyPart(
            TestBodyPart.bodypart_bytes_from_headers_and_values(
                (self.header_1,), self.value_1, "utf-8"
            ),
            encoding="utf-8",
        )
        self.part_2 = BodyPart(
            TestBodyPart.bodypart_bytes_from_headers_and_values(
                [], self.value_1, "utf-16"
            ),
            encoding="utf-16",
        )

    def test_equality_content_should_be_equal(self) -> None:
        part_3 = BodyPart(
            TestBodyPart.bodypart_bytes_from_headers_and_values(
                [], self.value_1, "utf-8"
            ),
            encoding="utf-8",
        )
        assert self.part_1.data == part_3.data

    def test_equality_content_equals_bytes(self) -> None:
        assert self.part_1.data == encode_with(self.value_1, "utf-8")

    def test_equality_content_should_not_be_equal(self) -> None:
        assert self.part_1.data != self.part_2.data

    def test_equality_content_does_not_equal_bytes(self) -> None:
        assert self.part_1.data != encode_with(self.value_1, "latin-1")

    def test_header_decoding_preserves_unicode(self) -> None:
        assert self.part_1.headers["Snowman"] == "☃"

    def test_data_can_be_decoded_explicitly(self) -> None:
        assert self.part_1.data.decode("utf-8") == self.part_2.data.decode("utf-16")

    def test_no_headers(self) -> None:
        sample_1 = b"\r\nNo headers\r\nTwo lines"
        part_3 = BodyPart(sample_1, encoding="utf-8")
        assert len(part_3.headers) == 0
        assert part_3.data == b"No headers\r\nTwo lines"

    def test_repeated_headers(self) -> None:
        part = BodyPart(
            b"X-Test: first\r\nX-Test: second\r\nx-test: third\r\n\r\nbody",
            encoding="utf-8",
        )
        assert part.headers.getlist("X-Test") == ["first", "second", "third"]
        assert part.data == b"body"

    def test_no_crlf_crlf_in_content(self) -> None:
        content = b"no CRLF CRLF here!\r\n"
        with pytest.raises(ImproperBodyPartContentError):
            BodyPart(content, encoding="utf-8")


class TestMultipartDecoder(unittest.TestCase):
    def test_repeated_headers_in_each_part(self) -> None:
        content = (
            b"--test\r\nX-Test: first\r\nX-Test: second\r\n\r\none"
            b"\r\n--test\r\nX-Test: third\r\nx-test: fourth\r\n\r\ntwo"
            b"\r\n--test--\r\n"
        )
        decoder = MultipartDecoder(
            content, content_type="multipart/mixed; boundary=test"
        )
        assert [part.headers.getlist("X-Test") for part in decoder.parts] == [
            ["first", "second"],
            ["third", "fourth"],
        ]
        assert [part.data for part in decoder.parts] == [b"one", b"two"]

    def setUp(self) -> None:
        self.sample_1 = (
            ("field 1", "value 1"),
            ("field 2", "value 2"),
            ("field 3", "value 3"),
            ("field 4", "value 4"),
        )
        self.boundary = "test boundary"
        self.encoded_1 = MultipartEncoder(self.sample_1, self.boundary)
        self.decoded_1 = MultipartDecoder(
            self.encoded_1.read(), content_type=self.encoded_1.content_type
        )

    def test_non_multipart_response_fails(self) -> None:
        jpeg_response = mock.NonCallableMagicMock(spec=urllib3.response.HTTPResponse)
        jpeg_response.headers = {"content-type": "image/jpeg"}
        with pytest.raises(NonMultipartContentTypeError):
            MultipartDecoder.from_response(jpeg_response)

    def test_length_of_parts(self) -> None:
        assert len(self.sample_1) == len(self.decoded_1.parts)

    def test_content_of_parts(self) -> None:
        def parts_equal(part: BodyPart, sample: tuple[str, str]) -> bool:
            return part.data == encode_with(sample[1], "utf-8")

        parts_iter = zip(self.decoded_1.parts, self.sample_1)
        assert all(parts_equal(part, sample) for part, sample in parts_iter)

    def test_header_of_parts(self) -> None:
        def parts_header_equal(part: BodyPart, sample: tuple[str, str]) -> bool:
            return (
                part.headers["Content-Disposition"] == f'form-data; name="{sample[0]}"'
            )

        parts_iter = zip(self.decoded_1.parts, self.sample_1)
        assert all(parts_header_equal(part, sample) for part, sample in parts_iter)

    def test_from_response(self) -> None:
        response = mock.NonCallableMagicMock(spec=urllib3.response.HTTPResponse)
        response.headers = {"content-type": 'multipart/related; boundary="samp1"'}
        cnt = io.BytesIO()
        cnt.write(b"\r\n--samp1\r\n")
        cnt.write(b"Header-1: Header-Value-1\r\n")
        cnt.write(b"Header-2: Header-Value-2\r\n")
        cnt.write(b"\r\n")
        cnt.write(b"Body 1, Line 1\r\n")
        cnt.write(b"Body 1, Line 2\r\n")
        cnt.write(b"--samp1\r\n")
        cnt.write(b"\r\n")
        cnt.write(b"Body 2, Line 1\r\n")
        cnt.write(b"--samp1--\r\n")
        response.data = cnt.getvalue()
        decoder_2 = MultipartDecoder.from_response(response)
        assert decoder_2.content_type == response.headers["content-type"]
        assert decoder_2.parts[0].data == b"Body 1, Line 1\r\nBody 1, Line 2"
        assert decoder_2.parts[0].headers["Header-1"] == "Header-Value-1"
        assert len(decoder_2.parts[1].headers) == 0
        assert decoder_2.parts[1].data == b"Body 2, Line 1"

    def test_from_response_needs_content_type(self) -> None:
        response = mock.NonCallableMagicMock(spec=urllib3.response.HTTPResponse)
        response.headers = {}
        response.data = b""

        with pytest.raises(
            ValueError, match="Cannot determine content-type header from response"
        ):
            MultipartDecoder.from_response(response)

    def test_from_responsecaplarge(self) -> None:
        response = mock.NonCallableMagicMock(spec=urllib3.response.HTTPResponse)
        response.headers = {"content-type": 'Multipart/Related; boundary="samp1"'}
        cnt = io.BytesIO()
        cnt.write(b"\r\n--samp1\r\n")
        cnt.write(b"Header-1: Header-Value-1\r\n")
        cnt.write(b"Header-2: Header-Value-2\r\n")
        cnt.write(b"\r\n")
        cnt.write(b"Body 1, Line 1\r\n")
        cnt.write(b"Body 1, Line 2\r\n")
        cnt.write(b"--samp1\r\n")
        cnt.write(b"\r\n")
        cnt.write(b"Body 2, Line 1\r\n")
        cnt.write(b"--samp1--\r\n")
        response.data = cnt.getvalue()
        decoder_2 = MultipartDecoder.from_response(response)
        assert decoder_2.content_type == response.headers["content-type"]
        assert decoder_2.parts[0].data == b"Body 1, Line 1\r\nBody 1, Line 2"
        assert decoder_2.parts[0].headers["Header-1"] == "Header-Value-1"
        assert len(decoder_2.parts[1].headers) == 0
        assert decoder_2.parts[1].data == b"Body 2, Line 1"
