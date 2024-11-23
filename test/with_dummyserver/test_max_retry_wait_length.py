from __future__ import annotations

import socket
import time

import pytest

from dummyserver.testcase import SocketDummyServerTestCase
from urllib3 import HTTPConnectionPool
from urllib3.util.retry import Retry


class TestMaxRetryWaitLength(SocketDummyServerTestCase):
    def start_retry_after_handler(self, retry_after_value: str) -> None:
        """
        Start a server that sends a Retry-After header with the specified value.
        """

        def socket_handler(listener: socket.socket) -> None:
            sock = listener.accept()[0]
            sock.send(
                f"HTTP/1.1 429 Too Many Requests\r\n"
                f"Retry-After: {retry_after_value}\r\n"
                f"Content-Length: 0\r\n"
                f"Connection: close\r\n\r\n".encode()
            )
            sock.close()

        self._start_server(socket_handler)

    def test_max_retry_wait_length_respected(self) -> None:
        """
        Test that max_retry_wait_length is respected when the Retry-After value is larger.
        """
        # Start a dummy server that returns a Retry-After of 100 seconds
        self.start_retry_after_handler("100")

        with HTTPConnectionPool(self.host, self.port) as pool:
            retries = Retry(total=1, max_retry_wait_length=2)
            print(retries.max_retry_wait_length)

            start_time = time.time()
            with pytest.raises(Exception):  # Catch the retry failure
                pool.urlopen("GET", "/", retries=retries)
            elapsed_time = time.time() - start_time

            # Ensure that we waited no longer than the specified max_retry_wait_length
            assert (
                elapsed_time < 20  # github actions may be very slow
            ), f"Elapsed time {elapsed_time} exceeded the max retry wait length"

    def test_no_max_retry_wait_length(self) -> None:
        """
        Test behavior when max_retry_wait_length is not specified (default behavior).
        """
        # Start a dummy server that returns a Retry-After of 5 seconds
        self.start_retry_after_handler("5")

        with HTTPConnectionPool(self.host, self.port) as pool:
            retries = Retry(total=1)

            start_time = time.time()
            with pytest.raises(Exception):  # Catch the retry failure
                pool.urlopen("GET", "/", retries=retries)
            elapsed_time = time.time() - start_time

            # Ensure that we waited for at least the Retry-After value
            assert (
                elapsed_time >= 5
            ), f"Elapsed time {elapsed_time} was less than expected Retry-After"

    def test_invalid_retry_after_header(self) -> None:
        """
        Test behavior when an invalid Retry-After header is received.
        """
        # Start a dummy server with an invalid Retry-After header
        self.start_retry_after_handler("invalid")

        with HTTPConnectionPool(self.host, self.port) as pool:
            retries = Retry(total=1, max_retry_wait_length=2)

            start_time = time.time()
            with pytest.raises(Exception):  # Catch the retry failure
                pool.urlopen("GET", "/", retries=retries)
            elapsed_time = time.time() - start_time

            # Ensure that no additional wait time occurred due to invalid Retry-After
            assert (
                elapsed_time < 1
            ), f"Elapsed time {elapsed_time} exceeded the expected behavior for invalid Retry-After"


if __name__ == "__main__":
    pytest.main()
