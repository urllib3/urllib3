import pytest

from urllib3.fields import RequestField
from urllib3.filepost import encode_multipart_formdata, iter_fields

BOUNDARY = "!! test boundary !!"
BOUNDARY_BYTES = BOUNDARY.encode()


class TestIterfields:
    def test_dict(self):
        for fieldname, value in iter_fields(dict(a="b")):
            assert (fieldname, value) == ("a", "b")

        assert list(sorted(iter_fields(dict(a="b", c="d")))) == [("a", "b"), ("c", "d")]

    def test_tuple_list(self):
        for fieldname, value in iter_fields([("a", "b")]):
            assert (fieldname, value) == ("a", "b")

        assert list(iter_fields([("a", "b"), ("c", "d")])) == [("a", "b"), ("c", "d")]


class TestMultipartEncoding:
    @pytest.mark.parametrize(
        "fields", [dict(k="v", k2="v2"), [("k", "v"), ("k2", "v2")]]
    )
    def test_input_datastructures(self, fields):
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
    def test_field_encoding(self, fields):
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

    def test_filename(self):
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

    def test_textplain(self):
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

    def test_explicit(self):
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

    def test_request_fields(self):
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
