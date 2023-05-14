from __future__ import annotations

import pytest

from urllib3 import HTTPSConnectionPool
from urllib3.exceptions import SSLError

from . import TraefikTestCase


class TestSsl(TraefikTestCase):
    def test_h3_no_ca_cert(self) -> None:
        """This case need a bit of explanations. urllib3 default tls context load default (ca) certificates
        whereas aioquic does not. This cause that strange situation where TCP/TLS works but UDP/TLS does not.
        """

        with HTTPSConnectionPool(self.host, self.https_port, retries=False) as p:
            for i in range(2):
                if i == 0:
                    resp = p.request("GET", "/get")
                    assert resp.version == 20

                    continue

                with pytest.raises(SSLError, match="TLS over QUIC did not succeed"):
                    p.request("GET", "/get")
