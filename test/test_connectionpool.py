import unittest

from urllib3.connectionpool import connection_from_url, HTTPConnectionPool
from urllib3.packages.ssl_match_hostname import CertificateError
from urllib3.exceptions import (
    ClosedPoolError,
    EmptyPoolError,
    HostChangedError,
    MaxRetryError,
    SSLError,
    TimeoutError,
)

from socket import timeout as SocketTimeout
from ssl import SSLError as BaseSSLError

try:   # Python 3
    from queue import Empty
    from http.client import HTTPException
except ImportError:
    from Queue import Empty
    from httplib import HTTPException


class TestConnectionPool(unittest.TestCase):
    def test_same_host(self):
        same_host = [
            ('http://google.com/', '/'),
            ('http://google.com/', 'http://google.com/'),
            ('http://google.com/', 'http://google.com'),
            ('http://google.com/', 'http://google.com/abra/cadabra'),
            ('http://google.com:42/', 'http://google.com:42/abracadabra'),
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
        ]

        for a, b in not_same_host:
            c = connection_from_url(a)
            self.assertFalse(c.is_same_host(b), "%s =? %s" % (a, b))

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

    def test_pool_size(self):
        POOL_SIZE = 1
        pool = HTTPConnectionPool(host='localhost', maxsize=POOL_SIZE, block=True)

        def _raise(ex):
            raise ex()

        def _test(exception, expect):
            pool._make_request = lambda *args, **kwargs: _raise(exception)
            with self.assertRaises(expect):
                pool.request('GET', '/')

            self.assertEqual(pool.pool.qsize(), POOL_SIZE)

        #make sure that all of the exceptions return the connection to the pool
        _test(Empty, TimeoutError)
        _test(SocketTimeout, TimeoutError)
        _test(BaseSSLError, SSLError)
        _test(CertificateError, SSLError)

        # The pool should never be empty, and with these two exceptions being raised,
        # a retry will be triggered, but that retry will fail, eventually raising
        # MaxRetryError, not EmptyPoolError
        # See: https://github.com/shazow/urllib3/issues/76
        pool._make_request = lambda *args, **kwargs: _raise(HTTPException)
        with self.assertRaises(MaxRetryError):
            pool.request('GET', '/', retries=1, pool_timeout=0.01)
        self.assertEqual(pool.pool.qsize(), POOL_SIZE)

    def test_assert_same_host(self):
        c = connection_from_url('http://google.com:80')

        with self.assertRaises(HostChangedError):
            c.request('GET', 'http://yahoo.com:80', assert_same_host=True)

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

        with self.assertRaises(ClosedPoolError):
            pool._get_conn()

        pool._put_conn(conn3)

        with self.assertRaises(ClosedPoolError):
            pool._get_conn()

        with self.assertRaises(Empty):
            old_pool_queue.get(block=False)


if __name__ == '__main__':
    unittest.main()
