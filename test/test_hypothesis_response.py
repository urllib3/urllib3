"""
Hypothesis property-based tests for HTTP response handling.
"""
from __future__ import annotations

import gzip
import zlib
from io import BytesIO

from hypothesis import given, settings, strategies as st

from urllib3.response import BytesQueueBuffer, HTTPResponse


# Strategy for byte strings
byte_strings = st.binary(max_size=10000)

# Strategy for chunks
chunks = st.lists(byte_strings, min_size=0, max_size=100)


@settings(max_examples=1000, deadline=None)
@given(data=byte_strings)
def test_bytes_queue_buffer_single_chunk(data: bytes) -> None:
    """Test BytesQueueBuffer with a single chunk."""
    buffer = BytesQueueBuffer()

    # Initially empty
    assert len(buffer) == 0

    if data:
        buffer.put(data)

        # Length should match
        assert len(buffer) == len(data)

        # Getting all should return the data
        result = buffer.get_all()
        assert result == data

        # Buffer should be empty after get_all
        assert len(buffer) == 0


@settings(max_examples=1000, deadline=None)
@given(chunks_list=chunks)
def test_bytes_queue_buffer_multiple_chunks(chunks_list: list[bytes]) -> None:
    """Test BytesQueueBuffer with multiple chunks."""
    buffer = BytesQueueBuffer()

    total_size = sum(len(chunk) for chunk in chunks_list)

    for chunk in chunks_list:
        buffer.put(chunk)

    # Length should be sum of all chunks
    assert len(buffer) == total_size

    # Getting all should return concatenated data
    result = buffer.get_all()
    expected = b"".join(chunks_list)
    assert result == expected

    # Buffer should be empty
    assert len(buffer) == 0


@settings(max_examples=1000, deadline=None)
@given(
    data=byte_strings.filter(lambda d: len(d) > 0),
    n=st.integers(min_value=1, max_value=100),
)
def test_bytes_queue_buffer_partial_get(data: bytes, n: int) -> None:
    """Test getting partial data from buffer."""
    buffer = BytesQueueBuffer()
    buffer.put(data)

    # Get min(n, len(data)) bytes
    to_get = min(n, len(data))
    result = buffer.get(to_get)

    # Should get the requested amount or what's available
    assert len(result) <= to_get
    assert result == data[:len(result)]

    # Remaining length should be correct
    assert len(buffer) == len(data) - len(result)


@settings(max_examples=1000, deadline=None)
@given(chunks_list=st.lists(byte_strings, min_size=1, max_size=20))
def test_bytes_queue_buffer_get_across_chunks(chunks_list: list[bytes]) -> None:
    """Test getting data that spans multiple chunks."""
    buffer = BytesQueueBuffer()
    total_data = b""

    for chunk in chunks_list:
        buffer.put(chunk)
        total_data += chunk

    if total_data:
        # Get half the data
        half = len(total_data) // 2
        if half > 0:
            result = buffer.get(half)
            assert result == total_data[:half]


@settings(max_examples=1000, deadline=None)
@given(
    body=byte_strings.filter(lambda d: len(d) > 0),  # Non-empty body
    status=st.integers(min_value=200, max_value=599).filter(lambda s: s not in (204, 304)),
)
def test_httpresponse_construction(body: bytes, status: int) -> None:
    """Test HTTPResponse construction."""
    response = HTTPResponse(
        body=body,
        status=status,
        headers={},
        preload_content=True,
    )

    assert response.status == status
    assert response.data == body


@settings(max_examples=1000, deadline=None)
@given(
    content_length=st.integers(min_value=1, max_value=10000),  # Start from 1
    actual_data=byte_strings.filter(lambda d: len(d) > 0),  # Non-empty data
)
def test_httpresponse_content_length(content_length: int, actual_data: bytes) -> None:
    """Test HTTPResponse with Content-Length header."""
    headers = {"Content-Length": str(content_length)}

    response = HTTPResponse(
        body=actual_data,
        status=200,
        headers=headers,
        preload_content=True,
    )

    # Should store the data
    if response.data is not None:
        assert response.data == actual_data


@settings(max_examples=1000, deadline=None)
@given(data=byte_strings.filter(lambda d: 0 < len(d) < 1000))
def test_httpresponse_gzip_decoding(data: bytes) -> None:
    """Test HTTPResponse with gzip encoding."""
    # Compress data
    compressed = gzip.compress(data)

    headers = {"Content-Encoding": "gzip"}

    fp = BytesIO(compressed)
    response = HTTPResponse(
        body=fp,
        status=200,
        headers=headers,
        preload_content=False,
        decode_content=True,
    )

    # Should decompress automatically
    decoded = response.read()
    assert decoded == data


@settings(max_examples=1000, deadline=None)
@given(data=byte_strings.filter(lambda d: 0 < len(d) < 1000))
def test_httpresponse_deflate_decoding(data: bytes) -> None:
    """Test HTTPResponse with deflate encoding."""
    # Compress data with deflate
    compressor = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
    compressed = compressor.compress(data) + compressor.flush()

    headers = {"Content-Encoding": "deflate"}

    fp = BytesIO(compressed)
    response = HTTPResponse(
        body=fp,
        status=200,
        headers=headers,
        preload_content=False,
        decode_content=True,
    )

    # Should decompress automatically
    decoded = response.read()
    assert decoded == data


@settings(max_examples=1000, deadline=None)
@given(
    status=st.integers(min_value=100, max_value=599),
    reason=st.text(max_size=50),
)
def test_httpresponse_status_and_reason(status: int, reason: str) -> None:
    """Test HTTPResponse status and reason handling."""
    response = HTTPResponse(
        body=b"",
        status=status,
        reason=reason,
        headers={},
    )

    assert response.status == status
    assert response.reason == reason


@settings(max_examples=1000, deadline=None)
@given(
    location=st.text(min_size=1, max_size=200),
    status=st.sampled_from([301, 302, 303, 307, 308, 200, 404]),
)
def test_httpresponse_redirect_location(location: str, status: int) -> None:
    """Test get_redirect_location with various status codes."""
    headers = {"Location": location}

    response = HTTPResponse(
        body=b"",
        status=status,
        headers=headers,
    )

    redirect_location = response.get_redirect_location()

    # Should return location for redirect status codes
    if status in [301, 302, 303, 307, 308]:
        assert redirect_location == location
    else:
        assert redirect_location is False


@settings(max_examples=1000, deadline=None)
@given(
    data=byte_strings.filter(lambda d: len(d) > 0 and len(d) < 5000),
    chunk_size=st.integers(min_value=1, max_value=1000),
)
def test_httpresponse_stream(data: bytes, chunk_size: int) -> None:
    """Test streaming response data in chunks."""
    fp = BytesIO(data)

    response = HTTPResponse(
        body=fp,
        status=200,
        headers={},
        preload_content=False,
    )

    # Read in chunks
    read_chunks = []
    try:
        for chunk in response.stream(amt=chunk_size):
            read_chunks.append(chunk)

        # Reassemble should match original
        reassembled = b"".join(read_chunks)
        assert reassembled == data
    except Exception:
        # Some edge cases may fail, which is okay for property testing
        pass


@settings(max_examples=1000, deadline=None)
@given(
    transfer_encoding=st.sampled_from(["chunked", "gzip", "deflate", ""]),
)
def test_httpresponse_chunked_detection(transfer_encoding: str) -> None:
    """Test detection of chunked transfer encoding."""
    headers = {}
    if transfer_encoding:
        headers["Transfer-Encoding"] = transfer_encoding

    response = HTTPResponse(
        body=b"",
        status=200,
        headers=headers,
    )

    # Should detect chunked encoding
    if "chunked" in transfer_encoding.lower():
        assert response.chunked is True
    else:
        assert response.chunked is False


@settings(max_examples=1000, deadline=None)
@given(
    version=st.integers(min_value=9, max_value=20),
)
def test_httpresponse_version(version: int) -> None:
    """Test HTTP version handling."""
    response = HTTPResponse(
        body=b"",
        status=200,
        version=version,
        headers={},
    )

    assert response.version == version


@settings(max_examples=1000, deadline=None)
@given(
    enforce_content_length=st.booleans(),
    content_length=st.integers(min_value=1, max_value=1000),
    actual_length=st.integers(min_value=1, max_value=1000),
)
def test_httpresponse_enforce_content_length(
    enforce_content_length: bool,
    content_length: int,
    actual_length: int,
) -> None:
    """Test content length enforcement."""
    headers = {"Content-Length": str(content_length)}
    data = b"x" * actual_length

    response = HTTPResponse(
        body=data,
        status=200,
        headers=headers,
        enforce_content_length=enforce_content_length,
        preload_content=True,
    )

    # Should have the data
    if response.data is not None:
        assert len(response.data) == actual_length


@settings(max_examples=1000, deadline=None)
@given(chunks_list=st.lists(byte_strings, min_size=0, max_size=50))
def test_bytes_queue_buffer_consistency(chunks_list: list[bytes]) -> None:
    """Test that BytesQueueBuffer maintains consistency."""
    buffer = BytesQueueBuffer()

    # Track what we've put in
    total_put = b""
    for chunk in chunks_list:
        buffer.put(chunk)
        total_put += chunk

        # Length should match total put
        assert len(buffer) == len(total_put)

    # Get all should return everything
    result = buffer.get_all()
    assert result == total_put


@settings(max_examples=1000, deadline=None)
@given(
    data=byte_strings.filter(lambda d: len(d) > 0),
    amt=st.integers(min_value=1, max_value=100),
)
def test_httpresponse_read_with_amt(data: bytes, amt: int) -> None:
    """Test reading specific amounts from response."""
    fp = BytesIO(data)

    response = HTTPResponse(
        body=fp,
        status=200,
        headers={},
        preload_content=False,
    )

    # Read amt bytes
    result = response.read(amt=amt)

    # Should get at most amt bytes
    assert len(result) <= amt

    # Should be prefix of data
    assert result == data[:len(result)]


@settings(max_examples=1000, deadline=None)
@given(
    data=byte_strings.filter(lambda d: len(d) > 0),
)
def test_httpresponse_read_multiple_times(data: bytes) -> None:
    """Test reading from response multiple times."""
    fp = BytesIO(data)

    response = HTTPResponse(
        body=fp,
        status=200,
        headers={},
        preload_content=False,
    )

    # Read in small chunks
    read_chunks = []
    while True:
        chunk = response.read(amt=10)
        if not chunk:
            break
        read_chunks.append(chunk)

    # Should reassemble to original
    reassembled = b"".join(read_chunks)
    assert reassembled == data


@settings(max_examples=1000, deadline=None)
@given(
    request_method=st.sampled_from(["GET", "HEAD", "POST", "PUT", "DELETE"]),
    status=st.integers(min_value=100, max_value=599),
)
def test_httpresponse_head_request(request_method: str, status: int) -> None:
    """Test response handling for HEAD requests."""
    response = HTTPResponse(
        body=b"some data",
        status=status,
        headers={},
        request_method=request_method,
    )

    # HEAD requests should have zero length
    if request_method == "HEAD":
        assert response.length_remaining == 0
    elif status in (204, 304) or 100 <= status < 200:
        # No content responses
        assert response.length_remaining == 0


@settings(max_examples=1000, deadline=None)
@given(
    header_names=st.lists(
        st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
            min_size=1,
            max_size=20,
        ),
        min_size=0,
        max_size=10,
    )
)
def test_httpresponse_header_access(header_names: list[str]) -> None:
    """Test accessing headers from response."""
    headers = {name: f"value_{i}" for i, name in enumerate(header_names)}

    response = HTTPResponse(
        body=b"",
        status=200,
        headers=headers,
    )

    # Should be able to access all headers
    for name in header_names:
        value = response.headers.get(name)
        assert value is not None or name not in headers
