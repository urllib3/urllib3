import sys
import unittest

from time import sleep

sys.path.append('../')
from urllib3.connectionpool import (
    connection_from_url,
    get_host,
    HTTPConnectionPool,
    make_headers)


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
        }
        for url, expected_host in url_host_map.iteritems():
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
            ('http://yahoo.com/', 'http://google.com/'),
            ('http://google.com:42', 'https://google.com/abracadabra'),
            ('http://google.com', 'https://google.net/'),
        ]

        for a, b in not_same_host:
            c = connection_from_url(a)
            self.assertFalse(c.is_same_host(b), "%s =? %s" % (a, b))

    def test_get_connection(self):
        # TODO: Rewrite this test somehow to use dummy_server instead of an external service.
        
        # timeout returned by www.apache.org server in keep-alive header
        WWW_APACHE_ORG_KEEP_ALIVE_TIMEOUT = 5

        pool = HTTPConnectionPool(host='www.apache.org',
                                  maxsize=1,
                                  timeout=3.0)

        r = pool.get_url('/',
                         retries=0,
                         headers={"Connection": "keep-alive"})
        self.assertEqual(r.status, 200, r.data)        

        sleep(WWW_APACHE_ORG_KEEP_ALIVE_TIMEOUT)

        # by now, the connection should have dropped, making
        # this fail without recycling closed HTTPConnections
        r = pool.get_url('/',
                         retries=0,
                         headers={"Connection": "keep-alive"})
        self.assertEqual(r.status, 200, r.data)

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

if __name__ == '__main__':
    unittest.main()
