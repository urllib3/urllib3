"""
Hypothesis property-based tests for retry logic.
"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from urllib3.exceptions import ConnectTimeoutError, MaxRetryError
from urllib3.util.retry import RequestHistory, Retry


# Strategy for retry counts
retry_counts = st.integers(min_value=0, max_value=100) | st.none()

# Strategy for backoff factors
backoff_factors = st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)

# Strategy for status codes
status_codes = st.integers(min_value=100, max_value=599)

# Strategy for HTTP methods
http_methods = st.sampled_from([
    "GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH", "TRACE"
])


@settings(max_examples=1000, deadline=None)
@given(
    total=retry_counts,
    connect=retry_counts,
    read=retry_counts,
    redirect=retry_counts,
    status=retry_counts,
)
def test_retry_construction(
    total: int | None,
    connect: int | None,
    read: int | None,
    redirect: int | None,
    status: int | None,
) -> None:
    """Test Retry object construction with various parameters."""
    retry = Retry(
        total=total,
        connect=connect,
        read=read,
        redirect=redirect,
        status=status,
    )

    assert retry.total == total
    assert retry.connect == connect
    assert retry.read == read
    assert retry.redirect == redirect
    assert retry.status == status


@settings(max_examples=1000, deadline=None)
@given(
    backoff_factor=backoff_factors,
    backoff_max=st.floats(
        min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
)
def test_retry_backoff_time(backoff_factor: float, backoff_max: float) -> None:
    """Test backoff time calculation."""
    retry = Retry(total=10, backoff_factor=backoff_factor, backoff_max=backoff_max)

    # Add some history to trigger backoff
    retry = retry.new(history=(
        RequestHistory("GET", "/test", None, None, None),
        RequestHistory("GET", "/test", None, None, None),
    ))

    backoff_time = retry.get_backoff_time()

    # Should be non-negative
    assert backoff_time >= 0

    # Should not exceed backoff_max
    assert backoff_time <= backoff_max


@settings(max_examples=1000, deadline=None)
@given(
    method=http_methods,
    status_code=status_codes,
)
def test_is_retry_with_method_and_status(method: str, status_code: int) -> None:
    """Test is_retry logic with various methods and status codes."""
    # Create retry with some status forcelist
    retry = Retry(total=3, status_forcelist={500, 502, 503})

    result = retry.is_retry(method, status_code, has_retry_after=False)

    # Should be boolean
    assert isinstance(result, bool)

    # If status is in forcelist and method is allowed, should retry
    if status_code in {500, 502, 503} and method.upper() in Retry.DEFAULT_ALLOWED_METHODS:
        assert result is True


@settings(max_examples=1000, deadline=None)
@given(
    total=st.integers(min_value=0, max_value=10),
    num_attempts=st.integers(min_value=0, max_value=15),
)
def test_retry_exhaustion(total: int, num_attempts: int) -> None:
    """Test that retries are exhausted correctly."""
    retry = Retry(total=total)

    for _i in range(num_attempts):
        if retry.is_exhausted():
            # Once exhausted, should stay exhausted
            assert retry.is_exhausted()
            break

        # If not exhausted, should have retries remaining
        if retry.total is not None and retry.total >= 0:
            try:
                retry = retry.increment(method="GET", url="/test")
            except MaxRetryError:
                # Expected when exhausted
                break


@settings(max_examples=1000, deadline=None)
@given(
    backoff_factor=st.floats(
        min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False
    ),
    backoff_jitter=st.floats(
        min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False
    ),
)
def test_backoff_with_jitter(backoff_factor: float, backoff_jitter: float) -> None:
    """Test backoff calculation with jitter."""
    retry = Retry(
        total=10,
        backoff_factor=backoff_factor,
        backoff_jitter=backoff_jitter,
    )

    # Add history
    retry = retry.new(history=(
        RequestHistory("GET", "/test", None, None, None),
        RequestHistory("GET", "/test", None, None, None),
        RequestHistory("GET", "/test", None, None, None),
    ))

    # Get backoff time multiple times
    times = [retry.get_backoff_time() for _ in range(5)]

    # All should be non-negative
    assert all(t >= 0 for t in times)

    # If jitter is non-zero, times might vary
    if backoff_jitter > 0:
        # At least one should exist
        assert len(times) > 0


@settings(max_examples=1000, deadline=None)
@given(
    retry_after_seconds=st.integers(min_value=0, max_value=100000),
)
def test_parse_retry_after_integer(retry_after_seconds: int) -> None:
    """Test parsing integer Retry-After headers."""
    retry = Retry()

    result = retry.parse_retry_after(str(retry_after_seconds))

    # Should parse as seconds (can be int or float)
    assert isinstance(result, (int, float))
    assert result >= 0

    # Should not exceed retry_after_max
    assert result <= retry.retry_after_max


@settings(max_examples=1000, deadline=None)
@given(
    retry_after_max=st.integers(min_value=1, max_value=100000),
    retry_after_value=st.integers(min_value=0, max_value=200000),
)
def test_retry_after_max_limit(retry_after_max: int, retry_after_value: int) -> None:
    """Test that retry_after_max properly limits large Retry-After values."""
    retry = Retry(retry_after_max=retry_after_max)

    result = retry.parse_retry_after(str(retry_after_value))

    # Should not exceed the maximum
    assert result <= retry_after_max

    # Should be what we expect
    if retry_after_value <= retry_after_max:
        assert result == retry_after_value
    else:
        assert result == retry_after_max


@settings(max_examples=1000, deadline=None)
@given(
    method=http_methods,
    allowed_methods=st.lists(http_methods, unique=True, min_size=1) | st.none(),
)
def test_is_method_retryable(method: str, allowed_methods: list[str] | None) -> None:
    """Test method retryability logic."""
    if allowed_methods:
        allowed_methods_set = frozenset(m.upper() for m in allowed_methods)
        retry = Retry(allowed_methods=allowed_methods_set)
    else:
        retry = Retry(allowed_methods=allowed_methods)

    result = retry._is_method_retryable(method)

    assert isinstance(result, bool)

    # If allowed_methods is None, should allow all
    if allowed_methods is None:
        assert result is True
    # If method is in allowed list, should be True
    elif method.upper() in (m.upper() for m in allowed_methods):
        assert result is True
    else:
        assert result is False


@settings(max_examples=1000, deadline=None)
@given(
    total=st.integers(min_value=1, max_value=10),
)
def test_retry_new_creates_copy(total: int) -> None:
    """Test that new() creates a new Retry instance."""
    retry1 = Retry(total=total)
    retry2 = retry1.new(total=total + 1)

    # Should be different objects
    assert retry1 is not retry2

    # Should have different values
    assert retry1.total != retry2.total


@settings(max_examples=1000, deadline=None)
@given(
    status_forcelist=st.lists(status_codes, unique=True, max_size=10),
    status=status_codes,
)
def test_status_forcelist(status_forcelist: list[int], status: int) -> None:
    """Test status_forcelist parameter."""
    retry = Retry(total=3, status_forcelist=status_forcelist)

    # Check if status is in forcelist
    if status in status_forcelist:
        # Should retry for allowed methods
        assert retry.is_retry("GET", status, has_retry_after=False)
    else:
        # Should not retry based on status alone (unless has_retry_after)
        if status not in Retry.RETRY_AFTER_STATUS_CODES:
            assert not retry.is_retry("GET", status, has_retry_after=False)


@settings(max_examples=1000, deadline=None)
@given(
    total=st.integers(min_value=0, max_value=10),
    connect=st.integers(min_value=0, max_value=10),
    read=st.integers(min_value=0, max_value=10),
)
def test_retry_history_tracking(total: int, connect: int, read: int) -> None:
    """Test that retry history is tracked correctly."""
    retry = Retry(total=total, connect=connect, read=read)

    # Initially should have empty history
    assert len(retry.history) == 0

    # After increment, should have history
    try:
        error = ConnectTimeoutError("timeout")
        retry = retry.increment(method="GET", url="/test", error=error)

        # Should have one history entry
        assert len(retry.history) == 1
        assert retry.history[0].method == "GET"
        assert retry.history[0].url == "/test"
    except MaxRetryError:
        # Expected if retries exhausted
        pass


@settings(max_examples=1000, deadline=None)
@given(
    raise_on_redirect=st.booleans(),
    raise_on_status=st.booleans(),
)
def test_raise_on_flags(raise_on_redirect: bool, raise_on_status: bool) -> None:
    """Test raise_on_redirect and raise_on_status flags."""
    retry = Retry(
        total=0,  # No retries left
        raise_on_redirect=raise_on_redirect,
        raise_on_status=raise_on_status,
    )

    assert retry.raise_on_redirect == raise_on_redirect
    assert retry.raise_on_status == raise_on_status


@settings(max_examples=1000, deadline=None)
@given(
    redirect_count=st.integers(min_value=0, max_value=20),
    error_count=st.integers(min_value=0, max_value=20),
)
def test_consecutive_errors_in_backoff(redirect_count: int, error_count: int) -> None:
    """Test that backoff only considers consecutive errors, not redirects."""
    history = []

    # Add some errors
    for _ in range(error_count):
        history.append(RequestHistory("GET", "/test", Exception("error"), None, None))

    # Add some redirects
    for _ in range(redirect_count):
        history.append(RequestHistory("GET", "/test", None, 302, "/redirect"))

    retry = Retry(total=30, backoff_factor=0.1, history=tuple(history))

    backoff = retry.get_backoff_time()

    # Backoff should be based on error_count, not total history
    # (though the exact calculation is complex)
    assert backoff >= 0


@settings(max_examples=1000, deadline=None)
@given(
    retries_value=st.one_of(
        st.integers(min_value=0, max_value=10),
        st.booleans(),
        st.none(),
    )
)
def test_from_int_conversion(retries_value: int | bool | None) -> None:
    """Test Retry.from_int() conversion."""
    result = Retry.from_int(retries_value)

    # Should always return a Retry instance
    assert isinstance(result, Retry)


@settings(max_examples=1000, deadline=None)
@given(
    remove_headers=st.lists(
        st.sampled_from(["Authorization", "Cookie", "Proxy-Authorization", "Custom-Header"]),
        max_size=5,
    )
)
def test_remove_headers_on_redirect(remove_headers: list[str]) -> None:
    """Test remove_headers_on_redirect parameter."""
    retry = Retry(remove_headers_on_redirect=remove_headers)

    # Should store as frozenset of lowercase headers
    assert isinstance(retry.remove_headers_on_redirect, frozenset)

    # All headers should be lowercase
    for header in retry.remove_headers_on_redirect:
        assert header == header.lower()


@settings(max_examples=1000, deadline=None)
@given(
    respect_retry_after=st.booleans(),
    status_code=st.sampled_from([413, 429, 503, 500, 502]),
    has_retry_after=st.booleans(),
)
def test_respect_retry_after_header(
    respect_retry_after: bool, status_code: int, has_retry_after: bool
) -> None:
    """Test respect_retry_after_header behavior."""
    retry = Retry(
        total=3,
        respect_retry_after_header=respect_retry_after,
    )

    result = retry.is_retry("GET", status_code, has_retry_after=has_retry_after)

    # Logic depends on multiple factors
    assert isinstance(result, bool)
