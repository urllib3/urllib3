import datetime
import logging
import ssl
import sys
import unittest
import warnings

import mock
from nose.plugins.skip import SkipTest

from dummyserver.testcase import (
    HTTPSDummyServerTestCase, IPV6HTTPSDummyServerTestCase
)
from dummyserver.server import (DEFAULT_CA, DEFAULT_CA_BAD, DEFAULT_CERTS,
                                NO_SAN_CERTS, NO_SAN_CA, DEFAULT_CA_DIR,
                                IPV6_ADDR_CERTS, IPV6_ADDR_CA, HAS_IPV6)

from test import (
    onlyPy26OrOlder,
    onlyPy279OrNewer,
    requires_network,
    TARPIT_HOST,
    clear_warnings,
)
from urllib3 import HTTPSConnectionPool
from urllib3.connection import (
    VerifiedHTTPSConnection,
    UnverifiedHTTPSConnection,
    RECENT_DATE,
)
from urllib3.exceptions import (
    SSLError,
    ReadTimeoutError,
    ConnectTimeoutError,
    InsecureRequestWarning,
    SystemTimeWarning,
    InsecurePlatformWarning,
)
from urllib3.packages import six
from urllib3.util.timeout import Timeout
import urllib3.util as util


ResourceWarning = getattr(
        six.moves.builtins,
        'ResourceWarning', type('ResourceWarning', (), {}))


log = logging.getLogger('urllib3.connectionpool')
log.setLevel(logging.NOTSET)
log.addHandler(logging.StreamHandler(sys.stdout))



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
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)

        conn = https_pool._new_conn()
        self.assertEqual(conn.__class__, VerifiedHTTPSConnection)

        with mock.patch('warnings.warn') as warn:
            r = https_pool.request('GET', '/')
            self.assertEqual(r.status, 200)

            if sys.version_info >= (2, 7, 9) or util.IS_PYOPENSSL:
                self.assertFalse(warn.called, warn.call_args_list)
            else:
                self.assertTrue(warn.called)
                if util.HAS_SNI:
                    call = warn.call_args_list[0]
                else:
                    call = warn.call_args_list[1]
                error = call[0][1]
                self.assertEqual(error, InsecurePlatformWarning)

    @onlyPy279OrNewer
    def test_ca_dir_verified(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_cert_dir=DEFAULT_CA_DIR)

        conn = https_pool._new_conn()
        self.assertEqual(conn.__class__, VerifiedHTTPSConnection)

        with mock.patch('warnings.warn') as warn:
            r = https_pool.request('GET', '/')
            self.assertEqual(r.status, 200)

            if sys.version_info >= (2, 7, 9):
                self.assertFalse(warn.called, warn.call_args_list)
            else:
                self.assertTrue(warn.called)
                call, = warn.call_args_list
                error = call[0][1]
                self.assertEqual(error, InsecurePlatformWarning)

    def test_invalid_common_name(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)
        try:
            https_pool.request('GET', '/')
            self.fail("Didn't raise SSL invalid common name")
        except SSLError as e:
            self.assertTrue("doesn't match" in str(e))

    def test_verified_with_bad_ca_certs(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA_BAD)

        try:
            https_pool.request('GET', '/')
            self.fail("Didn't raise SSL error with bad CA certs")
        except SSLError as e:
            self.assertTrue('certificate verify failed' in str(e),
                            "Expected 'certificate verify failed',"
                            "instead got: %r" % e)

    def test_verified_without_ca_certs(self):
        # default is cert_reqs=None which is ssl.CERT_NONE
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED')

        try:
            https_pool.request('GET', '/')
            self.fail("Didn't raise SSL error with no CA certs when"
                      "CERT_REQUIRED is set")
        except SSLError as e:
            # there is a different error message depending on whether or
            # not pyopenssl is injected
            self.assertTrue('No root certificates specified' in str(e) or
                            'certificate verify failed' in str(e),
                            "Expected 'No root certificates specified' or "
                            "'certificate verify failed', "
                            "instead got: %r" % e)

    def test_no_ssl(self):
        pool = HTTPSConnectionPool(self.host, self.port)
        pool.ConnectionCls = None
        self.assertRaises(SSLError, pool._new_conn)
        self.assertRaises(SSLError, pool.request, 'GET', '/')

    def test_unverified_ssl(self):
        """ Test that bare HTTPSConnection can connect, make requests """
        pool = HTTPSConnectionPool(self.host, self.port)
        pool.ConnectionCls = UnverifiedHTTPSConnection

        with mock.patch('warnings.warn') as warn:
            r = pool.request('GET', '/')
            self.assertEqual(r.status, 200)
            self.assertTrue(warn.called)

            call, = warn.call_args_list
            category = call[0][1]
            self.assertEqual(category, InsecureRequestWarning)

    def test_ssl_unverified_with_ca_certs(self):
        pool = HTTPSConnectionPool(self.host, self.port,
                                   cert_reqs='CERT_NONE',
                                   ca_certs=DEFAULT_CA_BAD)

        with mock.patch('warnings.warn') as warn:
            r = pool.request('GET', '/')
            self.assertEqual(r.status, 200)
            self.assertTrue(warn.called)

            calls = warn.call_args_list
            if sys.version_info >= (2, 7, 9) or util.IS_PYOPENSSL:
                category = calls[0][0][1]
            elif util.HAS_SNI:
                category = calls[1][0][1]
            else:
                category = calls[2][0][1]
            self.assertEqual(category, InsecureRequestWarning)

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
        try:
            import urllib3.contrib.pyopenssl
        except ImportError:
            raise SkipTest('Test requires PyOpenSSL')
        if (urllib3.connection.ssl_wrap_socket is
                urllib3.contrib.pyopenssl.orig_connection_ssl_wrap_socket):
            # Not patched
            raise SkipTest('Test should only be run after PyOpenSSL '
                           'monkey patching')

        https_pool = HTTPSConnectionPool('httpbin.org', 443,
                                         cert_reqs=ssl.CERT_REQUIRED)

        https_pool.request('HEAD', '/')

    def test_assert_hostname_false(self):
        https_pool = HTTPSConnectionPool('localhost', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)

        https_pool.assert_hostname = False
        https_pool.request('GET', '/')

    def test_assert_specific_hostname(self):
        https_pool = HTTPSConnectionPool('localhost', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)

        https_pool.assert_hostname = 'localhost'
        https_pool.request('GET', '/')

    def test_assert_fingerprint_md5(self):
        https_pool = HTTPSConnectionPool('localhost', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)

        https_pool.assert_fingerprint = 'F2:06:5A:42:10:3F:45:1C:17:FE:E6:' \
                                        '07:1E:8A:86:E5'

        https_pool.request('GET', '/')

    def test_assert_fingerprint_sha1(self):
        https_pool = HTTPSConnectionPool('localhost', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)

        https_pool.assert_fingerprint = '92:81:FE:85:F7:0C:26:60:EC:D6:B3:' \
                                        'BF:93:CF:F9:71:CC:07:7D:0A'
        https_pool.request('GET', '/')

    def test_assert_fingerprint_sha256(self):
        https_pool = HTTPSConnectionPool('localhost', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)

        https_pool.assert_fingerprint = ('C5:4D:0B:83:84:89:2E:AE:B4:58:BB:12:'
                                         'F7:A6:C4:76:05:03:88:D8:57:65:51:F3:'
                                         '1E:60:B0:8B:70:18:64:E6')
        https_pool.request('GET', '/')

    def test_assert_invalid_fingerprint(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)

        https_pool.assert_fingerprint = 'AA:AA:AA:AA:AA:AAAA:AA:AAAA:AA:' \
                                        'AA:AA:AA:AA:AA:AA:AA:AA:AA'

        self.assertRaises(SSLError, https_pool.request, 'GET', '/')
        https_pool._get_conn()

        # Uneven length
        https_pool.assert_fingerprint = 'AA:A'
        self.assertRaises(SSLError, https_pool.request, 'GET', '/')
        https_pool._get_conn()

        # Invalid length
        https_pool.assert_fingerprint = 'AA'
        self.assertRaises(SSLError, https_pool.request, 'GET', '/')

    def test_verify_none_and_bad_fingerprint(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_NONE',
                                         ca_certs=DEFAULT_CA_BAD)

        https_pool.assert_fingerprint = 'AA:AA:AA:AA:AA:AAAA:AA:AAAA:AA:' \
                                        'AA:AA:AA:AA:AA:AA:AA:AA:AA'
        self.assertRaises(SSLError, https_pool.request, 'GET', '/')

    def test_verify_none_and_good_fingerprint(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_NONE',
                                         ca_certs=DEFAULT_CA_BAD)

        https_pool.assert_fingerprint = '92:81:FE:85:F7:0C:26:60:EC:D6:B3:' \
                                        'BF:93:CF:F9:71:CC:07:7D:0A'
        https_pool.request('GET', '/')

    def test_good_fingerprint_and_hostname_mismatch(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)

        https_pool.assert_fingerprint = '92:81:FE:85:F7:0C:26:60:EC:D6:B3:' \
                                        'BF:93:CF:F9:71:CC:07:7D:0A'
        https_pool.request('GET', '/')

    @requires_network
    def test_https_timeout(self):
        timeout = Timeout(connect=0.001)
        https_pool = HTTPSConnectionPool(TARPIT_HOST, self.port,
                                         timeout=timeout, retries=False,
                                         cert_reqs='CERT_REQUIRED')

        timeout = Timeout(total=None, connect=0.001)
        https_pool = HTTPSConnectionPool(TARPIT_HOST, self.port,
                                         timeout=timeout, retries=False,
                                         cert_reqs='CERT_REQUIRED')
        self.assertRaises(ConnectTimeoutError, https_pool.request, 'GET', '/')

        timeout = Timeout(read=0.001)
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         timeout=timeout, retries=False,
                                         cert_reqs='CERT_REQUIRED')
        https_pool.ca_certs = DEFAULT_CA
        https_pool.assert_fingerprint = '92:81:FE:85:F7:0C:26:60:EC:D6:B3:' \
                                        'BF:93:CF:F9:71:CC:07:7D:0A'

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

    @onlyPy26OrOlder
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
                                             retries=False,
                                             cert_reqs=cert_reqs)
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
        fingerprint = '92:81:FE:85:F7:0C:26:60:EC:D6:B3:BF:93:CF:F9:71:CC:07:7D:0A'

        conn = VerifiedHTTPSConnection(self.host, self.port)
        https_pool = HTTPSConnectionPool(self.host, self.port,
                cert_reqs='CERT_REQUIRED', ca_certs=DEFAULT_CA,
                assert_fingerprint=fingerprint)

        https_pool._make_request(conn, 'GET', '/')

    def test_ssl_correct_system_time(self):
        self._pool.cert_reqs = 'CERT_REQUIRED'
        self._pool.ca_certs = DEFAULT_CA

        w = self._request_without_resource_warnings('GET', '/')
        self.assertEqual([], w)

    def test_ssl_wrong_system_time(self):
        self._pool.cert_reqs = 'CERT_REQUIRED'
        self._pool.ca_certs = DEFAULT_CA
        with mock.patch('urllib3.connection.datetime') as mock_date:
            mock_date.date.today.return_value = datetime.date(1970, 1, 1)

            w = self._request_without_resource_warnings('GET', '/')

            self.assertEqual(len(w), 1)
            warning = w[0]

            self.assertEqual(SystemTimeWarning, warning.category)
            self.assertTrue(str(RECENT_DATE) in warning.message.args[0])

    def _request_without_resource_warnings(self, method, url):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            self._pool.request(method, url)

        return [x for x in w if not isinstance(x.message, ResourceWarning)]


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

    def test_discards_connection_on_sslerror(self):
        self._pool.cert_reqs = 'CERT_REQUIRED'
        self.assertRaises(SSLError, self._pool.request, 'GET', '/')
        self._pool.ca_certs = DEFAULT_CA
        self._pool.request('GET', '/')

    def test_set_cert_default_cert_required(self):
        conn = VerifiedHTTPSConnection(self.host, self.port)
        conn.set_cert(ca_certs='/etc/ssl/certs/custom.pem')
        self.assertEqual(conn.cert_reqs, 'CERT_REQUIRED')


class TestHTTPS_NoSAN(HTTPSDummyServerTestCase):
    certs = NO_SAN_CERTS

    def test_warning_for_certs_without_a_san(self):
        """Ensure that a warning is raised when the cert from the server has
        no Subject Alternative Name."""
        with mock.patch('warnings.warn') as warn:
            https_pool = HTTPSConnectionPool(self.host, self.port,
                                             cert_reqs='CERT_REQUIRED',
                                             ca_certs=NO_SAN_CA)
            r = https_pool.request('GET', '/')
            self.assertEqual(r.status, 200)
            self.assertTrue(warn.called)



class TestHTTPS_IPv6Addr(IPV6HTTPSDummyServerTestCase):
    certs = IPV6_ADDR_CERTS

    def test_strip_square_brackets_before_validating(self):
        """Test that the fix for #760 works."""
        if not HAS_IPV6:
            raise SkipTest("Only runs on IPv6 systems")
        https_pool = HTTPSConnectionPool('[::1]', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=IPV6_ADDR_CA)
        r = https_pool.request('GET', '/')
        self.assertEqual(r.status, 200)


if __name__ == '__main__':
    unittest.main()
