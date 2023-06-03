import pytest
import six

import urllib3


@pytest.mark.skipif(
    six.PY2,
    reason="This behaviour isn't added when running urllib3 in Python 2",
)
class TestRequestImport(object):
    def test_request_import_warning(self):
        """Ensure an appropriate error is raised to the user
        if they try and run urllib3.request()"""
        with pytest.warns(UserWarning):
            urllib3.request(1, a=2)
