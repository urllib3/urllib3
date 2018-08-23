# -*- coding: utf-8 -*-
import os
import unittest

import mock
import pytest

try:
    from urllib3.contrib.pyopenssl import (
        _dnsname_to_stdlib, get_subj_alt_name
    )
    from cryptography import x509
    from OpenSSL.crypto import FILETYPE_PEM, load_certificate
except ImportError:
    pass


def setup_module():
    try:
        from urllib3.contrib.pyopenssl import inject_into_urllib3
        inject_into_urllib3()
    except ImportError as e:
        pytest.skip('Could not import PyOpenSSL: %r' % e)


def teardown_module():
    try:
        from urllib3.contrib.securetransport import extract_from_urllib3
        extract_from_urllib3()
    except ImportError:
        pass


from ..with_dummyserver.test_https import TestHTTPS, TestHTTPS_TLSv1  # noqa: F401
from ..with_dummyserver.test_socketlevel import (  # noqa: F401
    TestSNI, TestSocketClosing, TestClientCerts
)


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

    @mock.patch('urllib3.contrib.pyopenssl.log.warning')
    def test_get_subj_alt_name(self, mock_warning):
        """
        If a certificate has two subject alternative names, cryptography raises
        an x509.DuplicateExtension exception.
        """
        path = os.path.join(os.path.dirname(__file__), 'duplicate_san.pem')
        with open(path, 'r') as fp:
            cert = load_certificate(FILETYPE_PEM, fp.read())

        self.assertEqual(get_subj_alt_name(cert), [])

        self.assertEqual(mock_warning.call_count, 1)
        self.assertIsInstance(mock_warning.call_args[0][1],
                              x509.DuplicateExtension)
