from __future__ import absolute_import
import re
from collections import namedtuple

from ..exceptions import LocationParseError
from ..packages import six, rfc3986
from ..packages.rfc3986.exceptions import RFC3986Exception, ValidationError
from ..packages.rfc3986.validators import Validator
from ..packages.rfc3986.normalizers import normalize_host


url_attrs = ['scheme', 'auth', 'host', 'port', 'path', 'query', 'fragment']

# We only want to normalize urls with an HTTP(S) scheme.
# urllib3 infers URLs without a scheme (None) to be http.
NORMALIZABLE_SCHEMES = ('http', 'https', None)

# Regex for detecting URLs with schemes. RFC 3986 Section 3.1
SCHEME_REGEX = re.compile(r"^[a-zA-Z][a-zA-Z0-9+\-]*:")


class Url(namedtuple('Url', url_attrs)):
    """
    Data structure for representing an HTTP URL. Used as a return value for
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
    if not is_string:
        url = url.decode("utf-8")

    # RFC 3986 doesn't like URLs that have a host but don't start
    # with a scheme and we support URLs like that so we need to
    # detect that problem and add an empty scheme indication.
    # We don't get hurt on path-only URLs here as it's stripped
    # off and given an empty scheme anyways.
    if not SCHEME_REGEX.search(url):
        url = "//" + url

    try:
        iri_ref = rfc3986.IRIReference.from_string(url, encoding="utf-8")
    except (ValueError, RFC3986Exception):
        raise LocationParseError(url)

    def idna_encode(name):
        if name and any([ord(x) > 128 for x in name]):
            try:
                import idna
            except ImportError:
                raise LocationParseError("Unable to parse URL without the 'idna' module")
            try:
                return idna.encode(name, strict=True, std3_rules=True).lower()
            except idna.IDNAError:
                raise LocationParseError(u"Name '%s' is not a valid IDNA label" % name)
        return name

    has_authority = iri_ref.authority is not None
    uri_ref = iri_ref.encode(idna_encoder=idna_encode)
    if has_authority and uri_ref.authority is None:
        raise LocationParseError(url)

    if uri_ref.scheme in NORMALIZABLE_SCHEMES:
        uri_ref = uri_ref.normalize()

    # Run validator on the internal URIReference within the ParseResult
    validator = Validator()
    try:
        validator.check_validity_of(
            *validator.COMPONENT_NAMES
        ).validate(uri_ref)
    except ValidationError:
        raise LocationParseError(url)

    # For the sake of backwards compatibility we put empty
    # string values for path if there are any defined values
    # beyond the path in the URL.
    # TODO: Remove this when we break backwards compatibility.
    path = uri_ref.path
    if not path:
        if (uri_ref.query is not None
                or uri_ref.fragment is not None):
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
        scheme=to_input_type(uri_ref.scheme),
        auth=to_input_type(uri_ref.userinfo),
        host=to_input_type(uri_ref.host),
        port=int(uri_ref.port) if uri_ref.port is not None else None,
        path=to_input_type(path),
        query=to_input_type(uri_ref.query),
        fragment=to_input_type(uri_ref.fragment)
    )


def get_host(url):
    """
    Deprecated. Use :func:`parse_url` instead.
    """
    p = parse_url(url)
    return p.scheme or 'http', p.hostname, p.port
