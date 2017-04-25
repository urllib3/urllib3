# -*- coding: utf-8 -*-
import unittest

from nose.plugins.skip import SkipTest

try:
    from urllib3.contrib.pyopenssl import (inject_into_urllib3,
                                           extract_from_urllib3,
                                           _dnsname_to_stdlib)
except ImportError as e:
    raise SkipTest('Could not import PyOpenSSL: %r' % e)


from ..with_dummyserver.test_https import TestHTTPS, TestHTTPS_TLSv1  # noqa: F401
from ..with_dummyserver.test_socketlevel import (  # noqa: F401
    TestSNI, TestSocketClosing, TestClientCerts
)


def setup_module():
    inject_into_urllib3()


def teardown_module():
    extract_from_urllib3()


class TestPyOpenSSLHelpers(unittest.TestCase):
    """
    Tests for PyOpenSSL helper functions.
    """
    def test_dnsname_to_stdlib_simple(self):
        """
        We can convert a dnsname to a native string when the domain is simple.
        """
        name = u"उदाहरण.परीक"
        expected_result = 'xn--p1b6ci4b4b3a.xn--11b5bs8d'

        self.assertEqual(_dnsname_to_stdlib(name), expected_result)

    def test_dnsname_to_stdlib_leading_period(self):
        """
        If there is a . in front of the domain name we correctly encode it.
        """
        name = u".उदाहरण.परीक"
        expected_result = '.xn--p1b6ci4b4b3a.xn--11b5bs8d'

        self.assertEqual(_dnsname_to_stdlib(name), expected_result)

    def test_dnsname_to_stdlib_leading_splat(self):
        """
        If there's a wildcard character in the front of the string we handle it
        appropriately.
        """
        name = u"*.उदाहरण.परीक"
        expected_result = '*.xn--p1b6ci4b4b3a.xn--11b5bs8d'

        self.assertEqual(_dnsname_to_stdlib(name), expected_result)
