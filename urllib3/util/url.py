from __future__ import absolute_import

from ..exceptions import LocationParseError
from ..packages import rfc3986
from ..packages import six


url_attrs = ['scheme', 'auth', 'host', 'port', 'path', 'query', 'fragment']


class Url(object):
    """
    Datastructure for representing an HTTP URL. Used as a return value for
    :func:`parse_url`. Both the scheme and host are normalized as they are
    both case-insensitive according to RFC 3986.
    """

    def __init__(self, scheme=None, auth=None, host=None, port=None, path=None,
                 query=None, fragment=None, parse_result=None):
        if path and not path.startswith('/'):
            path = '/' + path
            if parse_result is not None:
                parse_result = parse_result.copy_with(path=path)

        if parse_result is None:
            parse_result = rfc3986.ParseResult.from_parts(
                scheme=scheme,
                userinfo=auth,
                host=host,
                port=port,
                path=path,
                query=query,
                fragment=fragment,
            )

        self._parseresult = parse_result

    def _replace(self, **kwargs):
        if 'auth' in kwargs:
            kwargs['userinfo'] = kwargs.pop('auth')

        return Url(parse_result=self._parseresult.copy_with(**kwargs))

    @property
    def scheme(self):
        return self._parseresult.scheme

    @property
    def auth(self):
        return self._parseresult.userinfo

    @property
    def host(self):
        return self._parseresult.host

    @property
    def hostname(self):
        """For backwards-compatibility with urlparse. We're nice like that."""
        return self.host

    @property
    def port(self):
        return self._parseresult.port

    @property
    def path(self):
        return self._parseresult.path

    @property
    def query(self):
        return self._parseresult.query

    @property
    def fragment(self):
        return self._parseresult.fragment

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
        url = self._parseresult.unsplit()
        if six.PY2:
            # NOTE(sigmavirus24): rfc3986 always returns a text-type. On Python 2,
            # __str__ cannot return unicode, so we have to encode to keep backwards
            # compatibility
            return url.encode('utf-8')
        return url

    def __str__(self):
        return self.url


def split_first(s, delims):
    """
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

    Partly backwards-compatible with :mod:`urlparse`.

    Example::

        >>> parse_url('http://google.com/mail/')
        Url(scheme='http', host='google.com', port=None, path='/mail/', ...)
        >>> parse_url('google.com:80')
        Url(scheme=None, host='google.com', port=80, path=None, ...)
        >>> parse_url('/foo?bar')
        Url(scheme=None, host=None, port=None, path='/foo', query='bar', ...)
    """

    # While this code has overlap with stdlib's urlparse, it is much
    # simplified for our needs and less annoying.
    # Additionally, this implementations does silly things to be optimal
    # on CPython.

    if not url:
        # Empty
        return Url()

    try:
        return Url(parse_result=rfc3986.urlparse(url))
    except (rfc3986.exceptions.InvalidAuthority, rfc3986.exceptions.InvalidPort):
        raise LocationParseError(url)


def get_host(url):
    """
    Deprecated. Use :func:`parse_url` instead.
    """
    p = parse_url(url)
    return p.scheme or 'http', p.hostname, p.port
