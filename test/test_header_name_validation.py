from __future__ import annotations

import pytest

from urllib3._collections import HTTPHeaderDict


@pytest.mark.parametrize("header_name", ["X Test", "X\tTest", "X\nTest", "X\rTest"])
def test_header_names_reject_whitespace(header_name: str) -> None:
    with pytest.raises(ValueError, match="Header name cannot contain whitespace"):
        HTTPHeaderDict({header_name: "value"})

    headers = HTTPHeaderDict()
    with pytest.raises(ValueError, match="Header name cannot contain whitespace"):
        headers[header_name] = "value"

    with pytest.raises(ValueError, match="Header name cannot contain whitespace"):
        headers.add(header_name, "value")


@pytest.mark.parametrize("header_name", ["X-Test", "X_Test", "X.Test", "x-test"])
def test_header_names_without_whitespace_are_accepted(header_name: str) -> None:
    headers = HTTPHeaderDict()
    headers[header_name] = "value"
    assert headers[header_name] == "value"

    headers.add(header_name, "another")
    assert headers.getlist(header_name) == ["value", "another"]


def test_bytes_header_names_are_validated() -> None:
    headers = HTTPHeaderDict()

    with pytest.raises(ValueError, match="Header name cannot contain whitespace"):
        headers[b"X Test"] = "value"  # type: ignore[index]

    with pytest.raises(ValueError, match="Header name cannot contain whitespace"):
        headers.add(b"X Test", "value")  # type: ignore[arg-type]
