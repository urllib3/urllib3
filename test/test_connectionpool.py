import unittest

from urllib3.connectionpool import connection_from_url, HTTPConnectionPool
from urllib3.exceptions import EmptyPoolError


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


if __name__ == '__main__':
    unittest.main()
