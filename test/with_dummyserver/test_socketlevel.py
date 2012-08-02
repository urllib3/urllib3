from urllib3 import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.poolmanager import proxy_from_url
from urllib3.exceptions import SSLError

from dummyserver.testcase import SocketDummyServerTestCase

from threading import Event

try:
    from ssl import HAS_SNI
except ImportError: # openssl without SNI
    HAS_SNI = False


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

if HAS_SNI:
    class TestSNI(SocketDummyServerTestCase):

        def test_hostname_in_first_request_packet(self):
            done_receiving = Event()
            self.buf = b''

            def socket_handler(listener):
                sock = listener.accept()[0]

                self.buf = sock.recv(65536) # We only accept one packet
                done_receiving.set()  # let the test know it can proceed

            self._start_server(socket_handler)
            pool = HTTPSConnectionPool(self.host, self.port)
            try:
                pool.request('GET', '/', retries=0)
            except SSLError: # We are violating the protocol
                pass
            done_receiving.wait()
            self.assertTrue(self.buf.find(self.host.encode()) != -1,
                            "missing hostname in SSL handshake")

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
