"""
Test what happens if Python was built without SSL

* Everything that does not involve HTTPS should still work
* HTTPS requests must fail with an error that points at the ssl module
"""

import sys
from nose.plugins.skip import SkipTest
import unittest


if 'test.ssl_blocker' not in sys.modules:
    raise SkipTest('you must set BLOCK_SSL=yes to block SSL')


class TestWithoutSSL(unittest.TestCase):

    def test_cannot_import_ssl(self):
        with self.assertRaises(ImportError):
            import ssl

    def test_import_urllib3(self):
        import urllib3
