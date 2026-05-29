from __future__ import annotations

import http.cookiejar
import urllib
from unittest import mock

import pytest

import urllib3.http2
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

    def test_extract_obsolete_folded_set_cookie(self) -> None:
        request = urllib.request.Request("http://google.com")
        cookiejar = http.cookiejar.CookieJar()
        response = HTTPResponse(
            headers={
                "set-cookie": "___utmvbtouVBFmB=gZg\r\n    XbNOjalT: Lte; path=/; Max-Age=900"
            },
            status=200,
            version=11,
            version_string="HTTP/1.1",
            reason="OK",
            preload_content=False,
            decode_content=False,
        )

        cookiejar.extract_cookies(response, request)  # type: ignore[arg-type]

        assert len(cookiejar) == 1
        cookie = next(iter(cookiejar))
        assert cookie.value == "gZg XbNOjalT: Lte"
        assert "\r" not in cookie.value
        assert "\n" not in cookie.value


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
