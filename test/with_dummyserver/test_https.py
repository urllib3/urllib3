import logging
import sys
import unittest

from dummyserver.testcase import HTTPSDummyServerTestCase

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

        try:
            https_pool.request('GET', '/')
            self.fail("Didn't raise SSL error with no CA")
        except SSLError as e:
            self.assertTrue('No root certificates' in str(e))

        https_pool.ca_certs = DEFAULT_CA_BAD

        try:
            https_pool.request('GET', '/')
            self.fail("Didn't raise SSL error with wrong CA")
        except SSLError as e:
            self.assertTrue('certificate verify failed' in str(e))

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


if __name__ == '__main__':
    unittest.main()
