import unittest

from urllib3.fields import format_header_param_rfc2231, guess_content_type, RequestField
from urllib3.packages.six import u


class RequestFieldRFC2231(RequestField):
        # This class is used instead of RequestField in some tests, because
        # changing the class-member RequestField.header_formatter in a test
        # will cause subsequent tests to fail
        header_formatter = staticmethod(format_header_param_rfc2231)


class TestRequestField(unittest.TestCase):

    def test_guess_content_type(self):
        self.assertTrue(guess_content_type('image.jpg') in
                        ['image/jpeg', 'image/pjpeg'])
        self.assertEqual(guess_content_type('notsure'),
                         'application/octet-stream')
        self.assertEqual(guess_content_type(None), 'application/octet-stream')

    def test_create(self):
        simple_field = RequestField('somename', 'data')
        self.assertEqual(simple_field.render_headers(), '\r\n')
        filename_field = RequestField('somename', 'data',
                                      filename='somefile.txt')
        self.assertEqual(filename_field.render_headers(), '\r\n')
        headers_field = RequestField('somename', 'data',
                                     headers={'Content-Length': 4})
        self.assertEqual(
            headers_field.render_headers(), 'Content-Length: 4\r\n\r\n')

    def test_make_multipart(self):
        field = RequestField('somename', 'data')
        field.make_multipart(content_type='image/jpg',
                             content_location='/test')
        self.assertEqual(
            field.render_headers(),
            'Content-Disposition: form-data; name="somename"\r\n'
            'Content-Type: image/jpg\r\n'
            'Content-Location: /test\r\n'
            '\r\n')

    def test_make_multipart_empty_filename(self):
        field = RequestField('somename', 'data', '')
        field.make_multipart(content_type='application/octet-stream')
        self.assertEqual(
            field.render_headers(),
            'Content-Disposition: form-data; name="somename"; filename=""\r\n'
            'Content-Type: application/octet-stream\r\n'
            '\r\n')

    def test_render_parts(self):
        field = RequestField('somename', 'data')
        parts = field._render_parts({'name': 'value', 'filename': 'value'})
        self.assertTrue('name="value"' in parts)
        self.assertTrue('filename="value"' in parts)
        parts = field._render_parts([('name', 'value'), ('filename', 'value')])
        self.assertEqual(parts, 'name="value"; filename="value"')

    def test_render_part_rfc2231_non_ascii(self):
        field = RequestFieldRFC2231('somename', 'data')
        param = field._render_part('filename', u('n\u00e4me'))
        self.assertEqual(param, u("filename*=utf-8''n%C3%A4me"))

    def test_render_part_rfc2231_ascii_only(self):
        field = RequestFieldRFC2231('somename', 'data')
        param = field._render_part('filename', u('name'))
        self.assertEqual(param, u('filename="name"'))

    def test_render_part_html5(self):
        field = RequestField('somename', 'data')
        param = field._render_part('filename', u('n\u00e4me'))
        self.assertEqual(param, u('filename="n\u00e4me"'))

    def test_from_tuples_rfc2231(self):
        field = RequestFieldRFC2231.from_tuples(u('fieldname'), (u('filen\u00e4me'), 'data'))
        cd = field.headers['Content-Disposition']
        self.assertEqual(cd, u("form-data; name=\"fieldname\"; filename*=utf-8''filen%C3%A4me"))

    def test_from_tuples_html5(self):
        field = RequestField.from_tuples(u('fieldname'), (u('filen\u00e4me'), 'data'))
        cd = field.headers['Content-Disposition']
        self.assertEqual(cd, u('form-data; name="fieldname"; filename="filen\u00e4me"'))
