import logging
import sys
import unittest

import mock

try:
    from urllib.parse import urlencode
except:
    from urllib import urlencode

from urllib3 import (
    encode_multipart_formdata,
    HTTPConnectionPool,
)
from urllib3.exceptions import (
    ConnectTimeoutError,
    EmptyPoolError,
    DecodeError,
    MaxRetryError,
    ReadTimeoutError,
)
from urllib3.packages.six import u
from urllib3 import util

from dummyserver.testcase import HTTPDummyServerTestCase

from nose.tools import timed

log = logging.getLogger('urllib3.connectionpool')
log.setLevel(logging.NOTSET)
log.addHandler(logging.StreamHandler(sys.stdout))

# We need a host that will not immediately close the connection with a TCP
# Reset. SO suggests this hostname
TARPIT_HOST = '10.255.255.1'

class TestConnectionPool(HTTPDummyServerTestCase):

    def setUp(self):
        self.pool = HTTPConnectionPool(self.host, self.port)

    def test_get(self):
        r = self.pool.request('GET', '/specific_method',
                               fields={'method': 'GET'})
        self.assertEqual(r.status, 200, r.data)

    def test_post_url(self):
        r = self.pool.request('POST', '/specific_method',
                               fields={'method': 'POST'})
        self.assertEqual(r.status, 200, r.data)

    def test_urlopen_put(self):
        r = self.pool.urlopen('PUT', '/specific_method?method=PUT')
        self.assertEqual(r.status, 200, r.data)

    def test_wrong_specific_method(self):
        # To make sure the dummy server is actually returning failed responses
        r = self.pool.request('GET', '/specific_method',
                               fields={'method': 'POST'})
        self.assertEqual(r.status, 400, r.data)

        r = self.pool.request('POST', '/specific_method',
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

        r = self.pool.request('POST', '/upload', fields=fields)
        self.assertEqual(r.status, 200, r.data)

    def test_one_name_multiple_values(self):
        fields = [
            ('foo', 'a'),
            ('foo', 'b'),
        ]

        # urlencode
        r = self.pool.request('GET', '/echo', fields=fields)
        self.assertEqual(r.data, b'foo=a&foo=b')

        # multipart
        r = self.pool.request('POST', '/echo', fields=fields)
        self.assertEqual(r.data.count(b'name="foo"'), 2)


    def test_unicode_upload(self):
        fieldname = u('myfile')
        filename = u('\xe2\x99\xa5.txt')
        data = u('\xe2\x99\xa5').encode('utf8')
        size = len(data)

        fields = {
            u('upload_param'): fieldname,
            u('upload_filename'): filename,
            u('upload_size'): size,
            fieldname: (filename, data),
        }

        r = self.pool.request('POST', '/upload', fields=fields)
        self.assertEqual(r.status, 200, r.data)

    def test_timeout_float(self):
        url = '/sleep?seconds=0.005'
        # Pool-global timeout
        pool = HTTPConnectionPool(self.host, self.port, timeout=0.001)
        self.assertRaises(ReadTimeoutError, pool.request, 'GET', url)

    def test_timeout(self):
        url = '/sleep?seconds=0.005'
        timeout = util.Timeout(read=0.001)

        # Pool-global timeout
        pool = HTTPConnectionPool(self.host, self.port, timeout=timeout)

        conn = pool._get_conn()
        # XXX why is this not a request timeout?
        self.assertRaises(ReadTimeoutError, pool._make_request,
                          conn, 'GET', url)
        pool._put_conn(conn)

        self.assertRaises(ReadTimeoutError, pool.request, 'GET', url)

        # Request-specific timeouts should raise errors
        pool = HTTPConnectionPool(self.host, self.port, timeout=0.5)

        conn = pool._get_conn()
        # XXX why is this not a request timeout?
        self.assertRaises(ReadTimeoutError, pool._make_request,
                          conn, 'GET', url, timeout=timeout)
        pool._put_conn(conn)

        self.assertRaises(ReadTimeoutError, pool.request,
                          'GET', url, timeout=timeout)

        # Timeout int/float passed directly to request and _make_request should
        # raise a request timeout
        self.assertRaises(ReadTimeoutError, pool.request,
                          'GET', url, timeout=0.001)
        conn = pool._new_conn()
        self.assertRaises(ReadTimeoutError, pool._make_request, conn,
                          'GET', url, timeout=0.001)
        pool._put_conn(conn)

        # Timeout int/float passed directly to _make_request should not raise a
        # request timeout if it's a high value
        pool.request('GET', url, timeout=5)

    @timed(0.1)
    def test_connect_timeout(self):
        url = '/sleep'
        timeout = util.Timeout(connect=0.001)

        # Pool-global timeout
        pool = HTTPConnectionPool(TARPIT_HOST, self.port, timeout=timeout)
        conn = pool._get_conn()
        self.assertRaises(ConnectTimeoutError, pool._make_request, conn, 'GET', url)
        pool._put_conn(conn)
        self.assertRaises(ConnectTimeoutError, pool.request, 'GET', url)

        # Request-specific connection timeouts
        big_timeout = util.Timeout(read=0.5, connect=0.5)
        pool = HTTPConnectionPool(TARPIT_HOST, self.port, timeout=big_timeout)
        conn = pool._get_conn()
        self.assertRaises(ConnectTimeoutError, pool._make_request, conn, 'GET',
                          url, timeout=timeout)

        pool._put_conn(conn)
        self.assertRaises(ConnectTimeoutError, pool.request, 'GET', url,
                          timeout=timeout)


    @timed(0.1)
    def test_total_timeout(self):
        url = '/sleep?seconds=0.005'
        timeout = util.Timeout(connect=3, read=5, total=0.001)
        pool = HTTPConnectionPool(TARPIT_HOST, self.port, timeout=timeout)
        conn = pool._get_conn()
        self.assertRaises(ConnectTimeoutError, pool._make_request, conn, 'GET', url)

        pool = HTTPConnectionPool(self.host, self.port, timeout=timeout)
        conn = pool._get_conn()
        self.assertRaises(ReadTimeoutError, pool._make_request, conn, 'GET', url)

        timeout = util.Timeout(total=None, connect=0.001)
        pool = HTTPConnectionPool(TARPIT_HOST, self.port, timeout=timeout)
        conn = pool._get_conn()
        self.assertRaises(ConnectTimeoutError, pool._make_request, conn, 'GET',
                          url)

    def test_timeout_success(self):
        timeout = util.Timeout(connect=3, read=5, total=None)
        pool = HTTPConnectionPool(self.host, self.port, timeout=timeout)
        pool.request('GET', '/')
        # This should not raise a "Timeout already started" error
        pool.request('GET', '/')

        pool = HTTPConnectionPool(self.host, self.port, timeout=timeout)
        # This should also not raise a "Timeout already started" error
        pool.request('GET', '/')

        timeout = util.Timeout(total=None)
        pool = HTTPConnectionPool(self.host, self.port, timeout=timeout)
        pool.request('GET', '/')


    def test_tunnel(self):
        # note the actual httplib.py has no tests for this functionality
        timeout = util.Timeout(total=None)
        pool = HTTPConnectionPool(self.host, self.port, timeout=timeout)
        conn = pool._get_conn()
        try:
            conn.set_tunnel(self.host, self.port)
        except AttributeError: # python 2.6
            conn._set_tunnel(self.host, self.port)

        conn._tunnel = mock.Mock(return_value=None)
        pool._make_request(conn, 'GET', '/')
        conn._tunnel.assert_called_once_with()

        # test that it's not called when tunnel is not set
        timeout = util.Timeout(total=None)
        pool = HTTPConnectionPool(self.host, self.port, timeout=timeout)
        conn = pool._get_conn()

        conn._tunnel = mock.Mock(return_value=None)
        pool._make_request(conn, 'GET', '/')
        self.assertEqual(conn._tunnel.called, False)


    def test_redirect(self):
        r = self.pool.request('GET', '/redirect', fields={'target': '/'}, redirect=False)
        self.assertEqual(r.status, 303)

        r = self.pool.request('GET', '/redirect', fields={'target': '/'})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Dummy server!')

    def test_maxretry(self):
        try:
            self.pool.request('GET', '/redirect',
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
        r = self.pool.request('POST', '/echo', fields=data, encode_multipart=False)
        self.assertEqual(r.data.decode('utf-8'), urlencode(data))

    def test_post_with_multipart(self):
        data = {'banana': 'hammock', 'lol': 'cat'}
        r = self.pool.request('POST', '/echo',
                                    fields=data,
                                    encode_multipart=True)
        body = r.data.split(b'\r\n')

        encoded_data = encode_multipart_formdata(data)[0]
        expected_body = encoded_data.split(b'\r\n')

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
            if line.startswith(b'--'):
                continue

            self.assertEqual(body[i], expected_body[i])

    def test_check_gzip(self):
        r = self.pool.request('GET', '/encodingrequest',
                                   headers={'accept-encoding': 'gzip'})
        self.assertEqual(r.headers.get('content-encoding'), 'gzip')
        self.assertEqual(r.data, b'hello, world!')

    def test_check_deflate(self):
        r = self.pool.request('GET', '/encodingrequest',
                                   headers={'accept-encoding': 'deflate'})
        self.assertEqual(r.headers.get('content-encoding'), 'deflate')
        self.assertEqual(r.data, b'hello, world!')

    def test_bad_decode(self):
        self.assertRaises(DecodeError, self.pool.request,
                          'GET', '/encodingrequest',
                          headers={'accept-encoding': 'garbage-deflate'})

        self.assertRaises(DecodeError, self.pool.request,
                          'GET', '/encodingrequest',
                          headers={'accept-encoding': 'garbage-gzip'})

    def test_connection_count(self):
        pool = HTTPConnectionPool(self.host, self.port, maxsize=1)

        pool.request('GET', '/')
        pool.request('GET', '/')
        pool.request('GET', '/')

        self.assertEqual(pool.num_connections, 1)
        self.assertEqual(pool.num_requests, 3)

    def test_connection_count_bigpool(self):
        http_pool = HTTPConnectionPool(self.host, self.port, maxsize=16)

        http_pool.request('GET', '/')
        http_pool.request('GET', '/')
        http_pool.request('GET', '/')

        self.assertEqual(http_pool.num_connections, 1)
        self.assertEqual(http_pool.num_requests, 3)

    def test_partial_response(self):
        pool = HTTPConnectionPool(self.host, self.port, maxsize=1)

        req_data = {'lol': 'cat'}
        resp_data = urlencode(req_data).encode('utf-8')

        r = pool.request('GET', '/echo', fields=req_data, preload_content=False)

        self.assertEqual(r.read(5), resp_data[:5])
        self.assertEqual(r.read(), resp_data[5:])

    def test_lazy_load_twice(self):
        # This test is sad and confusing. Need to figure out what's
        # going on with partial reads and socket reuse.

        pool = HTTPConnectionPool(self.host, self.port, block=True, maxsize=1, timeout=2)

        payload_size = 1024 * 2
        first_chunk = 512

        boundary = 'foo'

        req_data = {'count': 'a' * payload_size}
        resp_data = encode_multipart_formdata(req_data, boundary=boundary)[0]

        req2_data = {'count': 'b' * payload_size}
        resp2_data = encode_multipart_formdata(req2_data, boundary=boundary)[0]

        r1 = pool.request('POST', '/echo', fields=req_data, multipart_boundary=boundary, preload_content=False)

        self.assertEqual(r1.read(first_chunk), resp_data[:first_chunk])

        try:
            r2 = pool.request('POST', '/echo', fields=req2_data, multipart_boundary=boundary,
                                    preload_content=False, pool_timeout=0.001)

            # This branch should generally bail here, but maybe someday it will
            # work? Perhaps by some sort of magic. Consider it a TODO.

            self.assertEqual(r2.read(first_chunk), resp2_data[:first_chunk])

            self.assertEqual(r1.read(), resp_data[first_chunk:])
            self.assertEqual(r2.read(), resp2_data[first_chunk:])
            self.assertEqual(pool.num_requests, 2)

        except EmptyPoolError:
            self.assertEqual(r1.read(), resp_data[first_chunk:])
            self.assertEqual(pool.num_requests, 1)

        self.assertEqual(pool.num_connections, 1)

    def test_for_double_release(self):
        MAXSIZE=5

        # Check default state
        pool = HTTPConnectionPool(self.host, self.port, maxsize=MAXSIZE)
        self.assertEqual(pool.num_connections, 0)
        self.assertEqual(pool.pool.qsize(), MAXSIZE)

        # Make an empty slot for testing
        pool.pool.get()
        self.assertEqual(pool.pool.qsize(), MAXSIZE-1)

        # Check state after simple request
        pool.urlopen('GET', '/')
        self.assertEqual(pool.pool.qsize(), MAXSIZE-1)

        # Check state without release
        pool.urlopen('GET', '/', preload_content=False)
        self.assertEqual(pool.pool.qsize(), MAXSIZE-2)

        pool.urlopen('GET', '/')
        self.assertEqual(pool.pool.qsize(), MAXSIZE-2)

        # Check state after read
        pool.urlopen('GET', '/').data
        self.assertEqual(pool.pool.qsize(), MAXSIZE-2)

        pool.urlopen('GET', '/')
        self.assertEqual(pool.pool.qsize(), MAXSIZE-2)

    def test_release_conn_parameter(self):
        MAXSIZE=5
        pool = HTTPConnectionPool(self.host, self.port, maxsize=MAXSIZE)
        self.assertEqual(pool.pool.qsize(), MAXSIZE)

        # Make request without releasing connection
        pool.request('GET', '/', release_conn=False, preload_content=False)
        self.assertEqual(pool.pool.qsize(), MAXSIZE-1)

    ## FIXME: This borks on OSX because sockets on invalid hosts refuse to timeout. :(
    #def test_dns_error(self):
    #    pool = HTTPConnectionPool('thishostdoesnotexist.invalid', self.port, timeout=0.001)
    #
    #    with self.assertRaises(MaxRetryError):
    #        pool.request('GET', '/test', retries=2)


if __name__ == '__main__':
    unittest.main()
