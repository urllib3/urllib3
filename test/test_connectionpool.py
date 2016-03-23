import unittest

from urllib3._collections import OrderedDict
from urllib3.connectionpool import (
    connection_from_url,
    HTTPConnection,
    HTTPConnectionPool,
    HTTPSConnectionPool,
)
from urllib3.util.timeout import Timeout
from urllib3.packages import six
from urllib3.packages.ssl_match_hostname import CertificateError
from urllib3.exceptions import (
    ClosedPoolError,
    EmptyPoolError,
    HostChangedError,
    LocationValueError,
    MaxRetryError,
    ProtocolError,
    SSLError,
)

from io import BytesIO
from socket import error as SocketError
from ssl import SSLError as BaseSSLError

try:   # Python 3
    from queue import Empty
    from http.client import HTTPException, HTTPMessage
except ImportError:
    from Queue import Empty
    from httplib import HTTPException, HTTPMessage


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
    
    def test_preserves_request_header_order(self):
        """
        Ensure that headers provided to ConnectionPool.urlopen()
        are sent to the underlying httplib in the same order.
        """
        class AbortRequest(BaseException):
            pass
        
        expected_request_headers = OrderedDict([('X-Header-%d' % i, str(i)) for i in range(16)])
        
        c = connection_from_url('http://localhost:80')
        
        # Defer: Assert the request sent to httplib had the same header order
        #        as the original header arguments to ConnectionPool.urlopen().
        def patched_request(*args, **kwargs):
            actual_request_headers = kwargs['headers']
            self.assertEqual(
                list(actual_request_headers.items()),
                list(expected_request_headers.items()))
            raise AbortRequest()
        
        # Patch the .request() for new connections in the pool 
        original_new_conn = c._new_conn
        def patched_new_conn(*args, **kwargs):
            conn = original_new_conn(*args, **kwargs)
            conn.request = patched_request
            return conn
        c._new_conn = patched_new_conn
        
        try:
            c.urlopen('GET', '/', headers=expected_request_headers, release_conn=False)
        except AbortRequest:
            pass
    
    def test_preserves_response_header_order(self):
        """
        Ensure that headers returned by ConnectionPool.urlopen()
        are in the same order as received from the underlying httplib.
        """
        
        # NOTE: Using lowercase response header names since Python 2.x doesn't
        #       preserve their case, normalizing them all to lowercase.
        expected_response_headers = OrderedDict([('x-header-%d' % i, str(i)) for i in range(16)])
        
        c = connection_from_url('http://localhost:80')
        
        # Patch the .getresponse() for new connections in the pool to return
        # a simulated httplib.HTTPResponse
        original_new_conn = c._new_conn
        def patched_new_conn(*args, **kwargs):
            conn = original_new_conn(*args, **kwargs)
            conn.request = lambda *args, **kwargs: None
            conn.getresponse = lambda *args, **kwargs: \
                self._create_httplib_response(expected_response_headers)
            return conn
        c._new_conn = patched_new_conn
        
        actual_response = c.urlopen('GET', '/', release_conn=False)
        self.assertEqual(
            list(actual_response.headers.items()),
            list(expected_response_headers.items()))
    
    def _create_httplib_response(self, headers):
        class FakeHTTPResponse(object):
            status = 200
            reason = 'OK'
            version = '0.9'
            length = 0
            msg = self._create_httplib_message(headers)
        return FakeHTTPResponse()
    
    def _create_httplib_message(self, headers):
        if six.PY3:
            httplib_message = HTTPMessage()
            for (k, v) in headers.items():
                httplib_message.add_header(k, v)
        else:
            for (k, v) in headers.items():
                assert k == k.lower(), \
                    'Unwise to use anything but lowercase header names ' + \
                    'since Python 2.x normalizes them to lowercase internally.'
            header_text = ''.join(['%s: %s\r\n' % (k, v) for (k, v) in headers.items()])
            httplib_message = HTTPMessage(BytesIO(header_text.encode('utf8')))
        return httplib_message


if __name__ == '__main__':
    unittest.main()
