from urllib3 import HTTPConnectionPool
from urllib3.poolmanager import ProxyManager, proxy_from_url

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
                                 b'Proxy-Connection: Keep-Alive\r\n'
                                 b'Accept: */*\r\n'
                                 b'\r\n')
