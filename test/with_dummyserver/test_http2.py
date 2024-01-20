from __future__ import annotations

import subprocess
from test import notWindows

import pytest

import urllib3
from dummyserver.socketserver import DEFAULT_CERTS
from dummyserver.testcase import HTTPSHypercornDummyServerTestCase

DEFAULT_CERTS_HTTP2 = DEFAULT_CERTS.copy()
DEFAULT_CERTS_HTTP2["alpn_protocols"] = ["h2"]


def setup_module() -> None:
    try:
        from urllib3.contrib.http2 import inject_into_urllib3

        inject_into_urllib3()
    except ImportError as e:
        pytest.skip(f"Could not import h2: {e!r}")


def teardown_module() -> None:
    try:
        from urllib3.contrib.http2 import extract_from_urllib3

        extract_from_urllib3()
    except ImportError:
        pass


class TestHypercornDummyServerTestCase(HTTPSHypercornDummyServerTestCase):
    certs = DEFAULT_CERTS_HTTP2

    @classmethod
    def setup_class(cls) -> None:
        super().setup_class()
        cls.base_url = f"https://{cls.host}:{cls.port}"

    @notWindows()  # GitHub Actions Windows doesn't have HTTP/2 support.
    def test_hypercorn_server_http2(self) -> None:
        # This is a meta test to make sure our Hypercorn test server is actually using HTTP/2
        # before urllib3 is capable of speaking HTTP/2. Thanks, Daniel! <3
        output = subprocess.check_output(
            [
                "curl",
                "-vvv",
                "--http2",
                "--cacert",
                self.certs["ca_certs"],
                self.base_url,
            ],
            stderr=subprocess.STDOUT,
        )

        assert b"< HTTP/2 200" in output
        assert output.endswith(b"Dummy server!")

    def test_simple_http2(self) -> None:
        with urllib3.PoolManager(ca_certs=self.certs["ca_certs"]) as http:
            resp = http.request("HEAD", self.base_url, retries=False)

        assert resp.status == 200
        resp.headers.pop("date")
        assert resp.headers == {
            "content-type": "text/html; charset=utf-8",
            "content-length": "13",
            "server": "hypercorn-h2",
        }
