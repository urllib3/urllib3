import unittest
import zlib

from StringIO import StringIO

from urllib3.response import HTTPResponse

class TestLegacyResponse(unittest.TestCase):
    def test_getheaders(self):
        headers = {'host': 'example.com'}
        r = HTTPResponse(headers=headers)
        self.assertEqual(r.getheaders(), headers)

    def test_getheader(self):
        headers = {'host': 'example.com'}
        r = HTTPResponse(headers=headers)
        self.assertEqual(r.getheader('host'), 'example.com')


class TestResponse(unittest.TestCase):
    def test_cache_content(self):
        r = HTTPResponse('foo')
        self.assertEqual(r.data, 'foo')
        self.assertEqual(r._body, 'foo')

    def test_default(self):
        r = HTTPResponse()
        self.assertEqual(r.data, '')

    def test_preload(self):
        fp = StringIO('foo')

        r = HTTPResponse(fp, preload_content=True)

        self.assertEqual(fp.tell(), fp.len)
        self.assertEqual(r.data, 'foo')

    def test_no_preload(self):
        fp = StringIO('foo')

        r = HTTPResponse(fp, preload_content=False)

        self.assertEqual(fp.tell(), 0)
        self.assertEqual(r.data, 'foo')
        self.assertEqual(fp.tell(), fp.len)

    def test_decode_bad_data(self):
        data = '\x00' * 10
        self.assertRaises(zlib.error, HTTPResponse, data, headers={
            'content-encoding': 'deflate'
        })

    def test_decode_deflate(self):
        data = 'foo'.encode('zlib')

        fp = StringIO(data)
        r = HTTPResponse(fp, headers={'content-encoding': 'deflate'})

        self.assertEqual(r.data, 'foo')


if __name__ == '__main__':
    unittest.main()
