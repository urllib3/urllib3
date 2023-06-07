import pytest
import six

import urllib3


@pytest.mark.skipif(
    six.PY2,
    reason="This behaviour isn't added when running urllib3 in Python 2",
)
class TestRequestImport(object):
    def test_request_import_error(self):
        """Ensure an appropriate error is raised to the user
        if they try and run urllib3.request()"""
        with pytest.raises(TypeError) as exc_info:
            urllib3.request(1, a=2)
        assert "urllib3 v2" in exc_info.value.args[0]

    def test_request_method_import(self):
        """Ensure that * method imports are not broken by this change"""
        from urllib3.request import urlencode  # noqa: F401
