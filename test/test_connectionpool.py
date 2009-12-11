import unittest

import sys
sys.path.append('../')

from urllib3 import HTTPConnectionPool

class TestConnectionPool(unittest.TestCase):
    def test_get_host(self):
        url_host_map = {
            'http://google.com/mail': ('google.com', None),
            'http://google.com/mail/': ('google.com', None),
            'google.com/mail': ('google.com', None),
            'http://google.com/': ('google.com', None),
            'http://google.com': ('google.com', None),
            'http://www.google.com': ('www.google.com', None),
            'http://mail.google.com': ('mail.google.com', None),
            'http://google.com:8000/mail/': ('google.com', 8000),
            'http://google.com:8000': ('google.com', 8000),
        }
        for url, expected_host in url_host_map.iteritems():
            returned_host = HTTPConnectionPool.get_host(url)
            self.assertEquals(returned_host, expected_host)

