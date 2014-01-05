import unittest

from urllib3.filepost import encode_multipart_formdata, iter_fields
from urllib3.fields import RequestField
from urllib3.packages.six import b, u


BOUNDARY = '!! test boundary !!'


class SimpleNamespace(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


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
                'multipart/form-data; boundary=' + str(BOUNDARY))


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
            'multipart/form-data; boundary=' + str(BOUNDARY))


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
            'multipart/form-data; boundary=' + str(BOUNDARY))


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

        self.assertEqual(content_type,
            'multipart/form-data; boundary=' + str(BOUNDARY))

    def test_request_fields(self):
        fields = [RequestField('k', b'v', filename='somefile.txt', headers={'Content-Type': 'image/jpeg'})]

        encoded, content_type = encode_multipart_formdata(fields, boundary=BOUNDARY)

        self.assertEquals(encoded,
            b'--' + b(BOUNDARY) + b'\r\n'
            b'Content-Disposition: form-data; name="k"; filename="somefile.txt"\r\n'
            b'Content-Type: image/jpeg\r\n'
            b'\r\n'
            b'v\r\n'
            b'--' + b(BOUNDARY) + b'--\r\n'
            )

    def test_control_encoding(self):
        request = SimpleNamespace(form_data_encoding = 'iso-8859-1')
        fields = [(u('n\u00e4me\u011b'), u('va\u0142u\u00ea'))]
        encoded, content_type = encode_multipart_formdata(
            fields, boundary=BOUNDARY, request=request)
        self.assertEquals(encoded,
            b'--' + b(BOUNDARY) + b'\r\n'
            b'Content-Disposition: form-data; name="n\xe4me&#283;"\r\n'
            b'\r\n'
            b'va&#322;u\xea\r\n'
            b'--' + b(BOUNDARY) + b'--\r\n'
            )

    def test_control_style(self):
        request = SimpleNamespace(field_encoding_style = 'RFC2231')
        fields = [(u('n\u00e4me\u011b'), u('va\u0142u\u00ea'))]
        encoded, content_type = encode_multipart_formdata(
            fields, boundary=BOUNDARY, request=request)
        self.assertEquals(encoded,
            b'--' + b(BOUNDARY) + b'\r\n'
            b"Content-Disposition: form-data; name*=utf-8''n%C3%A4me%C4%9B\r\n"
            b'\r\n'
            b'va\xc5\x82u\xc3\xaa\r\n'
            b'--' + b(BOUNDARY) + b'--\r\n'
            )
