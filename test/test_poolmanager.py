import unittest

from urllib3.poolmanager import (
    PoolManager,
    pool_keys_by_scheme,
    HTTPPoolKey,
    HTTPSPoolKey,
)
from urllib3 import connection_from_url
from urllib3.exceptions import (
    ClosedPoolError,
    LocationValueError,
)
from urllib3.util import retry, timeout


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

    def test_http_pool_key_fields(self):
        """Assert the HTTPPoolKey fields are honored when selecting a pool."""
        connection_pool_kw = {
            'timeout': timeout.Timeout(3.14),
            'retries': retry.Retry(total=6, connect=2),
            'block': True,
            'strict': True,
        }
        p = PoolManager()
        conn_pools = [
            p.connection_from_url('http://example.com/'),
            p.connection_from_url('http://example.com:8000/'),
            p.connection_from_url('http://other.example.com/'),
        ]

        for key, value in connection_pool_kw.items():
            p.connection_pool_kw[key] = value
            conn_pools.append(p.connection_from_url('http://example.com/'))

        self.assertTrue(
            all(
                x is not y
                for i, x in enumerate(conn_pools)
                for j, y in enumerate(conn_pools)
                if i != j
            )
        )
        self.assertTrue(
            all(
                isinstance(key, HTTPPoolKey)
                for key in p.pools.keys())
        )

    def test_http_pool_key_extra_kwargs(self):
        """Assert non-HTTPPoolKey fields are ignored when selecting a pool."""
        p = PoolManager()
        conn_pool = p.connection_from_url('http://example.com/')
        p.connection_pool_kw['some_kwarg'] = 'that should be ignored'
        other_conn_pool = p.connection_from_url('http://example.com/')

        self.assertTrue(conn_pool is other_conn_pool)

    def test_https_pool_key_fields(self):
        """Assert the HTTPSPoolKey fields are honored when selecting a pool."""
        connection_pool_kw = {
            'timeout': timeout.Timeout(3.14),
            'retries': retry.Retry(total=6, connect=2),
            'block': True,
            'strict': True,
            'key_file': '/root/totally_legit.key',
            'cert_file': '/root/totally_legit.crt',
            'cert_reqs': 'CERT_REQUIRED',
            'ca_certs': '/root/path_to_pem',
            'ssl_version': 'SSLv23_METHOD',
        }
        p = PoolManager()
        conn_pools = [
            p.connection_from_url('https://example.com/'),
            p.connection_from_url('https://example.com:4333/'),
            p.connection_from_url('https://other.example.com/'),
        ]
        # Asking for a connection pool with the same key should give us an
        # existing pool.
        dup_pools = []

        for key, value in connection_pool_kw.items():
            p.connection_pool_kw[key] = value
            conn_pools.append(p.connection_from_url('https://example.com/'))
            dup_pools.append(p.connection_from_url('https://example.com/'))

        self.assertTrue(
            all(
                x is not y
                for i, x in enumerate(conn_pools)
                for j, y in enumerate(conn_pools)
                if i != j
            )
        )
        self.assertTrue(all(pool in conn_pools for pool in dup_pools))
        self.assertTrue(
            all(
                isinstance(key, HTTPSPoolKey)
                for key in p.pools.keys())
        )

    def test_https_pool_key_extra_kwargs(self):
        """Assert non-HTTPSPoolKey fields are ignored when selecting a pool."""
        p = PoolManager()
        conn_pool = p.connection_from_url('https://example.com/')
        p.connection_pool_kw['some_kwarg'] = 'that should be ignored'
        other_conn_pool = p.connection_from_url('https://example.com/')

        self.assertTrue(conn_pool is other_conn_pool)

    def test_default_pool_keys_copy(self):
        """Assert each PoolManager gets a copy of ``pool_keys_by_scheme``."""
        p = PoolManager()
        self.assertEqual(p.pool_keys_by_scheme, pool_keys_by_scheme)
        self.assertFalse(p.pool_keys_by_scheme is pool_keys_by_scheme)

    def test_pools_keyed_with_from_host(self):
        """Assert pools are still keyed correctly with connection_from_host."""
        ssl_kw = {
            'key_file': '/root/totally_legit.key',
            'cert_file': '/root/totally_legit.crt',
            'cert_reqs': 'CERT_REQUIRED',
            'ca_certs': '/root/path_to_pem',
            'ssl_version': 'SSLv23_METHOD',
        }
        p = PoolManager(5, **ssl_kw)
        conns = []
        conns.append(
            p.connection_from_host('example.com', 443, scheme='https')
        )

        for k in ssl_kw:
            p.connection_pool_kw[k] = 'newval'
            conns.append(
                p.connection_from_host('example.com', 443, scheme='https')
            )

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
