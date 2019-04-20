import datetime
import json
import logging
import ssl
import sys
import unittest
import warnings

import mock
import pytest

from dummyserver.testcase import (
    HTTPSDummyServerTestCase, IPV6HTTPSDummyServerTestCase
)
from dummyserver.server import (DEFAULT_CA, DEFAULT_CA_BAD, DEFAULT_CERTS,
                                DEFAULT_CLIENT_CERTS,
                                DEFAULT_CLIENT_NO_INTERMEDIATE_CERTS,
                                NO_SAN_CERTS, NO_SAN_CA, DEFAULT_CA_DIR,
                                IPV6_ADDR_CERTS, IPV6_ADDR_CA, HAS_IPV6,
                                IP_SAN_CERTS, IPV6_SAN_CERTS, IPV6_SAN_CA,
                                PASSWORD_CLIENT_KEYFILE)

from test import (
    onlyPy279OrNewer,
    notSecureTransport,
    notOpenSSL098,
    requires_network,
    requires_ssl_context_keyfile_password,
    fails_on_travis_gce,
    requiresTLSv1,
    requiresTLSv1_1,
    requiresTLSv1_2,
    requiresTLSv1_3,
    TARPIT_HOST,
)
from urllib3 import HTTPSConnectionPool
from urllib3.connection import (
    VerifiedHTTPSConnection,
    RECENT_DATE,
)
from urllib3.exceptions import (
    SSLError,
    ConnectTimeoutError,
    InsecureRequestWarning,
    SystemTimeWarning,
    InsecurePlatformWarning,
    MaxRetryError,
    ProtocolError,
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


TLSv1_CERTS = DEFAULT_CERTS.copy()
TLSv1_CERTS["ssl_version"] = getattr(ssl, "PROTOCOL_TLSv1", None)

TLSv1_1_CERTS = DEFAULT_CERTS.copy()
TLSv1_1_CERTS["ssl_version"] = getattr(ssl, "PROTOCOL_TLSv1_1", None)

TLSv1_2_CERTS = DEFAULT_CERTS.copy()
TLSv1_2_CERTS["ssl_version"] = getattr(ssl, "PROTOCOL_TLSv1_2", None)


class TestHTTPS(HTTPSDummyServerTestCase):
    tls_protocol_name = None

    def setUp(self):
        self._pool = HTTPSConnectionPool(self.host, self.port, ca_certs=DEFAULT_CA)
        self.addCleanup(self._pool.close)

    def test_simple(self):
        r = self._pool.request('GET', '/')
        self.assertEqual(r.status, 200, r.data)

    @fails_on_travis_gce
    def test_dotted_fqdn(self):
        pool = HTTPSConnectionPool(self.host + '.', self.port, ca_certs=DEFAULT_CA)
        r = pool.request('GET', '/')
        self.assertEqual(r.status, 200, r.data)

    def test_client_intermediate(self):
        client_cert, client_key = (
            DEFAULT_CLIENT_CERTS['certfile'],
            DEFAULT_CLIENT_CERTS['keyfile'],
        )
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         key_file=client_key,
                                         cert_file=client_cert,
                                         ca_certs=DEFAULT_CA)
        r = https_pool.request('GET', '/certificate')
        subject = json.loads(r.data.decode('utf-8'))
        assert subject['organizationalUnitName'].startswith(
            'Testing server cert')

    def test_client_no_intermediate(self):
        client_cert, client_key = (
            DEFAULT_CLIENT_NO_INTERMEDIATE_CERTS['certfile'],
            DEFAULT_CLIENT_NO_INTERMEDIATE_CERTS['keyfile']
        )
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_file=client_cert,
                                         key_file=client_key,
                                         ca_certs=DEFAULT_CA)
        try:
            https_pool.request('GET', '/certificate', retries=False)
        except SSLError as e:
            if not ('alert unknown ca' in str(e) or
                    'invalid certificate chain' in str(e) or
                    'unknown Cert Authority' in str(e) or
                    # https://github.com/urllib3/urllib3/issues/1422
                    'connection closed via error' in str(e) or
                    'WSAECONNRESET' in str(e)):
                raise
        except ProtocolError as e:
            # https://github.com/urllib3/urllib3/issues/1422
            if not ('An existing connection was forcibly closed by the remote host' in str(e)):
                raise

    @requires_ssl_context_keyfile_password
    def test_client_key_password(self):
        client_cert, client_key = (
            DEFAULT_CLIENT_CERTS['certfile'],
            PASSWORD_CLIENT_KEYFILE,
        )
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         ca_certs=DEFAULT_CA,
                                         key_file=client_key,
                                         cert_file=client_cert,
                                         key_password="letmein")
        r = https_pool.request('GET', '/certificate')
        subject = json.loads(r.data.decode('utf-8'))
        assert subject['organizationalUnitName'].startswith(
            'Testing server cert')

    @requires_ssl_context_keyfile_password
    def test_client_encrypted_key_requires_password(self):
        client_cert, client_key = (
            DEFAULT_CLIENT_CERTS['certfile'],
            PASSWORD_CLIENT_KEYFILE,
        )
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         key_file=client_key,
                                         cert_file=client_cert,
                                         key_password=None)

        with pytest.raises(MaxRetryError) as e:
            https_pool.request('GET', '/certificate')

        assert 'password is required' in str(e.value)
        assert isinstance(e.value.reason, SSLError)

    def test_verified(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)
        self.addCleanup(https_pool.close)

        conn = https_pool._new_conn()
        self.assertEqual(conn.__class__, VerifiedHTTPSConnection)

        with mock.patch('warnings.warn') as warn:
            r = https_pool.request('GET', '/')
            self.assertEqual(r.status, 200)

            # Modern versions of Python, or systems using PyOpenSSL, don't
            # emit warnings.
            if sys.version_info >= (2, 7, 9) or util.IS_PYOPENSSL \
                    or util.IS_SECURETRANSPORT:
                self.assertFalse(warn.called, warn.call_args_list)
            else:
                self.assertTrue(warn.called)
                if util.HAS_SNI:
                    call = warn.call_args_list[0]
                else:
                    call = warn.call_args_list[1]
                error = call[0][1]
                self.assertEqual(error, InsecurePlatformWarning)

    def test_verified_with_context(self):
        ctx = util.ssl_.create_urllib3_context(cert_reqs=ssl.CERT_REQUIRED)
        ctx.load_verify_locations(cafile=DEFAULT_CA)
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         ssl_context=ctx)
        self.addCleanup(https_pool.close)

        conn = https_pool._new_conn()
        self.assertEqual(conn.__class__, VerifiedHTTPSConnection)

        with mock.patch('warnings.warn') as warn:
            r = https_pool.request('GET', '/')
            self.assertEqual(r.status, 200)

            # Modern versions of Python, or systems using PyOpenSSL, don't
            # emit warnings.
            if sys.version_info >= (2, 7, 9) or util.IS_PYOPENSSL \
                    or util.IS_SECURETRANSPORT:
                self.assertFalse(warn.called, warn.call_args_list)
            else:
                self.assertTrue(warn.called)
                if util.HAS_SNI:
                    call = warn.call_args_list[0]
                else:
                    call = warn.call_args_list[1]
                error = call[0][1]
                self.assertEqual(error, InsecurePlatformWarning)

    def test_context_combines_with_ca_certs(self):
        ctx = util.ssl_.create_urllib3_context(cert_reqs=ssl.CERT_REQUIRED)
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         ca_certs=DEFAULT_CA,
                                         ssl_context=ctx)
        self.addCleanup(https_pool.close)

        conn = https_pool._new_conn()
        self.assertEqual(conn.__class__, VerifiedHTTPSConnection)

        with mock.patch('warnings.warn') as warn:
            r = https_pool.request('GET', '/')
            self.assertEqual(r.status, 200)

            # Modern versions of Python, or systems using PyOpenSSL, don't
            # emit warnings.
            if sys.version_info >= (2, 7, 9) or util.IS_PYOPENSSL \
                    or util.IS_SECURETRANSPORT:
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
    @notSecureTransport  # SecureTransport does not support cert directories
    @notOpenSSL098  # OpenSSL 0.9.8 does not support cert directories
    def test_ca_dir_verified(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_cert_dir=DEFAULT_CA_DIR)
        self.addCleanup(https_pool.close)

        conn = https_pool._new_conn()
        self.assertEqual(conn.__class__, VerifiedHTTPSConnection)

        with mock.patch('warnings.warn') as warn:
            r = https_pool.request('GET', '/')
            self.assertEqual(r.status, 200)
            self.assertFalse(warn.called, warn.call_args_list)

    def test_invalid_common_name(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)
        self.addCleanup(https_pool.close)

        try:
            https_pool.request('GET', '/')
            self.fail("Didn't raise SSL invalid common name")
        except MaxRetryError as e:
            self.assertIsInstance(e.reason, SSLError)
            self.assertTrue(
                "doesn't match" in str(e.reason) or
                "certificate verify failed" in str(e.reason)
            )

    def test_verified_with_bad_ca_certs(self):
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA_BAD)
        self.addCleanup(https_pool.close)

        try:
            https_pool.request('GET', '/')
            self.fail("Didn't raise SSL error with bad CA certs")
        except MaxRetryError as e:
            self.assertIsInstance(e.reason, SSLError)
            self.assertIn('certificate verify failed', str(e.reason),
                          "Expected 'certificate verify failed',"
                          "instead got: %r" % e.reason)

    def test_verified_without_ca_certs(self):
        # default is cert_reqs=None which is ssl.CERT_NONE
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED')
        self.addCleanup(https_pool.close)

        try:
            https_pool.request('GET', '/')
            self.fail("Didn't raise SSL error with no CA certs when"
                      "CERT_REQUIRED is set")
        except MaxRetryError as e:
            self.assertIsInstance(e.reason, SSLError)
            # there is a different error message depending on whether or
            # not pyopenssl is injected
            self.assertTrue('No root certificates specified' in str(e.reason) or
                            'certificate verify failed' in str(e.reason) or
                            'invalid certificate chain' in str(e.reason),
                            "Expected 'No root certificates specified',  "
                            "'certificate verify failed', or "
                            "'invalid certificate chain', "
                            "instead got: %r" % e.reason)

    def test_no_ssl(self):
        pool = HTTPSConnectionPool(self.host, self.port)
        pool.ConnectionCls = None
        self.addCleanup(pool.close)
        self.assertRaises(SSLError, pool._new_conn)
        with self.assertRaises(MaxRetryError) as cm:
            pool.request('GET', '/', retries=0)
        self.assertIsInstance(cm.exception.reason, SSLError)

    def test_unverified_ssl(self):
        """ Test that bare HTTPSConnection can connect, make requests """
        pool = HTTPSConnectionPool(self.host, self.port, cert_reqs=ssl.CERT_NONE)
        self.addCleanup(pool.close)

        with mock.patch('warnings.warn') as warn:
            r = pool.request('GET', '/')
            self.assertEqual(r.status, 200)
            self.assertTrue(warn.called)

            # Modern versions of Python, or systems using PyOpenSSL, only emit
            # the unverified warning. Older systems may also emit other
            # warnings, which we want to ignore here.
            calls = warn.call_args_list
            self.assertIn(InsecureRequestWarning, [x[0][1] for x in calls])

    def test_ssl_unverified_with_ca_certs(self):
        pool = HTTPSConnectionPool(self.host, self.port,
                                   cert_reqs='CERT_NONE',
                                   ca_certs=DEFAULT_CA_BAD)
        self.addCleanup(pool.close)

        with mock.patch('warnings.warn') as warn:
            r = pool.request('GET', '/')
            self.assertEqual(r.status, 200)
            self.assertTrue(warn.called)

            # Modern versions of Python, or systems using PyOpenSSL, only emit
            # the unverified warning. Older systems may also emit other
            # warnings, which we want to ignore here.
            calls = warn.call_args_list
            if sys.version_info >= (2, 7, 9) or util.IS_PYOPENSSL \
                    or util.IS_SECURETRANSPORT:
                category = calls[0][0][1]
            elif util.HAS_SNI:
                category = calls[1][0][1]
            else:
                category = calls[2][0][1]
            self.assertEqual(category, InsecureRequestWarning)

    def test_assert_hostname_false(self):
        https_pool = HTTPSConnectionPool('localhost', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)
        self.addCleanup(https_pool.close)

        https_pool.assert_hostname = False
        https_pool.request('GET', '/')

    def test_assert_specific_hostname(self):
        https_pool = HTTPSConnectionPool('localhost', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)
        self.addCleanup(https_pool.close)

        https_pool.assert_hostname = 'localhost'
        https_pool.request('GET', '/')

    def test_server_hostname(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA,
                                         server_hostname='localhost')
        self.addCleanup(https_pool.close)

        conn = https_pool._new_conn()
        conn.request('GET', '/')

        # Assert the wrapping socket is using the passed-through SNI name.
        # pyopenssl doesn't let you pull the server_hostname back off the
        # socket, so only add this assertion if the attribute is there (i.e.
        # the python ssl module).
        if hasattr(conn.sock, 'server_hostname'):
            self.assertEqual(conn.sock.server_hostname, "localhost")

    def test_assert_fingerprint_md5(self):
        https_pool = HTTPSConnectionPool('localhost', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)
        self.addCleanup(https_pool.close)

        https_pool.assert_fingerprint = 'F2:06:5A:42:10:3F:45:1C:17:FE:E6:' \
                                        '07:1E:8A:86:E5'

        https_pool.request('GET', '/')

    def test_assert_fingerprint_sha1(self):
        https_pool = HTTPSConnectionPool('localhost', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)
        self.addCleanup(https_pool.close)

        https_pool.assert_fingerprint = '92:81:FE:85:F7:0C:26:60:EC:D6:B3:' \
                                        'BF:93:CF:F9:71:CC:07:7D:0A'
        https_pool.request('GET', '/')

    def test_assert_fingerprint_sha256(self):
        https_pool = HTTPSConnectionPool('localhost', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)
        self.addCleanup(https_pool.close)

        https_pool.assert_fingerprint = ('C5:4D:0B:83:84:89:2E:AE:B4:58:BB:12:'
                                         'F7:A6:C4:76:05:03:88:D8:57:65:51:F3:'
                                         '1E:60:B0:8B:70:18:64:E6')
        https_pool.request('GET', '/')

    def test_assert_invalid_fingerprint(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)
        self.addCleanup(https_pool.close)

        https_pool.assert_fingerprint = 'AA:AA:AA:AA:AA:AAAA:AA:AAAA:AA:' \
                                        'AA:AA:AA:AA:AA:AA:AA:AA:AA'

        def _test_request(pool):
            with self.assertRaises(MaxRetryError) as cm:
                pool.request('GET', '/', retries=0)
            self.assertIsInstance(cm.exception.reason, SSLError)

        _test_request(https_pool)
        https_pool._get_conn()

        # Uneven length
        https_pool.assert_fingerprint = 'AA:A'
        _test_request(https_pool)
        https_pool._get_conn()

        # Invalid length
        https_pool.assert_fingerprint = 'AA'
        _test_request(https_pool)

    def test_verify_none_and_bad_fingerprint(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_NONE',
                                         ca_certs=DEFAULT_CA_BAD)
        self.addCleanup(https_pool.close)

        https_pool.assert_fingerprint = 'AA:AA:AA:AA:AA:AAAA:AA:AAAA:AA:' \
                                        'AA:AA:AA:AA:AA:AA:AA:AA:AA'
        with self.assertRaises(MaxRetryError) as cm:
            https_pool.request('GET', '/', retries=0)
        self.assertIsInstance(cm.exception.reason, SSLError)

    def test_verify_none_and_good_fingerprint(self):
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_NONE',
                                         ca_certs=DEFAULT_CA_BAD)
        self.addCleanup(https_pool.close)

        https_pool.assert_fingerprint = '92:81:FE:85:F7:0C:26:60:EC:D6:B3:' \
                                        'BF:93:CF:F9:71:CC:07:7D:0A'
        https_pool.request('GET', '/')

    @notSecureTransport
    def test_good_fingerprint_and_hostname_mismatch(self):
        # This test doesn't run with SecureTransport because we don't turn off
        # hostname validation without turning off all validation, which this
        # test doesn't do (deliberately). We should revisit this if we make
        # new decisions.
        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)
        self.addCleanup(https_pool.close)

        https_pool.assert_fingerprint = '92:81:FE:85:F7:0C:26:60:EC:D6:B3:' \
                                        'BF:93:CF:F9:71:CC:07:7D:0A'
        https_pool.request('GET', '/')

    @requires_network
    def test_https_timeout(self):
        timeout = Timeout(connect=0.001)
        https_pool = HTTPSConnectionPool(TARPIT_HOST, self.port,
                                         timeout=timeout, retries=False,
                                         cert_reqs='CERT_REQUIRED')
        self.addCleanup(https_pool.close)

        timeout = Timeout(total=None, connect=0.001)
        https_pool = HTTPSConnectionPool(TARPIT_HOST, self.port,
                                         timeout=timeout, retries=False,
                                         cert_reqs='CERT_REQUIRED')
        self.addCleanup(https_pool.close)
        self.assertRaises(ConnectTimeoutError, https_pool.request, 'GET', '/')

        timeout = Timeout(read=0.01)
        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         timeout=timeout, retries=False,
                                         cert_reqs='CERT_REQUIRED')
        self.addCleanup(https_pool.close)
        https_pool.ca_certs = DEFAULT_CA
        https_pool.assert_fingerprint = '92:81:FE:85:F7:0C:26:60:EC:D6:B3:' \
                                        'BF:93:CF:F9:71:CC:07:7D:0A'

        timeout = Timeout(total=None)
        https_pool = HTTPSConnectionPool(self.host, self.port, timeout=timeout,
                                         cert_reqs='CERT_NONE')
        self.addCleanup(https_pool.close)
        https_pool.request('GET', '/')

    def test_tunnel(self):
        """ test the _tunnel behavior """
        timeout = Timeout(total=None)
        https_pool = HTTPSConnectionPool(self.host, self.port, timeout=timeout,
                                         cert_reqs='CERT_NONE')
        self.addCleanup(https_pool.close)
        conn = https_pool._new_conn()
        self.addCleanup(conn.close)
        conn.set_tunnel(self.host, self.port)
        conn._tunnel = mock.Mock()
        https_pool._make_request(conn, 'GET', '/')
        conn._tunnel.assert_called_once_with()

    @requires_network
    def test_enhanced_timeout(self):
        def new_pool(timeout, cert_reqs='CERT_REQUIRED'):
            https_pool = HTTPSConnectionPool(TARPIT_HOST, self.port,
                                             timeout=timeout,
                                             retries=False,
                                             cert_reqs=cert_reqs)
            self.addCleanup(https_pool.close)
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

        https_pool = HTTPSConnectionPool(self.host, self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA,
                                         assert_fingerprint=fingerprint)
        self.addCleanup(https_pool.close)

        r = https_pool.request('GET', '/')
        assert r.status == 200

    @onlyPy279OrNewer
    def test_ssl_correct_system_time(self):
        self._pool.cert_reqs = 'CERT_REQUIRED'
        self._pool.ca_certs = DEFAULT_CA

        w = self._request_without_resource_warnings('GET', '/')
        self.assertEqual([], w)

    @onlyPy279OrNewer
    def test_ssl_wrong_system_time(self):
        self._pool.cert_reqs = 'CERT_REQUIRED'
        self._pool.ca_certs = DEFAULT_CA
        with mock.patch('urllib3.connection.datetime') as mock_date:
            mock_date.date.today.return_value = datetime.date(1970, 1, 1)

            w = self._request_without_resource_warnings('GET', '/')

            self.assertEqual(len(w), 1)
            warning = w[0]

            self.assertEqual(SystemTimeWarning, warning.category)
            self.assertIn(str(RECENT_DATE), warning.message.args[0])

    def _request_without_resource_warnings(self, method, url):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            self._pool.request(method, url)

        return [x for x in w if not isinstance(x.message, ResourceWarning)]

    def test_set_ssl_version_to_tls_version(self):
        if self.tls_protocol_name is None:
            pytest.skip("Skipping base test class")

        self._pool.ssl_version = self.certs['ssl_version']
        r = self._pool.request('GET', '/')
        self.assertEqual(r.status, 200, r.data)

    def test_set_cert_default_cert_required(self):
        conn = VerifiedHTTPSConnection(self.host, self.port)
        conn.set_cert()
        self.assertEqual(conn.cert_reqs, ssl.CERT_REQUIRED)

    def test_tls_protocol_name_of_socket(self):
        if self.tls_protocol_name is None:
            pytest.skip("Skipping base test class")

        conn = self._pool._get_conn()
        conn.connect()

        if not hasattr(conn.sock, 'version'):
            pytest.skip('SSLSocket.version() not available')

        self.assertEqual(conn.sock.version(), self.tls_protocol_name)


@requiresTLSv1()
class TestHTTPS_TLSv1(TestHTTPS):
    tls_protocol_name = 'TLSv1'
    certs = TLSv1_CERTS


@requiresTLSv1_1()
class TestHTTPS_TLSv1_1(TestHTTPS):
    tls_protocol_name = 'TLSv1.1'
    certs = TLSv1_1_CERTS


@requiresTLSv1_2()
class TestHTTPS_TLSv1_2(TestHTTPS):
    tls_protocol_name = 'TLSv1.2'
    certs = TLSv1_2_CERTS


@requiresTLSv1_3()
class TestHTTPS_TLSv1_3(TestHTTPS):
    tls_protocol_name = 'TLSv1.3'


class TestHTTPS_NoSAN(HTTPSDummyServerTestCase):
    certs = NO_SAN_CERTS

    def test_warning_for_certs_without_a_san(self):
        """Ensure that a warning is raised when the cert from the server has
        no Subject Alternative Name."""
        with mock.patch('warnings.warn') as warn:
            https_pool = HTTPSConnectionPool(self.host, self.port,
                                             cert_reqs='CERT_REQUIRED',
                                             ca_certs=NO_SAN_CA)
            self.addCleanup(https_pool.close)
            r = https_pool.request('GET', '/')
            self.assertEqual(r.status, 200)
            self.assertTrue(warn.called)


class TestHTTPS_IPSAN(HTTPSDummyServerTestCase):
    certs = IP_SAN_CERTS

    def test_can_validate_ip_san(self):
        """Ensure that urllib3 can validate SANs with IP addresses in them."""
        try:
            import ipaddress  # noqa: F401
        except ImportError:
            pytest.skip("Only runs on systems with an ipaddress module")

        https_pool = HTTPSConnectionPool('127.0.0.1', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=DEFAULT_CA)
        self.addCleanup(https_pool.close)
        r = https_pool.request('GET', '/')
        self.assertEqual(r.status, 200)


class TestHTTPS_IPv6Addr(IPV6HTTPSDummyServerTestCase):
    certs = IPV6_ADDR_CERTS

    @pytest.mark.skipif(not HAS_IPV6, reason='Only runs on IPv6 systems')
    def test_strip_square_brackets_before_validating(self):
        """Test that the fix for #760 works."""
        https_pool = HTTPSConnectionPool('[::1]', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=IPV6_ADDR_CA)
        self.addCleanup(https_pool.close)
        r = https_pool.request('GET', '/')
        self.assertEqual(r.status, 200)


class TestHTTPS_IPV6SAN(IPV6HTTPSDummyServerTestCase):
    certs = IPV6_SAN_CERTS

    def test_can_validate_ipv6_san(self):
        """Ensure that urllib3 can validate SANs with IPv6 addresses in them."""
        try:
            import ipaddress  # noqa: F401
        except ImportError:
            pytest.skip("Only runs on systems with an ipaddress module")

        https_pool = HTTPSConnectionPool('[::1]', self.port,
                                         cert_reqs='CERT_REQUIRED',
                                         ca_certs=IPV6_SAN_CA)
        self.addCleanup(https_pool.close)
        r = https_pool.request('GET', '/')
        self.assertEqual(r.status, 200)


if __name__ == '__main__':
    unittest.main()
