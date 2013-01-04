import unittest
import json

from dummyserver.testcase import HTTPDummyServerTestCase,HTTPDummyProxyTestCase,HTTPSDummyServerTestCase
from urllib3.poolmanager import proxy_from_url
from urllib3.connectionpool import port_by_scheme
from urllib3.exceptions import MaxRetryError

class TestHTTPProxyManager(HTTPDummyProxyTestCase,HTTPDummyServerTestCase):
    base_url = 'http://%s:%d' % (HTTPDummyServerTestCase.host, HTTPDummyServerTestCase.port)
    base_url_alt = 'http://%s:%d' % (HTTPDummyServerTestCase.host_alt, HTTPDummyServerTestCase.port)
    proxy_url = 'http://%s:%d' % (HTTPDummyProxyTestCase.proxy_host, HTTPDummyProxyTestCase.proxy_port)

    def test_redirect(self):
        http = proxy_from_url(self.proxy_url)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/' % self.base_url},
                         redirect=False)

        self.assertEqual(r.status, 303)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/' % self.base_url})

        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Dummy server!')

    def test_cross_host_redirect(self):
        http = proxy_from_url(self.proxy_url)

        cross_host_location = '%s/echo?a=b' % self.base_url_alt
        try:
            http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': cross_host_location},
                         timeout=0.1, retries=0)
            self.fail("Request succeeded instead of raising an exception like it should.")

        except MaxRetryError:
            pass

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/echo?a=b' % self.base_url_alt},
                         timeout=0.01, retries=1)
        self.assertNotEqual(r._pool.host, self.host_alt)

    def test_headers(self):
        http = proxy_from_url(self.proxy_url,headers={'Foo': 'bar'})

        r = http.request_encode_url('GET', '%s/headers' % self.base_url)
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), 'bar')

        r = http.request_encode_body('POST', '%s/headers' % self.base_url)
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), 'bar')

        r = http.request_encode_url('GET', '%s/headers' % self.base_url, headers={'Baz': 'quux'})
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), None)
        self.assertEqual(returned_headers.get('Baz'), 'quux')

        r = http.request_encode_body('GET', '%s/headers' % self.base_url, headers={'Baz': 'quux'})
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), None)
        self.assertEqual(returned_headers.get('Baz'), 'quux')


if __name__ == '__main__':
    unittest.main()
