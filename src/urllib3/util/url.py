import re
import typing

from ..exceptions import LocationParseError
from .util import to_str

# We only want to normalize urls with an HTTP(S) scheme.
# urllib3 infers URLs without a scheme (None) to be http.
_NORMALIZABLE_SCHEMES = ("http", "https", None)

# Almost all of these patterns were derived from the
# 'rfc3986' module: https://github.com/python-hyper/rfc3986
_PERCENT_RE = re.compile(r"%[a-fA-F0-9]{2}")
_SCHEME_RE = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+-]*:|/)")
_URI_RE = re.compile(
    r"^(?:([a-zA-Z][a-zA-Z0-9+.-]*):)?"
    r"(?://([^\\/?#]*))?"
    r"([^?#]*)"
    r"(?:\?([^#]*))?"
    r"(?:#(.*))?$",
    re.UNICODE | re.DOTALL,
)

_IPV4_PAT = r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}"
_HEX_PAT = "[0-9A-Fa-f]{1,4}"
_LS32_PAT = "(?:{hex}:{hex}|{ipv4})".format(hex=_HEX_PAT, ipv4=_IPV4_PAT)
_subs = {"hex": _HEX_PAT, "ls32": _LS32_PAT}
_variations = [
    #                            6( h16 ":" ) ls32
    "(?:%(hex)s:){6}%(ls32)s",
    #                       "::" 5( h16 ":" ) ls32
    "::(?:%(hex)s:){5}%(ls32)s",
    # [               h16 ] "::" 4( h16 ":" ) ls32
    "(?:%(hex)s)?::(?:%(hex)s:){4}%(ls32)s",
    # [ *1( h16 ":" ) h16 ] "::" 3( h16 ":" ) ls32
    "(?:(?:%(hex)s:)?%(hex)s)?::(?:%(hex)s:){3}%(ls32)s",
    # [ *2( h16 ":" ) h16 ] "::" 2( h16 ":" ) ls32
    "(?:(?:%(hex)s:){0,2}%(hex)s)?::(?:%(hex)s:){2}%(ls32)s",
    # [ *3( h16 ":" ) h16 ] "::"    h16 ":"   ls32
    "(?:(?:%(hex)s:){0,3}%(hex)s)?::%(hex)s:%(ls32)s",
    # [ *4( h16 ":" ) h16 ] "::"              ls32
    "(?:(?:%(hex)s:){0,4}%(hex)s)?::%(ls32)s",
    # [ *5( h16 ":" ) h16 ] "::"              h16
    "(?:(?:%(hex)s:){0,5}%(hex)s)?::%(hex)s",
    # [ *6( h16 ":" ) h16 ] "::"
    "(?:(?:%(hex)s:){0,6}%(hex)s)?::",
]

_UNRESERVED_PAT = (
    r"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._!\-~"
)
_IPV6_PAT = "(?:" + "|".join([x % _subs for x in _variations]) + ")"
_ZONE_ID_PAT = "(?:%25|%)(?:[" + _UNRESERVED_PAT + "]|%[a-fA-F0-9]{2})+"
_IPV6_ADDRZ_PAT = r"\[" + _IPV6_PAT + r"(?:" + _ZONE_ID_PAT + r")?\]"
_REG_NAME_PAT = r"(?:[^\[\]%:/?#]|%[a-fA-F0-9]{2})*"
_TARGET_RE = re.compile(r"^(/[^?#]*)(?:\?([^#]*))?(?:#.*)?$")

_IPV4_RE = re.compile("^" + _IPV4_PAT + "$")
_IPV6_RE = re.compile("^" + _IPV6_PAT + "$")
_IPV6_ADDRZ_RE = re.compile("^" + _IPV6_ADDRZ_PAT + "$")
_BRACELESS_IPV6_ADDRZ_RE = re.compile("^" + _IPV6_ADDRZ_PAT[2:-2] + "$")
_ZONE_ID_RE = re.compile("(" + _ZONE_ID_PAT + r")\]$")

_SUBAUTHORITY_PAT = ("^(?:(.*)@)?(%s|%s|%s)(?::([0-9]{0,5}))?$") % (
    _REG_NAME_PAT,
    _IPV4_PAT,
    _IPV6_ADDRZ_PAT,
)
_SUBAUTHORITY_RE = re.compile(_SUBAUTHORITY_PAT, re.UNICODE | re.DOTALL)

_UNRESERVED_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-~"
)
_SUB_DELIM_CHARS = set("!$&'()*+,;=")
_USERINFO_CHARS = _UNRESERVED_CHARS | _SUB_DELIM_CHARS | {":"}
_PATH_CHARS = _USERINFO_CHARS | {"@", "/"}
_QUERY_CHARS = _FRAGMENT_CHARS = _PATH_CHARS | {"?"}


class Url(
    typing.NamedTuple(
        "Url",
        [
            ("scheme", typing.Optional[str]),
            ("auth", typing.Optional[str]),
            ("host", typing.Optional[str]),
            ("port", typing.Optional[int]),
            ("path", typing.Optional[str]),
            ("query", typing.Optional[str]),
            ("fragment", typing.Optional[str]),
        ],
    )
):
    """
    Data structure for representing an HTTP URL. Used as a return value for
    :func:`parse_url`. Both the scheme and host are normalized as they are
    both case-insensitive according to RFC 3986.
    """

    def __new__(  # type: ignore
        cls,
        scheme: typing.Optional[str] = None,
        auth: typing.Optional[str] = None,
        host: typing.Optional[str] = None,
        port: typing.Optional[int] = None,
        path: typing.Optional[str] = None,
        query: typing.Optional[str] = None,
        fragment: typing.Optional[str] = None,
    ):
        if path and not path.startswith("/"):
            path = "/" + path
        if scheme is not None:
            scheme = scheme.lower()
        return super().__new__(cls, scheme, auth, host, port, path, query, fragment)

    @property
    def hostname(self) -> typing.Optional[str]:
        """For backwards-compatibility with urlparse. We're nice like that."""
        return self.host

    @property
    def request_uri(self) -> str:
        """Absolute path including the query string."""
        uri = self.path or "/"

        if self.query is not None:
            uri += "?" + self.query

        return uri

    @property
    def netloc(self) -> typing.Optional[str]:
        """Network location including host and port"""
        if self.host is None:
            return None
        if self.port:
            return f"{self.host}:{self.port}"
        return self.host

    @property
    def url(self) -> str:
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
        url = ""

        # We use "is not None" we want things to happen with empty strings (or 0 port)
        if scheme is not None:
            url += scheme + "://"
        if auth is not None:
            url += auth + "@"
        if host is not None:
            url += host
        if port is not None:
            url += ":" + str(port)
        if path is not None:
            url += path
        if query is not None:
            url += "?" + query
        if fragment is not None:
            url += "#" + fragment

        return url

    def __str__(self) -> str:
        return self.url


@typing.overload
def _encode_invalid_chars(
    component: str, allowed_chars: typing.Container[str]
) -> str:  # Abstract
    ...


@typing.overload
def _encode_invalid_chars(
    component: None, allowed_chars: typing.Container[str]
) -> None:  # Abstract
    ...


def _encode_invalid_chars(
    component: typing.Optional[str], allowed_chars: typing.Container[str]
) -> typing.Optional[str]:
    """Percent-encodes a URI component without reapplying
    onto an already percent-encoded component.
    """
    if component is None:
        return component

    component = to_str(component)

    # Normalize existing percent-encoded bytes.
    # Try to see if the component we're encoding is already percent-encoded
    # so we can skip all '%' characters but still encode all others.
    component, percent_encodings = _PERCENT_RE.subn(
        lambda match: match.group(0).upper(), component
    )

    uri_bytes = component.encode("utf-8", "surrogatepass")
    is_percent_encoded = percent_encodings == uri_bytes.count(b"%")
    encoded_component = bytearray()

    for i in range(0, len(uri_bytes)):
        # Will return a single character bytestring
        byte = uri_bytes[i : i + 1]
        byte_ord = ord(byte)
        if (is_percent_encoded and byte == b"%") or (
            byte_ord < 128 and byte.decode() in allowed_chars
        ):
            encoded_component += byte
            continue
        encoded_component.extend(b"%" + (hex(byte_ord)[2:].encode().zfill(2).upper()))

    return encoded_component.decode()


def _remove_path_dot_segments(path: str) -> str:
    # See http://tools.ietf.org/html/rfc3986#section-5.2.4 for pseudo-code
    segments = path.split("/")  # Turn the path into a list of segments
    output = []  # Initialize the variable to use to store output

    for segment in segments:
        # '.' is the current directory, so ignore it, it is superfluous
        if segment == ".":
            continue
        # Anything other than '..', should be appended to the output
        elif segment != "..":
            output.append(segment)
        # In this case segment == '..', if we can, we should pop the last
        # element
        elif output:
            output.pop()

    # If the path starts with '/' and the output is empty or the first string
    # is non-empty
    if path.startswith("/") and (not output or output[0]):
        output.insert(0, "")

    # If the path starts with '/.' or '/..' ensure we add one more empty
    # string to add a trailing '/'
    if path.endswith(("/.", "/..")):
        output.append("")

    return "/".join(output)


def _normalize_host(
    host: typing.Optional[str], scheme: typing.Optional[str]
) -> typing.Optional[str]:
    if host:
        if scheme in _NORMALIZABLE_SCHEMES:
            is_ipv6 = _IPV6_ADDRZ_RE.match(host)
            if is_ipv6:
                match = _ZONE_ID_RE.search(host)
                if match:
                    start, end = match.span(1)
                    zone_id = host[start:end]

                    if zone_id.startswith("%25") and zone_id != "%25":
                        zone_id = zone_id[3:]
                    else:
                        zone_id = zone_id[1:]
                    zone_id = _encode_invalid_chars(zone_id, _UNRESERVED_CHARS)
                    return f"{host[:start].lower()}%{zone_id}{host[end:]}"
                else:
                    return host.lower()
            elif not _IPV4_RE.match(host):
                return to_str(
                    b".".join([_idna_encode(label) for label in host.split(".")]),
                    "ascii",
                )
    return host


def _idna_encode(name: str) -> bytes:
    if name and any([ord(x) > 128 for x in name]):
        try:
            import idna  # type: ignore
        except ImportError:
            raise LocationParseError(
                "Unable to parse URL without the 'idna' module"
            ) from None

        try:
            return typing.cast(
                bytes, idna.encode(name.lower(), strict=True, std3_rules=True)
            )
        except idna.IDNAError:
            raise LocationParseError(
                f"Name '{name}' is not a valid IDNA label"
            ) from None

    return name.lower().encode("ascii")


def _encode_target(target: str) -> str:
    """Percent-encodes a request target so that there are no invalid characters

    Pre-condition for this function is that 'target' must start with '/'.
    If that is the case then _TARGET_RE will always produce a match.
    """
    match = _TARGET_RE.match(target)
    if not match:  # Defensive:
        raise LocationParseError(f"{target!r} is not a valid request URI")

    path, query = match.groups()
    encoded_target = _encode_invalid_chars(path, _PATH_CHARS)
    if query is not None:
        query = _encode_invalid_chars(query, _QUERY_CHARS)
        encoded_target += "?" + query
    return encoded_target


def parse_url(url: str) -> Url:
    """
    Given a url, return a parsed :class:`.Url` namedtuple. Best-effort is
    performed to parse incomplete urls. Fields not provided will be None.
    This parser is RFC 3986 compliant.

    The parser logic and helper functions are based heavily on
    work done in the ``rfc3986`` module.

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

    source_url = url
    if not _SCHEME_RE.search(url):
        url = "//" + url

    scheme: typing.Optional[str]
    authority: typing.Optional[str]
    auth: typing.Optional[str]
    host: typing.Optional[str]
    port: typing.Optional[str]
    port_int: typing.Optional[int]
    path: typing.Optional[str]
    query: typing.Optional[str]
    fragment: typing.Optional[str]

    try:
        scheme, authority, path, query, fragment = _URI_RE.match(url).groups()  # type: ignore
        normalize_uri = scheme is None or scheme.lower() in _NORMALIZABLE_SCHEMES

        if scheme:
            scheme = scheme.lower()

        if authority:
            auth, host, port = _SUBAUTHORITY_RE.match(authority).groups()  # type: ignore
            if auth and normalize_uri:
                auth = _encode_invalid_chars(auth, _USERINFO_CHARS)
            if port == "":
                port = None
        else:
            auth, host, port = None, None, None

        if port is not None:
            port_int = int(port)
            if not (0 <= port_int <= 65535):
                raise LocationParseError(url)
        else:
            port_int = None

        host = _normalize_host(host, scheme)

        if normalize_uri and path:
            path = _remove_path_dot_segments(path)
            path = _encode_invalid_chars(path, _PATH_CHARS)
        if normalize_uri and query:
            query = _encode_invalid_chars(query, _QUERY_CHARS)
        if normalize_uri and fragment:
            fragment = _encode_invalid_chars(fragment, _FRAGMENT_CHARS)

    except (ValueError, AttributeError):
        raise LocationParseError(source_url) from None

    # For the sake of backwards compatibility we put empty
    # string values for path if there are any defined values
    # beyond the path in the URL.
    # TODO: Remove this when we break backwards compatibility.
    if not path:
        if query is not None or fragment is not None:
            path = ""
        else:
            path = None

    return Url(
        scheme=scheme,
        auth=auth,
        host=host,
        port=port_int,
        path=path,
        query=query,
        fragment=fragment,
    )
