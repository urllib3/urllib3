import logging
import sys
import unittest

import mock
from nose.plugins.skip import SkipTest

from dummyserver.testcase import HTTPSDummyServerTestCase
from dummyserver.server import DEFAULT_CA, DEFAULT_CA_BAD, DEFAULT_CERTS

from test import base_ssl, backports_ssl, multi_ssl, requires_network

from urllib3 import HTTPSConnectionPool
import urllib3.connection
from urllib3.connection import (
    VerifiedHTTPSConnection,
    UnverifiedHTTPSConnection,
)
from urllib3.exceptions import SSLError, ConnectTimeoutError, ReadTimeoutError
from urllib3.util import Timeout


log = logging.getLogger('urllib3.connectionpool')
log.setLevel(logging.NOTSET)
log.addHandler(logging.StreamHandler(sys.stdout))

# We need a host that will not immediately close the connection with a TCP
# Reset. SO suggests this hostname
TARPIT_HOST = '10.255.255.1'

@multi_ssl()
class TestHTTPS(HTTPSDummyServerTestCase):
    def setUp(self):
        self._pool = HTTPSConnectionPool(self.host, self.port, ssl=self.ssl)

    def test_simple(self):
        r = self._pool.request('GET', '/')
        self.assertEqual(r.status, 200, r.data)

    def test_set_ssl_version_to_tlsv1(self):
        self._pool.ssl_version = self.ssl.PROTOCOL_TLSv1
        r = self._pool.request('GET', '/')
        self.assertEqual(r.status, 200, r.data)

    def test_verified(self):
        if not hasattr(self.ssl, 'match_hostname'):
            raise SkipTest('match_hostname() not found in SSL implementation')

        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ssl=self.ssl)

        conn = https_pool._new_conn()
        self.assertEqual(conn.__class__, VerifiedHTTPSConnection)

        self.assertRaises(SSLError, https_pool.request, 'GET', '/')

        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ssl=self.ssl)

        https_pool.ca_certs = DEFAULT_CA_BAD

        try:
            https_pool.request('GET', '/')
            self.fail("Didn't raise SSL error with wrong CA")
        except SSLError as e:
            self.assertTrue('certificate verify failed' in str(e),
                            "Expected 'certificate verify failed',"
                            "instead got: %r" % e)

        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ssl=self.ssl)

        https_pool.ca_certs = DEFAULT_CA
        https_pool.request('GET', '/')  # Should succeed without exceptions.

        https_fail_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                              cert_reqs='CERT_REQUIRED',
                                              ssl=self.ssl)
        https_fail_pool.ca_certs = DEFAULT_CA

        try:
            https_fail_pool.request('GET', '/')
            self.fail("Didn't raise SSL invalid common name")
        except SSLError as e:
            self.assertTrue("doesn't match" in str(e))

    def test_no_ssl(self):
        OriginalConnectionCls = self._pool.ConnectionCls
        try:
            self._pool.ConnectionCls = None

            self.assertRaises(SSLError, self._pool._new_conn)
            self.assertRaises(SSLError, self._pool.request, 'GET', '/')

        finally:
            self._pool.ConnectionCls = OriginalConnectionCls

    def test_unverified_ssl(self):
        """ Test that bare HTTPSConnection can connect, make requests """
        try:
            OriginalConnectionCls = self._pool.ConnectionCls
            self._pool.ConnectionCls = UnverifiedHTTPSConnection
            self._pool.request('GET', '/')

        finally:
            self._pool.ConnectionCls = OriginalConnectionCls

    def test_cert_reqs_as_constant(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs=self.ssl.CERT_REQUIRED,
                                         ssl=self.ssl)

        https_pool.ca_certs = DEFAULT_CA_BAD
        # if we pass in an invalid value it defaults to CERT_NONE
        self.assertRaises(SSLError, https_pool.request, 'GET', '/')

    def test_cert_reqs_as_short_string(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='REQUIRED',
                                         ssl=self.ssl)

        https_pool.ca_certs = DEFAULT_CA_BAD
        # if we pass in an invalid value it defaults to CERT_NONE
        self.assertRaises(SSLError, https_pool.request, 'GET', '/')

    def test_ssl_unverified_with_ca_certs(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_NONE',
                                         ssl=self.ssl)

        https_pool.ca_certs = DEFAULT_CA_BAD
        https_pool.request('GET', '/')

    def test_verified_without_ca_certs(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ssl=self.ssl)

        self.assertRaises(SSLError, https_pool.request, 'GET', '/')

    def test_invalid_ca_certs(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ssl=self.ssl)

        # Empty string won't throw on py2
        https_pool.ca_certs = '/no_valid_path_to_ca_certs'

        self.assertRaises(SSLError, https_pool.request, 'GET', '/')

    def test_assert_hostname_false(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ssl=self.ssl)

        https_pool.ca_certs = DEFAULT_CA
        https_pool.assert_hostname = False
        https_pool.request('GET', '/')

    def test_assert_specific_hostname(self):
        if not hasattr(self.ssl, 'match_hostname'):
            raise SkipTest('match_hostname() not found in SSL implementation')

        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ssl=self.ssl)

        https_pool.ca_certs = DEFAULT_CA
        https_pool.assert_hostname = 'localhost'
        https_pool.request('GET', '/')

    def test_assert_fingerprint_md5(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ssl=self.ssl)

        https_pool.ca_certs = DEFAULT_CA
        https_pool.assert_fingerprint = 'CA:84:E1:AD0E5a:ef:2f:C3:09' \
                                        ':E7:30:F8:CD:C8:5B'
        https_pool.request('GET', '/')

    def test_assert_fingerprint_sha1(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ssl=self.ssl)

        https_pool.ca_certs = DEFAULT_CA
        https_pool.assert_fingerprint = 'CC:45:6A:90:82:F7FF:C0:8218:8e:' \
                                        '7A:F2:8A:D7:1E:07:33:67:DE'
        https_pool.request('GET', '/')

    def test_assert_invalid_fingerprint(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ssl=self.ssl)

        https_pool.ca_certs = DEFAULT_CA
        https_pool.assert_fingerprint = 'AA:AA:AA:AA:AA:AAAA:AA:AAAA:AA:' \
                                        'AA:AA:AA:AA:AA:AA:AA:AA:AA'

        self.assertRaises(SSLError, https_pool.request, 'GET', '/')

        # invalid length
        https_pool.assert_fingerprint = 'AA'

        self.assertRaises(SSLError, https_pool.request, 'GET', '/')

        # uneven length
        https_pool.assert_fingerprint = 'AA:A'

        self.assertRaises(SSLError, https_pool.request, 'GET', '/')

    @requires_network
    def test_https_timeout(self):
        timeout = Timeout(connect=0.001)
        https_pool = HTTPSConnectionPool(TARPIT_HOST, self.port,
                                         timeout=timeout,
                                         cert_reqs='CERT_REQUIRED',
                                         ssl=self.ssl)

        timeout = Timeout(total=None, connect=0.001)
        https_pool = HTTPSConnectionPool(TARPIT_HOST, self.port,
                                         timeout=timeout,
                                         cert_reqs='CERT_REQUIRED',
                                         ssl=self.ssl)
        self.assertRaises(ConnectTimeoutError, https_pool.request, 'GET', '/')

        timeout = Timeout(read=0.001)
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         timeout=timeout,
                                         cert_reqs='CERT_REQUIRED',
                                         ssl=self.ssl)
        https_pool.ca_certs = DEFAULT_CA
        https_pool.assert_fingerprint = 'CC:45:6A:90:82:F7FF:C0:8218:8e:' \
                                        '7A:F2:8A:D7:1E:07:33:67:DE'
        url = '/sleep?seconds=0.005'
        self.assertRaises(ReadTimeoutError, https_pool.request, 'GET', url)

        timeout = Timeout(total=None)
        https_pool = HTTPSConnectionPool(self.host, self.port, timeout=timeout,
                                         cert_reqs='CERT_NONE',
                                         ssl=self.ssl)
        https_pool.request('GET', '/')


    def test_tunnel(self):
        """ test the _tunnel behavior """
        timeout = Timeout(total=None)
        https_pool = HTTPSConnectionPool(self.host, self.port, timeout=timeout,
                                         cert_reqs='CERT_NONE',
                                         ssl=self.ssl)
        conn = https_pool._new_conn()
        try:
            conn.set_tunnel(self.host, self.port)
        except AttributeError: # python 2.6
            conn._set_tunnel(self.host, self.port)
        conn._tunnel = mock.Mock()
        https_pool._make_request(conn, 'GET', '/')
        conn._tunnel.assert_called_once_with()


    def test_tunnel_old_python(self):
        """HTTPSConnection can still make connections if _tunnel_host isn't set

        The _tunnel_host attribute was added in 2.6.3 - because our test runners
        generally use the latest Python 2.6, we simulate the old version by
        deleting the attribute from the HTTPSConnection.
        """
        conn = self._pool._new_conn()
        del conn._tunnel_host
        self._pool._make_request(conn, 'GET', '/')


    @requires_network
    def test_enhanced_timeout(self):
        def new_pool(timeout, cert_reqs='CERT_REQUIRED'):
            https_pool = HTTPSConnectionPool(TARPIT_HOST, self.port,
                                             timeout=timeout,
                                             cert_reqs=cert_reqs,
                                             ssl=self.ssl)
            return https_pool

        https_pool = new_pool(Timeout(connect=0.001))
        conn = https_pool._new_conn()
        self.assertRaises(ConnectTimeoutError, https_pool.request, 'GET', '/')
        self.assertRaises(ConnectTimeoutError, https_pool._make_request, conn,
                          'GET', '/')

        https_pool = new_pool(Timeout(connect=5))
        self.assertRaises(ConnectTimeoutError, https_pool.request, 'GET', '/',
                          timeout=Timeout(connect=0.001))

        t = Timeout(total=None)
        https_pool = new_pool(t)
        conn = https_pool._new_conn()
        self.assertRaises(ConnectTimeoutError, https_pool.request, 'GET', '/',
                          timeout=Timeout(total=None, connect=0.001))

    def test_enhanced_ssl_connection(self):
        conn = VerifiedHTTPSConnection(self.host, self.port, ssl=self.ssl)
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         timeout=Timeout(total=None, connect=5),
                                         cert_reqs='CERT_REQUIRED',
                                         ssl=self.ssl)
        https_pool.ca_certs = DEFAULT_CA
        https_pool.assert_fingerprint = 'CC:45:6A:90:82:F7FF:C0:8218:8e:' \
                                        '7A:F2:8A:D7:1E:07:33:67:DE'
        https_pool._make_request(conn, 'GET', '/')


TestHTTPS_BaseSSL, TestHTTPS_BackportsSSL = TestHTTPS.ssl_impls


class TestHTTPS_PlatformCerts(HTTPSDummyServerTestCase):
    @requires_network
    def test_ssl_verified_with_platform_ca_certs(self):
        """
        We should rely on the platform CA file to validate authenticity of SSL
        certificates. Since this file is used by many components of the OS,
        such as curl, apt-get, etc., we decided to not touch it, in order to
        not compromise the security of the OS running the test suite (typically
        urllib3 developer's OS).

        This test assumes that httpbin.org uses a certificate signed by a well
        known Certificate Authority.
        """
        if not hasattr(backports_ssl, 'wrap_socket'):
            raise SkipTest('SSL implementation unavailable')

        https_pool = HTTPSConnectionPool('httpbin.org', 443,
                                         cert_reqs=backports_ssl.CERT_REQUIRED,
                                         ssl=backports_ssl)

        https_pool.request('HEAD', '/')


@multi_ssl()
class TestHTTPS_TLSv1(HTTPSDummyServerTestCase):
    certs = DEFAULT_CERTS.copy()

    def setUp(self):
        self._pool = HTTPSConnectionPool(self.host, self.port, ssl=self.ssl)
        self.certs['ssl_version'] = base_ssl.PROTOCOL_TLSv1

    def test_set_ssl_version_to_sslv3(self):
        self._pool.ssl_version = self.ssl.PROTOCOL_SSLv3
        self.assertRaises(SSLError, self._pool.request, 'GET', '/')

    def test_ssl_version_as_string(self):
        self._pool.ssl_version = 'PROTOCOL_SSLv3'
        self.assertRaises(SSLError, self._pool.request, 'GET', '/')

    def test_ssl_version_as_short_string(self):
        self._pool.ssl_version = 'SSLv3'
        self.assertRaises(SSLError, self._pool.request, 'GET', '/')


TestHTTPS_TLSv1_BaseSSL, TestHTTPS_TLSv1_BackportsSSL = \
    TestHTTPS_TLSv1.ssl_impls


if __name__ == '__main__':
    unittest.main()
