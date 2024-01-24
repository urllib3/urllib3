from __future__ import annotations

import subprocess
from test import notWindows

from dummyserver.testcase import HTTPSHypercornDummyServerTestCase


class TestHypercornDummyServerTestCase(HTTPSHypercornDummyServerTestCase):
    @notWindows()  # GitHub Actions Windows doesn't have HTTP/2 support.
    def test_curl_http_version(self, http_version: str) -> None:
        # This is a meta test to make sure our Hypercorn test server is actually using HTTP/2
        # before urllib3 is capable of speaking HTTP/2. Thanks, Daniel! <3
        output = subprocess.check_output(
            [
                "curl",
                "-vvv",
                "--http2" if http_version == "h2" else "--http1.1",
                "--cacert",
                self.certs["ca_certs"],
                f"https://{self.host}:{self.port}",
            ],
            stderr=subprocess.STDOUT,
        )

        if http_version == "h2":
            assert b"< HTTP/2 200" in output
        else:
            assert b"< HTTP/1.1 200" in output

        assert output.endswith(b"Dummy server!")
