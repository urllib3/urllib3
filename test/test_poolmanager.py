import unittest

from test import multi_ssl

from urllib3.poolmanager import PoolManager
from urllib3 import connection_from_url
from urllib3.exceptions import (
    ClosedPoolError,
    LocationParseError,
)


@multi_ssl()
class TestPoolManager(unittest.TestCase):
    def test_same_url(self):
        # Convince ourselves that normally we don't get the same object
        conn1 = connection_from_url('http://localhost:8081/foo', ssl=self.ssl)
        conn2 = connection_from_url('http://localhost:8081/bar', ssl=self.ssl)

        self.assertNotEqual(conn1, conn2)

        # Now try again using the PoolManager
        p = PoolManager(1, ssl=self.ssl)

        conn1 = p.connection_from_url('http://localhost:8081/foo')
        conn2 = p.connection_from_url('http://localhost:8081/bar')

        self.assertEqual(conn1, conn2)

    def test_many_urls(self):
        urls = [
            "http://localhost:8081/foo",
            "http://www.google.com/mail",
            "http://localhost:8081/bar",
            "https://www.google.com/",
            "https://www.google.com/mail",
            "http://yahoo.com",
            "http://bing.com",
            "http://yahoo.com/",
        ]

        connections = set()

        p = PoolManager(10, ssl=self.ssl)

        for url in urls:
            conn = p.connection_from_url(url)
            connections.add(conn)

        self.assertEqual(len(connections), 5)

    def test_manager_clear(self):
        p = PoolManager(5, ssl=self.ssl)

        conn_pool = p.connection_from_url('http://google.com')
        self.assertEqual(len(p.pools), 1)

        conn = conn_pool._get_conn()

        p.clear()
        self.assertEqual(len(p.pools), 0)

        self.assertRaises(ClosedPoolError, conn_pool._get_conn)

        conn_pool._put_conn(conn)

        self.assertRaises(ClosedPoolError, conn_pool._get_conn)

        self.assertEqual(len(p.pools), 0)


    def test_nohost(self):
        p = PoolManager(5, ssl=self.ssl)
        self.assertRaises(LocationParseError, p.connection_from_url, 'http://@')


TestPoolManager_BaseSSL, TestPoolManager_BackportsSSL = \
    TestPoolManager.ssl_impls


if __name__ == '__main__':
    unittest.main()
