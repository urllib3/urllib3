import sys
import unittest

from StringIO import StringIO


sys.path.append('../')


from urllib3.response import HTTPResponse


class TestResponse(unittest.TestCase):
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

    def test_decode_deflate(self):
        data = 'foo'.encode('zlib')

        fp = StringIO(data)
        r = HTTPResponse(fp, headers={'content-encoding': 'deflate'})

        self.assertEqual(r.data, 'foo')


if __name__ == '__main__':
    unittest.main()
