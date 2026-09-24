from __future__ import annotations

import warnings

from urllib3.exceptions import HTTPWarning

from test import clear_warnings


def test_clear_warnings_tuple_category_does_not_raise() -> None:
    """Filter categories may be a tuple of types; that must not TypeError.

    See https://github.com/urllib3/urllib3/issues/5053
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", (SyntaxWarning, DeprecationWarning))
        assert any(isinstance(f[2], tuple) for f in warnings.filters)
        clear_warnings(HTTPWarning)
        assert any(isinstance(f[2], tuple) for f in warnings.filters)


def test_clear_warnings_removes_httpwarning_even_inside_tuple() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", (HTTPWarning, UserWarning))
        clear_warnings(HTTPWarning)
        assert not any(
            _tuple_contains_cls(f[2], HTTPWarning) or (
                not isinstance(f[2], tuple) and isinstance(f[2], type) and issubclass(f[2], HTTPWarning)
            )
            for f in warnings.filters
        )


def _tuple_contains_cls(category: object, cls: type[Warning]) -> bool:
    return isinstance(category, tuple) and any(
        isinstance(item, type) and issubclass(item, cls) for item in category
    )
