from io import BytesIO, BufferedReader

import pytest
import mock

from urllib3.base import Response
from urllib3.response import HTTPResponse
from urllib3.exceptions import DecodeError
from urllib3.util.retry import Retry

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


def get_response():
    return Response(
        status_code=200,
        headers={},
        body=BytesIO(b'hello'),
        version=b"HTTP/1.1"
    )


class TestLegacyResponse(object):
    def test_getheaders(self):
        headers = {'host': 'example.com'}
        r = HTTPResponse(headers=headers)
        assert r.getheaders() == headers

    def test_getheader(self):
        headers = {'host': 'example.com'}
        r = HTTPResponse(headers=headers)
        assert r.getheader('host') == 'example.com'


class TestResponse(object):
    def test_cache_content(self):
        r = HTTPResponse('foo')
        assert r.data == 'foo'
        assert r._body == 'foo'

    def test_default(self):
        r = HTTPResponse()
        assert r.data == b''

    def test_none(self):
        r = HTTPResponse(None)
        assert r.data == b''

    def test_preload(self):
        fp = BytesIO(b'foo')

        r = HTTPResponse(fp, preload_content=True)

        assert fp.tell() == len(b'foo')
        assert r.data == b'foo'

    def test_no_preload(self):
        fp = BytesIO(b'foo')

        r = HTTPResponse(fp, preload_content=False)

        assert fp.tell() == 0
        assert r.data == b'foo'
        assert fp.tell() == len(b'foo')

    def test_decode_bad_data(self):
        fp = BytesIO(b'\x00' * 10)
        with pytest.raises(DecodeError):
            HTTPResponse(fp, headers={'content-encoding': 'deflate'})

    def test_reference_read(self):
        fp = BytesIO(b'foo')
        r = HTTPResponse(fp, preload_content=False)

        assert r.read(1) == b'f'
        assert r.read(2) == b'oo'
        assert r.read() == b''
        assert r.read() == b''

    def test_decode_deflate(self):
        import zlib
        data = zlib.compress(b'foo')

        fp = BytesIO(data)
        r = HTTPResponse(fp, headers={'content-encoding': 'deflate'})

        assert r.data == b'foo'

    def test_decode_deflate_case_insensitve(self):
        import zlib
        data = zlib.compress(b'foo')

        fp = BytesIO(data)
        r = HTTPResponse(fp, headers={'content-encoding': 'DeFlAtE'})

        assert r.data == b'foo'

    def test_chunked_decoding_deflate(self):
        import zlib
        data = zlib.compress(b'foo')

        fp = BytesIO(data)
        r = HTTPResponse(fp, headers={'content-encoding': 'deflate'},
                         preload_content=False)

        assert r.read(1) == b'f'
        # Buffer in case we need to switch to the raw stream
        assert r._decoder._data is None
        assert r.read(2) == b'oo'
        assert r.read() == b''
        assert r.read() == b''

    def test_chunked_decoding_deflate2(self):
        import zlib
        compress = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
        data = compress.compress(b'foo')
        data += compress.flush()

        fp = BytesIO(data)
        r = HTTPResponse(fp, headers={'content-encoding': 'deflate'},
                         preload_content=False)

        assert r.read(1) == b'f'
        # Once we've decoded data, we just stream to the decoder; no buffering
        assert r._decoder._data is None
        assert r.read(2) == b'oo'
        assert r.read() == b''
        assert r.read() == b''

    def test_chunked_decoding_gzip(self):
        import zlib
        compress = zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
        data = compress.compress(b'foo')
        data += compress.flush()

        fp = BytesIO(data)
        r = HTTPResponse(fp, headers={'content-encoding': 'gzip'},
                         preload_content=False)

        assert r.read(1) == b'f'
        assert r.read(2) == b'oo'
        assert r.read() == b''
        assert r.read() == b''

    def test_body_blob(self):
        resp = HTTPResponse(b'foo')
        assert resp.data == b'foo'
        assert resp.closed

    def test_io(self, sock):
        fp = BytesIO(b'foo')
        resp = HTTPResponse(fp, preload_content=False)

        assert not resp.closed
        assert resp.readable()
        assert not resp.writable()
        with pytest.raises(IOError):
            resp.fileno()

        resp.close()
        assert resp.closed

        # Try closing with a base Response
        try:
            hlr = get_response()
            resp2 = HTTPResponse(hlr.body, preload_content=False)
            assert not resp2.closed
            resp2.close()
            assert resp2.closed
        finally:
            hlr.close()

        # also try when only data is present.
        resp3 = HTTPResponse('foodata')
        with pytest.raises(IOError):
            resp3.fileno()

    def test_io_bufferedreader(self):
        fp = BytesIO(b'foo')
        resp = HTTPResponse(fp, preload_content=False)
        br = BufferedReader(resp)

        assert br.read() == b'foo'

        br.close()
        assert resp.closed

        b = b'!tenbytes!'
        fp = BytesIO(b)
        resp = HTTPResponse(fp, preload_content=False)
        br = BufferedReader(resp, 5)

        # This is necessary to make sure the "no bytes left" part of `readinto`
        # gets tested.
        assert len(br.read(5)) == 5
        assert len(br.read(5)) == 5
        assert len(br.read(5)) == 0

    def test_streaming(self):
        fp = [b'fo', b'o']
        resp = HTTPResponse(fp, preload_content=False)
        stream = resp.stream(decode_content=False)

        assert next(stream) == b'fo'
        assert next(stream) == b'o'
        with pytest.raises(StopIteration):
            next(stream)

    def test_double_streaming(self):
        fp = [b'fo', b'o']
        resp = HTTPResponse(fp, preload_content=False)

        stream = list(resp.stream(decode_content=False))
        assert stream == fp

        stream = list(resp.stream(decode_content=False))
        assert stream == []

    def test_closed_streaming(self):
        fp = BytesIO(b'foo')
        resp = HTTPResponse(fp, preload_content=False)
        resp.close()
        with pytest.raises(StopIteration):
            next(resp.stream())

    def test_close_midstream(self):
        # A mock fp object that wraps a list and allows closing.
        class MockFP(object):
            self.list = None

            def close(self):
                self.list = None

            def __iter__(self):
                return self

            def __next__(self):
                if not self.list:
                    raise StopIteration()
                return self.list.pop(0)

            next = __next__

        data = [b'fo', b'o']
        fp = MockFP()
        fp.list = data
        resp = HTTPResponse(fp, preload_content=False)
        stream = resp.stream()

        assert next(stream) == b'fo'
        resp.close()
        with pytest.raises(StopIteration):
            next(stream)

    def test_streaming_tell(self):
        fp = [b'fo', b'o']
        resp = HTTPResponse(fp, preload_content=False)
        stream = resp.stream(decode_content=False)

        position = 0

        position += len(next(stream))
        assert 2 == position
        assert 2 == resp.tell()

        position += len(next(stream))
        assert 3 == position
        assert 3 == resp.tell()

        with pytest.raises(StopIteration):
            next(stream)

    def test_gzipped_streaming(self):
        import zlib
        compress = zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
        data = compress.compress(b'foo')
        data += compress.flush()

        fp = BytesIO(data)
        resp = HTTPResponse(fp, headers={'content-encoding': 'gzip'},
                            preload_content=False)
        stream = resp.stream()

        assert next(stream) == b'foo'
        with pytest.raises(StopIteration):
            next(stream)

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
        assert payload == uncompressed_data

        assert len(data) == resp.tell()

        with pytest.raises(StopIteration):
            next(stream)

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
                self.consumed = 0

                assert b"".join(self.payloads) == payload

            def read(self, _):
                # Amount is unused.
                if len(self.payloads) > 0:
                    payload = self.payloads.pop(0)
                    self.consumed += len(payload)
                    return payload
                return b""

            def __iter__(self):
                return self

            def __next__(self):
                if not self.payloads:
                    raise StopIteration()
                return self.read(None)

            next = __next__

        uncompressed_data = zlib.decompress(ZLIB_PAYLOAD)

        payload_part_size = len(ZLIB_PAYLOAD) // NUMBER_OF_READS
        fp = MockCompressedDataReading(ZLIB_PAYLOAD, payload_part_size)
        resp = HTTPResponse(fp, headers={'content-encoding': 'deflate'},
                            preload_content=False)
        parts = []
        stream = resp.stream(1)

        for part in stream:
            parts.append(part)
            self.assertEqual(resp.tell(), fp.consumed)

        end_of_stream = resp.tell()

        with pytest.raises(StopIteration):
            next(stream)

        # Check that the payload is equal to the uncompressed data
        payload = b"".join(parts)
        assert uncompressed_data == payload

        # Check that the end of the stream is in the correct place
        assert len(ZLIB_PAYLOAD) == end_of_stream

    def test_deflate_streaming(self):
        import zlib
        data = zlib.compress(b'foo')

        fp = BytesIO(data)
        resp = HTTPResponse(fp, headers={'content-encoding': 'deflate'},
                            preload_content=False)
        stream = resp.stream()

        assert next(stream) == b'foo'
        with pytest.raises(StopIteration):
            next(stream)

    def test_deflate2_streaming(self):
        import zlib
        compress = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
        data = compress.compress(b'foo')
        data += compress.flush()

        fp = BytesIO(data)
        resp = HTTPResponse(fp, headers={'content-encoding': 'deflate'},
                            preload_content=False)
        stream = resp.stream()

        assert next(stream) == b'foo'
        with pytest.raises(StopIteration):
            next(stream)

    def test_empty_stream(self):
        fp = BytesIO(b'')
        resp = HTTPResponse(fp, preload_content=False)
        stream = resp.stream(decode_content=False)

        with pytest.raises(StopIteration):
            next(stream)

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

            def __iter__(self):
                return self

            def __next__(self):
                if self.fp is None:
                    raise StopIteration()
                return self.read(1)

            next = __next__
        bio = BytesIO(b'foo')
        fp = MockHTTPRequest()
        fp.fp = bio
        resp = HTTPResponse(fp, preload_content=False)
        stream = resp.stream()

        assert next(stream) == b'f'
        assert next(stream) == b'o'
        assert next(stream) == b'o'
        with pytest.raises(StopIteration):
            next(stream)

    def test_get_case_insensitive_headers(self):
        headers = {'host': 'example.com'}
        r = HTTPResponse(headers=headers)
        assert r.headers.get('host') == 'example.com'
        assert r.headers.get('Host') == 'example.com'

    def test_retries(self):
        fp = BytesIO(b'')
        resp = HTTPResponse(fp)
        assert resp.retries is None
        retry = Retry()
        resp = HTTPResponse(fp, retries=retry)
        assert resp.retries == retry
