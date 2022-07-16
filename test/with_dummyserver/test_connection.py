from http.client import ResponseNotReady
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


def test_returns_urllib3_HTTPResponse(pool: HTTPConnectionPool) -> None:
    conn = pool._get_conn()

    method = "GET"
    path = "/"

    conn.request(method, path)

    response: HTTPResponse = conn.getresponse()

    assert isinstance(response, HTTPResponse)


def test_does_not_release_conn(pool: HTTPConnectionPool) -> None:
    conn = pool._get_conn()

    method = "GET"
    path = "/"

    conn.request(method, path)

    response: HTTPResponse = conn.getresponse()

    response.release_conn()
    assert pool.pool.qsize() == 0  # type: ignore[union-attr]


def test_releases_conn(pool: HTTPConnectionPool) -> None:
    conn = pool._get_conn()

    method = "GET"
    path = "/"

    conn.request(method, path)

    response: HTTPResponse = conn.getresponse()
    # If these variables are set by the pool
    # then the response can release the connection
    # back into the pool.
    response._pool = pool
    response._connection = conn

    response.release_conn()
    assert pool.pool.qsize() == 1  # type: ignore[union-attr]


def test_double_getresponse(pool: HTTPConnectionPool) -> None:
    conn = pool._get_conn()

    method = "GET"
    path = "/"

    conn.request(method, path)

    _: HTTPResponse = conn.getresponse()

    # Calling getrepsonse() twice should cause an error
    with pytest.raises(ResponseNotReady):
        conn.getresponse()
