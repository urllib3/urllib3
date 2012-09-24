from urllib3 import HTTPConnectionPool
from urllib3.poolmanager import proxy_from_url
from urllib3.exceptions import MaxRetryError

from dummyserver.testcase import SocketDummyServerTestCase

from threading import Event


class TestCookies(SocketDummyServerTestCase):

    def test_multi_setcookie(self):
        def multicookie_response_handler(listener):
            sock = listener.accept()[0]

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            sock.send(b'HTTP/1.1 200 OK\r\n'
                      b'Set-Cookie: foo=1\r\n'
                      b'Set-Cookie: bar=1\r\n'
                      b'\r\n')

        self._start_server(multicookie_response_handler)
        pool = HTTPConnectionPool(self.host, self.port)
        r = pool.request('GET', '/', retries=0)
        self.assertEquals(r.headers, {'set-cookie': 'foo=1, bar=1'})


class TestSocketClosing(SocketDummyServerTestCase):

    def test_recovery_when_server_closes_connection(self):
        # Does the pool work seamlessly if an open connection in the
        # connection pool gets hung up on by the server, then reaches
        # the front of the queue again?

        done_closing = Event()

        def socket_handler(listener):
            for i in 0, 1:
                sock = listener.accept()[0]

                buf = b''
                while not buf.endswith(b'\r\n\r\n'):
                    buf = sock.recv(65536)

                body = 'Response %d' % i
                sock.send(('HTTP/1.1 200 OK\r\n'
                          'Content-Type: text/plain\r\n'
                          'Content-Length: %d\r\n'
                          '\r\n'
                          '%s' % (len(body), body)).encode('utf-8'))

                sock.close()  # simulate a server timing out, closing socket
                done_closing.set()  # let the test know it can proceed

        self._start_server(socket_handler)
        pool = HTTPConnectionPool(self.host, self.port)

        response = pool.request('GET', '/', retries=0)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, b'Response 0')

        done_closing.wait()  # wait until the socket in our pool gets closed

        response = pool.request('GET', '/', retries=0)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, b'Response 1')

        done_closing.wait()  # wait until the socket in our pool gets closed

    def test_retry_when_server_closes_connection_with_no_data(self):
        # Test that the retry mechanism works when the server drops the connection
        # prematurely

        done_closing = Event()

        def socket_handler(listener):
            for i in 0, 1, 2:
                sock = listener.accept()[0]

                # only interact with client the second time
                if i == 1:
                    buf = b''
                    while not buf.endswith(b'\r\n\r\n'):
                        buf = sock.recv(65536)

                    body = 'Response %d' % i
                    sock.send(('HTTP/1.1 200 OK\r\n'
                              'Content-Type: text/plain\r\n'
                              'Content-Length: %d\r\n'
                              '\r\n'
                              '%s' % (len(body), body)).encode('utf-8'))

                sock.close()  # simulate a server timing out, closing socket
                done_closing.set()  # let the test know it can proceed

        self._start_server(socket_handler)
        pool = HTTPConnectionPool(self.host, self.port)

        # Should succeed in the second retry
        response = pool.request('GET', '/', retries=1)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, b'Response 1')

        done_closing.wait()  # wait until the socket in our pool gets closed

        # Fail with no retries
        with self.assertRaises(MaxRetryError):
            response = pool.request('GET', '/', retries=0)

        done_closing.wait()  # wait until the socket in our pool gets closed




class TestProxyManager(SocketDummyServerTestCase):

    def test_simple(self):
        base_url = 'http://%s:%d' % (self.host, self.port)
        proxy = proxy_from_url(base_url)

        def echo_socket_handler(listener):
            sock = listener.accept()[0]

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            sock.send(('HTTP/1.1 200 OK\r\n'
                      'Content-Type: text/plain\r\n'
                      'Content-Length: %d\r\n'
                      '\r\n'
                      '%s' % (len(buf), buf.decode('utf-8'))).encode('utf-8'))

        self._start_server(echo_socket_handler)

        r = proxy.request('GET', 'http://google.com/')

        self.assertEqual(r.status, 200)
        self.assertEqual(r.data, b'GET http://google.com/ HTTP/1.1\r\n'
                                 b'Host: google.com\r\n'
                                 b'Accept-Encoding: identity\r\n'
                                 b'Accept: */*\r\n'
                                 b'\r\n')
