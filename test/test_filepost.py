from __future__ import annotations

from email import policy
from email.parser import BytesParser

import pytest

from urllib3.fields import RequestField
from urllib3.filepost import _TYPE_FIELDS, encode_multipart_formdata

BOUNDARY = "!! test boundary !!"
BOUNDARY_BYTES = BOUNDARY.encode()


class TestMultipartEncoding:
    @pytest.mark.parametrize("boundary", [None, "boundary", "abc-123_456.789+"])
    def test_token_boundary(self, boundary: str | None) -> None:
        encoded, content_type = encode_multipart_formdata(
            {"field": "value"}, boundary=boundary
        )
        encoded_boundary = encoded.split(b"\r\n", 1)[0][2:].decode()
        assert content_type == f"multipart/form-data; boundary={encoded_boundary}"
        if boundary is not None:
            assert encoded_boundary == boundary

    @pytest.mark.parametrize("separator", [" ", ":", "/", "?", "=", ",", "(", ")"])
    def test_boundary_requires_quotes(self, separator: str) -> None:
        boundary = f"part{separator}boundary"
        encoded, content_type = encode_multipart_formdata(
            {"field": "value"}, boundary=boundary
        )
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\n\r\n".encode() + encoded
        )

        assert message.get_boundary() == boundary
        assert not message.defects
        parts = list(message.iter_parts())
        assert len(parts) == 1
        assert parts[0].get_param("name", header="content-disposition") == "field"
        assert parts[0].get_payload(decode=True) == b"value"

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

        assert content_type == f'multipart/form-data; boundary="{BOUNDARY}"'

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

        assert content_type == f'multipart/form-data; boundary="{BOUNDARY}"'

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

        assert content_type == f'multipart/form-data; boundary="{BOUNDARY}"'

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

        assert content_type == f'multipart/form-data; boundary="{BOUNDARY}"'

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
