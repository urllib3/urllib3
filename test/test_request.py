from unittest import TestCase

from urllib3.request import Request, RequestMethods

class TestRequestMethods(TestCase):

    def setUp(self):
        self.rm = RequestMethods()

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

class TestRequest(TestCase):

    def setUp(self):
        self.request = Request('GET', 'https://google.com')

    def test_full_url(self):
        self.assertEqual(self.request.get_full_url(), 'https://google.com')

    def test_host(self):
        self.assertEqual(self.request.host, 'google.com')

    def test_type(self):
        self.assertEqual(self.request.type, 'https')

    def test_unverifiable(self):
        self.assertEqual(self.request.unverifiable, False)
        rq = Request('GET', 'https://google.com', redirected_by='http://yahoo.com')
        self.assertEqual(rq.unverifiable, True)

    def test_origin_req_host(self):
        self.assertEqual(self.request.origin_req_host, 'google.com')
        rq = Request('GET', 'https://google.com', redirected_by='http://yahoo.com')
        self.assertEqual(rq.origin_req_host, 'yahoo.com')

    def test_has_header(self):
        self.assertEqual(self.request.has_header('thingy'), False)
        rq = Request('GET', 'https://google.com', headers={'thingy':'thing2'})
        self.assertEqual(rq.has_header('thingy'), True)

    def test_get_header(self):
        self.assertEqual(self.request.get_header('thingy'), None)
        rq = Request('GET', 'https://google.com', headers={'thingy':'thing2'})
        self.assertEqual(rq.get_header('thingy'), 'thing2')

    def test_get_kwargs(self):
        intended_kw = {
            'method': 'GET',
            'url': 'https://google.com',
            'headers': {},
            'body': None
        }
        self.assertEqual(self.request.get_kwargs(), intended_kw)
