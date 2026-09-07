from __future__ import annotations

import typing
from unittest import mock

import pytest

import urllib3
from urllib3 import HTTPConnectionPool, HTTPResponse, PoolManager, ProxyManager
from urllib3._collections import HTTPHeaderDict
from urllib3._request_methods import RequestMethods
from urllib3.connection import HTTPConnection


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Type": "application/custom"},
        {b"Content-Type": b"application/custom"},
        {b"Content-Type": "application/custom", "X-Value": b"caf\xe9"},
    ],
)
def test_json_preserves_binary_header_inputs(
    headers: (
        typing.Mapping[str, str | bytes]
        | typing.Mapping[bytes, str | bytes]
        | typing.Mapping[str | bytes, str | bytes]
    ),
) -> None:
    request = RequestMethods()
    with mock.patch.object(request, "urlopen", return_value=HTTPResponse()) as urlopen:
        request.request("POST", "/", headers=headers, json={"hello": "world"})
    sent = HTTPHeaderDict(urlopen.call_args.kwargs["headers"])
    assert sent["Content-Type"] == "application/custom"
    assert len(sent.getlist("Content-Type")) == 1
    assert urlopen.call_args.kwargs["body"] == b'{"hello":"world"}'


@pytest.mark.parametrize(
    "headers",
    [
        {b"Host": b"example.test", b"Accept": b"application/json"},
        {"hOsT": "example.test", "aCcEpT": "application/json"},
    ],
)
def test_proxy_defaults_do_not_duplicate_binary_or_mixed_case_headers(
    headers: typing.Mapping[str, str | bytes] | typing.Mapping[bytes, str | bytes],
) -> None:
    proxy = ProxyManager("http://localhost:8080")
    sent = HTTPHeaderDict(proxy._set_proxy_headers("http://destination.test/", headers))
    assert sent.getlist("Host") == ["example.test"]
    assert sent.getlist("Accept") == ["application/json"]


def test_json_adds_content_type_to_readonly_binary_headers() -> None:
    from types import MappingProxyType

    headers = MappingProxyType({b"X-Value": b"caf\xe9"})
    request = RequestMethods()
    with mock.patch.object(request, "urlopen", return_value=HTTPResponse()) as urlopen:
        request.request("POST", "/", headers=headers, json={})
    sent = HTTPHeaderDict(urlopen.call_args.kwargs["headers"])
    assert sent["Content-Type"] == "application/json"
    assert sent["X-Value"] == "caf\xe9"
    assert list(headers) == [b"X-Value"]


if typing.TYPE_CHECKING:
    from typing_extensions import assert_type

    def check_public_header_inputs(
        strings: dict[str, str],
        byte_keys: dict[bytes, bytes],
        byte_values: dict[str, bytes],
        mixed: dict[str | bytes, str | bytes],
        readonly: typing.Mapping[str, str],
        header_dict: HTTPHeaderDict,
    ) -> None:
        # Preserve ordinary string mappings and HTTPHeaderDict despite Mapping's
        # invariant key parameter, while allowing binary and mixed inputs.
        for headers in (strings, byte_keys, byte_values, mixed, readonly, header_dict):
            pool = HTTPConnectionPool("localhost", headers=headers)
            manager = PoolManager(headers=headers)
            ProxyManager("http://localhost", headers=headers, proxy_headers=headers)
            urllib3.request("GET", "http://localhost", headers=headers)
            manager.request("POST", "http://localhost", headers=headers, json={})
            pool.urlopen("GET", "/", headers=headers)
            HTTPConnection("localhost").request("GET", "/", headers=headers)
            HTTPConnection("localhost").set_tunnel("localhost", headers=headers)
            response = HTTPResponse(headers=headers)
            assert_type(response.headers["Content-Type"], str)
            assert_type(HTTPHeaderDict(headers)["Content-Type"], str)
