from __future__ import annotations

import subprocess
from test import notWindows

from dummyserver.testcase import HypercornDummyServerTestCase


class TestHypercornDummyServerTestCase(HypercornDummyServerTestCase):
    @classmethod
    def setup_class(cls) -> None:
        super().setup_class()
        cls.base_url = f"http://{cls.host}:{cls.port}"

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
        assert output.endswith(b"Dummy Hypercorn server!")
