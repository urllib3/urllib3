import warnings

import pytest

from urllib3.connection import HTTPConnection


class TestVersionCompatibility(object):
    def test_connection_strict(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # strict=True is deprecated in Py33+
            HTTPConnection('localhost', 12345, strict=True)

            if w:
                pytest.fail('HTTPConnection raised warning on strict=True: %r' % w[0].message)

    def test_connection_source_address(self):
        try:
            # source_address does not exist in Py26-
            HTTPConnection('localhost', 12345, source_address='127.0.0.1')
        except TypeError as e:
            pytest.fail('HTTPConnection raised TypeError on source_adddress: %r' % e)
