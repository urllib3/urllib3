from __future__ import annotations

import pytest

from urllib3 import HTTPHeaderDict, HTTPSConnectionPool, request
from urllib3.exceptions import ProtocolError
from urllib3.util.request import SKIP_HEADER

from . import TraefikTestCase


class TestProtocolLevel(TraefikTestCase):
    def test_forbid_request_without_authority(self) -> None:
        with pytest.raises(
            ProtocolError,
            match="do not support emitting HTTP requests without the `Host` header",
        ):
            request(
                "GET",
                f"{self.https_url}/get",
                headers={"Host": SKIP_HEADER},
                retries=False,
            )

    @pytest.mark.parametrize(
        "headers",
        [
            [(f"x-urllib3-{p}", str(p)) for p in range(8)],
            [(f"x-urllib3-{p}", str(p)) for p in range(8)]
            + [(f"x-urllib3-{p}", str(p)) for p in range(16)],
            [("x-www-not-standard", "hello!world!")],
        ],
    )
    def test_headers(self, headers: list[tuple[str, str]]) -> None:
        dict_headers = dict(headers)

        with HTTPSConnectionPool(
            self.host, self.https_port, ca_certs=self.ca_mkcert
        ) as p:
            resp = p.request(
                "GET",
                f"{self.https_url}/headers",
                headers=dict_headers,
                retries=False,
            )

            assert resp.status == 200

            temoin = HTTPHeaderDict(dict_headers)
            payload = resp.json()

            seen = []

            for key, value in payload["headers"].items():
                if key in temoin:
                    seen.append(key)
                    assert temoin.get(key) in value

            assert len(seen) == len(dict_headers.keys())
