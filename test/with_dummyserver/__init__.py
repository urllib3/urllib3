from __future__ import annotations

import typing

import pytest

from urllib3 import HTTPConnectionPool, PoolManager
from urllib3.response import BaseHTTPResponse

PoolFactory = typing.Callable[..., HTTPConnectionPool]
PoolManagerFactory = typing.Callable[..., PoolManager]
RequestFunction = typing.Callable[..., BaseHTTPResponse]


@pytest.mark.usefixtures("server_scheme")
class DummyServerTestCase:
    """Base class for tests using a local HTTP or HTTPS dummy server."""

    host = "localhost"
    host_alt = "127.0.0.1"
    port: typing.ClassVar[int]
    scheme: typing.ClassVar[str]
    base_url: typing.ClassVar[str]
    base_url_alt: typing.ClassVar[str]
