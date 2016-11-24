# -*- coding: utf-8 -*-
import unittest

from nose.plugins.skip import SkipTest

try:
    from urllib3.contrib.pyopenssl import (inject_into_urllib3,
                                           extract_from_urllib3)
except ImportError as e:
    raise SkipTest('Could not import PyOpenSSL: %r' % e)

from mock import patch

class TestPyOpenSSLInjection(unittest.TestCase):
    """
    Tests for error handling in pyopenssl's 'inject_into urllib3'
    """
    def test_inject_validate_fail(self):
        """
        Injection should not be supported if we are missing required dependencies.
        """
        successfully_injected = False
        try:
            with patch("cryptography.x509.extensions.Extensions") as mock:

                # The following two lines are what this test intends to test.
                # The remainder of this function is setup and clean-up logic.
                del mock.get_extension_for_class
                self.assertRaises(ImportError, inject_into_urllib3)

                successfully_injected = True
        finally:
            if successfully_injected:
                # `inject_into_urllib3` is not supposed to succeed.
                # If it does, this test should fail, but we should
                # clean up so that subsequent tests are unaffected.
                extract_from_urllib3()
