from urllib3 import HTTPConnectionPool

from dummyserver.testcase import SocketDummyServerTestCase

class TestHeaderFail(SocketDummyServerTestCase):

    def test_header_name_trailing_space(self):
        def multiline_response_handler(listener):
            sock = listener.accept()[0]

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            sock.send( b'HTTP/1.1 200 OK\r\n'
                       b'Bad_Header : Hello\r\n'
                       b'Good_Header: Wont make it\r\n' 
                       b'\r\n')
            sock.close()

        self._start_server(multiline_response_handler)
        pool = HTTPConnectionPool(self.host, self.port)
        r = pool.request('GET', '/', retries=False)

        assert r.headers == {}
