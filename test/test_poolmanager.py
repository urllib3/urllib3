import unittest

from urllib3.poolmanager import PoolManager, SSL_KEYWORDS
from urllib3 import connection_from_url
from urllib3.exceptions import (
    ClosedPoolError,
    LocationValueError,
)


class TestPoolManager(unittest.TestCase):
    def test_same_url(self):
        # Convince ourselves that normally we don't get the same object
        conn1 = connection_from_url('http://localhost:8081/foo')
        conn2 = connection_from_url('http://localhost:8081/bar')

        self.assertNotEqual(conn1, conn2)

        # Now try again using the PoolManager
        p = PoolManager(1)

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

        p = PoolManager(10)

        for url in urls:
            conn = p.connection_from_url(url)
            connections.add(conn)

        self.assertEqual(len(connections), 5)

    def test_manager_clear(self):
        p = PoolManager(5)

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
        p = PoolManager(5)
        self.assertRaises(LocationValueError, p.connection_from_url, 'http://@')
        self.assertRaises(LocationValueError, p.connection_from_url, None)

    def test_contextmanager(self):
        with PoolManager(1) as p:
            conn_pool = p.connection_from_url('http://google.com')
            self.assertEqual(len(p.pools), 1)
            conn = conn_pool._get_conn()

        self.assertEqual(len(p.pools), 0)

        self.assertRaises(ClosedPoolError, conn_pool._get_conn)

        conn_pool._put_conn(conn)

        self.assertRaises(ClosedPoolError, conn_pool._get_conn)

        self.assertEqual(len(p.pools), 0)

    def test_pools_keyed_on_ssl_arguments_from_host(self):
        ssl_kw = {
            'key_file': '/root/totally_legit.key',
            'cert_file': '/root/totally_legit.crt',
            'cert_reqs': 'CERT_REQUIRED',
            'ca_certs': '/root/path_to_pem',
            'ssl_version': 'SSLv23_METHOD',
        }
        p = PoolManager(5)
        conns = []
        conns.append(
            p.connection_from_host(
                'example.com', 443, scheme='https', ssl_kwargs=ssl_kw
            )
        )

        for k in ssl_kw:
            ssl_kw[k] = 'newval'
            conns.append(
                p.connection_from_host(
                    'example.com', 443, scheme='https', ssl_kwargs=ssl_kw
                )
            )

        self.assertTrue(
            all(
                x is not y
                for i, x in enumerate(conns)
                for j, y in enumerate(conns)
                if i != j
            )
        )

    def test_pools_keyed_on_ssl_arguments_from_url(self):
        ssl_kw = {
            'key_file': '/root/totally_legit.key',
            'cert_file': '/root/totally_legit.crt',
            'cert_reqs': 'CERT_REQUIRED',
            'ca_certs': '/root/path_to_pem',
            'ssl_version': 'SSLv23_METHOD',
        }
        p = PoolManager(5, **ssl_kw)
        conns = []
        conns.append(p.connection_from_url('https://example.com/'))

        for k in ssl_kw:
            p.connection_pool_kw[k] = 'newval'
            conns.append(p.connection_from_url('https://example.com/'))

        self.assertTrue(
            all(
                x is not y
                for i, x in enumerate(conns)
                for j, y in enumerate(conns)
                if i != j
            )
        )


if __name__ == '__main__':
    unittest.main()
