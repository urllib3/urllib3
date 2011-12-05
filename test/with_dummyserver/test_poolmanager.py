import unittest

from dummyserver.testcase import HTTPDummyServerTestCase
from urllib3.poolmanager import PoolManager
from urllib3.exceptions import MaxRetryError


class TestPoolManager(HTTPDummyServerTestCase):
    base_url = 'http://%s:%d' % (HTTPDummyServerTestCase.host, HTTPDummyServerTestCase.port)

    def test_redirect(self):
        http = PoolManager()

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/' % self.base_url},
                         redirect=False)

        self.assertEqual(r.status, 303)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/' % self.base_url})

        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, 'Dummy server!')

    def test_cross_host_redirect(self):
        http = PoolManager()
        try:
            http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': 'http://192.0.2.0/echo?foo=bar'},
                         timeout=0.01, retries=1)
            self.fail("Request succeeded instead of raising an exception like it should.")
        except MaxRetryError:
            raise



if __name__ == '__main__':
    unittest.main()
