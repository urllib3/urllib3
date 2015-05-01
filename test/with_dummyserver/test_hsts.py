from datetime import datetime, timedelta
import unittest

import mock

from urllib3 import PoolManager
from urllib3.exceptions import MaxRetryError
from urllib3.util.url import Url, parse_url
from urllib3.hsts import match_domains, HSTSManager

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
        pool = PoolManager(retries=0)
        url = Url(scheme='https', host=self.https_host,
                  port=self.https_port, path='/hsts')

        pool.urlopen('GET', url.url)
        url = url._replace(scheme='http')
        pool.urlopen('GET', url.url)
        url = url._replace(query='max-age=0')
        pool.urlopen('GET', url.url)

        # we now try to connect of plain http to a htts server
        self.assertRaises(MaxRetryError, pool.urlopen, 'GET', url.url)
        self.assertEqual(len(pool.hsts_manager.db), 0)

    def test_hsts_expiration(self):
        max_age = 10000
        pool = PoolManager(retries=0)
        url = Url(scheme='https', host=self.https_host,
                  port=self.https_port, path='/hsts',
                  query='max-age={}'.format(max_age))

        pool.urlopen('GET', url.url)

        with mock.patch('urllib3.hsts.datetime') as mock_datetime:
            mock_datetime.now.return_value = datetime.now() + timedelta(max_age + 1)

            self.assertEqual(len(pool.hsts_manager.db), 0)


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

    def test_rewrite_url(self):
        hsts_manager = HSTSManager(None)

        data = [
            # original, rewritten
            ('http://example.com/', 'https://example.com/'),
            ('http://example.com:80/', 'https://example.com:443/'),
            ('http://example.com:123/', 'https://example.com:123/'),
        ]

        for original, rewritten in data:
            self.assertEqual(
                    rewritten,
                    hsts_manager.rewrite_url(parse_url(original)).url)
