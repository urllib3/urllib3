from urllib3 import HTTPConnectionPool
from dummyserver.testcase import SocketDummyServerTestCase
import pytest
import socket


class TestHeaderSpace(SocketDummyServerTestCase):
    def start_header_test_server(self, header_content: str, header_loc: str) -> None:
        """
        Start a server that sends a Retry-After header with the specified value.
        """

        def socket_handler(listener: socket.socket) -> None:
            sock = listener.accept()[0]
            sock.send(
                (f"HTTP/1.1 200 OK\r\n" +
                 (header_content if header_loc == "start" else "") +
                 f"Content-Length: 0\r\n" +
                 (header_content if header_loc == "middle" else "") +
                 f"Connection: close\r\n" +
                 (header_content if header_loc == "end" else "") +
                 "\r\n"
                 ).encode()
            )
            sock.close()

        self._start_server(socket_handler)

    def get_response_headers(self, pool: HTTPConnectionPool):
        headers = None
        try:
            response = pool.request('GET', '/')
            headers = response.headers
        except:
            headers = 'ERROR'
        return headers

    def test_normal_header(self) -> None:
        # Test a normal (legal) header, should accept. Completely work now.
        for header_loc in ["start", "middle", "end"]:
            self.start_header_test_server("Qwe-Asd: qweasd\r\n", header_loc)
            pool = HTTPConnectionPool(self.host, self.port)
            print(self.get_response_headers(pool))

    def test_space_in_header_name(self) -> None:
        # Test space in header name, should raise error. Not work, need to fix.  Current behavior:
        # start: ERROR
        # middle: HTTPHeaderDict({'Content-Length': '0'})
        # end: HTTPHeaderDict({'Content-Length': '0', 'Connection': 'close'})
        for header_loc in ["start", "middle", "end"]:
            self.start_header_test_server("Qwe -Asd: qweasd\r\n", header_loc)
            pool = HTTPConnectionPool(self.host, self.port)
            print(self.get_response_headers(pool))

    def test_space_before_header(self) -> None:
        # Test space before header name, should raise error. Not work, need to fix. Current behavior:
        # start: HTTPHeaderDict({'Content-Length': '0', 'Connection': 'close'})
        # middle: ERROR
        # end: HTTPHeaderDict({'Content-Length': '0', 'Connection': 'close\r\n Qwe-Asd: qweasd'})
        for header_loc in ["start", "middle", "end"]:
            self.start_header_test_server(" Qwe-Asd: qweasd\r\n", header_loc)
            pool = HTTPConnectionPool(self.host, self.port)
            print(self.get_response_headers(pool))

    def test_space_before_colon(self) -> None:
        # Test space before colon, should raise error. But if the header is in middle or end,
        # it will not raise error. Need to fix this.  Current behavior:
        # start: ERROR
        # middle: HTTPHeaderDict({'Content-Length': '0'})
        # end: HTTPHeaderDict({'Content-Length': '0', 'Connection': 'close'})
        for header_loc in ["start", "middle", "end"]:
            self.start_header_test_server("Qwe-Asd : qweasd\r\n", header_loc)
            pool = HTTPConnectionPool(self.host, self.port)
            print(self.get_response_headers(pool))

    def test_2_spaces_after_colon(self) -> None:
        # Test 2 spaces after colon, should accept. Completely work now.
        for header_loc in ["start", "middle", "end"]:
            self.start_header_test_server("Qwe-Asd:  qweasd\r\n", header_loc)
            pool = HTTPConnectionPool(self.host, self.port)
            print(self.get_response_headers(pool))

    def test_space_in_header_value(self) -> None:
        # Test space in header value, should accept. Completely work now.
        for header_loc in ["start", "middle", "end"]:
            self.start_header_test_server("Qwe-Asd: qwe asd\r\n", header_loc)
            pool = HTTPConnectionPool(self.host, self.port)
            print(self.get_response_headers(pool))

    def test_space_after_header_value(self) -> None:
        # Test space in header value, should ignore the latter space. But now it will include
        # the space in the value. Need to fix this.
        for header_loc in ["start", "middle", "end"]:
            self.start_header_test_server("Qwe-Asd: qweasd \r\n", header_loc)
            pool = HTTPConnectionPool(self.host, self.port)
            print(self.get_response_headers(pool))


if __name__ == '__main__':
    pytest.main()
