# -*- coding: utf-8 -*-
import unittest

from nose.plugins.skip import SkipTest

try:
    from urllib3.contrib.pyopenssl import (inject_into_urllib3,
                                           extract_from_urllib3)
except ImportError as e:
    raise SkipTest('Could not import PyOpenSSL: %r' % e)

from mock import patch, Mock


class TestPyOpenSSLInjection(unittest.TestCase):
    """
    Tests for error handling in pyopenssl's 'inject_into urllib3'
    """
    def test_inject_validate_fail_cryptography(self):
        """
        Injection should not be supported if cryptography is too old.
        """
        try:
            with patch("cryptography.x509.extensions.Extensions") as mock:
                del mock.get_extension_for_class
                self.assertRaises(ImportError, inject_into_urllib3)
        finally:
            # `inject_into_urllib3` is not supposed to succeed.
            # If it does, this test should fail, but we need to
            # clean up so that subsequent tests are unaffected.
            extract_from_urllib3()

    def test_inject_validate_fail_pyopenssl(self):
        """
        Injection should not be supported if pyOpenSSL is too old.
        """
        try:
            return_val = Mock()
            del return_val._x509
            with patch("OpenSSL.crypto.X509", return_value=return_val):
                self.assertRaises(ImportError, inject_into_urllib3)
        finally:
            # `inject_into_urllib3` is not supposed to succeed.
            # If it does, this test should fail, but we need to
            # clean up so that subsequent tests are unaffected.
            extract_from_urllib3()
