from typing import Generator

import pytest

from dummyserver.testcase import HTTPDummyServerTestCase as server
from urllib3 import HTTPConnectionPool
from urllib3.response import HTTPResponse


@pytest.fixture()
def pool() -> Generator[HTTPConnectionPool, None, None]:
    server.setup_class()

    with HTTPConnectionPool(server.host, server.port) as pool:
        yield pool

    server.teardown_class()


def test_requires_kwargs(pool: HTTPConnectionPool) -> None:
    conn = pool._get_conn()

    with pytest.raises(TypeError) as e:
        conn.getresponse("GET", "google.com", pool)  # type: ignore

    assert "getresponse() takes 1 positional argument but 4 were given" in str(e)


def test_returns_urllib3_HTTPResponse(pool: HTTPConnectionPool) -> None:
    conn = pool._get_conn()

    method = "GET"
    path = "/"

    conn.request(method, path)

    response: HTTPResponse = conn.getresponse(
        method=method,
        url=path,
        pool=pool,
        retries=None,
        decode_content=False,
        enforce_content_length=False,
        preload_content=False,
        response_conn=None,
    )

    assert isinstance(response, HTTPResponse)


def test_does_not_release_conn(pool: HTTPConnectionPool) -> None:
    conn = pool._get_conn()

    method = "GET"
    path = "/"

    conn.request(method, path)

    response: HTTPResponse = conn.getresponse(
        method=method,
        url=path,
        pool=pool,
        retries=None,
        decode_content=False,
        enforce_content_length=False,
        preload_content=True,
        response_conn=None,
    )

    response.close()

    assert pool.pool.qsize() == 0  # type: ignore[union-attr]


def test_releases_conn(pool: HTTPConnectionPool) -> None:
    conn = pool._get_conn()

    method = "GET"
    path = "/"

    conn.request(method, path)

    response: HTTPResponse = conn.getresponse(
        method=method,
        url=path,
        pool=pool,
        retries=None,
        decode_content=False,
        enforce_content_length=False,
        preload_content=True,
        response_conn=conn,
    )

    response.close()

    assert pool.pool.qsize() == 1  # type: ignore[union-attr]
