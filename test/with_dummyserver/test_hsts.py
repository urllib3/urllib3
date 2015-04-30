from urllib3 import PoolManager
from urllib3.util.url import Url

# proxy testcase has http and https servers
from dummyserver.testcase import HTTPDummyProxyTestCase


class HSTSTestCase(HTTPDummyProxyTestCase):
    def test_hsts(self):
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

                self.assertEqual(len(pool.hsts_store), hsts_entries)
