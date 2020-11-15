import http.cookiejar
import urllib

import pytest

from urllib3.connection import HTTPConnection
from urllib3.response import HTTPResponse


class TestVersionCompatibility:
    def test_connection_source_address(self):
        try:
            # source_address does not exist in Py26-
            HTTPConnection("localhost", 12345, source_address="127.0.0.1")
        except TypeError as e:
            pytest.fail(f"HTTPConnection raised TypeError on source_address: {e!r}")


class TestCookiejar:
    def test_extract(self):
        request = urllib.request.Request("http://google.com")
        cookiejar = http.cookiejar.CookieJar()
        response = HTTPResponse()

        cookies = [
            "sessionhash=abcabcabcabcab; path=/; HttpOnly",
            "lastvisit=1348253375; expires=Sat, 21-Sep-2050 18:49:35 GMT; path=/",
        ]
        for c in cookies:
            response.headers.add("set-cookie", c)
        cookiejar.extract_cookies(response, request)
        assert len(cookiejar) == len(cookies)
