import unittest

from urllib3.connectionpool import (
    connection_from_url,
    get_host,
    HTTPConnectionPool,
    make_headers)

from urllib3.exceptions import EmptyPoolError, LocationParseError


class TestConnectionPool(unittest.TestCase):
    def test_get_host(self):
        url_host_map = {
            'http://google.com/mail': ('http', 'google.com', None),
            'http://google.com/mail/': ('http', 'google.com', None),
            'google.com/mail': ('http', 'google.com', None),
            'http://google.com/': ('http', 'google.com', None),
            'http://google.com': ('http', 'google.com', None),
            'http://www.google.com': ('http', 'www.google.com', None),
            'http://mail.google.com': ('http', 'mail.google.com', None),
            'http://google.com:8000/mail/': ('http', 'google.com', 8000),
            'http://google.com:8000': ('http', 'google.com', 8000),
            'https://google.com': ('https', 'google.com', None),
            'https://google.com:8000': ('https', 'google.com', 8000),
            'http://user:password@127.0.0.1:1234': ('http', '127.0.0.1', 1234),
        }
        for url, expected_host in url_host_map.items():
            returned_host = get_host(url)
            self.assertEquals(returned_host, expected_host)

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

    def test_invalid_host(self):
        # TODO: Add more tests
        invalid_host = [
            'http://google.com:foo',
        ]

        for location in invalid_host:
            self.assertRaises(LocationParseError, get_host, location)


    def test_make_headers(self):
        self.assertEqual(
            make_headers(accept_encoding=True),
            {'accept-encoding': 'gzip,deflate'})

        self.assertEqual(
            make_headers(accept_encoding='foo,bar'),
            {'accept-encoding': 'foo,bar'})

        self.assertEqual(
            make_headers(accept_encoding=['foo', 'bar']),
            {'accept-encoding': 'foo,bar'})

        self.assertEqual(
            make_headers(accept_encoding=True, user_agent='banana'),
            {'accept-encoding': 'gzip,deflate', 'user-agent': 'banana'})

        self.assertEqual(
            make_headers(user_agent='banana'),
            {'user-agent': 'banana'})

        self.assertEqual(
            make_headers(keep_alive=True),
            {'connection': 'keep-alive'})

        self.assertEqual(
            make_headers(basic_auth='foo:bar'),
            {'authorization': 'Basic Zm9vOmJhcg=='})

    def test_max_connections(self):
        pool = HTTPConnectionPool(host='localhost', maxsize=1, block=True)

        pool._get_conn(timeout=0.01)

        try:
            pool._get_conn(timeout=0.01)
            self.fail("Managed to get a connection without EmptyPoolError")
        except EmptyPoolError:
            pass

        try:
            pool.get_url('/', pool_timeout=0.01)
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
