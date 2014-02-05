import unittest

from urllib3.fields import guess_content_type, RequestField
from urllib3.packages.six import u


class TestRequestField(unittest.TestCase):

    def test_guess_content_type(self):
        self.assertTrue(guess_content_type('image.jpg') in
                        ['image/jpeg', 'image/pjpeg'])
        self.assertEqual(guess_content_type('notsure'),
                         'application/octet-stream')
        self.assertEqual(guess_content_type(None), 'application/octet-stream')

    def test_create(self):
        simple_field = RequestField('somename', 'data')
        self.assertEqual(simple_field.render_headers(),
            'Content-Disposition: form-data; name="somename"\r\n\r\n')
        filename_field = RequestField('somename', 'data',
                                      filename='somefile.txt')
        self.assertEqual(filename_field.render_headers(),
            'Content-Disposition: form-data; name="somename"; filename="somefile.txt"\r\n'
            'Content-Type: text/plain\r\n'
            '\r\n')
        headers_field = RequestField('somename', 'data',
                                     headers={'Content-Length': 4})
        self.assertEqual(headers_field.render_headers(),
            'Content-Disposition: form-data; name="somename"\r\n'
            'Content-Length: 4\r\n\r\n')

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

    def test_render_parts(self):
        field = RequestField('somename', 'data')
        field.style = 'HTML5'
        parts = field._render_parts({'name': 'value', 'filename': 'value'})
        self.assertTrue('name="value"' in parts)
        self.assertTrue('filename="value"' in parts)
        parts = field._render_parts([('name', 'value'), ('filename', 'value')])
        self.assertEqual(parts, 'name="value"; filename="value"')

    def test_render_part_html5(self):
        field = RequestField('somename', 'data')
        field.style = 'HTML5'
        param = field._render_part('filename', u('name'))
        self.assertEqual(param, 'filename="name"')
        param = field._render_part('filename', u('n\u00e4me'))
        self.assertEqual(param, u('filename="n\u00e4me"'))
        param = field._render_part('filename', 'some"really\nbad\\name')
        self.assertEqual(param, 'filename="some\\"really bad\\\\name"')

    def test_render_part_rfc2231(self):
        field = RequestField('somename', 'data')
        field.style = 'RFC2231'
        param = field._render_part('filename', u('name'))
        self.assertEqual(param, 'filename="name"')
        param = field._render_part('filename', u('n\u00e4me'))
        self.assertEqual(param, "filename*=utf-8''n%C3%A4me")
        param = field._render_part('filename', 'some"really\nbad\\name')
        self.assertEqual(param, u("filename*=utf-8''some%22really%0Abad%5Cname"))

    def test_render_part_invalid_style(self):
        field = RequestField('somename', 'data')
        field.style = 'ThereIsNoSuchStyle'
        self.assertRaises(NotImplementedError,
            field._render_part, 'filename', u('name'))
