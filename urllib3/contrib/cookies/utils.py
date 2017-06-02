#!/usr/bin/python3

# Stuff here was stolen from requests

try:
    from http.cookiejar import Cookie
    from http.cookies import SimpleCookie
except ImportError:
    from cookielib import Cookie
    from Cookie import SimpleCookie

from datetime import datetime
from time import mktime, gmtime

def create_cookie(name, value, **kwargs):
    """Make a cookie from underspecified parameters.
    By default, the pair of `name` and `value` will be set for the domain ''
    and sent on every request (this is sometimes called a "supercookie").
    """
    result = dict(
        version=0,
        name=name,
        value=value,
        port=None,
        domain='',
        path='/',
        secure=False,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={"HttpOnly": None},
        rfc2109=False,
    )
    if kwargs.get("path") in ("", "/,"):
        del kwargs["path"]
    badargs = set(kwargs) - set(result)
    if badargs:
        err = "create_cookie() got unexpected keyword arguments: %s"
        raise TypeError(err % list(badargs))
    result.update(kwargs)
    result["port_specified"] = bool(result["port"])
    result["domain_specified"] = bool(result["domain"])
    result["domain_initial_dot"] = result["domain"].startswith(".")
    result["path_specified"] = bool(result["path"])
    return Cookie(**result)

def morsel_to_cookie(morsel):
    """Convert a Morsel object into a Cookie containing the one k/v pair."""
    expiry = morsel["max-age"] or morsel["expires"]
    try:
        # Is the expiry a date string (expires) or number (max-age)?
        float(expiry)
    except ValueError:
        # The expiry is a date string, use strptime
        try:
            expiry = mktime(datetime.strptime(expiry, "%a, %d-%b-%Y %H:%M:%S %Z").timetuple())
        except ValueError:
            # There is no expiry
            expiry = None
    else:
        # The expiry is a max-age, use numbers
        expiry = int(mktime(gmtime()) + float(expiry))
    c = create_cookie(
        name=morsel.key,
        value=morsel.value,
        version=morsel['version'] or 0,
        domain=morsel['domain'],
        path=morsel['path'],
        secure=bool(morsel['secure']),
        expires=expiry,
        discard=False,
        rest={'HttpOnly': morsel['httponly']}
    )
    return c

def cookie_to_morsel(cookie):
    c = SimpleCookie()
    m_info = dict(expires=cookie.expires,
        path=cookie.path,
        comment=cookie.comment,
        domain=cookie.domain,
        secure=False,
        version=0,
        httponly=False
    )
    c[cookie.name] = cookie.value
    for k, v in m_info.items():
        c[cookie.name][k] = v
    return c[cookie.name]