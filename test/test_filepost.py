import unittest

from urllib3.filepost import encode_multipart_formdata, iter_fields
from urllib3.packages.six import b, u


BOUNDARY = '!! test boundary !!'


class TestIterfields(unittest.TestCase):

    def test_dict(self):
        for fieldname, value in iter_fields(dict(a='b')):
            self.assertEqual((fieldname, value), ('a', 'b'))

        self.assertEqual(
            list(sorted(iter_fields(dict(a='b', c='d')))),
            [('a', 'b'), ('c', 'd')])

    def test_tuple_list(self):
        for fieldname, value in iter_fields([('a', 'b')]):
            self.assertEqual((fieldname, value), ('a', 'b'))

        self.assertEqual(
            list(iter_fields([('a', 'b'), ('c', 'd')])),
            [('a', 'b'), ('c', 'd')])


class TestMultipartEncoding(unittest.TestCase):

    def test_input_datastructures(self):
        fieldsets = [
            dict(k='v', k2='v2'),
            [('k', 'v'), ('k2', 'v2')],
        ]

        for fields in fieldsets:
            encoded, _ = encode_multipart_formdata(fields, boundary=BOUNDARY)
            self.assertEqual(encoded.count(b(BOUNDARY)), 3)


    def test_field_encoding(self):
        fieldsets = [
            [('k', 'v'), ('k2', 'v2')],
            [('k', b'v'), (u('k2'), b'v2')],
            [('k', b'v'), (u('k2'), 'v2')],
        ]

        for fields in fieldsets:
            encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)

            self.assertEqual(encoded,
                b'--' + b(BOUNDARY) + b'\r\n'
                b'Content-Disposition: form-data; name="k"\r\n'
                b'\r\n'
                b'v\r\n'
                b'--' + b(BOUNDARY) + b'\r\n'
                b'Content-Disposition: form-data; name="k2"\r\n'
                b'\r\n'
                b'v2\r\n'
                b'--' + b(BOUNDARY) + b'--\r\n'
                , fields)

            self.assertEqual(content_type,
                b'multipart/form-data; boundary=' + b(BOUNDARY))


    def test_filename(self):
        fields = [('k', ('somename', b'v'))]

        encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)

        self.assertEqual(encoded,
            b'--' + b(BOUNDARY) + b'\r\n'
            b'Content-Disposition: form-data; name="k"; filename="somename"\r\n'
            b'Content-Type: application/octet-stream\r\n'
            b'\r\n'
            b'v\r\n'
            b'--' + b(BOUNDARY) + b'--\r\n'
            )

        self.assertEqual(content_type,
            b'multipart/form-data; boundary=' + b(BOUNDARY))


    def test_textplain(self):
        fields = [('k', ('somefile.txt', b'v'))]

        encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)

        self.assertEqual(encoded,
            b'--' + b(BOUNDARY) + b'\r\n'
            b'Content-Disposition: form-data; name="k"; filename="somefile.txt"\r\n'
            b'Content-Type: text/plain\r\n'
            b'\r\n'
            b'v\r\n'
            b'--' + b(BOUNDARY) + b'--\r\n'
            )

        self.assertEqual(content_type,
            b'multipart/form-data; boundary=' + b(BOUNDARY))


    def test_explicit(self):
        fields = [('k', ('somefile.txt', b'v', 'image/jpeg'))]

        encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)

        self.assertEqual(encoded,
            b'--' + b(BOUNDARY) + b'\r\n'
            b'Content-Disposition: form-data; name="k"; filename="somefile.txt"\r\n'
            b'Content-Type: image/jpeg\r\n'
            b'\r\n'
            b'v\r\n'
            b'--' + b(BOUNDARY) + b'--\r\n'
            )

    def test_international_headers(self):
        fields = [(u('ke\u00ff'), (u('n\u00e4me'), b'v1')),
                  (u('\u03a4\u03b5\u03be\u03c4'), b'v2')]

        encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)

        self.assertEqual(encoded,
            b'--' + b(BOUNDARY) + b'\r\n'
            b'Content-Disposition: form-data;'
            b" name*=utf-8''ke%C3%BF;"
            b" filename*=utf-8''n%C3%A4me\r\n"
            b'Content-Type: application/octet-stream\r\n'
            b'\r\n'
            b'v1\r\n'
            b'--' + b(BOUNDARY) + b'\r\n'
            b'Content-Disposition: form-data;'
            b" name*=utf-8''%CE%A4%CE%B5%CE%BE%CF%84\r\n"
            b'\r\n'
            b'v2\r\n'
            b'--' + b(BOUNDARY) + b'--\r\n'
            )

        self.assertEqual(content_type,
            b'multipart/form-data; boundary=' + b(BOUNDARY))
