from __future__ import annotations

import socket

import pytest

from dummyserver.testcase import SocketDummyServerTestCase
from urllib3 import HTTPConnectionPool
from urllib3.exceptions import InvalidHeader

"""
Part of the space in header problem is caused by httplib, not urllib3. So these problems will be
difficult to fix.

I will only fix some of the problems that can be fixed in urllib3 only. Including:
1. Space after header value, I will remove that space.
2. Space before header name, I will raise error. But sometimes, this will be ignored by httplib,
in this case cannot raise error.

"""


class TestHeaderSpace(SocketDummyServerTestCase):
    def start_header_test_server(self, header_content: str, header_loc: str) -> None:
        """
        Start a server that sends a Retry-After header with the specified value.
        """

        def socket_handler(listener: socket.socket) -> None:
            sock = listener.accept()[0]
            sock.send(
                (
                    "HTTP/1.1 200 OK\r\n"
                    + (header_content if header_loc == "start" else "")
                    + "Content-Length: 0\r\n"
                    + (header_content if header_loc == "middle" else "")
                    + "Connection: close\r\n"
                    + (header_content if header_loc == "end" else "")
                    + "\r\n"
                ).encode()
            )
            sock.close()

        self._start_server(socket_handler)

    def get_response_headers(self, pool: HTTPConnectionPool):
        headers = None
        try:
            response = pool.request("GET", "/")
            headers = response.headers
        except Exception:
            headers = "ERROR"
        return headers

    def test_normal_header(self) -> None:
        # Test a normal (legal) header, should accept. Completely work now.
        for header_loc in ["start", "middle", "end"]:
            self.start_header_test_server("Qwe-Asd: qweasd\r\n", header_loc)
            pool = HTTPConnectionPool(self.host, self.port)
            response = pool.request("GET", "/")
            assert response.headers["Qwe-Asd"] == "qweasd"
            assert response.headers["Connection"] == "close"
            assert response.headers["Content-Length"] == "0"

    # def test_space_in_header_name(self) -> None:
    #     # Test space in header name, should raise error. Not work, need to fix.  Current behavior:
    #     # start: ERROR
    #     # middle: HTTPHeaderDict({'Content-Length': '0'})
    #     # end: HTTPHeaderDict({'Content-Length': '0', 'Connection': 'close'})
    #     # Will not fix this, this is caused by httplib, not urllib3.
    #     for header_loc in ["start", "middle", "end"]:
    #         self.start_header_test_server("Qwe -Asd: qweasd\r\n", header_loc)
    #         pool = HTTPConnectionPool(self.host, self.port)
    #         print(self.get_response_headers(pool))

    def test_space_before_header(self) -> None:
        """
        Test space before header name, should raise error. Not work, need to fix. Current behavior:
        start: HTTPHeaderDict({'Content-Length': '0', 'Connection': 'close'})
        middle: ERROR
        end: HTTPHeaderDict({'Content-Length': '0', 'Connection': 'close\r\n Qwe-Asd: qweasd'})
        Can only fix this partly (chack whether \r\n in header, if is, raise error). But still some
        situation will return success. But this is caused by httplib, not urllib3, so not fix it.
        """
        # Here: if the header with white space at front is the first one, httplib will remove this
        # header, so it will not raise an error.
        for header_loc in ["middle", "end"]:
            self.start_header_test_server(" Qwe-Asd: qweasd\r\n", header_loc)
            pool = HTTPConnectionPool(self.host, self.port)
            with pytest.raises(InvalidHeader):
                pool.request("GET", "/")

    # def test_space_before_colon(self) -> None:
    #     # Test space before colon, should raise error. But if the header is in middle or end,
    #     # it will not raise error. Need to fix this.  Current behavior:
    #     # start: ERROR
    #     # middle: HTTPHeaderDict({'Content-Length': '0'})
    #     # end: HTTPHeaderDict({'Content-Length': '0', 'Connection': 'close'})
    #     # Will not fix this, this is caused by httplib, not urllib3.
    #     for header_loc in ["start", "middle", "end"]:
    #         self.start_header_test_server("Qwe-Asd : qweasd\r\n", header_loc)
    #         pool = HTTPConnectionPool(self.host, self.port)
    #         print(self.get_response_headers(pool))

    def test_2_spaces_after_colon(self) -> None:
        # Test 2 spaces after colon, should accept. Completely work now.
        for header_loc in ["start", "middle", "end"]:
            self.start_header_test_server("Qwe-Asd:  qweasd\r\n", header_loc)
            pool = HTTPConnectionPool(self.host, self.port)
            response = pool.request("GET", "/")
            assert response.headers["Qwe-Asd"] == "qweasd"
            assert response.headers["Connection"] == "close"
            assert response.headers["Content-Length"] == "0"

    def test_space_in_header_value(self) -> None:
        # Test space in header value, should accept. Completely work now.
        for header_loc in ["start", "middle", "end"]:
            self.start_header_test_server("Qwe-Asd: qwe asd\r\n", header_loc)
            pool = HTTPConnectionPool(self.host, self.port)
            response = pool.request("GET", "/")
            assert response.headers["Qwe-Asd"] == "qwe asd"
            assert response.headers["Connection"] == "close"
            assert response.headers["Content-Length"] == "0"

    def test_space_after_header_value(self) -> None:
        # Test space in header value, should ignore the latter space. But previously it will include
        # the space in the value. Need to fix this.
        for header_loc in ["start", "middle", "end"]:
            self.start_header_test_server("Qwe-Asd: qweasd \r\n", header_loc)
            pool = HTTPConnectionPool(self.host, self.port)
            response = pool.request("GET", "/")
            assert response.headers["Qwe-Asd"] == "qweasd"
            assert response.headers["Connection"] == "close"
            assert response.headers["Content-Length"] == "0"


if __name__ == "__main__":
    pytest.main()
