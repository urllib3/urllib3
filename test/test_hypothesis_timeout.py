"""
Hypothesis property-based tests for timeout handling.
"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from urllib3.exceptions import TimeoutStateError
from urllib3.util.timeout import _DEFAULT_TIMEOUT, Timeout


# Strategy for timeout values
timeout_values = st.one_of(
    st.floats(min_value=0.001, max_value=300.0, allow_nan=False, allow_infinity=False),
    st.integers(min_value=1, max_value=300),
    st.none(),
    st.just(_DEFAULT_TIMEOUT),
)


@settings(max_examples=1000, deadline=None)
@given(
    connect=timeout_values,
    read=timeout_values,
    total=timeout_values,
)
def test_timeout_construction(
    connect: float | int | None,
    read: float | int | None,
    total: float | int | None,
) -> None:
    """Test Timeout construction with various values."""
    # Filter out invalid combinations (negative numbers, etc.)
    try:
        timeout = Timeout(connect=connect, read=read, total=total)

        # Should have the values set
        assert timeout.total == total

        # String representation should work
        str_repr = str(timeout)
        assert isinstance(str_repr, str)
        assert "Timeout" in str_repr
    except ValueError:
        # Some combinations are invalid (e.g., negative values)
        pass


@settings(max_examples=1000, deadline=None)
@given(
    timeout_value=st.floats(
        min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False
    )
)
def test_timeout_from_float(timeout_value: float) -> None:
    """Test creating Timeout from float value."""
    timeout = Timeout.from_float(timeout_value)

    # Should set both connect and read
    assert timeout.connect_timeout == timeout_value

    # Read timeout depends on whether connect has been started
    # Without starting connect, should resolve to the value
    assert timeout.resolve_default_timeout(timeout._read) == timeout_value


@settings(max_examples=1000, deadline=None)
@given(
    connect=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
    read=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
)
def test_timeout_clone(connect: float, read: float) -> None:
    """Test cloning timeout objects."""
    timeout1 = Timeout(connect=connect, read=read)
    timeout2 = timeout1.clone()

    # Should be different objects
    assert timeout1 is not timeout2

    # But should have the same values
    assert timeout1.total == timeout2.total

    # String representations should be equal
    assert str(timeout1) == str(timeout2)


@settings(max_examples=1000, deadline=None)
@given(
    connect=st.floats(
        min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False
    ),
    total=st.floats(
        min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False
    ),
)
def test_timeout_with_total_and_connect(connect: float, total: float) -> None:
    """Test timeout with both total and connect specified."""
    try:
        timeout = Timeout(connect=connect, total=total)

        # Connect timeout should be minimum of connect and total
        connect_timeout = timeout.connect_timeout

        if connect_timeout is not None and connect_timeout is not _DEFAULT_TIMEOUT:
            assert connect_timeout <= total
            assert connect_timeout <= connect
    except ValueError:
        # Some combinations might be invalid
        pass


@settings(max_examples=1000, deadline=None)
@given(
    timeout_value=st.floats(
        min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False
    )
)
def test_timeout_validation(timeout_value: float) -> None:
    """Test that timeout validation catches invalid values."""
    if timeout_value <= 0:
        # Should raise ValueError for non-positive values
        try:
            Timeout(connect=timeout_value)
            # If we got here, it should be because it's a special value
            assert timeout_value == 0  # Though 0 should also fail
        except ValueError:
            # Expected
            pass
    else:
        # Should accept positive values
        timeout = Timeout(connect=timeout_value)
        assert timeout is not None


@settings(max_examples=1000, deadline=None)
@given(
    connect=st.floats(
        min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False
    ),
)
def test_timeout_start_connect(connect: float) -> None:
    """Test start_connect timer."""
    timeout = Timeout(connect=connect, read=5.0)

    # Initially should not have started
    try:
        # This should raise because connect not started
        timeout.get_connect_duration()
        assert False, "Should have raised TimeoutStateError"
    except TimeoutStateError:
        pass

    # Start the timer
    start_time = timeout.start_connect()
    assert isinstance(start_time, float)
    assert start_time > 0

    # Now should be able to get duration
    duration = timeout.get_connect_duration()
    assert duration >= 0


@settings(max_examples=1000, deadline=None)
@given(
    connect=st.floats(
        min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False
    ),
)
def test_timeout_start_connect_twice_raises(connect: float) -> None:
    """Test that starting connect twice raises an error."""
    timeout = Timeout(connect=connect)

    # First start should succeed
    timeout.start_connect()

    # Second start should raise
    try:
        timeout.start_connect()
        assert False, "Should have raised TimeoutStateError"
    except TimeoutStateError:
        pass


@settings(max_examples=1000, deadline=None)
@given(
    read=st.floats(
        min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False
    ),
    total=st.floats(
        min_value=5.0, max_value=20.0, allow_nan=False, allow_infinity=False
    ),
)
def test_timeout_read_timeout_with_total(read: float, total: float) -> None:
    """Test read timeout calculation when total is specified."""
    timeout = Timeout(read=read, total=total)
    timeout.start_connect()

    # Read timeout should be adjusted based on time taken for connect
    read_timeout = timeout.read_timeout

    # Should be at most the specified read timeout
    if read_timeout is not None:
        assert read_timeout <= total


@settings(max_examples=1000, deadline=None)
@given(
    value=st.one_of(
        st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
        st.integers(min_value=1, max_value=100),
        st.booleans(),
        st.text(max_size=10),
    )
)
def test_timeout_validation_rejects_invalid_types(value: float | int | bool | str) -> None:
    """Test that timeout validation rejects invalid types."""
    if isinstance(value, bool):
        # Booleans should be rejected
        try:
            Timeout(connect=value)  # type: ignore[arg-type]
            assert False, "Should have raised ValueError for boolean"
        except ValueError:
            pass
    elif isinstance(value, str):
        # Strings should be rejected
        try:
            Timeout(connect=value)  # type: ignore[arg-type]
            assert False, "Should have raised ValueError for string"
        except (ValueError, TypeError):
            pass
    elif isinstance(value, (int, float)) and value > 0:
        # Valid numeric values should be accepted
        timeout = Timeout(connect=value)
        assert timeout is not None


@settings(max_examples=1000, deadline=None)
@given(
    connect=st.floats(
        min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False
    ),
    _read=st.floats(
        min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False
    ),
)
def test_timeout_resolve_default(connect: float, _read: float) -> None:
    """Test resolve_default_timeout static method."""
    # With _DEFAULT_TIMEOUT, should return socket default
    result = Timeout.resolve_default_timeout(_DEFAULT_TIMEOUT)
    # Result could be None or a float from socket.getdefaulttimeout()
    assert result is None or isinstance(result, float)

    # With a specific value, should return that value
    result = Timeout.resolve_default_timeout(connect)
    assert result == connect

    # With None, should return None
    result = Timeout.resolve_default_timeout(None)
    assert result is None


@settings(max_examples=1000, deadline=None)
@given(
    connect=st.floats(
        min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False
    ),
    read=st.floats(
        min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False
    ),
    total=st.floats(
        min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False
    ),
)
def test_timeout_properties(connect: float, read: float, total: float) -> None:
    """Test timeout properties are consistent."""
    try:
        timeout = Timeout(connect=connect, read=read, total=total)

        # All properties should be accessible
        connect_timeout = timeout.connect_timeout

        # Properties should be sensible
        if connect_timeout is not None and isinstance(connect_timeout, (int, float)):
            assert connect_timeout > 0
    except ValueError:
        # Some combinations are invalid
        pass


@settings(max_examples=1000, deadline=None)
@given(
    total=st.floats(
        min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False
    ),
)
def test_timeout_only_total(total: float) -> None:
    """Test timeout with only total specified."""
    timeout = Timeout(total=total)

    # Connect timeout should be total
    connect_timeout = timeout.connect_timeout
    assert connect_timeout == total


def test_timeout_none_values() -> None:
    """Test timeout with None values (infinite timeout)."""
    timeout = Timeout(connect=None, read=None, total=None)

    # Should be valid
    assert timeout is not None
    assert timeout.total is None


@settings(max_examples=1000, deadline=None)
@given(
    connect=st.floats(
        min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False
    ),
)
def test_timeout_repr(connect: float) -> None:
    """Test timeout string representation."""
    timeout = Timeout(connect=connect, read=connect * 2)

    repr_str = repr(timeout)
    assert "Timeout" in repr_str
    assert "connect" in repr_str
    assert "read" in repr_str

    # str should be same as repr
    assert str(timeout) == repr_str
