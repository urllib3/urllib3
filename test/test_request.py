from unittest import TestCase

from urllib3.request import Request


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
