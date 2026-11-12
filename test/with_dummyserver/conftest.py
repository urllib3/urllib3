from __future__ import annotations

import typing
from functools import partial

import pytest

import urllib3
from dummyserver.app import RETRY_TEST_NAMES
from dummyserver.socketserver import DEFAULT_CA
from dummyserver.testcase import DualHypercornDummyServerTestCase
from urllib3 import HTTPConnectionPool, HTTPSConnectionPool, PoolManager

from . import PoolFactory, PoolManagerFactory, RequestFunction


@pytest.fixture(scope="class", params=["http", "https"])
def server_scheme(request: pytest.FixtureRequest) -> str:
    """
    Select one of the running servers and set the test class URLs.
    """
    cls = request.cls
    assert cls is not None and issubclass(cls, DualHypercornDummyServerTestCase)
    scheme: str = request.param
    cls.scheme = scheme
    cls.port = cls.https_port if scheme == "https" else cls.http_port
    cls.base_url = f"{scheme}://{cls.host}:{cls.port}"
    cls.base_url_alt = f"{scheme}://{cls.host_alt}:{cls.port}"
    return scheme


@pytest.fixture
def connection_pool_kw(server_scheme: str) -> dict[str, typing.Any]:
    """Configure pools to trust the HTTPS test certificate."""
    return {"ca_certs": DEFAULT_CA} if server_scheme == "https" else {}


@pytest.fixture
def reset_retry_state() -> None:
    """
    Reset the retry endpoint so each test starts with a failed response.
    """
    RETRY_TEST_NAMES.clear()


@pytest.fixture
def pool_factory(
    server_scheme: str, connection_pool_kw: dict[str, typing.Any]
) -> PoolFactory:
    """Return a pool constructor configured for the test server."""
    pool_cls = HTTPSConnectionPool if server_scheme == "https" else HTTPConnectionPool
    return partial(pool_cls, **connection_pool_kw)


@pytest.fixture
def pool_manager_factory(
    connection_pool_kw: dict[str, typing.Any],
) -> PoolManagerFactory:
    """
    Return a pool manager constructor configured for the test server.
    """
    return partial(PoolManager, **connection_pool_kw)


@pytest.fixture
def http_request(
    pool_manager_factory: PoolManagerFactory, monkeypatch: pytest.MonkeyPatch
) -> typing.Generator[RequestFunction]:
    """
    Provide top-level requests with a temporary pool for the test
    server.
    """
    with pool_manager_factory() as pool:
        monkeypatch.setattr(urllib3, "_DEFAULT_POOL", pool)
        yield urllib3.request
