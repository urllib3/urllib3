"""
Hypothesis property-based tests for request utilities.
"""
from __future__ import annotations

import io

from hypothesis import given, settings, strategies as st

from urllib3.util.request import body_to_chunks, make_headers, set_file_position


# Strategy for HTTP methods
http_methods = st.sampled_from([
    "GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH", "TRACE", "CONNECT"
])

# Strategy for header values
header_values = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
    max_size=100,
)


@settings(max_examples=1000, deadline=None)
@given(
    keep_alive=st.booleans() | st.none(),
    accept_encoding=st.one_of(
        st.booleans(),
        st.lists(st.sampled_from(["gzip", "deflate", "br", "zstd"]), unique=True),
        st.text(max_size=50),
        st.none(),
    ),
    user_agent=st.one_of(header_values, st.none()),
    disable_cache=st.booleans() | st.none(),
)
def test_make_headers(
    keep_alive: bool | None,
    accept_encoding: bool | list[str] | str | None,
    user_agent: str | None,
    disable_cache: bool | None,
) -> None:
    """Test make_headers with various inputs."""
    headers = make_headers(
        keep_alive=keep_alive,
        accept_encoding=accept_encoding,
        user_agent=user_agent,
        disable_cache=disable_cache,
    )

    # Should return a dictionary
    assert isinstance(headers, dict)

    # Check for expected headers
    if keep_alive:
        assert "connection" in headers
        assert headers["connection"] == "keep-alive"

    if user_agent:
        assert "user-agent" in headers
        assert headers["user-agent"] == user_agent

    if disable_cache:
        assert "cache-control" in headers
        assert headers["cache-control"] == "no-cache"

    if accept_encoding:
        assert "accept-encoding" in headers


@settings(max_examples=1000, deadline=None)
@given(
    username=st.text(
        alphabet=st.characters(min_codepoint=0x20, max_codepoint=0xFF, blacklist_characters=":"),
        min_size=1,
        max_size=50,
    ),
    password=st.text(
        alphabet=st.characters(min_codepoint=0x20, max_codepoint=0xFF),
        min_size=1,
        max_size=50,
    ),
)
def test_make_headers_basic_auth(username: str, password: str) -> None:
    """Test make_headers with basic authentication."""
    auth_string = f"{username}:{password}"

    headers = make_headers(basic_auth=auth_string)

    # Should have authorization header
    assert "authorization" in headers
    assert headers["authorization"].startswith("Basic ")

    # Should be base64 encoded
    auth_value = headers["authorization"]
    assert len(auth_value) > len("Basic ")


@settings(max_examples=1000, deadline=None)
@given(
    username=st.text(
        alphabet=st.characters(min_codepoint=0x20, max_codepoint=0xFF, blacklist_characters=":"),
        min_size=1,
        max_size=50,
    ),
    password=st.text(
        alphabet=st.characters(min_codepoint=0x20, max_codepoint=0xFF),
        min_size=1,
        max_size=50,
    ),
)
def test_make_headers_proxy_basic_auth(username: str, password: str) -> None:
    """Test make_headers with proxy basic authentication."""
    auth_string = f"{username}:{password}"

    headers = make_headers(proxy_basic_auth=auth_string)

    # Should have proxy-authorization header
    assert "proxy-authorization" in headers
    assert headers["proxy-authorization"].startswith("Basic ")


@settings(max_examples=1000, deadline=None)
@given(
    body=st.one_of(
        st.binary(max_size=1000),
        st.text(max_size=1000),
        st.none(),
    ),
    method=http_methods,
    blocksize=st.integers(min_value=1, max_value=8192),
)
def test_body_to_chunks_with_bytes_and_str(
    body: bytes | str | None, method: str, blocksize: int
) -> None:
    """Test body_to_chunks with bytes and strings."""
    result = body_to_chunks(body, method, blocksize)

    # Should return ChunksAndContentLength
    assert hasattr(result, "chunks")
    assert hasattr(result, "content_length")

    chunks = result.chunks
    content_length = result.content_length

    if body is None:
        # No body
        assert chunks is None
        # Content-Length depends on method
        if method.upper() in {"GET", "HEAD", "DELETE", "TRACE", "OPTIONS", "CONNECT"}:
            assert content_length is None
        else:
            assert content_length == 0
    else:
        # Has body
        if chunks is not None:
            # Should be iterable
            chunks_list = list(chunks)
            # Reassemble
            if isinstance(body, str):
                body_bytes = body.encode("utf-8")
            else:
                body_bytes = body
            reassembled = b"".join(chunks_list)
            assert reassembled == body_bytes


@settings(max_examples=1000, deadline=None)
@given(
    data=st.binary(min_size=1, max_size=1000),
    method=http_methods,
    blocksize=st.integers(min_value=1, max_value=100),
)
def test_body_to_chunks_with_file_like(
    data: bytes, method: str, blocksize: int
) -> None:
    """Test body_to_chunks with file-like objects."""
    body = io.BytesIO(data)

    result = body_to_chunks(body, method, blocksize)

    # File-like objects should have chunks but no content_length
    assert result.chunks is not None
    assert result.content_length is None

    # Read all chunks
    chunks_list = list(result.chunks)
    reassembled = b"".join(chunks_list)

    # Should match original data
    assert reassembled == data


@settings(max_examples=1000, deadline=None)
@given(
    chunks_list=st.lists(st.binary(min_size=1, max_size=100), min_size=1, max_size=20),
    method=http_methods,
    blocksize=st.integers(min_value=1, max_value=100),
)
def test_body_to_chunks_with_iterable(
    chunks_list: list[bytes], method: str, blocksize: int
) -> None:
    """Test body_to_chunks with iterables."""
    result = body_to_chunks(iter(chunks_list), method, blocksize)

    # Iterables should work
    assert result.chunks is not None
    assert result.content_length is None

    # Should be able to iterate
    output_chunks = list(result.chunks)
    assert len(output_chunks) == len(chunks_list)


@settings(max_examples=1000, deadline=None)
@given(
    data=st.binary(min_size=10, max_size=200),
    position_ratio=st.floats(min_value=0.0, max_value=0.9),
)
def test_set_file_position_with_seekable(data: bytes, position_ratio: float) -> None:
    """Test set_file_position with seekable file-like object."""
    position = int(len(data) * position_ratio)

    body = io.BytesIO(data)

    # Set position
    result = set_file_position(body, position)

    # Should return the position
    assert result == position

    # File should be at that position
    assert body.tell() == position


@settings(max_examples=1000, deadline=None)
@given(data=st.binary(min_size=1, max_size=100))
def test_set_file_position_record_position(data: bytes) -> None:
    """Test set_file_position recording current position."""
    body = io.BytesIO(data)

    # Move to a position
    test_pos = len(data) // 2
    body.seek(test_pos)

    # Call without position to record
    result = set_file_position(body, None)

    # Should return current position
    assert result == test_pos


@settings(max_examples=1000, deadline=None)
@given(
    accept_encoding_list=st.lists(
        st.sampled_from(["gzip", "deflate", "br", "zstd", "identity"]),
        unique=True,
        min_size=1,
        max_size=5,
    )
)
def test_make_headers_accept_encoding_list(accept_encoding_list: list[str]) -> None:
    """Test make_headers with accept_encoding as list."""
    headers = make_headers(accept_encoding=accept_encoding_list)

    # Should have accept-encoding header
    assert "accept-encoding" in headers

    # Should contain all encodings
    encoding_header = headers["accept-encoding"]
    for encoding in accept_encoding_list:
        assert encoding in encoding_header

    # Should be comma-separated
    assert "," in encoding_header or len(accept_encoding_list) == 1


@settings(max_examples=1000, deadline=None)
@given(
    keep_alive=st.booleans(),
    user_agent=header_values,
    disable_cache=st.booleans(),
)
def test_make_headers_combinations(
    keep_alive: bool, user_agent: str, disable_cache: bool
) -> None:
    """Test make_headers with multiple options."""
    headers = make_headers(
        keep_alive=keep_alive,
        user_agent=user_agent,
        disable_cache=disable_cache,
    )

    # All requested headers should be present
    if keep_alive:
        assert "connection" in headers
    if user_agent:
        assert "user-agent" in headers
    if disable_cache:
        assert "cache-control" in headers


@settings(max_examples=1000, deadline=None)
@given(
    data=st.binary(min_size=1, max_size=100),
    blocksize=st.integers(min_value=1, max_value=50),
)
def test_body_to_chunks_blocksize_respected(data: bytes, blocksize: int) -> None:
    """Test that blocksize is respected when chunking file-like objects."""
    body = io.BytesIO(data)

    result = body_to_chunks(body, "POST", blocksize)

    assert result.chunks is not None

    # Read chunks and check sizes
    chunks_list = list(result.chunks)

    # Most chunks should be at most blocksize
    for chunk in chunks_list[:-1]:  # All but last
        assert len(chunk) <= blocksize

    # Reassemble should match
    reassembled = b"".join(chunks_list)
    assert reassembled == data


@settings(max_examples=1000, deadline=None)
@given(
    data=st.binary(min_size=1, max_size=100),
)
def test_body_to_chunks_with_memoryview(data: bytes) -> None:
    """Test body_to_chunks with memoryview (buffer protocol)."""
    mv = memoryview(data)

    result = body_to_chunks(mv, "POST", 8192)

    # Should handle memoryview
    assert result.chunks is not None
    assert result.content_length == len(data)

    # Should be able to use chunks
    chunks_list = list(result.chunks)
    reassembled = b"".join(chunks_list)
    assert reassembled == data


@settings(max_examples=1000, deadline=None)
@given(
    text=st.text(min_size=1, max_size=100),
    blocksize=st.integers(min_value=1, max_value=50),
)
def test_body_to_chunks_with_text_io(text: str, blocksize: int) -> None:
    """Test body_to_chunks with TextIOBase objects."""
    body = io.StringIO(text)

    result = body_to_chunks(body, "POST", blocksize)

    # Should handle text files (encoding to UTF-8)
    assert result.chunks is not None
    assert result.content_length is None

    # Should encode to UTF-8
    chunks_list = list(result.chunks)
    reassembled = b"".join(chunks_list)
    assert reassembled == text.encode("utf-8")


@settings(max_examples=1000, deadline=None)
@given(
    method=http_methods,
)
def test_body_to_chunks_none_body_content_length(method: str) -> None:
    """Test that None body sets appropriate Content-Length based on method."""
    result = body_to_chunks(None, method, 8192)

    assert result.chunks is None

    # Methods not expecting body should have None content-length
    if method.upper() in {"GET", "HEAD", "DELETE", "TRACE", "OPTIONS", "CONNECT"}:
        assert result.content_length is None
    else:
        # Methods expecting body should have 0 content-length
        assert result.content_length == 0


@settings(max_examples=1000, deadline=None)
@given(
    encoding_str=st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll"), whitelist_characters="-,"),
        min_size=1,
        max_size=50,
    )
)
def test_make_headers_accept_encoding_string(encoding_str: str) -> None:
    """Test make_headers with accept_encoding as string."""
    headers = make_headers(accept_encoding=encoding_str)

    # Should use the string as-is
    assert "accept-encoding" in headers
    assert headers["accept-encoding"] == encoding_str


@settings(max_examples=1000, deadline=None)
@given(accept_encoding=st.booleans())
def test_make_headers_accept_encoding_bool(accept_encoding: bool) -> None:
    """Test make_headers with accept_encoding as boolean."""
    headers = make_headers(accept_encoding=accept_encoding)

    if accept_encoding:
        # True should use default encodings
        assert "accept-encoding" in headers
        # Should contain common encodings
        encoding_header = headers["accept-encoding"]
        assert "gzip" in encoding_header
        assert "deflate" in encoding_header
    else:
        # False should not add header
        assert "accept-encoding" not in headers
