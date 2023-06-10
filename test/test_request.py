import types

import pytest

import urllib3
from urllib3.packages import six


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

    def test_request_module_properties(self):
        """Ensure properties of the overridden request module
        are still present"""
        assert isinstance(urllib3.request, types.ModuleType)
        expected_attrs = {"RequestMethods", "encode_multipart_formdata", "urlencode"}
        assert set(dir(urllib3.request)).issuperset(expected_attrs)
