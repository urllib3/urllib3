import unittest

from io import BytesIO, BufferedReader

from urllib3.response import HTTPResponse
from urllib3.exceptions import DecodeError

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
        self.assertEqual(r.data, None)

    def test_none(self):
        r = HTTPResponse(None)
        self.assertEqual(r.data, None)

    def test_preload(self):
        fp = BytesIO(b'foo')

        r = HTTPResponse(fp, preload_content=True)

        self.assertEqual(fp.tell(), len(b'foo'))
        self.assertEqual(r.data, b'foo')

    def test_no_preload(self):
        fp = BytesIO(b'foo')

        r = HTTPResponse(fp, preload_content=False)

        self.assertEqual(fp.tell(), 0)
        self.assertEqual(r.data, b'foo')
        self.assertEqual(fp.tell(), len(b'foo'))

    def test_decode_bad_data(self):
        fp = BytesIO(b'\x00' * 10)
        self.assertRaises(DecodeError, HTTPResponse, fp, headers={
            'content-encoding': 'deflate'
        })

    def test_decode_deflate(self):
        import zlib
        data = zlib.compress(b'foo')

        fp = BytesIO(data)
        r = HTTPResponse(fp, headers={'content-encoding': 'deflate'})

        self.assertEqual(r.data, b'foo')

    def test_decode_deflate_case_insensitve(self):
        import zlib
        data = zlib.compress(b'foo')

        fp = BytesIO(data)
        r = HTTPResponse(fp, headers={'content-encoding': 'DeFlAtE'})

        self.assertEqual(r.data, b'foo')

    def test_chunked_decoding_deflate(self):
        import zlib
        data = zlib.compress(b'foo')

        fp = BytesIO(data)
        r = HTTPResponse(fp, headers={'content-encoding': 'deflate'},
                         preload_content=False)

        self.assertEqual(r.read(3), b'')
        self.assertEqual(r.read(1), b'f')
        self.assertEqual(r.read(2), b'oo')

    def test_chunked_decoding_deflate2(self):
        import zlib
        compress = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
        data = compress.compress(b'foo')
        data += compress.flush()

        fp = BytesIO(data)
        r = HTTPResponse(fp, headers={'content-encoding': 'deflate'},
                         preload_content=False)

        self.assertEqual(r.read(1), b'')
        self.assertEqual(r.read(1), b'f')
        self.assertEqual(r.read(2), b'oo')

    def test_chunked_decoding_gzip(self):
        import zlib
        compress = zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
        data = compress.compress(b'foo')
        data += compress.flush()

        fp = BytesIO(data)
        r = HTTPResponse(fp, headers={'content-encoding': 'gzip'},
                         preload_content=False)

        self.assertEqual(r.read(11), b'')
        self.assertEqual(r.read(1), b'f')
        self.assertEqual(r.read(2), b'oo')

    def test_io(self):
        import socket
        try:
            from http.client import HTTPResponse as OldHTTPResponse
        except:
            from httplib import HTTPResponse as OldHTTPResponse

        fp = BytesIO(b'foo')
        resp = HTTPResponse(fp, preload_content=False)

        self.assertEqual(resp.closed, False)
        self.assertEqual(resp.readable(), True)
        self.assertEqual(resp.writable(), False)
        self.assertRaises(IOError, resp.fileno)

        resp.close()
        self.assertEqual(resp.closed, True)

        # Try closing with an `httplib.HTTPResponse`, because it has an
        # `isclosed` method.
        hlr = OldHTTPResponse(socket.socket())
        resp2 = HTTPResponse(hlr, preload_content=False)
        self.assertEqual(resp2.closed, False)
        resp2.close()
        self.assertEqual(resp2.closed, True)

        #also try when only data is present.
        resp3 = HTTPResponse('foodata')
        self.assertRaises(IOError, resp3.fileno)

        resp3._fp = 2
        # A corner case where _fp is present but doesn't have `closed`,
        # `isclosed`, or `fileno`.  Unlikely, but possible.
        self.assertEqual(resp3.closed, True)
        self.assertRaises(IOError, resp3.fileno)

    def test_io_bufferedreader(self):
        fp = BytesIO(b'foo')
        resp = HTTPResponse(fp, preload_content=False)
        br = BufferedReader(resp)

        self.assertEqual(br.read(), b'foo')

        br.close()
        self.assertEqual(resp.closed, True)

    def test_streaming(self):
        fp = BytesIO(b'foo')
        resp = HTTPResponse(fp, preload_content=False)
        stream = resp.stream(2, decode_content=False)

        self.assertEqual(next(stream), b'fo')
        self.assertEqual(next(stream), b'o')
        self.assertRaises(StopIteration, next, stream)

    def test_gzipped_streaming(self):
        import zlib
        compress = zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
        data = compress.compress(b'foo')
        data += compress.flush()

        fp = BytesIO(data)
        resp = HTTPResponse(fp, headers={'content-encoding': 'gzip'},
                         preload_content=False)
        stream = resp.stream(2)

        self.assertEqual(next(stream), b'f')
        self.assertEqual(next(stream), b'oo')
        self.assertRaises(StopIteration, next, stream)

    def test_deflate_streaming(self):
        import zlib
        data = zlib.compress(b'foo')

        fp = BytesIO(data)
        resp = HTTPResponse(fp, headers={'content-encoding': 'deflate'},
                         preload_content=False)
        stream = resp.stream(2)

        self.assertEqual(next(stream), b'f')
        self.assertEqual(next(stream), b'oo')
        self.assertRaises(StopIteration, next, stream)

    def test_deflate2_streaming(self):
        import zlib
        compress = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
        data = compress.compress(b'foo')
        data += compress.flush()

        fp = BytesIO(data)
        resp = HTTPResponse(fp, headers={'content-encoding': 'deflate'},
                         preload_content=False)
        stream = resp.stream(2)

        self.assertEqual(next(stream), b'f')
        self.assertEqual(next(stream), b'oo')
        self.assertRaises(StopIteration, next, stream)

    def test_empty_stream(self):
        fp = BytesIO(b'')
        resp = HTTPResponse(fp, preload_content=False)
        stream = resp.stream(2, decode_content=False)

        self.assertRaises(StopIteration, next, stream)

    def test_mock_httpresponse_stream(self):
        # Mock out a HTTP Request that does enough to make it through urllib3's
        # read() and close() calls, and also exhausts and underlying file
        # object.
        class MockHTTPRequest(object):
            self.fp = None

            def read(self, amt):
                data = self.fp.read(amt)
                if not data:
                    self.fp = None

                return data

            def close(self):
                self.fp = None

        bio = BytesIO(b'foo')
        fp = MockHTTPRequest()
        fp.fp = bio
        resp = HTTPResponse(fp, preload_content=False)
        stream = resp.stream(2)

        self.assertEqual(next(stream), b'fo')
        self.assertEqual(next(stream), b'o')
        self.assertRaises(StopIteration, next, stream)


if __name__ == '__main__':
    unittest.main()
