import unittest
import json
import socket

from dummyserver.testcase import HTTPDummyProxyTestCase
from dummyserver.server import DEFAULT_CA, DEFAULT_CA_BAD

from urllib3.poolmanager import proxy_from_url, ProxyManager
from urllib3.exceptions import MaxRetryError, SSLError, ProxyError
from urllib3.connectionpool import connection_from_url, VerifiedHTTPSConnection


class TestHTTPProxyManager(HTTPDummyProxyTestCase):

    def setUp(self):
        self.http_url = 'http://%s:%d' % (self.http_host, self.http_port)
        self.http_url_alt = 'http://%s:%d' % (self.http_host_alt,
                                              self.http_port)
        self.https_url = 'https://%s:%d' % (self.https_host, self.https_port)
        self.https_url_alt = 'https://%s:%d' % (self.https_host_alt,
                                                self.https_port)
        self.proxy_url = 'http://%s:%d' % (self.proxy_host, self.proxy_port)

    def test_basic_proxy(self):
        http = proxy_from_url(self.proxy_url)

        r = http.request('GET', '%s/' % self.http_url)
        self.assertEqual(r.status, 200)

        r = http.request('GET', '%s/' % self.https_url)
        self.assertEqual(r.status, 200)

    def test_nagle_proxy(self):
        """ Test that proxy connections do not have TCP_NODELAY turned on """
        http = proxy_from_url(self.proxy_url)
        hc2 = http.connection_from_host(self.http_host, self.http_port)
        conn = hc2._get_conn()
        hc2._make_request(conn, 'GET', '/')
        tcp_nodelay_setting = conn.sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
        self.assertEqual(tcp_nodelay_setting, 0,
                         ("Expected TCP_NODELAY for proxies to be set "
                          "to zero, instead was %s" % tcp_nodelay_setting))

    def test_proxy_conn_fail(self):
        # Get a free port on localhost, so a connection will be refused
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        free_port = s.getsockname()[1]
        s.close()

        http = proxy_from_url('http://127.0.0.1:%s/' % free_port)
        self.assertRaises(ProxyError, http.request, 'GET',
                          '%s/' % self.https_url)
        self.assertRaises(ProxyError, http.request, 'GET',
                          '%s/' % self.http_url)

    def test_oldapi(self):
        http = ProxyManager(connection_from_url(self.proxy_url))

        r = http.request('GET', '%s/' % self.http_url)
        self.assertEqual(r.status, 200)

        r = http.request('GET', '%s/' % self.https_url)
        self.assertEqual(r.status, 200)

    def test_proxy_verified(self):
        http = proxy_from_url(self.proxy_url, cert_reqs='REQUIRED',
                              ca_certs=DEFAULT_CA_BAD)
        https_pool = http._new_pool('https', self.https_host,
                                    self.https_port)
        try:
            https_pool.request('GET', '/')
            self.fail("Didn't raise SSL error with wrong CA")
        except SSLError as e:
            self.assertTrue('certificate verify failed' in str(e),
                            "Expected 'certificate verify failed',"
                            "instead got: %r" % e)

        http = proxy_from_url(self.proxy_url, cert_reqs='REQUIRED',
                              ca_certs=DEFAULT_CA)
        https_pool = http._new_pool('https', self.https_host,
                                    self.https_port)

        conn = https_pool._new_conn()
        self.assertEqual(conn.__class__, VerifiedHTTPSConnection)
        https_pool.request('GET', '/')  # Should succeed without exceptions.

        http = proxy_from_url(self.proxy_url, cert_reqs='REQUIRED',
                              ca_certs=DEFAULT_CA)
        https_fail_pool = http._new_pool('https', '127.0.0.1', self.https_port)

        try:
            https_fail_pool.request('GET', '/')
            self.fail("Didn't raise SSL invalid common name")
        except SSLError as e:
            self.assertTrue("doesn't match" in str(e))

    def test_redirect(self):
        http = proxy_from_url(self.proxy_url)

        r = http.request('GET', '%s/redirect' % self.http_url,
                         fields={'target': '%s/' % self.http_url},
                         redirect=False)

        self.assertEqual(r.status, 303)

        r = http.request('GET', '%s/redirect' % self.http_url,
                         fields={'target': '%s/' % self.http_url})

        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'Dummy server!')

    def test_cross_host_redirect(self):
        http = proxy_from_url(self.proxy_url)

        cross_host_location = '%s/echo?a=b' % self.http_url_alt
        try:
            http.request('GET', '%s/redirect' % self.http_url,
                         fields={'target': cross_host_location},
                         timeout=0.1, retries=0)
            self.fail("We don't want to follow redirects here.")

        except MaxRetryError:
            pass

        r = http.request('GET', '%s/redirect' % self.http_url,
                         fields={'target': '%s/echo?a=b' % self.http_url_alt},
                         timeout=0.1, retries=1)
        self.assertNotEqual(r._pool.host, self.http_host_alt)

    def test_cross_protocol_redirect(self):
        http = proxy_from_url(self.proxy_url)

        cross_protocol_location = '%s/echo?a=b' % self.https_url
        try:
            http.request('GET', '%s/redirect' % self.http_url,
                         fields={'target': cross_protocol_location},
                         timeout=0.1, retries=0)
            self.fail("We don't want to follow redirects here.")

        except MaxRetryError:
            pass

        r = http.request('GET', '%s/redirect' % self.http_url,
                         fields={'target': '%s/echo?a=b' % self.https_url},
                         timeout=0.1, retries=1)
        self.assertEqual(r._pool.host, self.https_host)

    def test_headers(self):
        http = proxy_from_url(self.proxy_url,headers={'Foo': 'bar'},
                proxy_headers={'Hickory': 'dickory'})

        r = http.request_encode_url('GET', '%s/headers' % self.http_url)
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), 'bar')
        self.assertEqual(returned_headers.get('Hickory'), 'dickory')
        self.assertEqual(returned_headers.get('Host'),
                '%s:%s'%(self.http_host,self.http_port))

        r = http.request_encode_url('GET', '%s/headers' % self.http_url_alt)
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), 'bar')
        self.assertEqual(returned_headers.get('Hickory'), 'dickory')
        self.assertEqual(returned_headers.get('Host'),
                '%s:%s'%(self.http_host_alt,self.http_port))

        r = http.request_encode_url('GET', '%s/headers' % self.https_url)
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), 'bar')
        self.assertEqual(returned_headers.get('Hickory'), None)
        self.assertEqual(returned_headers.get('Host'),
                '%s:%s'%(self.https_host,self.https_port))

        r = http.request_encode_url('GET', '%s/headers' % self.https_url_alt)
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), 'bar')
        self.assertEqual(returned_headers.get('Hickory'), None)
        self.assertEqual(returned_headers.get('Host'),
                '%s:%s'%(self.https_host_alt,self.https_port))

        r = http.request_encode_body('POST', '%s/headers' % self.http_url)
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), 'bar')
        self.assertEqual(returned_headers.get('Hickory'), 'dickory')
        self.assertEqual(returned_headers.get('Host'),
                '%s:%s'%(self.http_host,self.http_port))

        r = http.request_encode_url('GET', '%s/headers' % self.http_url, headers={'Baz': 'quux'})
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), None)
        self.assertEqual(returned_headers.get('Baz'), 'quux')
        self.assertEqual(returned_headers.get('Hickory'), 'dickory')
        self.assertEqual(returned_headers.get('Host'),
                '%s:%s'%(self.http_host,self.http_port))

        r = http.request_encode_url('GET', '%s/headers' % self.https_url, headers={'Baz': 'quux'})
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), None)
        self.assertEqual(returned_headers.get('Baz'), 'quux')
        self.assertEqual(returned_headers.get('Hickory'), None)
        self.assertEqual(returned_headers.get('Host'),
                '%s:%s'%(self.https_host,self.https_port))

        r = http.request_encode_body('GET', '%s/headers' % self.http_url, headers={'Baz': 'quux'})
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), None)
        self.assertEqual(returned_headers.get('Baz'), 'quux')
        self.assertEqual(returned_headers.get('Hickory'), 'dickory')
        self.assertEqual(returned_headers.get('Host'),
                '%s:%s'%(self.http_host,self.http_port))

        r = http.request_encode_body('GET', '%s/headers' % self.https_url, headers={'Baz': 'quux'})
        returned_headers = json.loads(r.data.decode())
        self.assertEqual(returned_headers.get('Foo'), None)
        self.assertEqual(returned_headers.get('Baz'), 'quux')
        self.assertEqual(returned_headers.get('Hickory'), None)
        self.assertEqual(returned_headers.get('Host'),
                '%s:%s'%(self.https_host,self.https_port))

    def test_proxy_pooling(self):
        http = proxy_from_url(self.proxy_url)

        for x in range(2):
            r = http.urlopen('GET', self.http_url)
        self.assertEqual(len(http.pools), 1)

        for x in range(2):
            r = http.urlopen('GET', self.http_url_alt)
        self.assertEqual(len(http.pools), 1)

        for x in range(2):
            r = http.urlopen('GET', self.https_url)
        self.assertEqual(len(http.pools), 2)

        for x in range(2):
            r = http.urlopen('GET', self.https_url_alt)
        self.assertEqual(len(http.pools), 3)

    def test_proxy_pooling_ext(self):
        http = proxy_from_url(self.proxy_url)
        hc1 = http.connection_from_url(self.http_url)
        hc2 = http.connection_from_host(self.http_host, self.http_port)
        hc3 = http.connection_from_url(self.http_url_alt)
        hc4 = http.connection_from_host(self.http_host_alt, self.http_port)
        self.assertEqual(hc1,hc2)
        self.assertEqual(hc2,hc3)
        self.assertEqual(hc3,hc4)

        sc1 = http.connection_from_url(self.https_url)
        sc2 = http.connection_from_host(self.https_host,
                self.https_port,scheme='https')
        sc3 = http.connection_from_url(self.https_url_alt)
        sc4 = http.connection_from_host(self.https_host_alt,
                self.https_port,scheme='https')
        self.assertEqual(sc1,sc2)
        self.assertNotEqual(sc2,sc3)
        self.assertEqual(sc3,sc4)


if __name__ == '__main__':
    unittest.main()
