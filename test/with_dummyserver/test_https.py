try: # Python 3
    from http.client import HTTPSConnection
except ImportError:
    from httplib import HTTPSConnection
import logging
import ssl
import sys
import unittest

import mock

from dummyserver.testcase import HTTPSDummyServerTestCase
from dummyserver.server import DEFAULT_CA, DEFAULT_CA_BAD, DEFAULT_CERTS

from urllib3 import HTTPSConnectionPool
from urllib3.connectionpool import VerifiedHTTPSConnection
from urllib3.exceptions import SSLError, ConnectTimeoutError, ReadTimeoutError
from urllib3.util import Timeout


log = logging.getLogger('urllib3.connectionpool')
log.setLevel(logging.NOTSET)
log.addHandler(logging.StreamHandler(sys.stdout))

# We need a host that will not immediately close the connection with a TCP
# Reset. SO suggests this hostname
TARPIT_HOST = '10.255.255.1'

class TestHTTPS(HTTPSDummyServerTestCase):
    def setUp(self):
        self._pool = HTTPSConnectionPool(self.host, self.port)

    def test_simple(self):
        r = self._pool.request('GET', '/')
        self.assertEqual(r.status, 200, r.data)

    def test_set_ssl_version_to_tlsv1(self):
        self._pool.ssl_version = ssl.PROTOCOL_TLSv1
        r = self._pool.request('GET', '/')
        self.assertEqual(r.status, 200, r.data)

    def test_verified(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED')

        conn = https_pool._new_conn()
        self.assertEqual(conn.__class__, VerifiedHTTPSConnection)

        self.assertRaises(SSLError, https_pool.request, 'GET', '/')

        https_pool.ca_certs = DEFAULT_CA_BAD

        try:
            https_pool.request('GET', '/')
            self.fail("Didn't raise SSL error with wrong CA")
        except SSLError as e:
            self.assertTrue('certificate verify failed' in str(e),
                            "Expected 'certificate verify failed',"
                            "instead got: %r" % e)

        https_pool.ca_certs = DEFAULT_CA
        https_pool.request('GET', '/')  # Should succeed without exceptions.

        https_fail_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                              cert_reqs='CERT_REQUIRED')
        https_fail_pool.ca_certs = DEFAULT_CA

        try:
            https_fail_pool.request('GET', '/')
            self.fail("Didn't raise SSL invalid common name")
        except SSLError as e:
            self.assertTrue("doesn't match" in str(e))

    def test_no_ssl(self):
        import urllib3.connectionpool
        OriginalHTTPSConnection = urllib3.connectionpool.HTTPSConnection
        OriginalSSL = urllib3.connectionpool.ssl

        urllib3.connectionpool.HTTPSConnection = None
        urllib3.connectionpool.ssl = None

        self.assertRaises(SSLError, self._pool._new_conn)

        self.assertRaises(SSLError, self._pool.request, 'GET', '/')

        # Undo
        urllib3.HTTPSConnection = OriginalHTTPSConnection
        urllib3.connectionpool.ssl = OriginalSSL

    def test_cert_reqs_as_constant(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs=ssl.CERT_REQUIRED)

        https_pool.ca_certs = DEFAULT_CA_BAD
        # if we pass in an invalid value it defaults to CERT_NONE
        self.assertRaises(SSLError, https_pool.request, 'GET', '/')

    def test_cert_reqs_as_short_string(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='REQUIRED')

        https_pool.ca_certs = DEFAULT_CA_BAD
        # if we pass in an invalid value it defaults to CERT_NONE
        self.assertRaises(SSLError, https_pool.request, 'GET', '/')

    def test_ssl_unverified_with_ca_certs(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_NONE')

        https_pool.ca_certs = DEFAULT_CA_BAD
        https_pool.request('GET', '/')

    def test_verified_without_ca_certs(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED')

        self.assertRaises(SSLError, https_pool.request, 'GET', '/')

    def test_invalid_ca_certs(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED')

        # Empty string won't throw on py2
        https_pool.ca_certs = '/no_valid_path_to_ca_certs'

        self.assertRaises(SSLError, https_pool.request, 'GET', '/')

    def test_assert_hostname_false(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED')

        https_pool.ca_certs = DEFAULT_CA
        https_pool.assert_hostname = False
        https_pool.request('GET', '/')

    def test_assert_specific_hostname(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED')

        https_pool.ca_certs = DEFAULT_CA
        https_pool.assert_hostname = 'localhost'
        https_pool.request('GET', '/')

    def test_assert_fingerprint_md5(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED')

        https_pool.ca_certs = DEFAULT_CA
        https_pool.assert_fingerprint = 'CA:84:E1:AD0E5a:ef:2f:C3:09' \
                                        ':E7:30:F8:CD:C8:5B'
        https_pool.request('GET', '/')

    def test_assert_fingerprint_sha1(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED')

        https_pool.ca_certs = DEFAULT_CA
        https_pool.assert_fingerprint = 'CC:45:6A:90:82:F7FF:C0:8218:8e:' \
                                        '7A:F2:8A:D7:1E:07:33:67:DE'
        https_pool.request('GET', '/')

    def test_assert_invalid_fingerprint(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED')

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

    def test_https_timeout(self):
        timeout = Timeout(connect=0.001)
        https_pool = HTTPSConnectionPool(TARPIT_HOST, self.port,
                                         timeout=timeout,
                                         cert_reqs='CERT_REQUIRED')

        timeout = Timeout(total=None, connect=0.001)
        https_pool = HTTPSConnectionPool(TARPIT_HOST, self.port,
                                         timeout=timeout,
                                         cert_reqs='CERT_REQUIRED')
        self.assertRaises(ConnectTimeoutError, https_pool.request, 'GET', '/')

        timeout = Timeout(read=0.001)
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         timeout=timeout,
                                         cert_reqs='CERT_REQUIRED')
        https_pool.ca_certs = DEFAULT_CA
        https_pool.assert_fingerprint = 'CC:45:6A:90:82:F7FF:C0:8218:8e:' \
                                        '7A:F2:8A:D7:1E:07:33:67:DE'
        url = '/sleep?seconds=0.005'
        self.assertRaises(ReadTimeoutError, https_pool.request, 'GET', url)

        timeout = Timeout(total=None)
        https_pool = HTTPSConnectionPool(self.host, self.port, timeout=timeout,
                                         cert_reqs='CERT_NONE')
        https_pool.request('GET', '/')


    def test_tunnel(self):
        """ test the _tunnel behavior """
        timeout = Timeout(total=None)
        https_pool = HTTPSConnectionPool(self.host, self.port, timeout=timeout,
                                         cert_reqs='CERT_NONE')
        conn = https_pool._new_conn()
        try:
            conn.set_tunnel(self.host, self.port)
        except AttributeError: # python 2.6
            conn._set_tunnel(self.host, self.port)
        conn._tunnel = mock.Mock()
        https_pool._make_request(conn, 'GET', '/')
        conn._tunnel.assert_called_once_with()


    def test_enhanced_timeout(self):
        import urllib3.connectionpool
        OriginalHTTPSConnection = urllib3.connectionpool.HTTPSConnection
        OriginalSSL = urllib3.connectionpool.ssl

        urllib3.connectionpool.ssl = None

        timeout = Timeout(connect=0.001)
        https_pool = HTTPSConnectionPool(TARPIT_HOST, self.port,
                                         timeout=timeout,
                                         cert_reqs='CERT_REQUIRED')
        conn = https_pool._new_conn()
        self.assertEqual(conn.__class__, HTTPSConnection)
        self.assertRaises(ConnectTimeoutError, https_pool.request, 'GET', '/')
        self.assertRaises(ConnectTimeoutError, https_pool._make_request, conn,
                          'GET', '/')

        timeout = Timeout(connect=5)
        https_pool = HTTPSConnectionPool(TARPIT_HOST, self.port,
                                         timeout=timeout,
                                         cert_reqs='CERT_REQUIRED')
        self.assertRaises(ConnectTimeoutError, https_pool.request, 'GET', '/',
                          timeout=Timeout(connect=0.001))

        timeout = Timeout(total=None)
        https_pool = HTTPSConnectionPool(TARPIT_HOST, self.port,
                                         timeout=timeout,
                                         cert_reqs='CERT_REQUIRED')
        conn = https_pool._new_conn()
        self.assertRaises(ConnectTimeoutError, https_pool.request, 'GET', '/',
                          timeout=Timeout(total=None, connect=0.001))

        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         timeout=timeout,
                                         cert_reqs='CERT_NONE')
        conn = https_pool._new_conn()
        try:
            conn.set_tunnel(self.host, self.port)
        except AttributeError: # python 2.6
            conn._set_tunnel(self.host, self.port)
        conn._tunnel = mock.Mock()
        try:
            https_pool._make_request(conn, 'GET', '/')
        except AttributeError:
            # wrap_socket unavailable when you mock out ssl
            pass
        conn._tunnel.assert_called_once_with()

        # Undo
        urllib3.HTTPSConnection = OriginalHTTPSConnection
        urllib3.connectionpool.ssl = OriginalSSL

    def test_enhanced_ssl_connection(self):
        conn = VerifiedHTTPSConnection(self.host, self.port)
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         timeout=Timeout(total=None, connect=5),
                                         cert_reqs='CERT_REQUIRED')
        https_pool.ca_certs = DEFAULT_CA
        https_pool.assert_fingerprint = 'CC:45:6A:90:82:F7FF:C0:8218:8e:' \
                                        '7A:F2:8A:D7:1E:07:33:67:DE'
        https_pool._make_request(conn, 'GET', '/')


class TestHTTPS_TLSv1(HTTPSDummyServerTestCase):
    certs = DEFAULT_CERTS.copy()
    certs['ssl_version'] = ssl.PROTOCOL_TLSv1

    def setUp(self):
        self._pool = HTTPSConnectionPool(self.host, self.port)

    def test_set_ssl_version_to_sslv3(self):
        self._pool.ssl_version = ssl.PROTOCOL_SSLv3
        self.assertRaises(SSLError, self._pool.request, 'GET', '/')

    def test_ssl_version_as_string(self):
        self._pool.ssl_version = 'PROTOCOL_SSLv3'
        self.assertRaises(SSLError, self._pool.request, 'GET', '/')

    def test_ssl_version_as_short_string(self):
        self._pool.ssl_version = 'SSLv3'
        self.assertRaises(SSLError, self._pool.request, 'GET', '/')


if __name__ == '__main__':
    unittest.main()
