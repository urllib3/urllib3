from __future__ import annotations

import socket
import threading
from test import LONG_TIMEOUT
from unittest import mock

import pytest

from dummyserver.testcase import SocketDummyServerTestCase, consume_socket
from urllib3 import PoolManager
from urllib3.exceptions import RetryAfterMaxExceededError
from urllib3.util.retry import Retry


class TestRetryAfterOnRedirect(SocketDummyServerTestCase):
    """``PoolManager`` follows redirects itself: it passes ``redirect=False`` to
    the connection pool, so ``HTTPConnectionPool``'s ``sleep_for_retry()`` call
    never runs and a ``Retry-After`` header on a redirect is ignored."""

    def _serve_redirect(self, retry_after: str | None) -> None:
        """Answer the first request with a 302, the second one with a 200."""
        quit_event = threading.Event()

        def socket_handler(listener: socket.socket) -> None:
            port = listener.getsockname()[1]
            listener.settimeout(LONG_TIMEOUT)
            for i in range(2):
                while True:
                    if quit_event.is_set():
                        return
                    try:
                        sock = listener.accept()[0]
                        break
                    except TimeoutError:
                        continue
                consume_socket(sock, quit_event=quit_event)
                if quit_event.is_set():
                    sock.close()
                    return
                if i == 0:
                    headers = [
                        b"HTTP/1.1 302 Found",
                        f"Location: http://{self.host}:{port}/redirected".encode(
                            "ascii"
                        ),
                    ]
                    if retry_after is not None:
                        headers.append(f"Retry-After: {retry_after}".encode("ascii"))
                    headers += [b"Content-Length: 0", b"Connection: close", b""]
                    sock.sendall(b"\r\n".join(headers) + b"\r\n")
                else:
                    sock.sendall(
                        b"HTTP/1.1 200 OK\r\n"
                        b"Content-Length: 0\r\n"
                        b"Connection: close\r\n\r\n"
                    )
                sock.close()

        self._start_server(socket_handler, quit_event=quit_event)

    @pytest.mark.parametrize("retry_after,expected", [("3600", 60), ("7", 7)])
    def test_redirect_sleeps_for_retry_after(
        self, retry_after: str, expected: float
    ) -> None:
        self._serve_redirect(retry_after)

        retries = Retry(total=2, retry_after_max=60)
        with mock.patch("time.sleep") as sleep_mock:
            with PoolManager() as pool:
                response = pool.urlopen(
                    "GET", self.base_url, retries=retries, timeout=5.0
                )

        assert response.status == 200
        assert sleep_mock.mock_calls == [mock.call(expected)]

    def test_redirect_raises_on_retry_after_max(self) -> None:
        self._serve_redirect("3600")

        retries = Retry(total=2, retry_after_max=60, raise_on_retry_after_max=True)
        with (
            mock.patch("time.sleep") as sleep_mock,
            pytest.raises(RetryAfterMaxExceededError) as exc_info,
        ):
            with PoolManager() as pool:
                pool.urlopen("GET", self.base_url, retries=retries, timeout=5.0)

        assert exc_info.value.retry_after == 3600
        assert exc_info.value.max_wait == 60
        sleep_mock.assert_not_called()

    def test_redirect_without_retry_after_does_not_sleep(self) -> None:
        self._serve_redirect(None)

        retries = Retry(total=2, retry_after_max=60, raise_on_retry_after_max=True)
        with mock.patch("time.sleep") as sleep_mock:
            with PoolManager() as pool:
                response = pool.urlopen(
                    "GET", self.base_url, retries=retries, timeout=5.0
                )

        assert response.status == 200
        sleep_mock.assert_not_called()

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/start"
