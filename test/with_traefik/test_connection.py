from __future__ import annotations

from http.client import ResponseNotReady

import pytest

from urllib3 import HttpVersion
from urllib3.connection import HTTPSConnection

from . import TraefikTestCase


class TestConnection(TraefikTestCase):
    def test_h3_probe_after_close(self) -> None:
        conn = HTTPSConnection(self.host, self.https_port, ca_certs=self.ca_mkcert)

        conn.request("GET", "/get")

        resp = conn.getresponse()

        assert resp.version == 20

        conn.close()

        conn.connect()

        conn.request("GET", "/get")

        resp = conn.getresponse()

        assert resp.version == 30

        conn.close()

    def test_h2_svn_conserved(self) -> None:
        conn = HTTPSConnection(
            self.host,
            self.https_port,
            ca_certs=self.ca_mkcert,
            disabled_svn={HttpVersion.h3},
        )

        conn.request("GET", "/get")

        resp = conn.getresponse()

        assert resp.version == 20

        conn.close()

        assert hasattr(conn, "_http_vsn") and conn._http_vsn == 20

        conn.connect()

        conn.request("GET", "/get")

        resp = conn.getresponse()

        assert resp.version == 20

    def test_getresponse_not_ready(self) -> None:
        conn = HTTPSConnection(
            self.host,
            self.https_port,
            ca_certs=self.ca_mkcert,
        )

        conn.close()

        with pytest.raises(ResponseNotReady):
            conn.getresponse()

    def test_quic_cache_capable(self) -> None:
        quic_cache_resumption: dict[tuple[str, int], tuple[str, int] | None] = {
            (self.host, self.https_port): ("", self.https_port)
        }

        conn = HTTPSConnection(
            self.host,
            self.https_port,
            ca_certs=self.ca_mkcert,
            preemptive_quic_cache=quic_cache_resumption,
        )

        conn.request("GET", "/get")
        resp = conn.getresponse()

        assert resp.status == 200
        assert resp.version == 30

    def test_quic_cache_capable_but_disabled(self) -> None:
        quic_cache_resumption: dict[tuple[str, int], tuple[str, int] | None] = {
            (self.host, self.https_port): ("", self.https_port)
        }

        conn = HTTPSConnection(
            self.host,
            self.https_port,
            ca_certs=self.ca_mkcert,
            preemptive_quic_cache=quic_cache_resumption,
            disabled_svn={HttpVersion.h3},
        )

        conn.request("GET", "/get")
        resp = conn.getresponse()

        assert resp.status == 200
        assert resp.version == 20

    def test_quic_cache_explicit_not_capable(self) -> None:
        quic_cache_resumption: dict[tuple[str, int], tuple[str, int] | None] = {
            (self.host, self.https_port): None
        }

        conn = HTTPSConnection(
            self.host,
            self.https_port,
            ca_certs=self.ca_mkcert,
            preemptive_quic_cache=quic_cache_resumption,
        )

        conn.request("GET", "/get")
        resp = conn.getresponse()

        assert resp.status == 200
        assert resp.version == 20

    def test_quic_cache_implicit_not_capable(self) -> None:
        quic_cache_resumption: dict[tuple[str, int], tuple[str, int] | None] = dict()

        conn = HTTPSConnection(
            self.host,
            self.https_port,
            ca_certs=self.ca_mkcert,
            preemptive_quic_cache=quic_cache_resumption,
        )

        conn.request("GET", "/get")
        resp = conn.getresponse()

        assert resp.status == 200
        assert resp.version == 20

        assert len(quic_cache_resumption.keys()) == 1
        assert (self.host, self.https_port) in quic_cache_resumption
