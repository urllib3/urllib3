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


class TestMultipartDecoder:
    def test_basic_decode(self) -> None:
        encoder = MultipartEncoder([("a", "1"), ("b", "2")], boundary="bound")
        body = encoder.read()
        decoder = MultipartDecoder(body, content_type=encoder.content_type)
        assert len(decoder.parts) == 2
        assert decoder.parts[0].data == b"1"
        assert decoder.parts[1].data == b"2"
        assert decoder.parts[0].headers["Content-Disposition"] == (
            'form-data; name="a"'
        )

    def test_body_part_text(self) -> None:
        part = BodyPart(b'Content-Disposition: form-data; name="x"\r\n\r\nhello')
        assert part.data == b"hello"

    def test_body_part_without_headers(self) -> None:
        part = BodyPart(b"\r\n\r\nbody")
        assert part.data == b"body"
        assert not part.headers

    def test_duplicate_part_headers_are_preserved(self) -> None:
        part = BodyPart(b"X-Value: one\r\nX-Value: two\r\n\r\ndata")
        assert part.headers.getlist("X-Value") == ["one", "two"]

    def test_decoder_errors_are_http_errors(self) -> None:
        assert issubclass(ImproperBodyPartContentError, HTTPError)
        assert issubclass(NonMultipartContentTypeError, HTTPError)

    def test_improper_body_part(self) -> None:
        with pytest.raises(ImproperBodyPartContentError):
            BodyPart(b"no-separator")

    def test_non_multipart_content_type(self) -> None:
        with pytest.raises(NonMultipartContentTypeError):
            MultipartDecoder(b"x", content_type="text/plain")

    def test_missing_boundary(self) -> None:
        with pytest.raises(NonMultipartContentTypeError):
            MultipartDecoder(b"x", content_type="multipart/form-data")

    def test_empty_content_type(self) -> None:
        with pytest.raises(NonMultipartContentTypeError, match="must not be empty"):
            MultipartDecoder(b"x", content_type="")

    def test_unterminated_quoted_boundary(self) -> None:
        with pytest.raises(NonMultipartContentTypeError, match="Unterminated boundary"):
            MultipartDecoder(
                b"x", content_type='multipart/form-data; boundary="missing'
            )

    def test_quoted_boundary_with_semicolon(self) -> None:
        decoder = MultipartDecoder(
            b'--a;b\r\nContent-Disposition: form-data; name="x"\r\n\r\ny\r\n--a;b--\r\n',
            content_type='multipart/form-data; boundary="a;b"',
        )
        assert decoder.boundary == b"a;b"
        assert decoder.parts[0].data == b"y"

    def test_preamble_and_epilogue_are_ignored(self) -> None:
        decoder = MultipartDecoder(
            b'preamble\r\n--b\r\nContent-Disposition: form-data; name="x"'
            b"\r\n\r\ny\r\n--b--\r\nepilogue",
            content_type="multipart/form-data; boundary=b",
        )
        assert len(decoder.parts) == 1
        assert decoder.parts[0].data == b"y"

    def test_boundary_prefix_inside_body_is_not_a_delimiter(self) -> None:
        decoder = MultipartDecoder(
            b'--b\r\nContent-Disposition: form-data; name="x"\r\n\r\n'
            b"first\r\n--boundary-is-data\r\nlast\r\n--b--\r\n",
            content_type="multipart/form-data; boundary=b",
        )
        assert decoder.parts[0].data == (b"first\r\n--boundary-is-data\r\nlast")

    def test_opening_boundary_without_following_boundary_has_no_parts(self) -> None:
        decoder = MultipartDecoder(
            b"--b\r\nContent-Disposition: form-data\r\n\r\ndata",
            content_type="multipart/form-data; boundary=b",
        )
        assert decoder.parts == ()

    def test_closing_boundary_before_parts_has_no_parts(self) -> None:
        decoder = MultipartDecoder(
            b"--b--\r\n", content_type="multipart/form-data; boundary=b"
        )
        assert decoder.parts == ()

    def test_body_without_any_boundary_has_no_parts(self) -> None:
        decoder = MultipartDecoder(
            b"not a multipart delimiter",
            content_type="multipart/form-data; boundary=b",
        )
        assert decoder.parts == ()

    def test_from_response(self) -> None:
        response = HTTPResponse(
            body=(
                b'--b\r\nContent-Disposition: form-data; name="x"\r\n\r\n'
                b"data\r\n--b--\r\n"
            ),
            headers={"Content-Type": "multipart/form-data; boundary=b"},
        )
        decoder = MultipartDecoder.from_response(response)
        assert decoder.parts[0].data == b"data"

    def test_from_response_requires_content_type(self) -> None:
        with pytest.raises(ValueError, match="Cannot determine Content-Type"):
            MultipartDecoder.from_response(HTTPResponse(body=b"data"))

    def test_file_part_round_trip(self) -> None:
        encoder = MultipartEncoder(
            [("file", ("name.bin", b"\x00\x01", "application/octet-stream"))],
            boundary="b",
        )
        body = encoder.read()
        decoder = MultipartDecoder(body, content_type=encoder.content_type)
        assert len(decoder.parts) == 1
        assert decoder.parts[0].data == b"\x00\x01"
        assert decoder.parts[0].headers["Content-Type"] == "application/octet-stream"
