"""
Hypothesis property-based tests for connection utilities.
"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from urllib3.util.proxy import connection_requires_http_tunnel
from urllib3.util.url import Url


# Strategy for URL schemes
schemes = st.sampled_from(["http", "https", "ws", "wss", None])

# Strategy for hostnames
hostnames = st.one_of(
    st.from_regex(r"[a-z0-9-]+(\.[a-z0-9-]+)*", fullmatch=True),
    st.just("localhost"),
    st.just("127.0.0.1"),
)

# Strategy for ports
ports = st.integers(min_value=1, max_value=65535) | st.none()


@settings(max_examples=1000, deadline=None)
@given(
    proxy_scheme=schemes,
    proxy_host=hostnames,
    proxy_port=ports,
    destination_scheme=schemes,
)
def test_connection_requires_http_tunnel(
    proxy_scheme: str | None,
    proxy_host: str,
    proxy_port: int | None,
    destination_scheme: str | None,
) -> None:
    """Test connection_requires_http_tunnel with various configurations."""
    # Create proxy URL
    proxy_url = Url(scheme=proxy_scheme, host=proxy_host, port=proxy_port)

    result = connection_requires_http_tunnel(
        proxy_url=proxy_url,
        proxy_config=None,
        destination_scheme=destination_scheme,
    )

    # Should return a boolean
    assert isinstance(result, bool)

    # HTTP destinations never require tunneling
    if destination_scheme == "http":
        assert result is False


@settings(max_examples=1000, deadline=None)
@given(destination_scheme=schemes)
def test_connection_requires_http_tunnel_no_proxy(
    destination_scheme: str | None,
) -> None:
    """Test that no proxy means no tunneling required."""
    result = connection_requires_http_tunnel(
        proxy_url=None,
        proxy_config=None,
        destination_scheme=destination_scheme,
    )

    # No proxy means no tunnel
    assert result is False


@settings(max_examples=1000, deadline=None)
@given(
    proxy_host=hostnames,
    destination_scheme=st.sampled_from(["http", "https"]),
)
def test_connection_requires_http_tunnel_http_vs_https(
    proxy_host: str,
    destination_scheme: str,
) -> None:
    """Test tunneling requirements for HTTP vs HTTPS destinations."""
    proxy_url = Url(scheme="http", host=proxy_host, port=8080)

    result = connection_requires_http_tunnel(
        proxy_url=proxy_url,
        proxy_config=None,
        destination_scheme=destination_scheme,
    )

    # HTTP destinations don't need tunnel
    if destination_scheme == "http":
        assert result is False
    # HTTPS destinations typically need tunnel (unless forwarding configured)
    elif destination_scheme == "https":
        assert result is True


@settings(max_examples=1000, deadline=None)
@given(
    proxy_scheme=st.sampled_from(["http", "https"]),
    proxy_host=hostnames,
)
def test_connection_requires_http_tunnel_proxy_schemes(
    proxy_scheme: str,
    proxy_host: str,
) -> None:
    """Test tunneling with different proxy schemes."""
    proxy_url = Url(scheme=proxy_scheme, host=proxy_host, port=8080)

    # Test with HTTPS destination
    result = connection_requires_http_tunnel(
        proxy_url=proxy_url,
        proxy_config=None,
        destination_scheme="https",
    )

    # Should require tunnel for HTTPS destination
    assert result is True


@settings(max_examples=1000, deadline=None)
@given(
    proxy_host=hostnames,
    proxy_port=ports,
    destination_scheme=schemes,
)
def test_connection_requires_http_tunnel_with_ports(
    proxy_host: str,
    proxy_port: int | None,
    destination_scheme: str | None,
) -> None:
    """Test tunneling logic with various port configurations."""
    proxy_url = Url(scheme="http", host=proxy_host, port=proxy_port)

    result = connection_requires_http_tunnel(
        proxy_url=proxy_url,
        proxy_config=None,
        destination_scheme=destination_scheme,
    )

    # Result should be consistent regardless of port
    assert isinstance(result, bool)


@settings(max_examples=1000, deadline=None)
@given(
    proxy_host=hostnames,
    destination_scheme=st.sampled_from([None, "http", "https", "ws", "wss", "ftp"]),
)
def test_connection_requires_http_tunnel_various_schemes(
    proxy_host: str,
    destination_scheme: str | None,
) -> None:
    """Test tunneling with various destination schemes."""
    proxy_url = Url(scheme="http", host=proxy_host, port=8080)

    result = connection_requires_http_tunnel(
        proxy_url=proxy_url,
        proxy_config=None,
        destination_scheme=destination_scheme,
    )

    # Should always return a boolean
    assert isinstance(result, bool)

    # HTTP should never require tunnel
    if destination_scheme == "http":
        assert result is False
    # Most other schemes should require tunnel
    elif destination_scheme in ("https", "ws", "wss"):
        assert result is True


@settings(max_examples=1000, deadline=None)
@given(
    proxy_host=hostnames,
    proxy_port=st.integers(min_value=1, max_value=65535),
)
def test_connection_tunnel_proxy_url_properties(
    proxy_host: str,
    proxy_port: int,
) -> None:
    """Test that proxy URL properties are handled correctly."""
    proxy_url = Url(scheme="http", host=proxy_host, port=proxy_port)

    # Ensure URL is well-formed
    assert proxy_url.scheme == "http"
    assert proxy_url.host == proxy_host
    assert proxy_url.port == proxy_port

    # Test tunneling logic
    result = connection_requires_http_tunnel(
        proxy_url=proxy_url,
        proxy_config=None,
        destination_scheme="https",
    )

    assert result is True


@settings(max_examples=1000, deadline=None)
@given(
    proxy_scheme=st.sampled_from(["http", "https"]),
    proxy_host=hostnames,
    destination_scheme=st.sampled_from(["http", "https"]),
)
def test_connection_tunnel_symmetric_cases(
    proxy_scheme: str,
    proxy_host: str,
    destination_scheme: str,
) -> None:
    """Test tunneling in symmetric proxy/destination scheme cases."""
    proxy_url = Url(scheme=proxy_scheme, host=proxy_host, port=8080)

    result = connection_requires_http_tunnel(
        proxy_url=proxy_url,
        proxy_config=None,
        destination_scheme=destination_scheme,
    )

    # HTTP destination never needs tunnel
    if destination_scheme == "http":
        assert result is False


@settings(max_examples=1000, deadline=None)
@given(
    hostname=st.one_of(
        st.from_regex(r"[a-z0-9-]{1,63}(\.[a-z0-9-]{1,63}){0,3}", fullmatch=True),
        st.just("localhost"),
        st.just("example.com"),
        st.just("sub.example.com"),
    )
)
def test_connection_tunnel_hostname_variations(hostname: str) -> None:
    """Test tunneling with various hostname formats."""
    proxy_url = Url(scheme="http", host=hostname, port=8080)

    result = connection_requires_http_tunnel(
        proxy_url=proxy_url,
        proxy_config=None,
        destination_scheme="https",
    )

    # Should require tunnel for HTTPS
    assert result is True


@settings(max_examples=1000, deadline=None)
@given(
    proxy_host=hostnames,
    use_https_proxy=st.booleans(),
)
def test_connection_tunnel_proxy_type_matters(
    proxy_host: str,
    use_https_proxy: bool,
) -> None:
    """Test that proxy type affects tunneling decisions."""
    proxy_scheme = "https" if use_https_proxy else "http"
    proxy_url = Url(scheme=proxy_scheme, host=proxy_host, port=8080)

    # For HTTPS destination
    result = connection_requires_http_tunnel(
        proxy_url=proxy_url,
        proxy_config=None,
        destination_scheme="https",
    )

    # Currently should always require tunnel for HTTPS destination
    # (unless proxy_config.use_forwarding_for_https is set, but we pass None)
    assert result is True


@settings(max_examples=1000, deadline=None)
@given(
    proxy_host=hostnames,
    destination_scheme=schemes,
)
def test_connection_tunnel_consistency(
    proxy_host: str,
    destination_scheme: str | None,
) -> None:
    """Test that tunneling logic is consistent across calls."""
    proxy_url = Url(scheme="http", host=proxy_host, port=8080)

    # Call multiple times
    result1 = connection_requires_http_tunnel(
        proxy_url=proxy_url,
        proxy_config=None,
        destination_scheme=destination_scheme,
    )

    result2 = connection_requires_http_tunnel(
        proxy_url=proxy_url,
        proxy_config=None,
        destination_scheme=destination_scheme,
    )

    # Should be consistent
    assert result1 == result2


@settings(max_examples=1000, deadline=None)
@given(proxy_host=hostnames)
def test_connection_tunnel_with_none_destination(proxy_host: str) -> None:
    """Test tunneling with None destination scheme."""
    proxy_url = Url(scheme="http", host=proxy_host, port=8080)

    result = connection_requires_http_tunnel(
        proxy_url=proxy_url,
        proxy_config=None,
        destination_scheme=None,
    )

    # None destination should require tunnel (not HTTP)
    assert result is True


@settings(max_examples=1000, deadline=None)
@given(
    proxy_host=hostnames,
    proxy_port=st.one_of(
        st.just(80),
        st.just(443),
        st.just(8080),
        st.just(3128),
        st.integers(min_value=1, max_value=65535),
    ),
)
def test_connection_tunnel_common_proxy_ports(
    proxy_host: str,
    proxy_port: int,
) -> None:
    """Test tunneling with commonly used proxy ports."""
    proxy_url = Url(scheme="http", host=proxy_host, port=proxy_port)

    result = connection_requires_http_tunnel(
        proxy_url=proxy_url,
        proxy_config=None,
        destination_scheme="https",
    )

    # Should require tunnel regardless of proxy port
    assert result is True


@settings(max_examples=1000, deadline=None)
@given(
    proxy_scheme=st.sampled_from(["http", "https"]),
    proxy_host=hostnames,
)
def test_connection_tunnel_all_http_methods(
    proxy_scheme: str,
    proxy_host: str,
) -> None:
    """Test that tunneling logic works for various HTTP methods."""
    proxy_url = Url(scheme=proxy_scheme, host=proxy_host, port=8080)

    # Tunneling requirement is independent of HTTP method
    # Test with different destination schemes
    for dest_scheme in ["http", "https"]:
        result = connection_requires_http_tunnel(
            proxy_url=proxy_url,
            proxy_config=None,
            destination_scheme=dest_scheme,
        )

        if dest_scheme == "http":
            assert result is False
        else:
            assert result is True
