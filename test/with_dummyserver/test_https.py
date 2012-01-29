import logging
import sys
import unittest

from dummyserver.testcase import HTTPSDummyServerTestCase
from dummyserver.server import DEFAULT_CA, DEFAULT_CA_BAD

from urllib3 import HTTPSConnectionPool
from urllib3.connectionpool import VerifiedHTTPSConnection
from urllib3.exceptions import SSLError


log = logging.getLogger('urllib3.connectionpool')
log.setLevel(logging.NOTSET)
log.addHandler(logging.StreamHandler(sys.stdout))


class TestHTTPS(HTTPSDummyServerTestCase):
    def setUp(self):
        self._pool = HTTPSConnectionPool(self.host, self.port)

    def test_simple(self):
        r = self._pool.request('GET', '/specific_method',
                               fields={'method': 'GET'})
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
                            "Expected 'certificate verify failed', instead got: %r" % e)

        https_pool.ca_certs = DEFAULT_CA
        https_pool.request('GET', '/') # Should succeed without exceptions.

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

        self.assertRaises(SSLError,
            lambda: self._pool.request('GET', '/specific_method',
                                       fields={'method': 'GET'}))

        # Undo
        urllib3.HTTPSConnection = OriginalHTTPSConnection
        urllib3.connectionpool.ssl = OriginalSSL



if __name__ == '__main__':
    unittest.main()
