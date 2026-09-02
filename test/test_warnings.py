from __future__ import annotations

import warnings

from urllib3.exceptions import HTTPWarning, SecurityWarning

from test import clear_warnings


def test_clear_warnings_accepts_tuple_filter_category() -> None:
    """Filter categories may be a tuple of types, as inserted by codeop."""
    original = list(warnings.filters)
    try:
        warnings.filters.insert(
            0,
            ("ignore", None, (SyntaxWarning, DeprecationWarning), None, 0),
        )
        warnings.simplefilter("always", HTTPWarning)
        # Must not raise TypeError: issubclass() arg 1 must be a class
        clear_warnings(HTTPWarning)
        remaining_categories = [f[2] for f in warnings.filters]
        assert HTTPWarning not in remaining_categories
        assert not any(
            cat is HTTPWarning
            or (isinstance(cat, type) and issubclass(cat, HTTPWarning))
            for cat in remaining_categories
            if not isinstance(cat, tuple)
        )
        assert any(
            isinstance(cat, tuple) and SyntaxWarning in cat
            for cat in remaining_categories
        )
        # Tuple entries that are not HTTPWarning subclasses are preserved.
        clear_warnings(SecurityWarning)
    finally:
        warnings.filters[:] = original
