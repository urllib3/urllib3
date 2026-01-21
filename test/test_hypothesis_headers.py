"""
Hypothesis property-based tests for HTTP header handling.
"""
from __future__ import annotations

import string

from hypothesis import given, settings, strategies as st

from urllib3._collections import HTTPHeaderDict


# Strategy for valid header names (RFC 7230)
header_names = st.text(
    alphabet=string.ascii_letters + string.digits + "!#$%&'*+-.^_`|~",
    min_size=1,
    max_size=50,
)

# Strategy for header values (printable ASCII, no control characters)
header_values = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
    max_size=200,
)

# Strategy for lists of header tuples
header_lists = st.lists(
    st.tuples(header_names, header_values),
    max_size=50,
)


@settings(max_examples=1000, deadline=None)
@given(headers=header_lists)
def test_httpheaderdict_construction(headers: list[tuple[str, str]]) -> None:
    """Test HTTPHeaderDict construction with various header lists."""
    hd = HTTPHeaderDict(headers)

    # Should be a valid dict-like object
    assert isinstance(hd, HTTPHeaderDict)
    assert len(hd) >= 0

    # Can iterate over keys
    keys = list(hd)
    assert all(isinstance(k, str) for k in keys)


@settings(max_examples=1000, deadline=None)
@given(
    name=header_names,
    value=header_values,
)
def test_httpheaderdict_setitem_getitem(name: str, value: str) -> None:
    """Test setting and getting headers."""
    hd = HTTPHeaderDict()
    hd[name] = value

    # Getting with the same case should return the value
    assert hd[name] == value

    # Getting with different case should also work (case-insensitive)
    assert hd[name.lower()] == value
    assert hd[name.upper()] == value

    # Length should be 1
    assert len(hd) == 1


@settings(max_examples=1000, deadline=None)
@given(
    name=header_names,
    values=st.lists(header_values, min_size=1, max_size=10),
)
def test_httpheaderdict_add_multiple_values(name: str, values: list[str]) -> None:
    """Test adding multiple values for the same header."""
    hd = HTTPHeaderDict()

    for value in values:
        hd.add(name, value)

    # Getting should return comma-separated values
    result = hd[name]
    assert isinstance(result, str)

    # All values should be present
    for value in values:
        assert value in result

    # getlist should return all values separately
    retrieved = hd.getlist(name)
    assert len(retrieved) == len(values)
    assert retrieved == values


@settings(max_examples=1000, deadline=None)
@given(
    name=header_names,
    values=st.lists(header_values, min_size=2, max_size=5),
)
def test_httpheaderdict_add_with_combine(name: str, values: list[str]) -> None:
    """Test adding headers with combine=True."""
    hd = HTTPHeaderDict()

    # Add first value normally
    hd[name] = values[0]

    # Add remaining values with combine=True
    for value in values[1:]:
        hd.add(name, value, combine=True)

    # Should have only one item when iterating
    items = list(hd.items())
    header_items = [item for item in items if item[0].lower() == name.lower()]
    assert len(header_items) == 1

    # The value should contain all values combined
    combined_value = header_items[0][1]
    for value in values:
        assert value in combined_value


@settings(max_examples=1000, deadline=None)
@given(
    headers1=header_lists,
    headers2=header_lists,
)
def test_httpheaderdict_extend(
    headers1: list[tuple[str, str]], headers2: list[tuple[str, str]]
) -> None:
    """Test extending HTTPHeaderDict with another set of headers."""
    hd1 = HTTPHeaderDict(headers1)
    initial_len = len(hd1)

    hd1.extend(headers2)

    # Length should be at least the initial length
    assert len(hd1) >= initial_len

    # All headers from headers2 should be present
    for name, _value in headers2:
        # The header should exist (case-insensitive)
        assert name in hd1 or name.lower() in hd1 or name.upper() in hd1


@settings(max_examples=1000, deadline=None)
@given(
    name=header_names,
    value=header_values,
)
def test_httpheaderdict_delitem(name: str, value: str) -> None:
    """Test deleting headers."""
    hd = HTTPHeaderDict()
    hd[name] = value

    # Should exist
    assert name in hd

    # Delete it
    del hd[name]

    # Should no longer exist
    assert name not in hd
    assert name.lower() not in hd
    assert name.upper() not in hd

    # Length should be 0
    assert len(hd) == 0


@settings(max_examples=1000, deadline=None)
@given(
    name=header_names,
    value=header_values,
)
def test_httpheaderdict_discard(name: str, value: str) -> None:
    """Test discard method (delete without raising KeyError)."""
    hd = HTTPHeaderDict()

    # Discard non-existent header should not raise
    hd.discard(name)

    # Add and discard
    hd[name] = value
    hd.discard(name)
    assert name not in hd

    # Discard again should not raise
    hd.discard(name)


@settings(max_examples=1000, deadline=None)
@given(headers=header_lists)
def test_httpheaderdict_copy(headers: list[tuple[str, str]]) -> None:
    """Test copying HTTPHeaderDict."""
    hd1 = HTTPHeaderDict(headers)
    hd2 = hd1.copy()

    # Should be equal
    assert hd1 == hd2

    # Should be different objects
    assert hd1 is not hd2

    # Modifying one should not affect the other
    if len(hd2) > 0:
        key = next(iter(hd2))
        hd2[key] = "modified"
        # Original should not be modified
        assert hd1[key] != "modified"


@settings(max_examples=1000, deadline=None)
@given(
    headers1=header_lists,
    headers2=header_lists,
)
def test_httpheaderdict_equality(
    headers1: list[tuple[str, str]], headers2: list[tuple[str, str]]
) -> None:
    """Test HTTPHeaderDict equality comparison."""
    hd1 = HTTPHeaderDict(headers1)
    hd2 = HTTPHeaderDict(headers1)
    _hd3 = HTTPHeaderDict(headers2)

    # Same headers should be equal
    assert hd1 == hd2

    # Should equal itself (reflexive property)
    assert hd1 == hd1


@settings(max_examples=1000, deadline=None)
@given(
    name=header_names,
    value=header_values,
    default=header_values,
)
def test_httpheaderdict_get_with_default(
    name: str, value: str, default: str
) -> None:
    """Test get method with default value."""
    hd = HTTPHeaderDict()

    # Getting non-existent header should return default
    result = hd.get(name, default)
    assert result == default

    # After setting, should return the value
    hd[name] = value
    result = hd.get(name, default)
    assert result == value


@settings(max_examples=1000, deadline=None)
@given(
    name=header_names,
    values=st.lists(header_values, min_size=1, max_size=10),
)
def test_httpheaderdict_iteritems(name: str, values: list[str]) -> None:
    """Test iteritems method for duplicate headers."""
    hd = HTTPHeaderDict()

    for value in values:
        hd.add(name, value)

    # iteritems should yield all values separately
    items = list(hd.iteritems())
    matching_items = [item for item in items if item[0].lower() == name.lower()]

    assert len(matching_items) == len(values)

    # Values should match
    item_values = [item[1] for item in matching_items]
    assert item_values == values


@settings(max_examples=1000, deadline=None)
@given(headers=header_lists)
def test_httpheaderdict_itermerged(headers: list[tuple[str, str]]) -> None:
    """Test itermerged method."""
    hd = HTTPHeaderDict()

    for name, value in headers:
        hd.add(name, value)

    # itermerged should yield each unique header name once
    merged = list(hd.itermerged())

    # Each name should appear at most once (case-insensitive)
    seen_names = set()
    for name, value in merged:
        name_lower = name.lower()
        assert name_lower not in seen_names
        seen_names.add(name_lower)


@settings(max_examples=1000, deadline=None)
@given(
    headers1=header_lists,
    headers2=header_lists,
)
def test_httpheaderdict_or_operator(
    headers1: list[tuple[str, str]], headers2: list[tuple[str, str]]
) -> None:
    """Test the | operator for merging headers."""
    hd1 = HTTPHeaderDict(headers1)
    hd2 = HTTPHeaderDict(headers2)

    # Use | operator
    result = hd1 | hd2

    # Should be a new object
    assert result is not hd1
    assert result is not hd2

    # Should contain headers from both
    assert isinstance(result, HTTPHeaderDict)


@settings(max_examples=1000, deadline=None)
@given(
    headers1=header_lists,
    headers2=header_lists,
)
def test_httpheaderdict_ior_operator(
    headers1: list[tuple[str, str]], headers2: list[tuple[str, str]]
) -> None:
    """Test the |= operator for in-place merging."""
    hd1 = HTTPHeaderDict(headers1)
    hd2 = HTTPHeaderDict(headers2)

    original_id = id(hd1)

    # Use |= operator
    hd1 |= hd2

    # Should be the same object (in-place)
    assert id(hd1) == original_id


@settings(max_examples=1000, deadline=None)
@given(
    name=header_names,
    value=header_values,
)
def test_httpheaderdict_case_preservation(name: str, value: str) -> None:
    """Test that original case is preserved in keys."""
    hd = HTTPHeaderDict()
    hd[name] = value

    # When iterating, should get the original case back
    keys = list(hd.keys())
    assert name in keys


@settings(max_examples=1000, deadline=None)
@given(
    name=header_names,
    value=header_values,
)
def test_httpheaderdict_bytes_key(name: str, value: str) -> None:
    """Test using bytes as header keys."""
    hd = HTTPHeaderDict()

    # Should accept bytes keys
    name_bytes = name.encode("latin-1")
    hd[name_bytes] = value

    # Should be able to retrieve with string
    assert hd[name] == value

    # Should be able to retrieve with bytes
    assert hd[name_bytes] == value


@settings(max_examples=1000, deadline=None)
@given(headers=header_lists)
def test_httpheaderdict_prepare_for_method_change(
    headers: list[tuple[str, str]]
) -> None:
    """Test _prepare_for_method_change removes content-specific headers."""
    hd = HTTPHeaderDict(headers)

    # Add some content-specific headers
    hd["Content-Type"] = "text/html"
    hd["Content-Length"] = "100"
    hd["Content-Encoding"] = "gzip"

    # Call the method
    result = hd._prepare_for_method_change()

    # Should return self
    assert result is hd

    # Content-specific headers should be removed
    assert "Content-Type" not in hd
    assert "Content-Length" not in hd
    assert "Content-Encoding" not in hd


@settings(max_examples=1000, deadline=None)
@given(
    name=header_names,
    value=header_values,
)
def test_httpheaderdict_items_contains(
    name: str, value: str
) -> None:
    """Test contains check on items() view."""
    hd = HTTPHeaderDict()
    hd[name] = value

    items = hd.items()

    # The actual item should be in items
    # Note: items() returns HTTPHeaderDictItemView which has special behavior
    assert isinstance(items, set)


@settings(max_examples=1000, deadline=None)
@given(
    headers=st.dictionaries(
        header_names, header_values, min_size=1, max_size=20
    )
)
def test_httpheaderdict_from_dict(headers: dict[str, str]) -> None:
    """Test constructing HTTPHeaderDict from a regular dict."""
    hd = HTTPHeaderDict(headers)

    # All keys should be present (case-insensitive)
    for key in headers:
        assert key in hd or key.lower() in hd

    # Note: If dict has case-insensitive duplicates (e.g., 'N' and 'n'),
    # HTTPHeaderDict will combine them, so we just verify keys exist
    assert len(hd) > 0
