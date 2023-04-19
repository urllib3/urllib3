"""
Test connections without the builtin ssl module
"""
from __future__ import annotations

import subprocess
import sys
import textwrap

from dummyserver.testcase import HTTPDummyServerTestCase


class TestHTTPWithoutSSL(HTTPDummyServerTestCase):
    def test_simple(self) -> None:
        script = textwrap.dedent(
            """\
            import sys

            sys.modules["ssl"] = None
            sys.modules["_ssl"] = None

            import urllib3

            host = sys.argv[1]
            port = int(sys.argv[2])

            with urllib3.HTTPConnectionPool(host, port) as pool:
                r = pool.request("GET", "/")
                assert r.status == 200, r.data
            """
        )
        subprocess.run(
            [sys.executable, "-c", script, self.host, str(self.port)], check=True
        )


def test_https_without_ssl() -> None:
    script = textwrap.dedent(
        """\
        import sys

        sys.modules["ssl"] = None
        sys.modules["_ssl"] = None

        import pytest
        import urllib3

        with urllib3.HTTPSConnectionPool(
            "localhost", 443, cert_reqs="NONE"
        ) as pool:
            with pytest.raises(
                ImportError, match=r"SSL module is not available"
            ):
                pool.request("GET", "/")
        """
    )
    subprocess.run([sys.executable, "-c", script], check=True)
