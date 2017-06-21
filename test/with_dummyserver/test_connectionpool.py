import io
import logging
import socket
import sys
import unittest
import time
import warnings

import mock

from .. import (
    TARPIT_HOST, VALID_SOURCE_ADDRESSES, INVALID_SOURCE_ADDRESSES,
)
from ..port_helpers import find_unused_port
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
    NewConnectionError,
    UnrewindableBodyError,
)
from urllib3.packages.six import b, u
from urllib3.packages.six.moves.urllib.parse import urlencode
from urllib3.util.retry import Retry, RequestHistory
from urllib3.util.timeout import Timeout

from dummyserver.testcase import HTTPDummyServerTestCase, SocketDummyServerTestCase
from dummyserver.server import NoIPv6Warning, HAS_IPV6_AND_DNS

from threading import Event

log = logging.getLogger('urllib3.connectionpool')
log.setLevel(logging.NOTSET)
log.addHandler(logging.StreamHandler(sys.stdout))


SHORT_TIMEOUT = 0.001
LONG_TIMEOUT = 0.03


def wait_for_socket(ready_event):
    ready_event.wait()
    ready_event.clear()


class TestConnectionPoolTimeouts(SocketDummyServerTestCase):

    def test_timeout_float(self):
        block_event = Event()
        ready_event = self.start_basic_handler(block_send=block_event, num=2)

        # Pool-global timeout
        pool = HTTPConnectionPool(self.host, self.port, timeout=SHORT_TIMEOUT, retries=False)
        self.addCleanup(pool.close)
        wait_for_socket(ready_event)
        self.assertRaises(ReadTimeoutError, pool.request, 'GET', '/')
        block_event.set()  # Release block

        # Shouldn't raise this time
        wait_for_socket(ready_event)
        block_event.set()  # Pre-release block
        pool.request('GET', '/')

    def test_conn_closed(self):
        block_event = Event()
        self.start_basic_handler(block_send=block_event, num=1)

        pool = HTTPConnectionPool(self.host, self.port, timeout=SHORT_TIMEOUT, retries=False)
        self.addCleanup(pool.close)
        conn = pool._get_conn()
        pool._put_conn(conn)
        try:
            pool.urlopen('GET', '/')
            self.fail("The request should fail with a timeout error.")
        except ReadTimeoutError:
            if conn.sock:
                self.assertRaises(socket.error, conn.sock.recv, 1024)
        finally:
            pool._put_conn(conn)

        block_event.set()

    def test_timeout(self):
        # Requests should time out when expected
        block_event = Event()
        ready_event = self.start_basic_handler(block_send=block_event, num=6)

        # Pool-global timeout
        timeout = Timeout(read=SHORT_TIMEOUT)
        pool = HTTPConnectionPool(self.host, self.port, timeout=timeout, retries=False)
        self.addCleanup(pool.close)

        wait_for_socket(ready_event)
        conn = pool._get_conn()
        self.assertRaises(ReadTimeoutError, pool._make_request, conn, 'GET', '/')
        pool._put_conn(conn)
        block_event.set()  # Release request

        wait_for_socket(ready_event)
        block_event.clear()
        self.assertRaises(ReadTimeoutError, pool.request, 'GET', '/')
        block_event.set()  # Release request

        # Request-specific timeouts should raise errors
        pool = HTTPConnectionPool(self.host, self.port, timeout=LONG_TIMEOUT, retries=False)
        self.addCleanup(pool.close)

        conn = pool._get_conn()
        wait_for_socket(ready_event)
        now = time.time()
        self.assertRaises(ReadTimeoutError, pool._make_request, conn, 'GET', '/', timeout=timeout)
        delta = time.time() - now
        block_event.set()  # Release request

        message = "timeout was pool-level LONG_TIMEOUT rather than request-level SHORT_TIMEOUT"
        self.assertTrue(delta < LONG_TIMEOUT, message)
        pool._put_conn(conn)

        wait_for_socket(ready_event)
        now = time.time()
        self.assertRaises(ReadTimeoutError, pool.request, 'GET', '/', timeout=timeout)
        delta = time.time() - now

        message = "timeout was pool-level LONG_TIMEOUT rather than request-level SHORT_TIMEOUT"
        self.assertTrue(delta < LONG_TIMEOUT, message)
        block_event.set()  # Release request

        # Timeout int/float passed directly to request and _make_request should
        # raise a request timeout
        wait_for_socket(ready_event)
        self.assertRaises(ReadTimeoutError, pool.request, 'GET', '/', timeout=SHORT_TIMEOUT)
        block_event.set()  # Release request

        wait_for_socket(ready_event)
        conn = pool._new_conn()
        # FIXME: This assert flakes sometimes. Not sure why.
        self.assertRaises(ReadTimeoutError,
                          pool._make_request,
                          conn, 'GET', '/',
                          timeout=SHORT_TIMEOUT)
        block_event.set()  # Release request

    def test_connect_timeout(self):
        url = '/'
        host, port = TARPIT_HOST, 80
        timeout = Timeout(connect=SHORT_TIMEOUT)

        # Pool-global timeout
        pool = HTTPConnectionPool(host, port, timeout=timeout)
        self.addCleanup(pool.close)
        conn = pool._get_conn()
        self.assertRaises(ConnectTimeoutError, pool._make_request, conn, 'GET', url)

        # Retries
        retries = Retry(connect=0)
        self.assertRaises(MaxRetryError, pool.request, 'GET', url, retries=retries)

        # Request-specific connection timeouts
        big_timeout = Timeout(read=LONG_TIMEOUT, connect=LONG_TIMEOUT)
        pool = HTTPConnectionPool(host, port, timeout=big_timeout, retries=False)
        self.addCleanup(pool.close)
        conn = pool._get_conn()
        self.assertRaises(ConnectTimeoutError,
                          pool._make_request,
                          conn, 'GET', url,
                          timeout=timeout)

        pool._put_conn(conn)
        self.assertRaises(ConnectTimeoutError, pool.request, 'GET', url, timeout=timeout)

    def test_total_applies_connect(self):
        host, port = TARPIT_HOST, 80

        timeout = Timeout(total=None, connect=SHORT_TIMEOUT)
        pool = HTTPConnectionPool(host, port, timeout=timeout)
        self.addCleanup(pool.close)
        conn = pool._get_conn()
        self.addCleanup(conn.close)
        self.assertRaises(ConnectTimeoutError, pool._make_request, conn, 'GET', '/')

        timeout = Timeout(connect=3, read=5, total=SHORT_TIMEOUT)
        pool = HTTPConnectionPool(host, port, timeout=timeout)
        self.addCleanup(pool.close)
        conn = pool._get_conn()
        self.addCleanup(conn.close)
        self.assertRaises(ConnectTimeoutError, pool._make_request, conn, 'GET', '/')

    def test_total_timeout(self):
        block_event = Event()
        ready_event = self.start_basic_handler(block_send=block_event, num=2)

        wait_for_socket(ready_event)
        # This will get the socket to raise an EAGAIN on the read
        timeout = Timeout(connect=3, read=SHORT_TIMEOUT)
        pool = HTTPConnectionPool(self.host, self.port, timeout=timeout, retries=False)
        self.addCleanup(pool.close)
        self.assertRaises(ReadTimeoutError, pool.request, 'GET', '/')

        block_event.set()
        wait_for_socket(ready_event)
        block_event.clear()

        # The connect should succeed and this should hit the read timeout
        timeout = Timeout(connect=3, read=5, total=SHORT_TIMEOUT)
        pool = HTTPConnectionPool(self.host, self.port, timeout=timeout, retries=False)
        self.addCleanup(pool.close)
        self.assertRaises(ReadTimeoutError, pool.request, 'GET', '/')

    def test_create_connection_timeout(self):
        timeout = Timeout(connect=SHORT_TIMEOUT, total=LONG_TIMEOUT)
        pool = HTTPConnectionPool(TARPIT_HOST, self.port, timeout=timeout, retries=False)
        self.addCleanup(pool.close)
        conn = pool._new_conn()
        self.assertRaises(ConnectTimeoutError, conn.connect)


class TestConnectionPool(HTTPDummyServerTestCase):

    def setUp(self):
        self.pool = HTTPConnectionPool(self.host, self.port)
        self.addCleanup(self.pool.close)

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

    def test_request_method_body(self):
        body = b'hi'
        r = self.pool.request('POST', '/echo', body=body)
        self.assertEqual(r.data, body)

        fields = [('hi', 'hello')]
        self.assertRaises(TypeError, self.pool.request, 'POST', '/echo', body=body, fields=fields)

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

    def test_nagle(self):
        """ Test that connections have TCP_NODELAY turned on """
        # This test needs to be here in order to be run. socket.create_connection actually tries
        # to connect to the host provided so we need a dummyserver to be running.
        pool = HTTPConnectionPool(self.host, self.port)
        self.addCleanup(pool.close)
        conn = pool._get_conn()
        self.addCleanup(conn.close)
        pool._make_request(conn, 'GET', '/')
        tcp_nodelay_setting = conn.sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
        self.assertTrue(tcp_nodelay_setting)

    def test_socket_options(self):
        """Test that connections accept socket options."""
        # This test needs to be here in order to be run. socket.create_connection actually tries to
        # connect to the host provided so we need a dummyserver to be running.
        pool = HTTPConnectionPool(self.host, self.port, socket_options=[
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        ])
        s = pool._new_conn()._new_conn()  # Get the socket
        using_keepalive = s.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) > 0
        self.assertTrue(using_keepalive)
        s.close()

    def test_disable_default_socket_options(self):
        """Test that passing None disables all socket options."""
        # This test needs to be here in order to be run. socket.create_connection actually tries
        # to connect to the host provided so we need a dummyserver to be running.
        pool = HTTPConnectionPool(self.host, self.port, socket_options=None)
        s = pool._new_conn()._new_conn()
        using_nagle = s.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) == 0
        self.assertTrue(using_nagle)
        s.close()

    def test_defaults_are_applied(self):
        """Test that modifying the default socket options works."""
        # This test needs to be here in order to be run. socket.create_connection actually tries
        # to connect to the host provided so we need a dummyserver to be running.
        pool = HTTPConnectionPool(self.host, self.port)
        self.addCleanup(pool.close)
        # Get the HTTPConnection instance
        conn = pool._new_conn()
        self.addCleanup(conn.close)
        # Update the default socket options
        conn.default_socket_options += [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
        s = conn._new_conn()
        self.addCleanup(s.close)
        nagle_disabled = s.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) > 0
        using_keepalive = s.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) > 0
        self.assertTrue(nagle_disabled)
        self.assertTrue(using_keepalive)

    def test_connection_error_retries(self):
        """ ECONNREFUSED error should raise a connection error, with retries """
        port = find_unused_port()
        pool = HTTPConnectionPool(self.host, port)
        try:
            pool.request('GET', '/', retries=Retry(connect=3))
            self.fail("Should have failed with a connection error.")
        except MaxRetryError as e:
            self.assertEqual(type(e.reason), NewConnectionError)

    def test_timeout_success(self):
        timeout = Timeout(connect=3, read=5, total=None)
        pool = HTTPConnectionPool(self.host, self.port, timeout=timeout)
        self.addCleanup(pool.close)
        pool.request('GET', '/')
        # This should not raise a "Timeout already started" error
        pool.request('GET', '/')

        pool = HTTPConnectionPool(self.host, self.port, timeout=timeout)
        self.addCleanup(pool.close)
        # This should also not raise a "Timeout already started" error
        pool.request('GET', '/')

        timeout = Timeout(total=None)
        pool = HTTPConnectionPool(self.host, self.port, timeout=timeout)
        self.addCleanup(pool.close)
        pool.request('GET', '/')

    def test_tunnel(self):
        # note the actual httplib.py has no tests for this functionality
        timeout = Timeout(total=None)
        pool = HTTPConnectionPool(self.host, self.port, timeout=timeout)
        self.addCleanup(pool.close)
        conn = pool._get_conn()
        self.addCleanup(conn.close)
        try:
            conn.set_tunnel(self.host, self.port)
        except AttributeError:  # python 2.6
            conn._set_tunnel(self.host, self.port)

        conn._tunnel = mock.Mock(return_value=None)
        pool._make_request(conn, 'GET', '/')
        conn._tunnel.assert_called_once_with()

        # test that it's not called when tunnel is not set
        timeout = Timeout(total=None)
        pool = HTTPConnectionPool(self.host, self.port, timeout=timeout)
        self.addCleanup(pool.close)
        conn = pool._get_conn()
        self.addCleanup(conn.close)

        conn._tunnel = mock.Mock(return_value=None)
        pool._make_request(conn, 'GET', '/')
        self.assertEqual(conn._tunnel.called, False)

    def test_redirect(self):
        r = self.pool.request('GET', '/redirect', fields={'target': '/'}, redirect=False)
        self.assertEqual(r.status, 303)

        r = self.pool.request('GET', '/redirect', fields={'target': '/'})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Dummy server!')

    def test_bad_connect(self):
        pool = HTTPConnectionPool('badhost.invalid', self.port)
        try:
            pool.request('GET', '/', retries=5)
            self.fail("should raise timeout exception here")
        except MaxRetryError as e:
            self.assertEqual(type(e.reason), NewConnectionError)

    def test_keepalive(self):
        pool = HTTPConnectionPool(self.host, self.port, block=True, maxsize=1)
        self.addCleanup(pool.close)

        r = pool.request('GET', '/keepalive?close=0')
        r = pool.request('GET', '/keepalive?close=0')

        self.assertEqual(r.status, 200)
        self.assertEqual(pool.num_connections, 1)
        self.assertEqual(pool.num_requests, 2)

    def test_keepalive_close(self):
        pool = HTTPConnectionPool(self.host, self.port,
                                  block=True, maxsize=1, timeout=2)
        self.addCleanup(pool.close)

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
        self.addCleanup(pool.close)

        pool.request('GET', '/')
        pool.request('GET', '/')
        pool.request('GET', '/')

        self.assertEqual(pool.num_connections, 1)
        self.assertEqual(pool.num_requests, 3)

    def test_connection_count_bigpool(self):
        http_pool = HTTPConnectionPool(self.host, self.port, maxsize=16)
        self.addCleanup(http_pool.close)

        http_pool.request('GET', '/')
        http_pool.request('GET', '/')
        http_pool.request('GET', '/')

        self.assertEqual(http_pool.num_connections, 1)
        self.assertEqual(http_pool.num_requests, 3)

    def test_partial_response(self):
        pool = HTTPConnectionPool(self.host, self.port, maxsize=1)
        self.addCleanup(pool.close)

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

        r1 = pool.request('POST', '/echo',
                          fields=req_data,
                          multipart_boundary=boundary,
                          preload_content=False)

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
        MAXSIZE = 5

        # Check default state
        pool = HTTPConnectionPool(self.host, self.port, maxsize=MAXSIZE)
        self.addCleanup(pool.close)
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
        MAXSIZE = 5
        pool = HTTPConnectionPool(self.host, self.port, maxsize=MAXSIZE)
        self.assertEqual(pool.pool.qsize(), MAXSIZE)

        # Make request without releasing connection
        pool.request('GET', '/', release_conn=False, preload_content=False)
        self.assertEqual(pool.pool.qsize(), MAXSIZE-1)

    def test_dns_error(self):
        pool = HTTPConnectionPool('thishostdoesnotexist.invalid', self.port, timeout=0.001)
        self.assertRaises(MaxRetryError, pool.request, 'GET', '/test', retries=2)

    def test_source_address(self):
        for addr, is_ipv6 in VALID_SOURCE_ADDRESSES:
            if is_ipv6 and not HAS_IPV6_AND_DNS:
                warnings.warn("No IPv6 support: skipping.",
                              NoIPv6Warning)
                continue
            pool = HTTPConnectionPool(self.host, self.port,
                                      source_address=addr, retries=False)
            self.addCleanup(pool.close)
            r = pool.request('GET', '/source_address')
            self.assertEqual(r.data, b(addr[0]))

    def test_source_address_error(self):
        for addr in INVALID_SOURCE_ADDRESSES:
            pool = HTTPConnectionPool(self.host, self.port, source_address=addr, retries=False)
            # FIXME: This assert flakes sometimes. Not sure why.
            self.assertRaises(NewConnectionError,
                              pool.request,
                              'GET', '/source_address?{0}'.format(addr))

    def test_stream_keepalive(self):
        x = 2

        for _ in range(x):
            response = self.pool.request(
                    'GET',
                    '/chunked',
                    headers={
                        'Connection': 'keep-alive',
                        },
                    preload_content=False,
                    retries=False,
                    )
            for chunk in response.stream():
                self.assertEqual(chunk, b'123')

        self.assertEqual(self.pool.num_connections, 1)
        self.assertEqual(self.pool.num_requests, x)

    def test_chunked_gzip(self):
        response = self.pool.request(
                'GET',
                '/chunked_gzip',
                preload_content=False,
                decode_content=True,
                )

        self.assertEqual(b'123' * 4, response.read())

    def test_cleanup_on_connection_error(self):
        '''
        Test that connections are recycled to the pool on
        connection errors where no http response is received.
        '''
        poolsize = 3
        with HTTPConnectionPool(self.host, self.port, maxsize=poolsize, block=True) as http:
            self.assertEqual(http.pool.qsize(), poolsize)

            # force a connection error by supplying a non-existent
            # url. We won't get a response for this  and so the
            # conn won't be implicitly returned to the pool.
            self.assertRaises(MaxRetryError,
                              http.request,
                              'GET', '/redirect',
                              fields={'target': '/'}, release_conn=False, retries=0)

            r = http.request('GET', '/redirect',
                             fields={'target': '/'},
                             release_conn=False,
                             retries=1)
            r.release_conn()

            # the pool should still contain poolsize elements
            self.assertEqual(http.pool.qsize(), http.pool.maxsize)

    def test_mixed_case_hostname(self):
        pool = HTTPConnectionPool("LoCaLhOsT", self.port)
        self.addCleanup(pool.close)
        response = pool.request('GET', "http://LoCaLhOsT:%d/" % self.port)
        self.assertEqual(response.status, 200)


class TestRetry(HTTPDummyServerTestCase):
    def setUp(self):
        self.pool = HTTPConnectionPool(self.host, self.port)
        self.addCleanup(self.pool.close)

    def test_max_retry(self):
        try:
            r = self.pool.request('GET', '/redirect',
                                  fields={'target': '/'},
                                  retries=0)
            self.fail("Failed to raise MaxRetryError exception, returned %r" % r.status)
        except MaxRetryError:
            pass

    def test_disabled_retry(self):
        """ Disabled retries should disable redirect handling. """
        r = self.pool.request('GET', '/redirect',
                              fields={'target': '/'},
                              retries=False)
        self.assertEqual(r.status, 303)

        r = self.pool.request('GET', '/redirect',
                              fields={'target': '/'},
                              retries=Retry(redirect=False))
        self.assertEqual(r.status, 303)

        pool = HTTPConnectionPool('thishostdoesnotexist.invalid', self.port, timeout=0.001)
        self.assertRaises(NewConnectionError, pool.request, 'GET', '/test', retries=False)

    def test_read_retries(self):
        """ Should retry for status codes in the whitelist """
        retry = Retry(read=1, status_forcelist=[418])
        resp = self.pool.request('GET', '/successful_retry',
                                 headers={'test-name': 'test_read_retries'},
                                 retries=retry)
        self.assertEqual(resp.status, 200)

    def test_read_total_retries(self):
        """ HTTP response w/ status code in the whitelist should be retried """
        headers = {'test-name': 'test_read_total_retries'}
        retry = Retry(total=1, status_forcelist=[418])
        resp = self.pool.request('GET', '/successful_retry',
                                 headers=headers, retries=retry)
        self.assertEqual(resp.status, 200)

    def test_retries_wrong_whitelist(self):
        """HTTP response w/ status code not in whitelist shouldn't be retried"""
        retry = Retry(total=1, status_forcelist=[202])
        resp = self.pool.request('GET', '/successful_retry',
                                 headers={'test-name': 'test_wrong_whitelist'},
                                 retries=retry)
        self.assertEqual(resp.status, 418)

    def test_default_method_whitelist_retried(self):
        """ urllib3 should retry methods in the default method whitelist """
        retry = Retry(total=1, status_forcelist=[418])
        resp = self.pool.request('OPTIONS', '/successful_retry',
                                 headers={'test-name': 'test_default_whitelist'},
                                 retries=retry)
        self.assertEqual(resp.status, 200)

    def test_retries_wrong_method_list(self):
        """Method not in our whitelist should not be retried, even if code matches"""
        headers = {'test-name': 'test_wrong_method_whitelist'}
        retry = Retry(total=1, status_forcelist=[418],
                      method_whitelist=['POST'])
        resp = self.pool.request('GET', '/successful_retry',
                                 headers=headers, retries=retry)
        self.assertEqual(resp.status, 418)

    def test_read_retries_unsuccessful(self):
        headers = {'test-name': 'test_read_retries_unsuccessful'}
        resp = self.pool.request('GET', '/successful_retry',
                                 headers=headers, retries=1)
        self.assertEqual(resp.status, 418)

    def test_retry_reuse_safe(self):
        """ It should be possible to reuse a Retry object across requests """
        headers = {'test-name': 'test_retry_safe'}
        retry = Retry(total=1, status_forcelist=[418])
        resp = self.pool.request('GET', '/successful_retry',
                                 headers=headers, retries=retry)
        self.assertEqual(resp.status, 200)
        resp = self.pool.request('GET', '/successful_retry',
                                 headers=headers, retries=retry)
        self.assertEqual(resp.status, 200)

    def test_retry_return_in_response(self):
        headers = {'test-name': 'test_retry_return_in_response'}
        retry = Retry(total=2, status_forcelist=[418])
        resp = self.pool.request('GET', '/successful_retry',
                                 headers=headers, retries=retry)
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.retries.total, 1)
        self.assertEqual(resp.retries.history,
                         (RequestHistory('GET', '/successful_retry', None, 418, None),))

    def test_retry_redirect_history(self):
        resp = self.pool.request('GET', '/redirect', fields={'target': '/'})
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.retries.history,
                         (RequestHistory('GET', '/redirect?target=%2F', None, 303, '/'),))

    def test_multi_redirect_history(self):
        r = self.pool.request('GET', '/multi_redirect',
                              fields={'redirect_codes': '303,302,200'},
                              redirect=False)
        self.assertEqual(r.status, 303)
        self.assertEqual(r.retries.history, tuple())

        r = self.pool.request('GET', '/multi_redirect', retries=10,
                              fields={'redirect_codes': '303,302,301,307,302,200'})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Done redirecting')

        expected = [(303, '/multi_redirect?redirect_codes=302,301,307,302,200'),
                    (302, '/multi_redirect?redirect_codes=301,307,302,200'),
                    (301, '/multi_redirect?redirect_codes=307,302,200'),
                    (307, '/multi_redirect?redirect_codes=302,200'),
                    (302, '/multi_redirect?redirect_codes=200')]
        actual = [(history.status, history.redirect_location) for history in r.retries.history]
        self.assertEqual(actual, expected)


class TestRetryAfter(HTTPDummyServerTestCase):
    def setUp(self):
        self.pool = HTTPConnectionPool(self.host, self.port)
        self.addCleanup(self.pool.close)

    def test_retry_after(self):
        # Request twice in a second to get a 429 response.
        r = self.pool.request('GET', '/retry_after',
                              fields={'status': '429 Too Many Requests'},
                              retries=False)
        r = self.pool.request('GET', '/retry_after',
                              fields={'status': '429 Too Many Requests'},
                              retries=False)
        self.assertEqual(r.status, 429)

        r = self.pool.request('GET', '/retry_after',
                              fields={'status': '429 Too Many Requests'},
                              retries=True)
        self.assertEqual(r.status, 200)

        # Request twice in a second to get a 503 response.
        r = self.pool.request('GET', '/retry_after',
                              fields={'status': '503 Service Unavailable'},
                              retries=False)
        r = self.pool.request('GET', '/retry_after',
                              fields={'status': '503 Service Unavailable'},
                              retries=False)
        self.assertEqual(r.status, 503)

        r = self.pool.request('GET', '/retry_after',
                              fields={'status': '503 Service Unavailable'},
                              retries=True)
        self.assertEqual(r.status, 200)

        # Ignore Retry-After header on status which is not defined in
        # Retry.RETRY_AFTER_STATUS_CODES.
        r = self.pool.request('GET', '/retry_after',
                              fields={'status': "418 I'm a teapot"},
                              retries=True)
        self.assertEqual(r.status, 418)

    def test_redirect_after(self):
        r = self.pool.request('GET', '/redirect_after', retries=False)
        self.assertEqual(r.status, 303)

        t = time.time()
        r = self.pool.request('GET', '/redirect_after')
        self.assertEqual(r.status, 200)
        delta = time.time() - t
        self.assertTrue(delta >= 1)

        t = time.time()
        timestamp = t + 2
        r = self.pool.request('GET', '/redirect_after?date=' + str(timestamp))
        self.assertEqual(r.status, 200)
        delta = time.time() - t
        self.assertTrue(delta >= 1)

        # Retry-After is past
        t = time.time()
        timestamp = t - 1
        r = self.pool.request('GET', '/redirect_after?date=' + str(timestamp))
        delta = time.time() - t
        self.assertEqual(r.status, 200)
        self.assertTrue(delta < 1)


class TestFileBodiesOnRetryOrRedirect(HTTPDummyServerTestCase):
    def setUp(self):
        self.pool = HTTPConnectionPool(self.host, self.port, timeout=0.1)
        self.addCleanup(self.pool.close)

    def test_retries_put_filehandle(self):
        """HTTP PUT retry with a file-like object should not timeout"""
        retry = Retry(total=3, status_forcelist=[418])
        # httplib reads in 8k chunks; use a larger content length
        content_length = 65535
        data = b'A' * content_length
        uploaded_file = io.BytesIO(data)
        headers = {'test-name': 'test_retries_put_filehandle',
                   'Content-Length': str(content_length)}
        resp = self.pool.urlopen('PUT', '/successful_retry',
                                 headers=headers,
                                 retries=retry,
                                 body=uploaded_file,
                                 assert_same_host=False, redirect=False)
        self.assertEqual(resp.status, 200)

    def test_redirect_put_file(self):
        """PUT with file object should work with a redirection response"""
        retry = Retry(total=3, status_forcelist=[418])
        # httplib reads in 8k chunks; use a larger content length
        content_length = 65535
        data = b'A' * content_length
        uploaded_file = io.BytesIO(data)
        headers = {'test-name': 'test_redirect_put_file',
                   'Content-Length': str(content_length)}
        url = '/redirect?target=/echo&status=307'
        resp = self.pool.urlopen('PUT', url,
                                 headers=headers,
                                 retries=retry,
                                 body=uploaded_file,
                                 assert_same_host=False, redirect=True)
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.data, data)

    def test_redirect_with_failed_tell(self):
        """Abort request if failed to get a position from tell()"""
        class BadTellObject(io.BytesIO):

            def tell(self):
                raise IOError

        body = BadTellObject(b'the data')
        url = '/redirect?target=/successful_retry'
        # httplib uses fileno if Content-Length isn't supplied,
        # which is unsupported by BytesIO.
        headers = {'Content-Length': '8'}
        try:
            self.pool.urlopen('PUT', url, headers=headers, body=body)
            self.fail('PUT successful despite failed rewind.')
        except UnrewindableBodyError as e:
            self.assertTrue('Unable to record file position for' in str(e))


class TestRetryPoolSize(HTTPDummyServerTestCase):
    def setUp(self):
        retries = Retry(
            total=1,
            raise_on_status=False,
            status_forcelist=[404],
        )
        self.pool = HTTPConnectionPool(self.host, self.port, maxsize=10,
                                       retries=retries, block=True)
        self.addCleanup(self.pool.close)

    def test_pool_size_retry(self):
        self.pool.urlopen('GET', '/not_found', preload_content=False)
        self.assertEquals(self.pool.num_connections, 1)


class TestRedirectPoolSize(HTTPDummyServerTestCase):
    def setUp(self):
        retries = Retry(
            total=1,
            raise_on_status=False,
            status_forcelist=[404],
            redirect=True,
        )
        self.pool = HTTPConnectionPool(self.host, self.port, maxsize=10,
                                       retries=retries, block=True)
        self.addCleanup(self.pool.close)

    def test_pool_size_redirect(self):
        self.pool.urlopen('GET', '/redirect', preload_content=False)
        self.assertEquals(self.pool.num_connections, 1)


if __name__ == '__main__':
    unittest.main()
