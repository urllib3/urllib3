import unittest
import warnings

from urllib3.connection import HTTPConnection


class TestVersionCompatibility(unittest.TestCase):
    def test_connection_strict(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # strict=True is deprecated in Py33+
            conn = HTTPConnection('localhost', 12345, strict=True)

            if w:
                self.fail('HTTPConnection raised warning on strict=True: %r' % w[0].message)
