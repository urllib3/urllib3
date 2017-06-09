import unittest
import json

from nose.plugins.skip import SkipTest
from dummyserver.server import HAS_IPV6
from dummyserver.testcase import (HTTPDummyServerTestCase,
                                  IPv6HTTPDummyServerTestCase)
from urllib3.poolmanager import PoolManager
from urllib3.connectionpool import port_by_scheme
from urllib3.exceptions import MaxRetryError
from urllib3.util.retry import Retry


class TestPoolManager(HTTPDummyServerTestCase):

    def setUp(self):
        self.base_url = 'http://%s:%d' % (self.host, self.port)
        self.base_url_alt = 'http://%s:%d' % (self.host_alt, self.port)

    def test_redirect(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/' % self.base_url},
                         redirect=False)

        self.assertEqual(r.status, 303)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/' % self.base_url})

        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Dummy server!')

    def test_redirect_twice(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/redirect' % self.base_url},
                         redirect=False)

        self.assertEqual(r.status, 303)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/redirect?target=%s/' % (self.base_url,
                                                                       self.base_url)})

        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Dummy server!')

    def test_redirect_to_relative_url(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '/redirect'},
                         redirect=False)

        self.assertEqual(r.status, 303)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '/redirect'})

        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Dummy server!')

    def test_cross_host_redirect(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        cross_host_location = '%s/echo?a=b' % self.base_url_alt
        try:
            http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': cross_host_location},
                         timeout=1, retries=0)
            self.fail("Request succeeded instead of raising an exception like it should.")

        except MaxRetryError:
            pass

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/echo?a=b' % self.base_url_alt},
                         timeout=1, retries=1)

        self.assertEqual(r._pool.host, self.host_alt)

    def test_too_many_redirects(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        try:
            r = http.request('GET', '%s/redirect' % self.base_url,
                             fields={'target': '%s/redirect?target=%s/' % (self.base_url,
                                                                           self.base_url)},
                             retries=1)
            self.fail("Failed to raise MaxRetryError exception, returned %r" % r.status)
        except MaxRetryError:
            pass

        try:
            r = http.request('GET', '%s/redirect' % self.base_url,
                             fields={'target': '%s/redirect?target=%s/' % (self.base_url,
                                                                           self.base_url)},
                             retries=Retry(total=None, redirect=1))
            self.fail("Failed to raise MaxRetryError exception, returned %r" % r.status)
        except MaxRetryError:
            pass

    def test_raise_on_redirect(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/redirect?target=%s/' % (self.base_url,
                                                                       self.base_url)},
                         retries=Retry(total=None, redirect=1, raise_on_redirect=False))

        self.assertEqual(r.status, 303)

    def test_raise_on_status(self):
        http = PoolManager()
        self.addCleanup(http.clear)

        try:
            # the default is to raise
            r = http.request('GET', '%s/status' % self.base_url,
                             fields={'status': '500 Internal Server Error'},
                             retries=Retry(total=1, status_forcelist=range(500, 600)))
            self.fail("Failed to raise MaxRetryError exception, returned %r" % r.status)
        except MaxRetryError:
            pass

        try:
            # raise explicitly
            r = http.request('GET', '%s/status' % self.base_url,
                             fields={'status': '500 Internal Server Error'},
                             retries=Retry(total=1,
                                           status_forcelist=range(500, 600),
                                           raise_on_status=True))
            self.fail("Failed to raise MaxRetryError exception, returned %r" % r.status)
        except MaxRetryError:
            pass

        # don't raise
        r = http.request('GET', '%s/status' % self.base_url,
                         fields={'status': '500 Internal Server Error'},
                         retries=Retry(total=1,
                                       status_forcelist=range(500, 600),
                                       raise_on_status=False))

        self.assertEqual(r.status, 500)

    def test_missing_port(self):
        # Can a URL that lacks an explicit port like ':80' succeed, or
        # will all such URLs fail with an error?

        http = PoolManager()
        self.addCleanup(http.clear)

        # By globally adjusting `port_by_scheme` we pretend for a moment
        # that HTTP's default port is not 80, but is the port at which
        # our test server happens to be listening.
        port_by_scheme['http'] = self.port
        try:
            r = http.request('GET', 'http://%s/' % self.host, retries=0)
        finally:
            port_by_scheme['http'] = 80

        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Dummy server!')

    def test_headers(self):
        http = PoolManager(headers={'Foo': 'bar'})
        self.addCleanup(http.clear)

        r = http.request('GET', '%s/headers' % self.base_url)
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), 'bar')

        r = http.request('POST', '%s/headers' % self.base_url)
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), 'bar')

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

    def test_http_with_ssl_keywords(self):
        http = PoolManager(ca_certs='REQUIRED')
        self.addCleanup(http.clear)

        r = http.request('GET', 'http://%s:%s/' % (self.host, self.port))
        self.assertEqual(r.status, 200)

    def test_http_with_ca_cert_dir(self):
        http = PoolManager(ca_certs='REQUIRED', ca_cert_dir='/nosuchdir')
        self.addCleanup(http.clear)

        r = http.request('GET', 'http://%s:%s/' % (self.host, self.port))
        self.assertEqual(r.status, 200)


class TestIPv6PoolManager(IPv6HTTPDummyServerTestCase):
    if not HAS_IPV6:
        raise SkipTest("IPv6 is not supported on this system.")

    def setUp(self):
        self.base_url = 'http://[%s]:%d' % (self.host, self.port)

    def test_ipv6(self):
        http = PoolManager()
        self.addCleanup(http.clear)
        http.request('GET', self.base_url)


if __name__ == '__main__':
    unittest.main()
