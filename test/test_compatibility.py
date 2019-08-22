from urllib3.response import HTTPResponse
from urllib3.packages.six.moves import http_cookiejar, urllib


class TestCookiejar(object):
    def test_extract(self):
        request = urllib.request.Request("http://google.com")
        cookiejar = http_cookiejar.CookieJar()
        response = HTTPResponse()

        cookies = [
            "sessionhash=abcabcabcabcab; path=/; HttpOnly",
            "lastvisit=1348253375; expires=Sat, 21-Sep-2050 18:49:35 GMT; path=/",
        ]
        for c in cookies:
            response.headers.add("set-cookie", c)
        cookiejar.extract_cookies(response, request)
        assert len(cookiejar) == len(cookies)
