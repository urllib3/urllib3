import logging
import sys
import os
import unittest


from urllib3 import HTTPSConnectionPool
from urllib3.connectionpool import VerifiedHTTPSConnection
from urllib3.exceptions import (
    TimeoutError, EmptyPoolError, MaxRetryError, SSLError,
)



HOST = "localhost"
PORT = 8082

CERTS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                          '../certs/'))

CA_PATH = os.path.join(CERTS_PATH, 'client.pem')
CA_BAD_PATH = os.path.join(CERTS_PATH, 'client_bad.pem')


log = logging.getLogger('urllib3.connectionpool')
log.setLevel(logging.NOTSET)
log.addHandler(logging.StreamHandler(sys.stdout))


class TestHTTPS(unittest.TestCase):

    @classmethod
    def _announce_setup(cls, test_id, test_type):
        # Create connection pool and test for dummy server...
        try:
            r = cls._http_pool.request('GET', '/set_up', retries=1,
                                  fields={'test_id': test_id,
                                          'test_type': test_type})
            if r.data != "Dummy server is ready!":
                raise Exception("Got unexpected response: %s" % r.data)
        except Exception, e:
            raise Exception("Dummy server not running, make sure HOST and PORT "
                            "correspond to the dummy server: %s" % e.message)

    @classmethod
    def setUpClass(cls):
        cls._http_pool = HTTPSConnectionPool(HOST, PORT)
        cls._announce_setup(cls.__name__, test_type='suite')

    def setUp(self):
        self._announce_setup(self.id(), test_type='case')

    def test_simple(self):
        r = self._http_pool.request('GET', '/specific_method',
                                   fields={'method': 'GET'})
        self.assertEqual(r.status, 200, r.data)

    def test_verified(self):
        https_pool = HTTPSConnectionPool(HOST, PORT,
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
