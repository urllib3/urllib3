import unittest

from urllib3 import PoolManager
from urllib3.util.url import Url
from urllib3.util.hsts import match_domains

# proxy testcase has http and https servers
from dummyserver.testcase import HTTPDummyProxyTestCase


class HSTSTestCase(HTTPDummyProxyTestCase):
    def test_hsts_simple(self):
        pool = PoolManager()

        for scheme, host, port in (
            ('http', self.http_host, self.http_port),
            ('https', self.https_host, self.https_port)
        ):
            for endpoint in ('', 'hsts'):

                url = Url(scheme=scheme, host=host, port=port,
                          path='/' + endpoint).url
                pool.urlopen('GET', url)

                if endpoint == 'hsts' and scheme == 'https':
                    hsts_entries = 1
                else:
                    hsts_entries = 0

                self.assertEqual(len(pool.hsts_manager.db), hsts_entries)

    def test_hsts(self):
        pool = PoolManager()
        url = Url(scheme='https', host=self.https_host,
                  port=self.https_port, path='/hsts')

        pool.urlopen('GET', url.url)
        url = url._replace(scheme='http')
        pool.urlopen('GET', url.url)


class HSTSTestCase2(unittest.TestCase):
    def test_hsts_record_match(self):
        data = [
            # sub, super, include_subdomain, match
            ('example.com', 'example.com', False, True),
            ('foo.example.com', 'example.com', False, False),
            ('foo.example.com', 'xxxxxxx.com', False, False),
            ('example.com', 'foo.example.com', False, False),
            ('example.com', 'example.com', True, True),
            ('foo.example.com', 'example.com', True, True),
            ('foo.example.com', 'xxxxxxx.com', True, False),
            ('example.com', 'foo.example.com', True, False),
        ]

        for sub, sup, include_subdomain, match in data:
            self.assertEqual(match_domains(sub, sup, include_subdomain), match,
                             "{0} == {1} (subdomains: {2})".format(
                                sub, sup, include_subdomain))
