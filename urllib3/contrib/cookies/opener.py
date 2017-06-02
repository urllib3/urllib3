#!/usr/bin/python3

__author__ = 'Andrew Wang'

try: # Python 3
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.util import get_host, make_headers

from .structure import CookieSession

__all__ = ("opener", "RegularOpener", "SecureOpener")

#UA = "Mozilla/5.0 (X11; Linux x86_64; rv:14.0) Gecko/20100101 Firefox/14.0.1"
UA = None
headers = make_headers(keep_alive=True, accept_encoding=["gzip", "deflate"], user_agent=UA)
headers["cookie"] = ""

def opener(url, **opener_kwargs):
    o = urlparse(url)
    print(o)
    if not o.scheme and not o.netloc:
        url = "http://" + url
        return opener(url, **opener_kwargs)
    openers_by_scheme = {"http": RegularOpener, "https": SecureOpener}
    return openers_by_scheme[o.scheme](url, **opener_kwargs)

class RegularOpener(HTTPConnectionPool):
    def __init__(self, host, port=None, strict=False,
                 timeout=None, maxsize=1, block=False, headers=headers):
        try:
            host = get_host(host)[1]
        except TypeError: # Already a host-ified host
            pass
        headers = {k.lower(): v for (k, v) in headers.items()}
        HTTPConnectionPool.__init__(self, host, port, strict, timeout, maxsize, block, headers)
        self.cookie_session = CookieSession()

    def urlopen(self, method, url, body=None, headers=None, retries=3, redirect=True, assert_same_host=True,
                timeout=None, pool_timeout=None, release_conn=None, **response_kw):
        """
        Same as :meth:`urllib3.connectionpool.HTTPConnectionPool.urlopen`
        with custom cross-host redirect logic and only sends the request-uri
        portion of the ``url``.

        The given ``url`` parameter must be absolute, such that an appropriate
        :class:`urllib3.connectionpool.ConnectionPool` can be chosen for it.
        """
        if headers is None:
            headers = {k.lower(): v for (k, v) in self.headers.items()}
        headers.setdefault("cookie", "")
        for key, val in self.headers.items():
            headers.setdefault(key, val)
        # Now the updated Cookie string will be stored into the HTTP request.
        # The cookie header may contain duplicate entries (e.g. k=a; k=b;)
        headers["cookie"] = self.headers["cookie"] + headers["cookie"]
        # This will be resolved by putting the header in the SimpleCookie
        self.cookie_session.feed(self.headers)
        self.cookie_session.feed(headers)
        headers["cookie"] = self.cookie_session.extract()
        response = HTTPConnectionPool.urlopen(self, method, url, body, headers, retries, False, assert_same_host, timeout, pool_timeout,
            release_conn, **response_kw)
        self.cookie_session.feed(self.headers)
        self.cookie_session.feed(response.headers)
        self.cookie_session.feed(headers)
        headers["cookie"] = self.cookie_session.extract()
        redirect_location = redirect and response.get_redirect_location()
        if not redirect_location:
            return response
        if response.status == 303:
            method = "GET"
        return self.urlopen(method, redirect_location, body, headers, retries - 1, redirect, assert_same_host, timeout, pool_timeout,
            release_conn, **response_kw)

class SecureOpener(HTTPSConnectionPool, RegularOpener):
    def __init__(self, host, port=None, strict=False, timeout=None, maxsize=1, block=False, headers=headers, key_file=None,
                 cert_file=None, cert_reqs="CERT_NONE", ca_certs=None):
        RegularOpener.__init__(self, host, port, strict, timeout, maxsize, block, headers)
        HTTPSConnectionPool.__init__(self, host, port, strict, timeout, maxsize, block, headers, key_file, cert_file, cert_reqs, ca_certs)

    def urlopen(self, *args, **kwargs):
        return RegularOpener.urlopen(self, *args, **kwargs)