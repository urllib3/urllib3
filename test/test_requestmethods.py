from unittest import TestCase

import urllib3.request

class TestRequestMethods(TestCase):

    def setUp(self):
        self.rm = urllib3.request.RequestMethods()

    def test_encode_body_implicitly(self):
        boundary = '00000'
        fields = {'thing1': 'thing2'}
        headers, body = self.rm.encode_body_and_headers('POST', fields=fields, multipart_boundary=boundary)
        self.assertEqual(headers, {'Content-Type': 'multipart/form-data; boundary=00000'})
        intended_body = (
            b'--00000\r\n'
            b'Content-Disposition: form-data; name="thing1"\r\n'
            b'\r\n'
            b'thing2\r\n'
            b'--00000--\r\n'
        )
        self.assertEqual(body, intended_body)

    def test_encode_body_explicitly(self):
        boundary = '00000'
        fields = {'thing1': 'thing2'}
        headers, body = self.rm.encode_body_and_headers('POST', form_fields=fields, multipart_boundary=boundary)
        self.assertEqual(headers, {'Content-Type': 'multipart/form-data; boundary=00000'})
        intended_body = (
            b'--00000\r\n'
            b'Content-Disposition: form-data; name="thing1"\r\n'
            b'\r\n'
            b'thing2\r\n'
            b'--00000--\r\n'
        )
        self.assertEqual(body, intended_body)

    def test_encode_body_partially_explicitly(self):
        boundary = '00000'
        fields = {'thing1': 'thing2'}
        form_fields = {'thing3': 'thing4'}
        headers, body = self.rm.encode_body_and_headers('POST', fields=fields, form_fields=form_fields,
                                                        multipart_boundary=boundary)
        self.assertEqual(headers, {'Content-Type': 'multipart/form-data; boundary=00000'})
        intended_body = (
            b'--00000\r\n'
            b'Content-Disposition: form-data; name="thing1"\r\n'
            b'\r\n'
            b'thing2\r\n'
            b'--00000\r\n'
            b'Content-Disposition: form-data; name="thing3"\r\n'
            b'\r\n'
            b'thing4\r\n'
            b'--00000--\r\n'
        )
        self.assertEqual(body, intended_body)

    def test_encode_urlencoded_body_implicitly(self):
        fields = {'thing1': 'thing2'}
        headers, body = self.rm.encode_body_and_headers('POST', fields=fields, encode_multipart=False)
        self.assertEqual(headers, {'Content-Type': 'application/x-www-form-urlencoded'})
        intended_body = ('thing1=thing2')
        self.assertEqual(body, intended_body)

    def test_encode_urlencoded_body_explicitly(self):
        fields = {'thing1': 'thing2'}
        headers, body = self.rm.encode_body_and_headers('POST', form_fields=fields, encode_multipart=False)
        self.assertEqual(headers, {'Content-Type': 'application/x-www-form-urlencoded'})
        intended_body = ('thing1=thing2')
        self.assertEqual(body, intended_body)

    def test_encode_urlencoded_body_partially_explicitly(self):
        fields = {'thing1': 'thing2'}
        form_fields = {'thing3': 'thing4'}
        headers, body = self.rm.encode_body_and_headers('POST', fields=fields, form_fields=form_fields, encode_multipart=False)
        self.assertEqual(headers, {'Content-Type': 'application/x-www-form-urlencoded'})
        intended_body = ('thing1=thing2&thing3=thing4')
        self.assertEqual(body, intended_body)

    def test_encode_url_implicitly(self):
        fields = {'thing1': 'thing2'}
        url = self.rm.encode_url('GET', 'http://google.com', fields=fields)
        self.assertEqual(url, 'http://google.com?thing1=thing2')

    def test_encode_url_explicitly(self):
        fields = {'thing1': 'thing2'}
        url = self.rm.encode_url('GET', 'http://google.com', url_params=fields)
        self.assertEqual(url, 'http://google.com?thing1=thing2')

    def test_encode_url_partially_explicitly(self):
        fields = {'thing1': 'thing2'}
        params = {'thing3': 'thing4'}
        url = self.rm.encode_url('GET', 'http://google.com', fields=fields, url_params=params)
        self.assertEqual(url, 'http://google.com?thing1=thing2&thing3=thing4')