import unittest

from urllib3 import HTTPSConnectionPool
from dummyserver.server import CERTS_PATH
from os import path

try:
    from ssl import HAS_SNI
except ImportError:
    HAS_SNI = False

SNI_TEST_URL = "sni.velox.ch"
SNI_TEST_CA  = path.join(CERTS_PATH, 'QuoVadis_Root_CA_2.pem')

class TestExternal(unittest.TestCase):

    def test_sni(self):
        if HAS_SNI:
            https_pool = HTTPSConnectionPool(SNI_TEST_URL,
                                             cert_reqs='CERT_REQUIRED')
            https_pool.ca_certs = SNI_TEST_CA
            https_pool.request('GET', '/')
