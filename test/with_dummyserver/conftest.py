from __future__ import annotations

import typing
from functools import partial
from pathlib import Path
from test.conftest import _write_cert_to_dir

import pytest
import trustme

import urllib3
from dummyserver.app import RETRY_TEST_NAMES, hypercorn_app
from dummyserver.hypercornserver import run_hypercorn_in_thread
from dummyserver.socketserver import DEFAULT_CA, DEFAULT_CA_KEY, DEFAULT_CERTS
from urllib3 import HTTPConnectionPool, HTTPSConnectionPool, PoolManager

from . import PoolFactory, PoolManagerFactory, RequestFunction


@pytest.fixture(scope="class", params=["http", "https"])
def server_scheme(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> typing.Generator[str]:
    """
    Start a server for the selected scheme and set the test class URLs.
    """
    cls = request.cls
    assert cls is not None
    scheme = request.param
    if scheme == "https":
        ca = trustme.CA.from_pem(
            Path(DEFAULT_CA).read_bytes(), Path(DEFAULT_CA_KEY).read_bytes()
        )
        server_cert = ca.issue_cert(cls.host, cls.host_alt)
        certs = {
            **DEFAULT_CERTS,
            **_write_cert_to_dir(server_cert, tmp_path_factory.mktemp("http-server")),
        }
    else:
        certs = None
    with run_hypercorn_in_thread(cls.host, certs, hypercorn_app) as port:
        cls.scheme = scheme
        cls.port = port
        cls.base_url = f"{scheme}://{cls.host}:{port}"
        cls.base_url_alt = f"{scheme}://{cls.host_alt}:{port}"
        yield scheme


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
