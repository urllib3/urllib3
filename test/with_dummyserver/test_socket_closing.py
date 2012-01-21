from urllib3 import HTTPConnectionPool, PoolManager
from urllib3.connectionpool import port_by_scheme

from dummyserver.testcase import SocketDummyServerTestCase

from threading import Event


class TestSocketClosing(SocketDummyServerTestCase):

    def test_recovery_when_server_closes_connection(self):
        # Does the pool work seamlessly if an open connection in the
        # connection pool gets hung up on by the server, then reaches
        # the front of the queue again?

        done_closing = Event()

        def socket_handler(listener):
            for i in 0, 1:
                sock = listener.accept()[0]

                buf = ''
                while not buf.endswith('\r\n\r\n'):
                    buf = sock.recv(65536)

                body = 'Response %d' % i
                sock.send('HTTP/1.1 200 OK\r\n'
                          'Content-Type: text/plain\r\n'
                          'Content-Length: %d\r\n'
                          '\r\n'
                          '%s' % (len(body), body))

                sock.close()  # simulate a server timing out, closing socket
                done_closing.set()  # let the test know it can proceed

        self._start_server(socket_handler)
        pool = HTTPConnectionPool(self.host, self.port)

        response = pool.request('GET', '/', retries=0)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, 'Response 0')

        done_closing.wait()  # wait until the socket in our pool gets closed

        response = pool.request('GET', '/', retries=0)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, 'Response 1')


    def test_request_survives_missing_port_number(self):
        # Can a URL that lacks an explicit port like ':80' succeed, or
        # will all such URLs fail with an error?

        def socket_server(listener):
            sock = listener.accept()[0]

            buf = ''
            while not buf.endswith('\r\n\r\n'):
                buf = sock.recv(65536)

            sock.send('HTTP/1.1 200 OK\r\n'
                      'Content-Type: text/plain\r\n'
                      'Content-Length: 8\r\n'
                      '\r\n'
                      'Inspire.')
            sock.close()

        # By globally adjusting `port_by_scheme` we pretend for a moment
        # that HTTP's default port is not 80, but is the port at which
        # our test server happens to be listening.

        p = PoolManager()
        self._start_server(socket_server)
        port_by_scheme['http'] = self.port
        try:
            response = p.request('GET', 'http://%s/' % self.host, retries=0)
        finally:
            port_by_scheme['http'] = 80
        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, 'Inspire.')
