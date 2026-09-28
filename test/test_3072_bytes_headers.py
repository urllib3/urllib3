from __future__ import annotations

import pytest

from urllib3._collections import HTTPHeaderDict


@pytest.fixture()
def d() -> HTTPHeaderDict:
    header_dict = HTTPHeaderDict(Cookie="foo")
    header_dict.add("cookie", "bar")
    return header_dict


class TestHTTPHeaderDictBytesValues:
    """Regression tests for https://github.com/urllib3/urllib3/issues/3072."""

    def test_setitem_with_bytes_value(self, d: HTTPHeaderDict) -> None:
        # The bytes value gets converted to str. The API is typed for str only,
        # but the implementation continues supports bytes.
        d["Cookie"] = b"foo"  # type: ignore[assignment]
        assert d["cookie"] == "foo"
        assert d.getlist("cookie") == ["foo"]
        d["Cookie"] = "Schönefeld/1.18.0".encode("latin-1")  # type: ignore[assignment]
        assert d["cookie"] == "Schönefeld/1.18.0"

    def test_add_with_bytes_value(self, d: HTTPHeaderDict) -> None:
        # The bytes value gets converted to str. The API is typed for str only,
        # but the implementation continues supports bytes.
        d.add("bar", b"foo")  # type: ignore[arg-type]
        d.add("Bar", "bar")
        d.add(b"BAR", b"asdf", combine=True)  # type: ignore[arg-type]
        assert d.getlist("bar") == ["foo", "bar, asdf"]
        assert d["bar"] == "foo, bar, asdf"
