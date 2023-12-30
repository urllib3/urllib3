from __future__ import annotations

import subprocess
from test import notWindows

import pytest

import urllib3
from dummyserver.testcase import HTTPSHypercornDummyServerTestCase


def setup_module() -> None:
    try:
        from urllib3.contrib.http2 import inject_into_urllib3

        inject_into_urllib3()
    except ImportError as e:
        pytest.skip(f"Could not import h2: {e!r}")


def teardown_module() -> None:
    try:
        from urllib3.contrib.pyopenssl import extract_from_urllib3

        extract_from_urllib3()
    except ImportError:
        pass


class TestHypercornDummyServerTestCase(HTTPSHypercornDummyServerTestCase):
    @classmethod
    def setup_class(cls) -> None:
        super().setup_class()
        cls.base_url = f"https://{cls.host}:{cls.port}"

    @notWindows()  # GitHub Actions Windows doesn't have HTTP/2 support.
    def test_hypercorn_server_http2(self) -> None:
        # This is a meta test to make sure our Hypercorn test server is actually using HTTP/2
        # before urllib3 is capable of speaking HTTP/2. Thanks, Daniel! <3
        output = subprocess.check_output(
            ["curl", "-vvv", "--http2", self.base_url], stderr=subprocess.STDOUT
        )

        # curl does HTTP/1.1 and upgrades to HTTP/2 without TLS which is fine
        # for us. Hypercorn supports this thankfully, but we should try with
        # HTTPS as well once that's available.
        assert b"< HTTP/2 200" in output
        assert output.endswith(b"Dummy server!")

    def test_simple_http2(self):
        with urllib3.PoolManager(ca_certs=self.certs["ca_certs"]) as http:
            resp = http.request("HEAD", self.base_url, retries=False)

        assert resp.status == 200
        resp.headers.pop("date")
        assert resp.headers == {
            "content-type": "text/html; charset=utf-8",
            "content-length": "13",
            "server": "hypercorn-h2",
        }
