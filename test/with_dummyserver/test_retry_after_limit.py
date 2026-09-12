from __future__ import annotations

import socket
from unittest import mock

import pytest

from dummyserver.testcase import SocketDummyServerTestCase
from urllib3 import HTTPConnectionPool, PoolManager
from urllib3.exceptions import RetryAfterMaxExceededError
from urllib3.util.retry import Retry


class TestRetryAfterConnectionRelease(SocketDummyServerTestCase):
    @pytest.mark.parametrize(
        "manager,status", [(False, 503), (False, 302), (True, 503)]
    )
    def test_excessive_wait_releases_streamed_response(
        self, manager: bool, status: int
    ) -> None:
        requests: list[bytes] = []

        def serve(listener: socket.socket) -> None:
            with listener.accept()[0] as sock:
                sock.settimeout(5)
                for index in range(2):
                    request = b""
                    while not request.endswith(b"\r\n\r\n"):
                        chunk = sock.recv(65536)
                        if not chunk:
                            raise RuntimeError("Connection closed before next request")
                        request += chunk
                    requests.append(request)
                    if index == 0:
                        response = (
                            f"HTTP/1.1 {status} Retry\r\n"
                            "Retry-After: 3600\r\nLocation: /redirected\r\n"
                            "Content-Length: 4\r\n\r\nbusy"
                        ).encode("ascii")
                    else:
                        response = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"
                    sock.sendall(response)

        self._start_server(serve)
        retry = Retry(total=1, retry_after_max=60, raise_on_retry_after_max=True)
        client = (
            PoolManager(maxsize=1, block=True)
            if manager
            else HTTPConnectionPool(self.host, self.port, maxsize=1, block=True)
        )
        prefix = f"http://{self.host}:{self.port}" if manager else ""
        with client, mock.patch("time.sleep") as sleep:
            with pytest.raises(RetryAfterMaxExceededError) as caught:
                client.request(
                    "GET",
                    prefix + "/first",
                    retries=retry,
                    preload_content=False,
                    timeout=2,
                    pool_timeout=1,
                )
            assert caught.value.retry_after == 3600
            assert caught.value.max_wait == 60
            assert len(requests) == 1
            sleep.assert_not_called()
            response = client.request(
                "GET",
                prefix + "/next",
                retries=False,
                timeout=2,
                pool_timeout=1,
            )
            assert response.data == b"ok"
        assert len(requests) == 2
        assert requests[0].startswith(b"GET /first ")
        assert requests[1].startswith(b"GET /next ")
