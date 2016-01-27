import unittest

from io import BytesIO, BufferedReader

try:
    import http.client as httplib
except ImportError:
    import httplib
from urllib3.response import HTTPResponse
from urllib3.exceptions import DecodeError, ResponseNotChunked, ProtocolError


from base64 import b64decode

# A known random (i.e, not-too-compressible) payload generated with:
#    "".join(random.choice(string.printable) for i in xrange(512))
#    .encode("zlib").encode("base64")
# Randomness in tests == bad, and fixing a seed may not be sufficient.
ZLIB_PAYLOAD = b64decode(b"""\
eJwFweuaoQAAANDfineQhiKLUiaiCzvuTEmNNlJGiL5QhnGpZ99z8luQfe1AHoMioB+QSWHQu/L+
lzd7W5CipqYmeVTBjdgSATdg4l4Z2zhikbuF+EKn69Q0DTpdmNJz8S33odfJoVEexw/l2SS9nFdi
pis7KOwXzfSqarSo9uJYgbDGrs1VNnQpT9f8zAorhYCEZronZQF9DuDFfNK3Hecc+WHLnZLQptwk
nufw8S9I43sEwxsT71BiqedHo0QeIrFE01F/4atVFXuJs2yxIOak3bvtXjUKAA6OKnQJ/nNvDGKZ
Khe5TF36JbnKVjdcL1EUNpwrWVfQpFYJ/WWm2b74qNeSZeQv5/xBhRdOmKTJFYgO96PwrHBlsnLn
a3l0LwJsloWpMbzByU5WLbRE6X5INFqjQOtIwYz5BAlhkn+kVqJvWM5vBlfrwP42ifonM5yF4ciJ
auHVks62997mNGOsM7WXNG3P98dBHPo2NhbTvHleL0BI5dus2JY81MUOnK3SGWLH8HeWPa1t5KcW
S5moAj5HexY/g/F8TctpxwsvyZp38dXeLDjSQvEQIkF7XR3YXbeZgKk3V34KGCPOAeeuQDIgyVhV
nP4HF2uWHA==""")


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

    def test_reference_read(self):
        fp = BytesIO(b'foo')
        r = HTTPResponse(fp, preload_content=False)

        self.assertEqual(r.read(1), b'f')
        self.assertEqual(r.read(2), b'oo')
        self.assertEqual(r.read(), b'')
        self.assertEqual(r.read(), b'')

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
        self.assertEqual(r.read(), b'')
        self.assertEqual(r.read(), b'')


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
        self.assertEqual(r.read(), b'')
        self.assertEqual(r.read(), b'')


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
        self.assertEqual(r.read(), b'')
        self.assertEqual(r.read(), b'')


    def test_body_blob(self):
        resp = HTTPResponse(b'foo')
        self.assertEqual(resp.data, b'foo')
        self.assertTrue(resp.closed)

    def test_io(self):
        import socket

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
        hlr = httplib.HTTPResponse(socket.socket())
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

        b = b'fooandahalf'
        fp = BytesIO(b)
        resp = HTTPResponse(fp, preload_content=False)
        br = BufferedReader(resp, 5)

        br.read(1)  # sets up the buffer, reading 5
        self.assertEqual(len(fp.read()), len(b) - 5)

        # This is necessary to make sure the "no bytes left" part of `readinto`
        # gets tested.
        while not br.closed:
            br.read(5)

    def test_io_readinto(self):
        # This test is necessary because in py2.6, `readinto` doesn't get called
        # in `test_io_bufferedreader` like it does for all the other python
        # versions.  Probably this is because the `io` module in py2.6 is an
        # old version that has a different underlying implementation.


        fp = BytesIO(b'foo')
        resp = HTTPResponse(fp, preload_content=False)

        barr = bytearray(3)
        assert resp.readinto(barr) == 3
        assert b'foo' == barr

        # The reader should already be empty, so this should read nothing.
        assert resp.readinto(barr) == 0
        assert b'foo' == barr

    def test_streaming(self):
        fp = BytesIO(b'foo')
        resp = HTTPResponse(fp, preload_content=False)
        stream = resp.stream(2, decode_content=False)

        self.assertEqual(next(stream), b'fo')
        self.assertEqual(next(stream), b'o')
        self.assertRaises(StopIteration, next, stream)

    def test_streaming_tell(self):
        fp = BytesIO(b'foo')
        resp = HTTPResponse(fp, preload_content=False)
        stream = resp.stream(2, decode_content=False)

        position = 0

        position += len(next(stream))
        self.assertEqual(2, position)
        self.assertEqual(position, resp.tell())

        position += len(next(stream))
        self.assertEqual(3, position)
        self.assertEqual(position, resp.tell())

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

    def test_gzipped_streaming_tell(self):
        import zlib
        compress = zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
        uncompressed_data = b'foo'
        data = compress.compress(uncompressed_data)
        data += compress.flush()

        fp = BytesIO(data)
        resp = HTTPResponse(fp, headers={'content-encoding': 'gzip'},
                         preload_content=False)
        stream = resp.stream()

        # Read everything
        payload = next(stream)
        self.assertEqual(payload, uncompressed_data)

        self.assertEqual(len(data), resp.tell())

        self.assertRaises(StopIteration, next, stream)

    def test_concatenated_gzip_streaming(self):
        import zlib
        data = []
        uncompressed_data = []
        for i in range(3):
            compress = zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
            ud = b'foo{0}'.format(i)
            d = compress.compress(ud)
            d += compress.flush()
            data.append(d)
            uncompressed_data.append(ud)
        data = ''.join(data)
        uncompressed_data = ''.join(uncompressed_data)
        fp = BytesIO(data)
        resp = HTTPResponse(fp, headers={'content-encoding': 'gzip'},
                         preload_content=False)
        stream = resp.stream()

        # Read everything
        payload = next(stream)
        self.assertEqual(payload, uncompressed_data)
        

    def test_deflate_streaming_tell_intermediate_point(self):
        # Ensure that ``tell()`` returns the correct number of bytes when
        # part-way through streaming compressed content.
        import zlib

        NUMBER_OF_READS = 10

        class MockCompressedDataReading(BytesIO):
            """
            A ByteIO-like reader returning ``payload`` in ``NUMBER_OF_READS``
            calls to ``read``.
            """

            def __init__(self, payload, payload_part_size):
                self.payloads = [
                    payload[i*payload_part_size:(i+1)*payload_part_size]
                    for i in range(NUMBER_OF_READS+1)]

                assert b"".join(self.payloads) == payload

            def read(self, _):
                # Amount is unused.
                if len(self.payloads) > 0:
                    return self.payloads.pop(0)
                return b""

        uncompressed_data = zlib.decompress(ZLIB_PAYLOAD)

        payload_part_size = len(ZLIB_PAYLOAD) // NUMBER_OF_READS
        fp = MockCompressedDataReading(ZLIB_PAYLOAD, payload_part_size)
        resp = HTTPResponse(fp, headers={'content-encoding': 'deflate'},
                            preload_content=False)
        stream = resp.stream()

        parts_positions = [(part, resp.tell()) for part in stream]
        end_of_stream = resp.tell()

        self.assertRaises(StopIteration, next, stream)

        parts, positions = zip(*parts_positions)

        # Check that the payload is equal to the uncompressed data
        payload = b"".join(parts)
        self.assertEqual(uncompressed_data, payload)

        # Check that the positions in the stream are correct
        expected = [(i+1)*payload_part_size for i in range(NUMBER_OF_READS)]
        self.assertEqual(expected, list(positions))

        # Check that the end of the stream is in the correct place
        self.assertEqual(len(ZLIB_PAYLOAD), end_of_stream)

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

    def test_mock_transfer_encoding_chunked(self):
        stream = [b"fo", b"o", b"bar"]
        fp = MockChunkedEncodingResponse(stream)
        r = httplib.HTTPResponse(MockSock)
        r.fp = fp
        resp = HTTPResponse(r, preload_content=False, headers={'transfer-encoding': 'chunked'})

        i = 0
        for c in resp.stream():
            self.assertEqual(c, stream[i])
            i += 1

    def test_mock_gzipped_transfer_encoding_chunked_decoded(self):
        """Show that we can decode the gizpped and chunked body."""
        def stream():
            # Set up a generator to chunk the gzipped body
            import zlib
            compress = zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
            data = compress.compress(b'foobar')
            data += compress.flush()
            for i in range(0, len(data), 2):
                yield data[i:i+2]

        fp = MockChunkedEncodingResponse(list(stream()))
        r = httplib.HTTPResponse(MockSock)
        r.fp = fp
        headers = {'transfer-encoding': 'chunked', 'content-encoding': 'gzip'}
        resp = HTTPResponse(r, preload_content=False, headers=headers)

        data = b''
        for c in resp.stream(decode_content=True):
            data += c

        self.assertEqual(b'foobar', data)

    def test_mock_transfer_encoding_chunked_custom_read(self):
        stream = [b"foooo", b"bbbbaaaaar"]
        fp = MockChunkedEncodingResponse(stream)
        r = httplib.HTTPResponse(MockSock)
        r.fp = fp
        r.chunked = True
        r.chunk_left = None
        resp = HTTPResponse(r, preload_content=False, headers={'transfer-encoding': 'chunked'})
        expected_response = [b'fo', b'oo', b'o', b'bb', b'bb', b'aa', b'aa', b'ar']
        response = list(resp.read_chunked(2))
        if getattr(self, "assertListEqual", False):
            self.assertListEqual(expected_response, response)
        else:
            for index, item in enumerate(response):
                v = expected_response[index]
                self.assertEqual(item, v)

    def test_mock_transfer_encoding_chunked_unlmtd_read(self):
        stream = [b"foooo", b"bbbbaaaaar"]
        fp = MockChunkedEncodingResponse(stream)
        r = httplib.HTTPResponse(MockSock)
        r.fp = fp
        r.chunked = True
        r.chunk_left = None
        resp = HTTPResponse(r, preload_content=False, headers={'transfer-encoding': 'chunked'})
        if getattr(self, "assertListEqual", False):
            self.assertListEqual(stream, list(resp.read_chunked()))
        else:
            for index, item in enumerate(resp.read_chunked()):
                v = stream[index]
                self.assertEqual(item, v)

    def test_read_not_chunked_response_as_chunks(self):
        fp = BytesIO(b'foo')
        resp = HTTPResponse(fp, preload_content=False)
        r = resp.read_chunked()
        self.assertRaises(ResponseNotChunked, next, r)

    def test_invalid_chunks(self):
        stream = [b"foooo", b"bbbbaaaaar"]
        fp = MockChunkedInvalidEncoding(stream)
        r = httplib.HTTPResponse(MockSock)
        r.fp = fp
        r.chunked = True
        r.chunk_left = None
        resp = HTTPResponse(r, preload_content=False, headers={'transfer-encoding': 'chunked'})
        self.assertRaises(ProtocolError, next, resp.read_chunked())

    def test_chunked_response_without_crlf_on_end(self):
        stream = [b"foo", b"bar", b"baz"]
        fp = MockChunkedEncodingWithoutCRLFOnEnd(stream)
        r = httplib.HTTPResponse(MockSock)
        r.fp = fp
        r.chunked = True
        r.chunk_left = None
        resp = HTTPResponse(r, preload_content=False, headers={'transfer-encoding': 'chunked'})
        if getattr(self, "assertListEqual", False):
            self.assertListEqual(stream, list(resp.stream()))
        else:
            for index, item in enumerate(resp.stream()):
                v = stream[index]
                self.assertEqual(item, v)

    def test_chunked_response_with_extensions(self):
        stream = [b"foo", b"bar"]
        fp = MockChunkedEncodingWithExtensions(stream)
        r = httplib.HTTPResponse(MockSock)
        r.fp = fp
        r.chunked = True
        r.chunk_left = None
        resp = HTTPResponse(r, preload_content=False, headers={'transfer-encoding': 'chunked'})
        if getattr(self, "assertListEqual", False):
            self.assertListEqual(stream, list(resp.stream()))
        else:
            for index, item in enumerate(resp.stream()):
                v = stream[index]
                self.assertEqual(item, v)

    def test_get_case_insensitive_headers(self):
        headers = {'host': 'example.com'}
        r = HTTPResponse(headers=headers)
        self.assertEqual(r.headers.get('host'), 'example.com')
        self.assertEqual(r.headers.get('Host'), 'example.com')


class MockChunkedEncodingResponse(object):

    def __init__(self, content):
        """
        content: collection of str, each str is a chunk in response
        """
        self.content = content
        self.index = 0  # This class iterates over self.content.
        self.closed = False
        self.cur_chunk = b''
        self.chunks_exhausted = False

    @staticmethod
    def _encode_chunk(chunk):
        # In the general case, we can't decode the chunk to unicode
        length = '%X\r\n' % len(chunk)
        return length.encode() + chunk + b'\r\n'

    def _pop_new_chunk(self):
        if self.chunks_exhausted:
            return b""
        try:
            chunk = self.content[self.index]
        except IndexError:
            chunk = b''
            self.chunks_exhausted = True
        else:
            self.index += 1
        chunk = self._encode_chunk(chunk)
        if not isinstance(chunk, bytes):
            chunk = chunk.encode()
        return chunk

    def pop_current_chunk(self, amt=-1, till_crlf=False):
        if amt > 0 and till_crlf:
            raise ValueError("Can't specify amt and till_crlf.")
        if len(self.cur_chunk) <= 0:
            self.cur_chunk = self._pop_new_chunk()
        if till_crlf:
            try:
                i = self.cur_chunk.index(b"\r\n")
            except ValueError:
                # No CRLF in current chunk -- probably caused by encoder.
                self.cur_chunk = b""
                return b""
            else:
                chunk_part = self.cur_chunk[:i+2]
                self.cur_chunk = self.cur_chunk[i+2:]
                return chunk_part
        elif amt <= -1:
            chunk_part = self.cur_chunk
            self.cur_chunk = b''
            return chunk_part
        else:
            try:
                chunk_part = self.cur_chunk[:amt]
            except IndexError:
                chunk_part = self.cur_chunk
                self.cur_chunk = b''
            else:
                self.cur_chunk = self.cur_chunk[amt:]
            return chunk_part

    def readline(self):
        return self.pop_current_chunk(till_crlf=True)

    def read(self, amt=-1):
        return self.pop_current_chunk(amt)

    def flush(self):
        # Python 3 wants this method.
        pass

    def close(self):
        self.closed = True


class MockChunkedInvalidEncoding(MockChunkedEncodingResponse):

    def _encode_chunk(self, chunk):
        return 'ZZZ\r\n%s\r\n' % chunk.decode()


class MockChunkedEncodingWithoutCRLFOnEnd(MockChunkedEncodingResponse):

    def _encode_chunk(self, chunk):
        return '%X\r\n%s%s' % (len(chunk), chunk.decode(),
            "\r\n" if len(chunk) > 0 else "")


class MockChunkedEncodingWithExtensions(MockChunkedEncodingResponse):

    def _encode_chunk(self, chunk):
        return '%X;asd=qwe\r\n%s\r\n' % (len(chunk), chunk.decode())


class MockSock(object):
    @classmethod
    def makefile(cls, *args, **kwargs):
        return


if __name__ == '__main__':
    unittest.main()
