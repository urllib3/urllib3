import logging
import sys
import unittest
import urllib

from urllib3 import encode_multipart_formdata, HTTPConnectionPool
from urllib3.exceptions import TimeoutError, EmptyPoolError, MaxRetryError

from dummyserver.testcase import HTTPDummyServerTestCase


log = logging.getLogger('urllib3.connectionpool')
log.setLevel(logging.NOTSET)
log.addHandler(logging.StreamHandler(sys.stdout))


class TestConnectionPool(HTTPDummyServerTestCase):

    def setUp(self):
        self._pool = HTTPConnectionPool(self.host, self.port)

    def test_get(self):
        r = self._pool.request('GET', '/specific_method',
                               fields={'method': 'GET'})
        self.assertEqual(r.status, 200, r.data)

    def test_post_url(self):
        r = self._pool.request('POST', '/specific_method',
                               fields={'method': 'POST'})
        self.assertEqual(r.status, 200, r.data)

    def test_urlopen_put(self):
        r = self._pool.urlopen('PUT', '/specific_method?method=PUT')
        self.assertEqual(r.status, 200, r.data)

    def test_wrong_specific_method(self):
        # To make sure the dummy server is actually returning failed responses
        r = self._pool.request('GET', '/specific_method',
                               fields={'method': 'POST'})
        self.assertEqual(r.status, 400, r.data)

        r = self._pool.request('POST', '/specific_method',
                               fields={'method': 'GET'})
        self.assertEqual(r.status, 400, r.data)

    def test_upload(self):
        data = "I'm in ur multipart form-data, hazing a cheezburgr"
        fields = {
            'upload_param': 'filefield',
            'upload_filename': 'lolcat.txt',
            'upload_size': len(data),
            'filefield': ('lolcat.txt', data),
        }

        r = self._pool.request('POST', '/upload', fields=fields)
        self.assertEqual(r.status, 200, r.data)

    def test_unicode_upload(self):
        fieldname = u'myfile'
        filename = u'\xe2\x99\xa5.txt'
        data = u'\xe2\x99\xa5'.encode('utf8')
        size = len(data)

        fields = {
            u'upload_param': fieldname,
            u'upload_filename': filename,
            u'upload_size': size,
            fieldname: (filename, data),
        }

        r = self._pool.request('POST', '/upload', fields=fields)
        self.assertEqual(r.status, 200, r.data)

    def test_timeout(self):
        pool = HTTPConnectionPool(self.host, self.port, timeout=0.01)
        try:
            pool.request('GET', '/sleep',
                         fields={'seconds': '0.02'})
            self.fail("Failed to raise TimeoutError exception")
        except TimeoutError:
            pass

    def test_redirect(self):
        r = self._pool.request('GET', '/redirect',
                                   fields={'target': '/'},
                                   redirect=False)
        self.assertEqual(r.status, 303)

        r = self._pool.request('GET', '/redirect',
                                   fields={'target': '/'})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, 'Dummy server!')

    def test_maxretry(self):
        try:
            self._pool.request('GET', '/redirect',
                                   fields={'target': '/'},
                                   retries=0)
            self.fail("Failed to raise MaxRetryError exception")
        except MaxRetryError:
            pass

    def test_keepalive(self):
        pool = HTTPConnectionPool(self.host, self.port, block=True, maxsize=1)

        r = pool.request('GET', '/keepalive?close=0')
        r = pool.request('GET', '/keepalive?close=0')

        self.assertEqual(r.status, 200)
        self.assertEqual(pool.num_connections, 1)
        self.assertEqual(pool.num_requests, 2)

    def test_keepalive_close(self):
        # NOTE: This used to run against apache.org but it made the test suite
        # really slow and fail half the time. Setting it to skip until we can
        # make this run better locally.
        pool = HTTPConnectionPool(self.host, self.port,
                                  block=True, maxsize=1, timeout=2)

        r = pool.request('GET', '/keepalive?close=1', retries=0,
                         headers={
                             "Connection": "close",
                         })

        self.assertEqual(pool.num_connections, 1)

        # The dummyserver will have responded with Connection:close,
        # and httplib will properly cleanup the socket.

        # We grab the HTTPConnection object straight from the Queue,
        # because _get_conn() is where the check & reset occurs
        # pylint: disable-msg=W0212
        conn = pool.pool.get()
        self.assertEqual(conn.sock, None)
        pool._put_conn(conn)

        # Now with keep-alive
        r = pool.request('GET', '/keepalive?close=0', retries=0,
                         headers={
                             "Connection": "keep-alive",
                         })

        # The dummyserver responded with Connection:keep-alive, the connection
        # persists.
        conn = pool.pool.get()
        self.assertNotEqual(conn.sock, None)
        pool._put_conn(conn)

        # Another request asking the server to close the connection. This one
        # should get cleaned up for the next request.
        r = pool.request('GET', '/keepalive?close=1', retries=0,
                         headers={
                             "Connection": "close",
                         })

        self.assertEqual(r.status, 200)

        conn = pool.pool.get()
        self.assertEqual(conn.sock, None)
        pool._put_conn(conn)

        # Next request
        r = pool.request('GET', '/keepalive?close=0')

    def test_post_with_urlencode(self):
        data = {'banana': 'hammock', 'lol': 'cat'}
        r = self._pool.request('POST', '/echo',
                                    fields=data,
                                    encode_multipart=False)
        self.assertEqual(r.data, urllib.urlencode(data))

    def test_post_with_multipart(self):
        data = {'banana': 'hammock', 'lol': 'cat'}
        r = self._pool.request('POST', '/echo',
                                    fields=data,
                                    encode_multipart=True)
        body = r.data.split('\r\n')

        encoded_data = encode_multipart_formdata(data)[0]
        expected_body = encoded_data.split('\r\n')

        # TODO: Get rid of extra parsing stuff when you can specify
        # a custom boundary to encode_multipart_formdata
        """
        We need to loop the return lines because a timestamp is attached
        from within encode_multipart_formdata. When the server echos back
        the data, it has the timestamp from when the data was encoded, which
        is not equivalent to when we run encode_multipart_formdata on
        the data again.
        """
        for i, line in enumerate(body):
            if line.startswith('--'):
                continue

            self.assertEqual(body[i], expected_body[i])

    def test_check_gzip(self):
        r = self._pool.request('GET', '/encodingrequest',
                                   headers={'accept-encoding': 'gzip'})
        self.assertEqual(r.headers.get('content-encoding'), 'gzip')
        self.assertEqual(r.data, 'hello, world!')

    def test_check_deflate(self):
        r = self._pool.request('GET', '/encodingrequest',
                                   headers={'accept-encoding': 'deflate'})
        self.assertEqual(r.headers.get('content-encoding'), 'deflate')
        self.assertEqual(r.data, 'hello, world!')

    def test_connection_count(self):
        http_pool = HTTPConnectionPool(self.host, self.port, maxsize=1)

        http_pool.request('GET', '/')
        http_pool.request('GET', '/')
        http_pool.request('GET', '/')

        self.assertEqual(http_pool.num_connections, 1)
        self.assertEqual(http_pool.num_requests, 3)

    def test_partial_response(self):
        http_pool = HTTPConnectionPool(self.host, self.port, maxsize=1)

        req_data = {'lol': 'cat'}
        resp_data = urllib.urlencode(req_data)

        r = http_pool.request('GET', '/echo', fields=req_data, preload_content=False)

        self.assertEqual(r.read(5), resp_data[:5])
        self.assertEqual(r.read(), resp_data[5:])

    def test_lazy_load_twice(self):
        # This test is sad and confusing. Need to figure out what's
        # going on with partial reads and socket reuse.

        http_pool = HTTPConnectionPool(self.host, self.port, block=True, maxsize=1, timeout=2)

        payload_size = 1024 * 2
        first_chunk = 512

        boundary = 'foo'

        req_data = {'count': 'a' * payload_size}
        resp_data = encode_multipart_formdata(req_data, boundary=boundary)[0]

        req2_data = {'count': 'b' * payload_size}
        resp2_data = encode_multipart_formdata(req2_data, boundary=boundary)[0]

        r1 = http_pool.request('POST', '/echo', fields=req_data, multipart_boundary=boundary, preload_content=False)

        self.assertEqual(r1.read(first_chunk), resp_data[:first_chunk])

        try:
            r2 = http_pool.request('POST', '/echo', fields=req2_data, multipart_boundary=boundary,
                                    preload_content=False, pool_timeout=0.001)

            # This branch should generally bail here, but maybe someday it will
            # work? Perhaps by some sort of magic. Consider it a TODO.

            self.assertEqual(r2.read(first_chunk), resp2_data[:first_chunk])

            self.assertEqual(r1.read(), resp_data[first_chunk:])
            self.assertEqual(r2.read(), resp2_data[first_chunk:])
            self.assertEqual(http_pool.num_requests, 2)

        except EmptyPoolError:
            self.assertEqual(r1.read(), resp_data[first_chunk:])
            self.assertEqual(http_pool.num_requests, 1)

        self.assertEqual(http_pool.num_connections, 1)

    def test_for_double_release(self):
        MAXSIZE=5

        # Check default state
        http_pool = HTTPConnectionPool(self.host, self.port, maxsize=MAXSIZE)
        self.assertEqual(http_pool.num_connections, 0)

        # Make an empty slot for testing
        http_pool.pool.get()

        self.assertEqual(http_pool.pool.qsize(), MAXSIZE-1)


        # Check state after simple request
        http_pool.urlopen('GET', '/')
        self.assertEqual(http_pool.pool.qsize(), MAXSIZE-1)

        # Check state without release
        http_pool.urlopen('GET', '/', preload_content=False)
        self.assertEqual(http_pool.pool.qsize(), MAXSIZE-2)

        http_pool.urlopen('GET', '/')
        self.assertEqual(http_pool.pool.qsize(), MAXSIZE-2)

        # Check state after read
        http_pool.urlopen('GET', '/').data
        self.assertEqual(http_pool.pool.qsize(), MAXSIZE-2)

        http_pool.urlopen('GET', '/')
        self.assertEqual(http_pool.pool.qsize(), MAXSIZE-2)


if __name__ == '__main__':
    unittest.main()
