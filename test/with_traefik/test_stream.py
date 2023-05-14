from __future__ import annotations

from json import JSONDecodeError, loads

import pytest

from urllib3 import HTTPSConnectionPool

from . import TraefikTestCase


class TestStreamResponse(TraefikTestCase):
    @pytest.mark.parametrize(
        "amt",
        [
            None,
            1,
            3,
            5,
            16,
            64,
            1024,
            16544,
        ],
    )
    def test_h2n3_stream(self, amt: int | None) -> None:
        with HTTPSConnectionPool(
            self.host, self.https_port, ca_certs=self.ca_mkcert
        ) as p:
            for i in range(3):
                resp = p.request("GET", "/get", preload_content=False)

                assert resp.status == 200
                assert resp.version == (20 if i == 0 else 30)

                chunks = []

                for chunk in resp.stream(amt):
                    chunks.append(chunk)

                try:
                    payload_reconstructed = loads(b"".join(chunks))
                except JSONDecodeError as e:
                    print(e)
                    payload_reconstructed = None

                assert (
                    payload_reconstructed is not None
                ), f"HTTP/{resp.version/10} stream failure"
                assert (
                    "args" in payload_reconstructed
                ), f"HTTP/{resp.version/10} stream failure"

    def test_read_zero(self) -> None:
        with HTTPSConnectionPool(
            self.host, self.https_port, ca_certs=self.ca_mkcert
        ) as p:
            resp = p.request("GET", "/get", preload_content=False)
            assert resp.status == 200

            assert resp.read(0) == b""

            for i in range(5):
                assert len(resp.read(1)) == 1

            assert resp.read(0) == b""
            assert len(resp.read()) > 0
