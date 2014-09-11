import unittest

from urllib3.connectionpool import (
    connection_from_url,
    HTTPConnection,
    HTTPConnectionPool,
)
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
)

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



if __name__ == '__main__':
    unittest.main()
