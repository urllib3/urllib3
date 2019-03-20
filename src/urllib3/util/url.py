from __future__ import absolute_import
import re
from collections import namedtuple

from ..exceptions import LocationParseError
from ..packages import six, rfc3986
from ..packages.rfc3986.exceptions import RFC3986Exception


url_attrs = ['scheme', 'auth', 'host', 'port', 'path', 'query', 'fragment']

# We only want to normalize urls with an HTTP(S) scheme.
# urllib3 infers URLs without a scheme (None) to be http.
NORMALIZABLE_SCHEMES = ('http', 'https', None)

# Regex for detecting URLs with schemes. RFC 3986 Section 3.1
SCHEME_REGEX = re.compile(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://")


class Url(namedtuple('Url', url_attrs)):
    """
    Datastructure for representing an HTTP URL. Used as a return value for
    :func:`parse_url`. Both the scheme and host are normalized as they are
    both case-insensitive according to RFC 3986.
    """
    __slots__ = ()

    def __new__(cls, scheme=None, auth=None, host=None, port=None, path=None,
                query=None, fragment=None):
        if path and not path.startswith('/'):
            path = '/' + path
        if scheme:
            scheme = scheme.lower()
        if host and scheme in NORMALIZABLE_SCHEMES:
            host = host.lower()
        return super(Url, cls).__new__(cls, scheme, auth, host, port, path,
                                       query, fragment)

    @property
    def hostname(self):
        """For backwards-compatibility with urlparse. We're nice like that."""
        return self.host

    @property
    def request_uri(self):
        """Absolute path including the query string."""
        uri = self.path or '/'

        if self.query is not None:
            uri += '?' + self.query

        return uri

    @property
    def netloc(self):
        """Network location including host and port"""
        if self.port:
            return '%s:%d' % (self.host, self.port)
        return self.host

    @property
    def url(self):
        """
        Convert self into a url

        This function should more or less round-trip with :func:`.parse_url`. The
        returned url may not be exactly the same as the url inputted to
        :func:`.parse_url`, but it should be equivalent by the RFC (e.g., urls
        with a blank port will have : removed).

        Example: ::

            >>> U = parse_url('http://google.com/mail/')
            >>> U.url
            'http://google.com/mail/'
            >>> Url('http', 'username:password', 'host.com', 80,
            ... '/path', 'query', 'fragment').url
            'http://username:password@host.com:80/path?query#fragment'
        """
        scheme, auth, host, port, path, query, fragment = self
        url = ''

        # We use "is not None" we want things to happen with empty strings (or 0 port)
        if scheme is not None:
            url += scheme + '://'
        if auth is not None:
            url += auth + '@'
        if host is not None:
            url += host
        if port is not None:
            url += ':' + str(port)
        if path is not None:
            url += path
        if query is not None:
            url += '?' + query
        if fragment is not None:
            url += '#' + fragment

        return url

    def __str__(self):
        return self.url


def split_first(s, delims):
    """
    Deprecated. No longer used by parse_url().

    Given a string and an iterable of delimiters, split on the first found
    delimiter. Return two split parts and the matched delimiter.

    If not found, then the first part is the full input string.

    Example::

        >>> split_first('foo/bar?baz', '?/=')
        ('foo', 'bar?baz', '/')
        >>> split_first('foo/bar?baz', '123')
        ('foo/bar?baz', '', None)

    Scales linearly with number of delims. Not ideal for large number of delims.
    """
    min_idx = None
    min_delim = None
    for d in delims:
        idx = s.find(d)
        if idx < 0:
            continue

        if min_idx is None or idx < min_idx:
            min_idx = idx
            min_delim = d

    if min_idx is None or min_idx < 0:
        return s, '', None

    return s[:min_idx], s[min_idx + 1:], min_delim


def parse_url(url):
    """
    Given a url, return a parsed :class:`.Url` namedtuple. Best-effort is
    performed to parse incomplete urls. Fields not provided will be None.
    This parser is RFC 3986 compliant.

    :param str url: URL to parse into a :class:`.Url` namedtuple.

    Partly backwards-compatible with :mod:`urlparse`.

    Example::

        >>> parse_url('http://google.com/mail/')
        Url(scheme='http', host='google.com', port=None, path='/mail/', ...)
        >>> parse_url('google.com:80')
        Url(scheme=None, host='google.com', port=80, path=None, ...)
        >>> parse_url('/foo?bar')
        Url(scheme=None, host=None, port=None, path='/foo', query='bar', ...)
    """
    if not url:
        # Empty
        return Url()

    is_string = not isinstance(url, six.binary_type)

    # RFC 3986 doesn't like URLs that have a host but don't start
    # with a scheme and we support URLs like that so we need to
    # detect that problem and add an empty scheme indication.
    # We don't get hurt on path-only URLs here as it's stripped
    # off and given an empty scheme anyways.
    if not SCHEME_REGEX.search(url):
        url = "//" + url

    try:
        parse_result = rfc3986.urlparse(url, encoding="utf-8")
    except (ValueError, RFC3986Exception):
        raise LocationParseError(url)

    # RFC 3986 doesn't assert ports must be non-negative.
    if parse_result.port and parse_result.port < 0:
        raise LocationParseError(url)

    # For the sake of backwards compatibility we put empty
    # string values for path if there are any defined values
    # beyond the path in the URL.
    # TODO: Remove this when we break backwards compatibility.
    path = parse_result.path
    if not path:
        if (parse_result.query is not None
                or parse_result.fragment is not None):
            path = ""
        else:
            path = None

    # Ensure that each part of the URL is a `str` for
    # backwards compatibility.
    def to_input_type(x):
        if x is None:
            return None
        elif not is_string and not isinstance(x, six.binary_type):
            return x.encode('utf-8')
        return x

    return Url(
        scheme=to_input_type(parse_result.scheme),
        auth=to_input_type(parse_result.userinfo),
        host=to_input_type(parse_result.hostname),
        port=parse_result.port,
        path=to_input_type(path),
        query=to_input_type(parse_result.query),
        fragment=to_input_type(parse_result.fragment)
    )


def get_host(url):
    """
    Deprecated. Use :func:`parse_url` instead.
    """
    p = parse_url(url)
    return p.scheme or 'http', p.hostname, p.port
