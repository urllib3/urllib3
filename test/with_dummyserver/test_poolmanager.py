import unittest

from dummyserver.testcase import HTTPDummyServerTestCase
from urllib3.poolmanager import PoolManager
from urllib3.exceptions import MaxRetryError


class TestPoolManager(HTTPDummyServerTestCase):
    base_url = 'http://%s:%d' % (HTTPDummyServerTestCase.host, HTTPDummyServerTestCase.port)
    base_url_alt = 'http://%s:%d' % (HTTPDummyServerTestCase.host_alt, HTTPDummyServerTestCase.port)

    def test_redirect(self):
        http = PoolManager()

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/' % self.base_url},
                         redirect=False)

        self.assertEqual(r.status, 303)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/' % self.base_url})

        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Dummy server!')

    def test_cross_host_redirect(self):
        http = PoolManager()

        cross_host_location = '%s/echo?a=b' % self.base_url_alt
        try:
            http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': cross_host_location},
                         timeout=0.01, retries=1)
            self.fail("Request succeeded instead of raising an exception like it should.")

        except MaxRetryError:
            pass

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/echo?a=b' % self.base_url_alt},
                         timeout=0.01, retries=2)

        self.assertEqual(r._pool.host, self.host_alt)




if __name__ == '__main__':
    unittest.main()
