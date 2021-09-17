import pytest
import requests

from dummyserver.server import DEFAULT_CA
from dummyserver.testcase import HTTPDummyServerTestCase, HTTPSDummyServerTestCase


class TestHTTPIntegration(HTTPDummyServerTestCase):
    def test_requests_integration(self) -> None:
        with pytest.warns(DeprecationWarning) as records:
            response = requests.get(f"{self.scheme}://{self.host}:{self.port}")

        assert 200 == response.status_code
        msg = (
            "The 'strict' parameter is no longer needed on Python 3+. "
            "This will raise an error in urllib3 v3.0.0."
        )
        assert any(
            isinstance(record.message, Warning) and record.message.args[0] == msg
            for record in records
        )


class TestHTTPSIntegration(HTTPSDummyServerTestCase):
    def test_requests_integration(self) -> None:
        with pytest.warns(DeprecationWarning) as records:
            response = requests.get(
                f"{self.scheme}://{self.host}:{self.port}", verify=DEFAULT_CA
            )

        assert 200 == response.status_code
        msg = (
            "The 'strict' parameter is no longer needed on Python 3+. "
            "This will raise an error in urllib3 v3.0.0."
        )
        assert any(
            isinstance(record.message, Warning) and record.message.args[0] == msg
            for record in records
        )
