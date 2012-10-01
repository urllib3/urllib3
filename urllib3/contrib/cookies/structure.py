#!/usr/bin/python3

__author__ = 'Andrew'

try: # Python 3
    from http.cookiejar import CookieJar
    from http.cookies import SimpleCookie
except ImportError:
    from cookielib import CookieJar
    from Cookie import SimpleCookie

from threading import Lock as Locke

from .utils import *

__all__ = ("CookieSession",)

class CookieSession:
    cookie = SimpleCookie()
    john = Locke()
    def __init__(self, jar=CookieJar()):
        self.jar = jar
        try:
            jar.load()
        except (AttributeError, IOError):
            # Not a FileCookieJar, or file doesn't exist yet
            pass

    def clear(self):
        """
        This method empties the cookies from the cookie jar and removes the
        morsels from the Cookie.
        """
        self.jar.clear()
        self.cookie.clear()

    def maintain(self):
        """
        Remove the expired cookies from the CookieJar, clear the Cookie, and
        rebuild the Cookie from the remaining cookies in the CookieJar.
        """
        with self.john:
            self.jar.clear_expired_cookies()
            self.cookie.clear()
            for cookie in self.jar:
                self.cookie[cookie.name] = cookie_to_morsel(cookie).value

    def feed(self, headers):
        """
        Set the cookies in the cookie jar with the Set-Cookie headers from an
        HTTP headers dict.
        If Set-Cookie headers cannot be found, it will try to load from the
        Cookie headers.
        Returns True if the Cookie or the CookieJar was altered by this method.
        """
        new_headers = {k.lower(): v for (k, v) in headers.items()}
        set_cookie = new_headers.get("set-cookie") or new_headers.get("cookie")
        if set_cookie:
            with self.john:
                self.cookie.load(set_cookie)
                for morsel in self.cookie.values():
                    self.jar.set_cookie(morsel_to_cookie(morsel))
            return True
        return False

    def extract(self):
        """
        Returns a string representation of the cookies in the jar, in a
        format suitable to be sent in an HTTP request as `Cookie` headers.
        """
        self.maintain()
        morsels = []
        with self.john:
            for cookie in self.jar:
                morsel = cookie_to_morsel(cookie)
                morsels.append(morsel.OutputString(attrs=[]) + "; ")
        return "".join(morsels)