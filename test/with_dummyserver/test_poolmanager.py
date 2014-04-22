import unittest
import json
import warnings

from urllib3.packages.six import b
from dummyserver.testcase import (HTTPDummyServerTestCase,
                                  IPv6HTTPDummyServerTestCase)
from urllib3.poolmanager import PoolManager
from urllib3.connectionpool import port_by_scheme
from urllib3.exceptions import  SSLError, MaxRetryError, PythonVersionWarning
from test import (
    onlyPy27OrNewer, onlyPy26OrOlder, VALID_SOURCE_ADDRESSES,
    INVALID_SOURCE_ADDRESSES)

class TestPoolManager(HTTPDummyServerTestCase):

    def setUp(self):
        self.base_url = 'http://%s:%d' % (self.host, self.port)
        self.base_url_alt = 'http://%s:%d' % (self.host_alt, self.port)
        self.source_address_url = (
            'http://%s:%s/source_address' % (self.host, self.port))

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

    def test_redirect_twice(self):
        http = PoolManager()

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/redirect' % self.base_url},
                         redirect=False)

        self.assertEqual(r.status, 303)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/redirect?target=%s/' % (self.base_url, self.base_url)})

        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Dummy server!')

    def test_redirect_to_relative_url(self):
        http = PoolManager()

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields = {'target': '/redirect'},
                         redirect = False)

        self.assertEqual(r.status, 303)

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields = {'target': '/redirect'})

        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Dummy server!')

    def test_cross_host_redirect(self):
        http = PoolManager()

        cross_host_location = '%s/echo?a=b' % self.base_url_alt
        try:
            http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': cross_host_location},
                         timeout=0.01, retries=0)
            self.fail("Request succeeded instead of raising an exception like it should.")

        except MaxRetryError:
            pass

        r = http.request('GET', '%s/redirect' % self.base_url,
                         fields={'target': '%s/echo?a=b' % self.base_url_alt},
                         timeout=0.01, retries=1)

        self.assertEqual(r._pool.host, self.host_alt)

    def test_missing_port(self):
        # Can a URL that lacks an explicit port like ':80' succeed, or
        # will all such URLs fail with an error?

        http = PoolManager()

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

        r = http.request('GET', 'http://%s:%s/' % (self.host, self.port))
        self.assertEqual(r.status, 200)

    @onlyPy26OrOlder
    def test_source_address_ignored(self):
        # No warning is issued if source_address is omitted.
        http = PoolManager()
        with warnings.catch_warnings(record=True) as w:
            r = http.request('GET', self.source_address_url)
            assert r.status == 200
            assert (
                not w or not issubclass(w[-1].category, PythonVersionWarning))

        # source_address is ignored in Python 2.6 and older. Warning issued.
        http = PoolManager()
        with warnings.catch_warnings(record=True) as w:
            for addr in INVALID_SOURCE_ADDRESSES:
                r = http.request(
                    'GET', self.source_address_url, source_address=addr)
                assert r.status == 200
            assert issubclass(w[-1].category, PythonVersionWarning)
        assert len(http.pools) == 1

        with warnings.catch_warnings(record=True) as w:
            http = PoolManager(source_address=INVALID_SOURCE_ADDRESSES[0])
            r = http.request(
                'GET', self.source_address_url, source_address=addr)
            assert r.status == 200
            assert issubclass(w[-1].category, PythonVersionWarning)

    @onlyPy27OrNewer
    def test_request_source_address(self):
        http = PoolManager()
        for addr in VALID_SOURCE_ADDRESSES:
            r = http.request(
                'GET', self.source_address_url, source_address=addr)
            assert r.data == b(addr[0])

        num_pools = len(http.pools)
        assert num_pools == len(VALID_SOURCE_ADDRESSES)
        
        # ConnectionPools are reused.
        pool1 = http.connection_from_url(
            self.source_address_url, source_address=VALID_SOURCE_ADDRESSES[0])
        pool2 = http.connection_from_url(
            self.source_address_url, source_address=VALID_SOURCE_ADDRESSES[0])
        pool3 = http.connection_from_url(
            self.source_address_url, source_address=VALID_SOURCE_ADDRESSES[1])
        assert pool1 == pool2 and pool2 != pool3

        # An omitted source_address counts as a unique source_address.
        r = http.request('GET', self.source_address_url)
        assert r.status == 200 and len(http.pools) == num_pools + 1

    @onlyPy27OrNewer
    def test_constructor_source_address(self):
        # Requests default to the constructor's optional source_address.
        for addr in VALID_SOURCE_ADDRESSES:
            http = PoolManager(source_address=addr)
            
            r = http.request('GET', self.source_address_url)
            assert r.data == b(addr[0])
            
            remaining = list(VALID_SOURCE_ADDRESSES)
            remaining.remove(addr)
            for remaddr in remaining:
                r = http.request(
                    'GET', self.source_address_url, source_address=remaddr)
                assert r.data == b(remaddr[0])
            assert len(http.pools) == len(VALID_SOURCE_ADDRESSES)


class TestIPv6PoolManager(IPv6HTTPDummyServerTestCase):
    def setUp(self):
        self.base_url = 'http://[%s]:%d' % (self.host, self.port)

    def test_ipv6(self):
        http = PoolManager()
        http.request('GET', self.base_url)

if __name__ == '__main__':
    unittest.main()
