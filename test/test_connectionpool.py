from __future__ import absolute_import

import unittest

from urllib3.connectionpool import (
    connection_from_url,
    HTTPConnection,
    HTTPConnectionPool,
    HTTPSConnectionPool,
)
from urllib3.response import httplib, HTTPResponse
from urllib3.util.timeout import Timeout
from urllib3.packages.ssl_match_hostname import CertificateError
from urllib3.exceptions import (
    ClosedPoolError,
    EmptyPoolError,
    HostChangedError,
    LocationValueError,
    MaxRetryError,
    ProtocolError,
    SSLError,
    TimeoutError,
)
from urllib3._collections import HTTPHeaderDict
from .test_response import MockChunkedEncodingResponse, MockSock

from socket import error as SocketError
from ssl import SSLError as BaseSSLError

try:   # Python 3
    from queue import Empty
    from http.client import HTTPException
except ImportError:
    from Queue import Empty
    from httplib import HTTPException


class TestConnectionPool(unittest.TestCase):
    """
    Tests in this suite should exercise the ConnectionPool functionality
    without actually making any network requests or connections.
    """
    def test_same_host(self):
        same_host = [
            ('http://google.com/', '/'),
            ('http://google.com/', 'http://google.com/'),
            ('http://google.com/', 'http://google.com'),
            ('http://google.com/', 'http://google.com/abra/cadabra'),
            ('http://google.com:42/', 'http://google.com:42/abracadabra'),
            # Test comparison using default ports
            ('http://google.com:80/', 'http://google.com/abracadabra'),
            ('http://google.com/', 'http://google.com:80/abracadabra'),
            ('https://google.com:443/', 'https://google.com/abracadabra'),
            ('https://google.com/', 'https://google.com:443/abracadabra'),
        ]

        for a, b in same_host:
            c = connection_from_url(a)
            self.assertTrue(c.is_same_host(b), "%s =? %s" % (a, b))

        not_same_host = [
            ('https://google.com/', 'http://google.com/'),
            ('http://google.com/', 'https://google.com/'),
            ('http://yahoo.com/', 'http://google.com/'),
            ('http://google.com:42', 'https://google.com/abracadabra'),
            ('http://google.com', 'https://google.net/'),
            # Test comparison with default ports
            ('http://google.com:42', 'http://google.com'),
            ('https://google.com:42', 'https://google.com'),
            ('http://google.com:443', 'http://google.com'),
            ('https://google.com:80', 'https://google.com'),
            ('http://google.com:443', 'https://google.com'),
            ('https://google.com:80', 'http://google.com'),
            ('https://google.com:443', 'http://google.com'),
            ('http://google.com:80', 'https://google.com'),
        ]

        for a, b in not_same_host:
            c = connection_from_url(a)
            self.assertFalse(c.is_same_host(b), "%s =? %s" % (a, b))
            c = connection_from_url(b)
            self.assertFalse(c.is_same_host(a), "%s =? %s" % (b, a))

    def test_same_host_no_port(self):
        # This test was introduced in #801 to deal with the fact that urllib3
        # never initializes ConnectionPool objects with port=None.
        same_host_http = [
            ('google.com', '/'),
            ('google.com', 'http://google.com/'),
            ('google.com', 'http://google.com'),
            ('google.com', 'http://google.com/abra/cadabra'),
            # Test comparison using default ports
            ('google.com', 'http://google.com:80/abracadabra'),
        ]
        same_host_https = [
            ('google.com', '/'),
            ('google.com', 'https://google.com/'),
            ('google.com', 'https://google.com'),
            ('google.com', 'https://google.com/abra/cadabra'),
            # Test comparison using default ports
            ('google.com', 'https://google.com:443/abracadabra'),
        ]

        for a, b in same_host_http:
            c = HTTPConnectionPool(a)
            self.assertTrue(c.is_same_host(b), "%s =? %s" % (a, b))
        for a, b in same_host_https:
            c = HTTPSConnectionPool(a)
            self.assertTrue(c.is_same_host(b), "%s =? %s" % (a, b))

        not_same_host_http = [
            ('google.com', 'https://google.com/'),
            ('yahoo.com', 'http://google.com/'),
            ('google.com', 'https://google.net/'),
        ]
        not_same_host_https = [
            ('google.com', 'http://google.com/'),
            ('yahoo.com', 'https://google.com/'),
            ('google.com', 'https://google.net/'),
        ]

        for a, b in not_same_host_http:
            c = HTTPConnectionPool(a)
            self.assertFalse(c.is_same_host(b), "%s =? %s" % (a, b))
            c = HTTPConnectionPool(b)
            self.assertFalse(c.is_same_host(a), "%s =? %s" % (b, a))
        for a, b in not_same_host_https:
            c = HTTPSConnectionPool(a)
            self.assertFalse(c.is_same_host(b), "%s =? %s" % (a, b))
            c = HTTPSConnectionPool(b)
            self.assertFalse(c.is_same_host(a), "%s =? %s" % (b, a))

    def test_max_connections(self):
        pool = HTTPConnectionPool(host='localhost', maxsize=1, block=True)

        pool._get_conn(timeout=0.01)

        try:
            pool._get_conn(timeout=0.01)
            self.fail("Managed to get a connection without EmptyPoolError")
        except EmptyPoolError:
            pass

        try:
            pool.request('GET', '/', pool_timeout=0.01)
            self.fail("Managed to get a connection without EmptyPoolError")
        except EmptyPoolError:
            pass

        self.assertEqual(pool.num_connections, 1)

    def test_pool_edgecases(self):
        pool = HTTPConnectionPool(host='localhost', maxsize=1, block=False)

        conn1 = pool._get_conn()
        conn2 = pool._get_conn() # New because block=False

        pool._put_conn(conn1)
        pool._put_conn(conn2) # Should be discarded

        self.assertEqual(conn1, pool._get_conn())
        self.assertNotEqual(conn2, pool._get_conn())

        self.assertEqual(pool.num_connections, 3)

    def test_exception_str(self):
        self.assertEqual(
            str(EmptyPoolError(HTTPConnectionPool(host='localhost'), "Test.")),
            "HTTPConnectionPool(host='localhost', port=None): Test.")

    def test_retry_exception_str(self):
        self.assertEqual(
            str(MaxRetryError(
                HTTPConnectionPool(host='localhost'), "Test.", None)),
            "HTTPConnectionPool(host='localhost', port=None): "
            "Max retries exceeded with url: Test. (Caused by None)")

        err = SocketError("Test")

        # using err.__class__ here, as socket.error is an alias for OSError
        # since Py3.3 and gets printed as this
        self.assertEqual(
            str(MaxRetryError(
                HTTPConnectionPool(host='localhost'), "Test.", err)),
            "HTTPConnectionPool(host='localhost', port=None): "
            "Max retries exceeded with url: Test. "
            "(Caused by %r)" % err)


    def test_pool_size(self):
        POOL_SIZE = 1
        pool = HTTPConnectionPool(host='localhost', maxsize=POOL_SIZE, block=True)

        def _raise(ex):
            raise ex()

        def _test(exception, expect):
            pool._make_request = lambda *args, **kwargs: _raise(exception)
            self.assertRaises(expect, pool.request, 'GET', '/')

            self.assertEqual(pool.pool.qsize(), POOL_SIZE)

        # Make sure that all of the exceptions return the connection to the pool
        _test(Empty, EmptyPoolError)
        _test(BaseSSLError, SSLError)
        _test(CertificateError, SSLError)

        # The pool should never be empty, and with these two exceptions being raised,
        # a retry will be triggered, but that retry will fail, eventually raising
        # MaxRetryError, not EmptyPoolError
        # See: https://github.com/shazow/urllib3/issues/76
        pool._make_request = lambda *args, **kwargs: _raise(HTTPException)
        self.assertRaises(MaxRetryError, pool.request,
                          'GET', '/', retries=1, pool_timeout=0.01)
        self.assertEqual(pool.pool.qsize(), POOL_SIZE)

    def test_assert_same_host(self):
        c = connection_from_url('http://google.com:80')

        self.assertRaises(HostChangedError, c.request,
                          'GET', 'http://yahoo.com:80', assert_same_host=True)

    def test_pool_close(self):
        pool = connection_from_url('http://google.com:80')

        # Populate with some connections
        conn1 = pool._get_conn()
        conn2 = pool._get_conn()
        conn3 = pool._get_conn()
        pool._put_conn(conn1)
        pool._put_conn(conn2)

        old_pool_queue = pool.pool

        pool.close()
        self.assertEqual(pool.pool, None)

        self.assertRaises(ClosedPoolError, pool._get_conn)

        pool._put_conn(conn3)

        self.assertRaises(ClosedPoolError, pool._get_conn)

        self.assertRaises(Empty, old_pool_queue.get, block=False)

    def test_pool_timeouts(self):
        pool = HTTPConnectionPool(host='localhost')
        conn = pool._new_conn()
        self.assertEqual(conn.__class__, HTTPConnection)
        self.assertEqual(pool.timeout.__class__, Timeout)
        self.assertEqual(pool.timeout._read, Timeout.DEFAULT_TIMEOUT)
        self.assertEqual(pool.timeout._connect, Timeout.DEFAULT_TIMEOUT)
        self.assertEqual(pool.timeout.total, None)

        pool = HTTPConnectionPool(host='localhost', timeout=3)
        self.assertEqual(pool.timeout._read, 3)
        self.assertEqual(pool.timeout._connect, 3)
        self.assertEqual(pool.timeout.total, None)

    def test_no_host(self):
        self.assertRaises(LocationValueError, HTTPConnectionPool, None)

    def test_contextmanager(self):
        with connection_from_url('http://google.com:80') as pool:
            # Populate with some connections
            conn1 = pool._get_conn()
            conn2 = pool._get_conn()
            conn3 = pool._get_conn()
            pool._put_conn(conn1)
            pool._put_conn(conn2)

            old_pool_queue = pool.pool

        self.assertEqual(pool.pool, None)
        self.assertRaises(ClosedPoolError, pool._get_conn)

        pool._put_conn(conn3)
        self.assertRaises(ClosedPoolError, pool._get_conn)
        self.assertRaises(Empty, old_pool_queue.get, block=False)

    def test_absolute_url(self):
        c = connection_from_url('http://google.com:80')
        self.assertEqual(
                'http://google.com:80/path?query=foo',
                c._absolute_url('path?query=foo'))

    def test_ca_certs_default_cert_required(self):
        with connection_from_url('https://google.com:80', ca_certs='/etc/ssl/certs/custom.pem') as pool:
            conn = pool._get_conn()
            self.assertEqual(conn.cert_reqs, 'CERT_REQUIRED')

    def test_cleanup_on_extreme_connection_error(self):
        """
        This test validates that we clean up properly even on exceptions that
        we'd not otherwise catch, i.e. those that inherit from BaseException
        like KeyboardInterrupt or gevent.Timeout. See #805 for more details.
        """
        class RealBad(BaseException):
            pass

        def kaboom(*args, **kwargs):
            raise RealBad()

        c = connection_from_url('http://localhost:80')
        c._make_request = kaboom

        initial_pool_size = c.pool.qsize()

        try:
            # We need to release_conn this way or we'd put it away regardless.
            c.urlopen('GET', '/', release_conn=False)
        except RealBad:
            pass

        new_pool_size = c.pool.qsize()
        self.assertEqual(initial_pool_size, new_pool_size)

    def test_release_conn_param_is_respected_after_http_error_retry(self):
        """For successful ```urlopen(release_conn=False)```, the connection isn't released, even after a retry.

        This is a regression test for issue #651 [1], where the connection
        would be released if the initial request failed, even if a retry
        succeeded.

        [1] <https://github.com/shazow/urllib3/issues/651>
        """

        class _raise_once_make_request_function(object):
            """Callable that can mimic `_make_request()`.

            Raises the given exception on its first call, but returns a
            successful response on subsequent calls.
            """
            def __init__(self, ex):
                super(_raise_once_make_request_function, self).__init__()
                self._ex = ex

            def __call__(self, *args, **kwargs):
                if self._ex:
                    ex, self._ex = self._ex, None
                    raise ex()
                response = httplib.HTTPResponse(MockSock)
                response.fp = MockChunkedEncodingResponse([b'f', b'o', b'o'])
                response.headers = response.msg = HTTPHeaderDict()
                return response

        def _test(exception):
            pool = HTTPConnectionPool(host='localhost', maxsize=1, block=True)

            # Verify that the request succeeds after two attempts, and that the
            # connection is left on the response object, instead of being
            # released back into the pool.
            pool._make_request = _raise_once_make_request_function(exception)
            response = pool.urlopen('GET', '/', retries=1,
                                    release_conn=False, preload_content=False,
                                    chunked=True)
            self.assertEqual(pool.pool.qsize(), 0)
            self.assertEqual(pool.num_connections, 2)
            self.assertTrue(response.connection is not None)

            response.release_conn()
            self.assertEqual(pool.pool.qsize(), 1)
            self.assertTrue(response.connection is None)

        # Run the test case for all the retriable exceptions.
        _test(TimeoutError)
        _test(HTTPException)
        _test(SocketError)
        _test(ProtocolError)

    def test_custom_http_response_class(self):

        class CustomHTTPResponse(HTTPResponse):
            pass

        class CustomConnectionPool(HTTPConnectionPool):
            ResponseCls = CustomHTTPResponse

            def _make_request(self, *args, **kwargs):
                httplib_response = httplib.HTTPResponse(MockSock)
                httplib_response.fp = MockChunkedEncodingResponse([b'f', b'o', b'o'])
                httplib_response.headers = httplib_response.msg = HTTPHeaderDict()
                return httplib_response

        pool = CustomConnectionPool(host='localhost', maxsize=1, block=True)
        response = pool.request('GET', '/', retries=False, chunked=True,
                                preload_content=False)
        self.assertTrue(isinstance(response, CustomHTTPResponse))


if __name__ == '__main__':
    unittest.main()
