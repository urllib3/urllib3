from __future__ import annotations

from base64 import b64decode
from io import BytesIO

import pytest

from urllib3 import HTTPSConnectionPool

from . import TraefikTestCase


class TestPostBody(TraefikTestCase):
    def test_overrule_unicode_content_length(self) -> None:
        with HTTPSConnectionPool(
            self.host, self.https_port, ca_certs=self.ca_mkcert
        ) as p:
            resp = p.request("POST", "/post", body="🚀", headers={"Content-Length": "1"})

            assert resp.status == 200
            assert "Content-Length" in resp.json()["headers"]
            assert resp.json()["headers"]["Content-Length"][0] == "4"

    @pytest.mark.parametrize(
        "method",
        [
            "POST",
            "PUT",
            "PATCH",
        ],
    )
    @pytest.mark.parametrize(
        "body",
        [
            "This is a rocket 🚀!",
            "This is a rocket 🚀!".encode(),
            BytesIO(b"foo" * 100),
            b"x" * 10,
            BytesIO(b"x" * 64),
            b"foo\r\n",  # meant to verify that function unpack_chunk() in method send() work in edge cases
            BytesIO(b"foo\r\n"),
        ],
    )
    def test_h2n3_data(self, method: str, body: bytes | str | BytesIO) -> None:
        with HTTPSConnectionPool(
            self.host, self.https_port, ca_certs=self.ca_mkcert
        ) as p:
            for i in range(3):
                if isinstance(body, BytesIO):
                    body.seek(0, 0)

                resp = p.request(method, f"/{method.lower()}", body=body)

                assert resp.status == 200
                assert resp.version == (20 if i == 0 else 30)

                print(resp.json()["data"])

                payload_seen_by_server: bytes = b64decode(resp.json()["data"][37:])

                if isinstance(body, str):
                    assert payload_seen_by_server == body.encode(
                        "utf-8"
                    ), f"HTTP/{resp.version/10} POST body failure: str"
                elif isinstance(body, bytes):
                    assert (
                        payload_seen_by_server == body
                    ), f"HTTP/{resp.version/10} POST body failure: bytes"
                else:
                    body.seek(0, 0)
                    assert (
                        payload_seen_by_server == body.read()
                    ), f"HTTP/{resp.version/10} POST body failure: BytesIO"

    @pytest.mark.parametrize(
        "method",
        [
            "POST",
            "PUT",
            "PATCH",
        ],
    )
    @pytest.mark.parametrize(
        "fields",
        [
            {"a": "c", "d": "f", "foo": "bar"},
            {"bobaaz": "really confident"},
            {"z": "", "o": "klm"},
        ],
    )
    def test_h2n3_form_field(self, method: str, fields: dict[str, str]) -> None:
        with HTTPSConnectionPool(
            self.host, self.https_port, ca_certs=self.ca_mkcert
        ) as p:
            for i in range(2):
                resp = p.request(method, f"/{method.lower()}", fields=fields)

                assert resp.status == 200
                assert resp.version == (20 if i == 0 else 30)

                payload = resp.json()

                for key in fields:
                    assert key in payload["form"]
                    assert fields[key] in payload["form"][key]
