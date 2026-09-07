from __future__ import annotations

import typing

import pytest

from urllib3._collections import HTTPHeaderDict
from urllib3._request_methods import _prepare_request_headers_for_method_change
from urllib3.connectionpool import _copy_and_merge_proxy_headers


@pytest.mark.parametrize("use_bytes", [False, True])
def test_method_change_removes_the_same_entity_headers(use_bytes: bool) -> None:
    removable = [
        "Content-Encoding",
        "Content-Language",
        "Content-Location",
        "Content-Type",
        "Content-Length",
        "Digest",
        "Last-Modified",
    ]
    source: typing.Mapping[str | bytes, str | bytes]
    if use_bytes:
        source = {
            **{name.encode(): b"value" for name in removable},
            b"Transfer-Encoding": b"chunked",
            b"X-Keep": b"value",
        }
    else:
        source = {
            **{name: "value" for name in removable},
            "Transfer-Encoding": "chunked",
            "X-Keep": "value",
        }
    original = dict(source)

    prepared = _prepare_request_headers_for_method_change(source)

    expected = (
        {b"Transfer-Encoding": b"chunked", b"X-Keep": b"value"}
        if use_bytes
        else {"Transfer-Encoding": "chunked", "X-Keep": "value"}
    )
    assert dict(prepared) == expected
    assert source == original


def test_forward_proxy_merge_accepts_read_only_mapping() -> None:
    class ReadOnlyHeaders(typing.Mapping[bytes, bytes]):
        def __init__(self, values: dict[bytes, bytes]) -> None:
            self._data = values

        def __getitem__(self, key: bytes) -> bytes:
            return self._data[key]

        def __iter__(self) -> typing.Iterator[bytes]:
            return iter(self._data)

        def __len__(self) -> int:
            return len(self._data)

    headers = ReadOnlyHeaders({b"X-Request": b"value"})
    merged = _copy_and_merge_proxy_headers(headers, {b"X-Proxy": b"value"})

    assert dict(merged) == {b"X-Request": b"value", b"X-Proxy": b"value"}
    assert dict(headers) == {b"X-Request": b"value"}


def test_proxy_headers_override_mixed_case_and_preserve_repeated_headers() -> None:
    request_headers = HTTPHeaderDict()
    request_headers.add("X-Repeat", "one")
    request_headers.add("X-Repeat", "two")
    request_headers["proxy-authorization"] = "request"

    merged = _copy_and_merge_proxy_headers(
        request_headers,
        {b"Proxy-Authorization": b"configured", b"X-Opaque": b"\xff"},
    )

    assert isinstance(merged, HTTPHeaderDict)
    assert merged.getlist("X-Repeat") == ["one", "two"]
    assert merged["Proxy-Authorization"] == "configured"
    assert merged["X-Opaque"].encode("latin-1") == b"\xff"


def test_repeated_proxy_headers_are_combined_without_reordering() -> None:
    request_headers = HTTPHeaderDict(
        {
            "A": "a",
            "Proxy-Authorization": "request",
            "B": "b",
        }
    )
    proxy_headers = HTTPHeaderDict()
    proxy_headers.add("Proxy-Authorization", "one")
    proxy_headers.add("Proxy-Authorization", "two")

    merged = _copy_and_merge_proxy_headers(request_headers, proxy_headers)

    assert isinstance(merged, HTTPHeaderDict)
    assert list(merged.items()) == [
        ("A", "a"),
        ("Proxy-Authorization", "one, two"),
        ("B", "b"),
    ]
