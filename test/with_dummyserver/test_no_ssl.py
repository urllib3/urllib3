"""
Test connections without the builtin ssl module

Note: Import urllib3 inside the test functions to get the importblocker to work
"""
from ..test_no_ssl import TestWithoutSSL

from dummyserver.testcase import (
        HTTPDummyServerTestCase, HTTPSDummyServerTestCase)

import pytest
import urllib3


class TestHTTPWithoutSSL(HTTPDummyServerTestCase, TestWithoutSSL):

    @pytest.mark.skip(reason=(
        "TestWithoutSSL mutates sys.modules."
        "This breaks the backend loading code which imports modules at runtime."
        "See discussion at https://github.com/python-trio/urllib3/pull/42"
    ))
    def test_simple(self):
        pool = urllib3.HTTPConnectionPool(self.host, self.port)
        self.addCleanup(pool.close)
        r = pool.request('GET', '/')
        self.assertEqual(r.status, 200, r.data)


class TestHTTPSWithoutSSL(HTTPSDummyServerTestCase, TestWithoutSSL):
    def test_simple(self):
        try:
            pool = urllib3.HTTPSConnectionPool(self.host, self.port)
        except urllib3.exceptions.SSLError as e:
            self.assertIn('SSL module is not available', str(e))
        finally:
            pool.close()
