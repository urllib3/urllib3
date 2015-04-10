"""
Test connections without the builtin ssl module

Note: Import urllib3 inside the test functions to get the importblocker to work
"""
from ..test_no_ssl import TestWithoutSSL

from dummyserver.testcase import (
        HTTPDummyServerTestCase, HTTPSDummyServerTestCase)


class TestHTTPWithoutSSL(HTTPDummyServerTestCase, TestWithoutSSL):
    def test_simple(self):
        import urllib3

        pool = urllib3.HTTPConnectionPool(self.host, self.port)
        r = pool.request('GET', '/')
        self.assertEqual(r.status, 200, r.data)


class TestHTTPSWithoutSSL(HTTPSDummyServerTestCase, TestWithoutSSL):
    def test_simple(self):
        import urllib3

        pool = urllib3.HTTPSConnectionPool(self.host, self.port)
        try:
            pool.request('GET', '/')
        except urllib3.exceptions.SSLError as e:
            self.assertTrue('SSL module is not available' in str(e))
