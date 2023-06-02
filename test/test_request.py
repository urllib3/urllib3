import pytest

import urllib3


class TestRequestImport(object):
    def test_request_import_warning(self):
        """Ensure an appropriate error is raised to the user
        if they try and import urllib3.request directly"""
        with pytest.warns(UserWarning):
            urllib3.request(1, a=2)
