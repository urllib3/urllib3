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


class TestBodyPart(unittest.TestCase):
    @staticmethod
    def bodypart_bytes_from_headers_and_values(
        headers: typing.Sequence[tuple[str, str]], value: str, encoding: str
    ) -> bytes:
        return b"\r\n\r\n".join(
            [
                b"\r\n".join(
                    [b": ".join([encode_with(i, encoding) for i in h]) for h in headers]
                ),
                encode_with(value, encoding),
            ]
        )

    def setUp(self) -> None:
        self.header_1 = ("Snowman", "\u2603")
        self.value_1 = "\u00a9"
        self.part_1 = BodyPart(
            TestBodyPart.bodypart_bytes_from_headers_and_values(
                (self.header_1,), self.value_1, "utf-8"
            ),
            "utf-8",
        )
        self.part_2 = BodyPart(
            TestBodyPart.bodypart_bytes_from_headers_and_values(
                [], self.value_1, "utf-16"
            ),
            "utf-16",
        )

    def test_equality_content_should_be_equal(self) -> None:
        part_3 = BodyPart(
            TestBodyPart.bodypart_bytes_from_headers_and_values(
                [], self.value_1, "utf-8"
            ),
            "utf-8",
        )
        assert self.part_1.content == part_3.content

    def test_equality_content_equals_bytes(self) -> None:
        assert self.part_1.content == encode_with(self.value_1, "utf-8")

    def test_equality_content_should_not_be_equal(self) -> None:
        assert self.part_1.content != self.part_2.content

    def test_equality_content_does_not_equal_bytes(self) -> None:
        assert self.part_1.content != encode_with(self.value_1, "latin-1")

    def test_changing_encoding_changes_text(self) -> None:
        part_2_orig_text = self.part_2.text
        self.part_2.encoding = "latin-1"
        assert self.part_2.text != part_2_orig_text

    def test_text_should_be_equal(self) -> None:
        assert self.part_1.text == self.part_2.text

    def test_no_headers(self) -> None:
        sample_1 = b"\r\n\r\nNo headers\r\nTwo lines"
        part_3 = BodyPart(sample_1, "utf-8")
        assert len(part_3.headers) == 0
        assert part_3.content == b"No headers\r\nTwo lines"

    def test_no_crlf_crlf_in_content(self) -> None:
        content = b"no CRLF CRLF here!\r\n"
        with pytest.raises(ImproperBodyPartContentError):
            BodyPart(content, "utf-8")


class TestMultipartDecoder(unittest.TestCase):
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
            self.encoded_1.read(), self.encoded_1.content_type
        )

    def test_non_multipart_response_fails(self) -> None:
        jpeg_response = mock.NonCallableMagicMock(spec=urllib3.response.HTTPResponse)
        jpeg_response.headers = {"content-type": "image/jpeg"}
        with pytest.raises(NonMultipartContentTypeError):
            MultipartDecoder.from_response(jpeg_response)

    def test_missing_boundary_raises_descriptive_error(self) -> None:
        """Verify that a multipart content-type without a boundary parameter raises
        NonMultipartContentTypeError with a clear message instead of AttributeError."""
        content_type_without_boundary = "multipart/form-data"
        with pytest.raises(
            NonMultipartContentTypeError,
            match="No boundary parameter found in content-type",
        ):
            MultipartDecoder(b"", content_type_without_boundary)

    def test_length_of_parts(self) -> None:
        assert len(self.sample_1) == len(self.decoded_1.parts)

    def test_content_of_parts(self) -> None:
        def parts_equal(part: BodyPart, sample: tuple[str, str]) -> bool:
            return part.content == encode_with(sample[1], "utf-8")

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
        assert decoder_2.parts[0].content == b"Body 1, Line 1\r\nBody 1, Line 2"
        assert decoder_2.parts[0].headers["Header-1"] == "Header-Value-1"
        assert len(decoder_2.parts[1].headers) == 0
        assert decoder_2.parts[1].content == b"Body 2, Line 1"

    def test_from_response_needs_content_type(self) -> None:
        response = mock.NonCallableMagicMock(spec=urllib3.response.HTTPResponse)
        response.headers = {}
        response.data = b""

        with pytest.raises(
            ValueError, match="Cannot determine content-type header from response"
        ):
            MultipartDecoder.from_response(response)

    def test_from_response_caps_large(self) -> None:
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
        assert decoder_2.parts[0].content == b"Body 1, Line 1\r\nBody 1, Line 2"
        assert decoder_2.parts[0].headers["Header-1"] == "Header-Value-1"
        assert len(decoder_2.parts[1].headers) == 0
        assert decoder_2.parts[1].content == b"Body 2, Line 1"

    def test_encoding_stored(self) -> None:
        assert self.decoded_1.encoding == "utf-8"

    def test_content_type_stored(self) -> None:
        assert self.decoded_1.content_type == self.encoded_1.content_type
