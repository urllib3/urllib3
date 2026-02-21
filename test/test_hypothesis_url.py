"""
Hypothesis property-based tests for URL parsing and manipulation.
"""
from __future__ import annotations

import string

import pytest
from hypothesis import given, settings, strategies as st

from urllib3.exceptions import LocationParseError
from urllib3.util.url import Url, _encode_invalid_chars, _encode_target, parse_url


# Strategy for valid schemes
schemes = st.sampled_from(["http", "https", "ftp", "ws", "wss"]) | st.none()

# Strategy for hostnames
hostnames = st.one_of(
    # Regular domain names
    st.from_regex(
        r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
        r"(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*",
        fullmatch=True
    ),
    # IPv4 addresses
    st.from_regex(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", fullmatch=True),
    # IPv6 addresses (simplified)
    st.just("::1"),
    st.just("[::1]"),
    st.just("[2001:db8::1]"),
    st.none(),
)

# Strategy for ports
ports = st.integers(min_value=1, max_value=65535) | st.none()

# Strategy for paths
paths = st.one_of(
    st.just(""),
    st.just("/"),
    st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters="-._~:/?#[]@!$&'()*+,;=",
        ),
        min_size=1,
        max_size=100,
    ).map(lambda s: "/" + s if s and not s.startswith("/") else s),
    st.none(),
)

# Strategy for query strings
queries = st.one_of(
    st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters="-._~:/?#[]@!$&'()*+,;=%",
        ),
        max_size=100,
    ),
    st.none(),
)

# Strategy for fragments
fragments = queries  # Same character set


@settings(max_examples=1000, deadline=None)
@given(
    scheme=schemes,
    host=hostnames,
    port=ports,
    path=paths,
    query=queries,
    fragment=fragments,
)
def test_url_construction_is_valid(
    scheme: str | None,
    host: str | None,
    port: int | None,
    path: str | None,
    query: str | None,
    fragment: str | None,
) -> None:
    """Test that Url construction with valid inputs produces valid URLs."""
    url = Url(
        scheme=scheme,
        auth=None,
        host=host,
        port=port,
        path=path,
        query=query,
        fragment=fragment,
    )

    # Properties that should always hold
    assert url.scheme == (scheme.lower() if scheme else None)
    assert url.host == host
    assert url.port == port
    assert url.query == query
    assert url.fragment == fragment

    # If path is provided and doesn't start with /, it should be prepended
    if path and not path.startswith("/"):
        assert url.path == "/" + path
    else:
        assert url.path == path


@settings(max_examples=1000, deadline=None)
@given(url_string=st.text(min_size=1, max_size=200))
def test_parse_url_never_crashes(url_string: str) -> None:
    """Test that parse_url never crashes, only raises LocationParseError."""
    try:
        result = parse_url(url_string)
        # If it succeeds, result should be a Url
        assert isinstance(result, Url)
    except LocationParseError:
        # This is expected for invalid URLs
        pass


@settings(max_examples=1000, deadline=None)
@given(
    scheme=st.sampled_from(["http", "https"]),
    host=st.from_regex(r"[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?", fullmatch=True),
    port=st.integers(min_value=1, max_value=65535),
)
def test_url_roundtrip(scheme: str, host: str, port: int) -> None:
    """Test that URL construction and string conversion roundtrip correctly."""
    url = Url(scheme=scheme, host=host, port=port, path="/test", query="foo=bar")
    url_string = url.url

    # The string should contain the components
    assert scheme in url_string
    assert host in url_string
    assert str(port) in url_string

    # Parsing the string should give us back equivalent components
    parsed = parse_url(url_string)
    assert parsed.scheme == scheme
    assert parsed.host == host
    assert parsed.port == port


@settings(max_examples=1000, deadline=None)
@given(
    path=st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters="-._~:@!$&'()*+,;=/",
        ),
        min_size=1,
        max_size=100,
    )
)
def test_encode_target_with_valid_paths(path: str) -> None:
    """Test _encode_target with various valid paths."""
    # Ensure path starts with /
    if not path.startswith("/"):
        path = "/" + path

    try:
        encoded = _encode_target(path)
        # Should always return a string
        assert isinstance(encoded, str)
        # Should start with /
        assert encoded.startswith("/")
    except LocationParseError:
        # Some paths may be invalid
        pass


@settings(max_examples=1000, deadline=None)
@given(
    component=st.text(
        alphabet=st.characters(
            min_codepoint=0x20,
            max_codepoint=0x7E,
        ),
        max_size=50,
    ),
)
def test_encode_invalid_chars_idempotent(component: str) -> None:
    """Test that encoding is idempotent for valid characters."""
    allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-~")

    encoded1 = _encode_invalid_chars(component, allowed_chars)
    encoded2 = _encode_invalid_chars(encoded1, allowed_chars)

    # Encoding twice should give the same result
    assert encoded1 == encoded2


@settings(max_examples=1000, deadline=None)
@given(
    url_string=st.from_regex(
        r"https?://[a-z0-9.-]+(/[a-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*)?",
        fullmatch=True
    )
)
def test_parse_url_on_valid_http_urls(url_string: str) -> None:
    """Test parse_url on strings that look like valid HTTP URLs."""
    result = parse_url(url_string)

    # Should successfully parse
    assert isinstance(result, Url)
    assert result.scheme in ("http", "https")
    assert result.host is not None

    # URL property should give us back a string
    assert isinstance(result.url, str)


@settings(max_examples=1000, deadline=None)
@given(
    auth=st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters="-._~:@",
        ),
        min_size=1,
        max_size=50,
    ),
    host=st.from_regex(r"[a-z0-9.-]+", fullmatch=True),
)
def test_url_with_auth(auth: str, host: str) -> None:
    """Test URL construction with authentication."""
    url = Url(scheme="https", auth=auth, host=host, path="/")

    # Authority should contain both auth and host
    authority = url.authority
    if authority:
        assert auth in authority
        assert host in authority
        assert "@" in authority


@settings(max_examples=1000, deadline=None)
@given(
    host=hostnames.filter(lambda h: h is not None),
    port=ports,
)
def test_netloc_property(host: str, port: int | None) -> None:
    """Test the netloc property with various host/port combinations."""
    url = Url(host=host, port=port)
    netloc = url.netloc

    if netloc is None:
        assert host is None
    else:
        assert host in netloc
        if port:
            assert str(port) in netloc


@settings(max_examples=1000, deadline=None)
@given(
    path=st.text(
        alphabet=string.ascii_letters + string.digits + "/_-.",
        min_size=1,
        max_size=100
    ),
    query=st.text(
        alphabet=string.ascii_letters + string.digits + "&=_-",
        max_size=100
    ) | st.none(),
)
def test_request_uri_property(path: str, query: str | None) -> None:
    """Test the request_uri property."""
    if not path.startswith("/"):
        path = "/" + path

    url = Url(path=path, query=query)
    request_uri = url.request_uri

    assert request_uri.startswith("/")
    assert path in request_uri

    if query:
        assert "?" in request_uri
        assert query in request_uri


@settings(max_examples=1000, deadline=None)
@given(
    base_path=st.text(alphabet=string.ascii_letters + "/_-.", min_size=1, max_size=50),
    segments=st.lists(st.sampled_from([".", "..", "normal"]), min_size=0, max_size=10),
)
def test_path_normalization(base_path: str, segments: list[str]) -> None:
    """Test that path normalization handles . and .. correctly."""
    if not base_path.startswith("/"):
        base_path = "/" + base_path

    path = base_path + "/" + "/".join(segments)

    try:
        url = parse_url(f"http://example.com{path}")
        # The path should be normalized
        if url.path:
            # Should not contain /./ or trailing /. (except at end if there was one)
            if not path.endswith("/."):
                assert "/./" not in url.path
    except LocationParseError:
        pass


@settings(max_examples=1000, deadline=None)
@given(
    port_value=st.integers(min_value=-1000, max_value=100000)
)
def test_parse_url_port_validation(port_value: int) -> None:
    """Test that invalid ports are rejected."""
    url_string = f"http://example.com:{port_value}/"

    if 0 <= port_value <= 65535:
        # Valid port range
        result = parse_url(url_string)
        assert result.port == port_value
    else:
        # Invalid port range should raise LocationParseError
        with pytest.raises(LocationParseError):
            parse_url(url_string)


@settings(max_examples=1000, deadline=None)
@given(url_string=st.text(min_size=0, max_size=50))
def test_empty_and_short_urls(url_string: str) -> None:
    """Test parse_url with empty and very short strings."""
    try:
        result = parse_url(url_string)
        # Should always return a Url instance
        assert isinstance(result, Url)
    except LocationParseError:
        # Some short strings are invalid URLs, which is expected
        pass


@settings(max_examples=1000, deadline=None)
@given(
    scheme=st.sampled_from(["http", "https"]),
    host=st.from_regex(r"[a-z0-9-]+", fullmatch=True),
    path1=st.text(alphabet=string.ascii_lowercase + "/_", min_size=1, max_size=20),
    path2=st.text(alphabet=string.ascii_lowercase + "/_", min_size=1, max_size=20),
)
def test_url_equality_and_comparison(
    scheme: str, host: str, path1: str, path2: str
) -> None:
    """Test URL equality and comparison operations."""
    if not path1.startswith("/"):
        path1 = "/" + path1
    if not path2.startswith("/"):
        path2 = "/" + path2

    url1 = Url(scheme=scheme, host=host, path=path1)
    url2 = Url(scheme=scheme, host=host, path=path1)
    url3 = Url(scheme=scheme, host=host, path=path2)

    # Same components should be equal
    assert url1 == url2

    # Different paths should not be equal (unless paths happen to be the same)
    if path1 != path2:
        assert url1 != url3
