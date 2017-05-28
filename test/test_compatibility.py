import pytest
import unittest
import warnings

from urllib3.connection import HTTPConnection


class TestVersionCompatibility(unittest.TestCase):
    def test_connection_strict(self):
        with pytest.warns(None) as w:
            warnings.simplefilter("always")

            # strict=True is deprecated in Py33+
            HTTPConnection('localhost', 12345, strict=True)

            if w:
                self.fail('HTTPConnection raised warning on strict=True: %r' % w[0].message)

    def test_connection_source_address(self):
        try:
            # source_address does not exist in Py26-
            HTTPConnection('localhost', 12345, source_address='127.0.0.1')
        except TypeError as e:
            self.fail('HTTPConnection raised TypeError on source_adddress: %r' % e)
