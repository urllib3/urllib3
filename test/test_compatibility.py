from __future__ import annotations

import http.cookiejar
import urllib
from unittest import mock

import pytest

import urllib3.http2
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.http2.connection import (
    HTTP2CleartextConnection,
    HTTP2Connection,
    HTTP2UpgradeConnection,
)
from urllib3.response import HTTPResponse


class TestCookiejar:
    def test_extract(self) -> None:
        request = urllib.request.Request("http://google.com")
        cookiejar = http.cookiejar.CookieJar()
        response = HTTPResponse()

        cookies = [
            "sessionhash=abcabcabcabcab; path=/; HttpOnly",
            "lastvisit=1348253375; expires=Sat, 21-Sep-2050 18:49:35 GMT; path=/",
        ]
        for c in cookies:
            response.headers.add("set-cookie", c)
        cookiejar.extract_cookies(response, request)  # type: ignore[arg-type]
        assert len(cookiejar) == len(cookies)


class TestInitialization:
    @mock.patch("urllib3.http2.version")
    def test_h2_version_check(self, mock_version: mock.MagicMock) -> None:
        try:
            mock_version.return_value = "4.1.0"
            urllib3.http2.inject_into_urllib3()

            mock_version.return_value = "3.9.9"
            with pytest.raises(
                ImportError, match="urllib3 v2 supports h2 version 4.x.x.*"
            ):
                urllib3.http2.inject_into_urllib3()

            mock_version.return_value = "5.0.0"
            with pytest.raises(
                ImportError, match="urllib3 v2 supports h2 version 4.x.x.*"
            ):
                urllib3.http2.inject_into_urllib3()
        finally:
            urllib3.http2.extract_from_urllib3()

    def test_h2c_injection_is_opt_in(self) -> None:
        try:
            urllib3.http2.inject_into_urllib3()

            assert HTTPSConnectionPool.ConnectionCls is HTTP2Connection
            assert HTTPConnectionPool.ConnectionCls is HTTPConnection
        finally:
            urllib3.http2.extract_from_urllib3()

    def test_h2c_injection(self) -> None:
        try:
            urllib3.http2.inject_into_urllib3(h2c=True)

            assert HTTPSConnectionPool.ConnectionCls is HTTP2Connection
            assert HTTPConnectionPool.ConnectionCls is HTTP2CleartextConnection
        finally:
            urllib3.http2.extract_from_urllib3()

        assert HTTPSConnectionPool.ConnectionCls is HTTPSConnection
        assert HTTPConnectionPool.ConnectionCls is HTTPConnection

    def test_h2c_prior_knowledge_injection(self) -> None:
        try:
            urllib3.http2.inject_into_urllib3(h2c="prior_knowledge")

            assert HTTPSConnectionPool.ConnectionCls is HTTP2Connection
            assert HTTPConnectionPool.ConnectionCls is HTTP2CleartextConnection
        finally:
            urllib3.http2.extract_from_urllib3()

    def test_h2c_upgrade_injection(self) -> None:
        try:
            urllib3.http2.inject_into_urllib3(h2c="upgrade")

            assert HTTPSConnectionPool.ConnectionCls is HTTP2Connection
            assert HTTPConnectionPool.ConnectionCls is HTTP2UpgradeConnection
        finally:
            urllib3.http2.extract_from_urllib3()

    def test_h2c_injection_rejects_unknown_mode(self) -> None:
        try:
            with pytest.raises(ValueError):
                urllib3.http2.inject_into_urllib3(h2c="unknown")  # type: ignore[arg-type]

            assert HTTPSConnectionPool.ConnectionCls is HTTPSConnection
            assert HTTPConnectionPool.ConnectionCls is HTTPConnection
        finally:
            urllib3.http2.extract_from_urllib3()

    def test_repeated_h2c_injection_can_disable_h2c(self) -> None:
        try:
            urllib3.http2.inject_into_urllib3(h2c="upgrade")
            urllib3.http2.inject_into_urllib3()

            assert HTTPSConnectionPool.ConnectionCls is HTTP2Connection
            assert HTTPConnectionPool.ConnectionCls is HTTPConnection
        finally:
            urllib3.http2.extract_from_urllib3()

    def test_repeated_h2c_injection_restores_original_connections(self) -> None:
        try:
            urllib3.http2.inject_into_urllib3(h2c="upgrade")
            urllib3.http2.inject_into_urllib3(h2c="prior_knowledge")

            assert HTTPSConnectionPool.ConnectionCls is HTTP2Connection
            assert HTTPConnectionPool.ConnectionCls is HTTP2CleartextConnection
        finally:
            urllib3.http2.extract_from_urllib3()

        assert HTTPSConnectionPool.ConnectionCls is HTTPSConnection
        assert HTTPConnectionPool.ConnectionCls is HTTPConnection
