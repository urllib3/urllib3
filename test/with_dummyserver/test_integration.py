import pytest
import requests

from dummyserver.server import DEFAULT_CA
from dummyserver.testcase import HTTPDummyServerTestCase, HTTPSDummyServerTestCase


class TestHTTPIntegration(HTTPDummyServerTestCase):
    def test_requests_integration(self):
        with pytest.warns(DeprecationWarning) as record:
            response = requests.get(f"{self.scheme}://{self.host}:{self.port}")

        assert 200 == response.status_code
        assert 1 == len(record)
        msg = (
            "The 'strict' parameter is no longer needed on Python 3+. "
            "This will raise an error in urllib3 v3.0.0."
        )
        assert record[0].message.args[0] == msg


class TestHTTPSIntegration(HTTPSDummyServerTestCase):
    def test_requests_integration(self):
        with pytest.warns(DeprecationWarning) as record:
            response = requests.get(
                f"{self.scheme}://{self.host}:{self.port}", verify=DEFAULT_CA
            )

        assert 200 == response.status_code
        assert 1 == len(record)
        msg = (
            "The 'strict' parameter is no longer needed on Python 3+. "
            "This will raise an error in urllib3 v3.0.0."
        )
        assert record[0].message.args[0] == msg
