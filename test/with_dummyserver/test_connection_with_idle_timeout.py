from __future__ import annotations

import contextlib
import time
import typing

import pytest

from dummyserver.testcase import HypercornDummyServerTestCase as server
from urllib3 import HTTPConnectionPool


@pytest.fixture()
def pool() -> typing.Generator[HTTPConnectionPool, None, None]:
    server.setup_class()

    with HTTPConnectionPool(
        server.host, server.port, idle_timeout=5, maxsize=1
    ) as pool:
        yield pool

    server.teardown_class()


def test_last_activity_is_updated(pool: HTTPConnectionPool) -> None:
    with contextlib.closing(pool._get_conn()) as conn:
        assert conn.idle_timeout is not None
        assert conn.last_activity is not None
        la = conn.last_activity
        time.sleep(0.5)  # timer resolution in windows is 16.5 ms
        conn.request("GET", "/")
        assert conn.last_activity > la


def test_same_connection_if_time_is_not_exhausted(pool: HTTPConnectionPool) -> None:
    with contextlib.closing(pool._get_conn()) as conn1:
        conn1.request("GET", "/")
        response = conn1.getresponse()
        response._pool = pool  # type: ignore[attr-defined]
        response._connection = conn1  # type: ignore[attr-defined]
        response.release_conn()

        with contextlib.closing(pool._get_conn()) as conn2:
            assert conn1 is conn2


def test_new_connection_if_idle_timeout_has_passed(pool: HTTPConnectionPool) -> None:
    with contextlib.closing(pool._get_conn()) as conn1:
        conn1.request("GET", "/")
        response = conn1.getresponse()
        response._pool = pool  # type: ignore[attr-defined]
        response._connection = conn1  # type: ignore[attr-defined]
        response.release_conn()

        time.sleep(6)
        with contextlib.closing(pool._get_conn()) as conn2:
            assert conn1 is not conn2
