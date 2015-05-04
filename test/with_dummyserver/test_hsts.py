from datetime import datetime, timedelta

import mock

from urllib3 import PoolManager
from urllib3.exceptions import MaxRetryError
from urllib3.util.url import Url

# proxy testcase has http and https servers
from dummyserver.testcase import (HTTPDummyProxyTestCase,
                                  SocketDummyServerTestCase)


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
                  query='max-age={0}'.format(max_age))

        pool.urlopen('GET', url.url)

        with mock.patch('urllib3.hsts.HSTSRecord._now') as mock_now:
            mock_now.return_value = datetime.now() + timedelta(seconds=max_age + 1)

            self.assertEqual(len(pool.hsts_manager.db), 0)

    def test_invalid_hsts_header(self):
        pool = PoolManager(retries=0)
        url = Url(scheme='https', host=self.https_host,
                  port=self.https_port, path='/hsts',
                  query='max-age=invalid')

        pool.urlopen('GET', url.url)
        self.assertEqual(len(pool.hsts_manager.db), 0)
