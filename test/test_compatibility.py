from __future__ import annotations

import http.cookiejar
import urllib
import pytest
from unittest import mock

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
    def test_h2_version_check(self) -> None:
        with mock.patch.dict('sys.modules', {}):
            import src.urllib3

        mock_h2 = mock.Mock()

        mock_h2.__version__ = '4.1.0'
        with mock.patch.dict('sys.modules', {'h2': mock_h2}):
            import src.urllib3

        mock_h2.__version__ = '3.9.9'
        with mock.patch.dict('sys.modules', {'h2': mock_h2}):
            with pytest.raises(ImportError) as excinfo:
                import src.urllib3
            assert "h2 version 4.x.x" in str(excinfo.value)

        mock_h2.__version__ = '5.0.0'
        with mock.patch.dict('sys.modules', {'h2': mock_h2}):
            with pytest.raises(ImportError) as excinfo:
                import src.urllib3
            assert "h2 version 4.x.x" in str(excinfo.value)