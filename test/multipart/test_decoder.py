from __future__ import annotations

import pytest

from urllib3 import HTTPResponse
from urllib3.exceptions import HTTPError
from urllib3.multipart import (
    ImproperBodyPartContentError,
    MultipartDecoder,
    MultipartEncoder,
    NonMultipartContentTypeError,
)
from urllib3.multipart.decoder import BodyPart


def test_body_part() -> None:
    part = BodyPart(b"X-Test: one\r\nX-Test: two\r\n\r\n\xffdata\r\n")
    assert part.data == b"\xffdata\r\n"
    assert part.headers.getlist("X-Test") == ["one", "two"]


def test_headerless_part() -> None:
    part = BodyPart(b"\r\ndata\r\nTwo lines")
    assert not part.headers
    assert part.data == b"data\r\nTwo lines"


def test_invalid_part() -> None:
    with pytest.raises(ImproperBodyPartContentError):
        BodyPart(b"no CRLF CRLF here!\r\n")


def test_round_trip() -> None:
    fields: list[tuple[str, str | bytes]] = [("first", "☃"), ("second", b"\x00\xff")]
    encoder = MultipartEncoder(fields, boundary="test boundary")
    decoder = MultipartDecoder(encoder.read(), content_type=encoder.content_type)
    assert [part.data for part in decoder.parts] == ["☃".encode(), b"\x00\xff"]
    assert decoder.parts[0].headers["Content-Disposition"] == 'form-data; name="first"'
    assert decoder.parts[1].headers["Content-Disposition"] == 'form-data; name="second"'


@pytest.mark.parametrize(
    "content_type",
    ['multipart/related; boundary="samp1"', 'Multipart/Related; boundary="samp1"'],
)
def test_from_response(content_type: str) -> None:
    response = HTTPResponse(
        body=b"\r\n--samp1\r\nHeader-1: Value-1\r\n\r\nBody 1\r\n"
        b"--samp1\r\n\r\nBody 2\r\n--samp1--\r\n",
        headers={"Content-Type": content_type},
    )
    decoder = MultipartDecoder.from_response(response)
    assert decoder.content_type == content_type
    assert decoder.parts[0].data == b"Body 1"
    assert decoder.parts[0].headers["Header-1"] == "Value-1"
    assert not decoder.parts[1].headers
    assert decoder.parts[1].data == b"Body 2"


def test_missing_content_type() -> None:
    with pytest.raises(ValueError, match="Cannot determine Content-Type"):
        MultipartDecoder.from_response(HTTPResponse(body=b""))


@pytest.mark.parametrize(
    "content_type",
    [
        "",
        "image/jpeg",
        "multipart",
        "multipart/",
        "multipart/mixed",
        'multipart/mixed; boundary=""',
        'multipart/mixed; boundary="☃"',
    ],
)
def test_invalid_content_type(content_type: str) -> None:
    with pytest.raises(NonMultipartContentTypeError):
        MultipartDecoder(b"", content_type=content_type)


@pytest.mark.parametrize("boundary", ["abc", "quoted;boundary"])
def test_delimiter_lines_preamble_and_epilogue(boundary: str) -> None:
    marker = boundary.encode()
    payload = b"data\r\n--" + marker + b"X\r\nmore\r\n"
    content = (
        b"preamble\r\n--"
        + marker
        + b"\r\n\r\n"
        + payload
        + b"\r\n--"
        + marker
        + b"--\r\nepilogue"
    )
    decoder = MultipartDecoder(
        content, content_type=f'multipart/mixed; boundary="{boundary}"'
    )
    assert len(decoder.parts) == 1
    assert decoder.parts[0].data == payload


def test_empty_multipart() -> None:
    assert (
        MultipartDecoder(b"--b--\r\n", content_type="multipart/mixed; boundary=b").parts
        == ()
    )


def test_missing_closing_boundary() -> None:
    with pytest.raises(ImproperBodyPartContentError):
        MultipartDecoder(b"--b\r\n\r\ndata", content_type="multipart/mixed; boundary=b")


def test_errors_are_http_errors() -> None:
    assert issubclass(ImproperBodyPartContentError, HTTPError)
    assert issubclass(NonMultipartContentTypeError, HTTPError)
