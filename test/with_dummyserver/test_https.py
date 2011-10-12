import logging
import sys
import os
import unittest

from .dummy_server import HTTPSDummyServerTestCase

from urllib3 import HTTPSConnectionPool
from urllib3.connectionpool import VerifiedHTTPSConnection
from urllib3.exceptions import (
    TimeoutError, EmptyPoolError, MaxRetryError, SSLError,
)



CERTS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                          'certs'))

CA_PATH = os.path.join(CERTS_PATH, 'client.pem')
CA_BAD_PATH = os.path.join(CERTS_PATH, 'client_bad.pem')


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
        except SSLError, e:
            self.assertIn('No root certificates', str(e))

        https_pool.ca_certs = CA_BAD_PATH

        try:
            https_pool.request('GET', '/')
            self.fail("Didn't raise SSL error with wrong CA")
        except SSLError, e:
            self.assertIn('certificate verify failed', str(e))

        https_pool.ca_certs = CA_PATH
        https_pool.request('GET', '/') # Should succeed without exceptions.


if __name__ == '__main__':
    unittest.main()
