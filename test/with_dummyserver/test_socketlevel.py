
from urllib3 import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.poolmanager import proxy_from_url
from urllib3.exceptions import MaxRetryError, ReadTimeoutError, SSLError
from urllib3 import util

from dummyserver.testcase import SocketDummyServerTestCase
from dummyserver.server import DEFAULT_CERTS, DEFAULT_CA

from nose.plugins.skip import SkipTest
from threading import Event
import socket
import time
import ssl


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
            sock.close()

        self._start_server(multicookie_response_handler)
        pool = HTTPConnectionPool(self.host, self.port)
        r = pool.request('GET', '/', retries=0)
        self.assertEquals(r.headers, {'set-cookie': 'foo=1, bar=1'})


class TestSNI(SocketDummyServerTestCase):

    def test_hostname_in_first_request_packet(self):
        if not util.HAS_SNI:
            raise SkipTest('SNI-support not available')

        done_receiving = Event()
        self.buf = b''

        def socket_handler(listener):
            sock = listener.accept()[0]

            self.buf = sock.recv(65536) # We only accept one packet
            done_receiving.set()  # let the test know it can proceed
            sock.close()

        self._start_server(socket_handler)
        pool = HTTPSConnectionPool(self.host, self.port)
        try:
            pool.request('GET', '/', retries=0)
        except SSLError: # We are violating the protocol
            pass
        done_receiving.wait()
        self.assertTrue(self.host.encode() in self.buf,
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

    def test_connection_refused(self):
        # Does the pool retry if there is no listener on the port?
        # Get a free port on localhost, so a connection will be refused
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        free_port = s.getsockname()[1]
        s.close()

        pool = HTTPConnectionPool(self.host, free_port)
        self.assertRaises(MaxRetryError, pool.request, 'GET', '/', retries=0)

    def test_connection_timeout(self):
        timed_out = Event()
        def socket_handler(listener):
            timed_out.wait()
            sock = listener.accept()[0]
            sock.close()

        self._start_server(socket_handler)
        pool = HTTPConnectionPool(self.host, self.port, timeout=0.001)

        self.assertRaises(ReadTimeoutError, pool.request, 'GET', '/', retries=0)

        timed_out.set()

    def test_timeout_errors_cause_retries(self):

        def socket_handler(listener):
            sock = listener.accept()[0]
            # First request.
            # Pause before responding so the first request times out.
            time.sleep(0.002)
            sock.close()

            sock = listener.accept()[0]

            # Second request.
            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            # Now respond immediately.
            body = 'Response 2'
            sock.send(('HTTP/1.1 200 OK\r\n'
                      'Content-Type: text/plain\r\n'
                      'Content-Length: %d\r\n'
                      '\r\n'
                      '%s' % (len(body), body)).encode('utf-8'))

            sock.close()  # Close the socket.

        self._start_server(socket_handler)
        t = util.Timeout(connect=0.001, read=0.001)
        pool = HTTPConnectionPool(self.host, self.port, timeout=t)

        response = pool.request('GET', '/', retries=1)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, b'Response 2')


class TestProxyManager(SocketDummyServerTestCase):

    def test_simple(self):
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
            sock.close()

        self._start_server(echo_socket_handler)
        base_url = 'http://%s:%d' % (self.host, self.port)
        proxy = proxy_from_url(base_url)

        r = proxy.request('GET', 'http://google.com/')

        self.assertEqual(r.status, 200)
        # FIXME: The order of the headers is not predictable right now. We
        # should fix that someday (maybe when we migrate to
        # OrderedDict/MultiDict).
        self.assertEqual(sorted(r.data.split(b'\r\n')),
                         sorted([
                             b'GET http://google.com/ HTTP/1.1',
                             b'Host: google.com',
                             b'Accept-Encoding: identity',
                             b'Accept: */*',
                             b'',
                             b'',
                         ]))


class TestSSL(SocketDummyServerTestCase):

    def test_ssl_failure_midway_through_conn(self):
        def socket_handler(listener):
            sock = listener.accept()[0]
            sock2 = sock.dup()
            ssl_sock = ssl.wrap_socket(sock,
                                       server_side=True,
                                       keyfile=DEFAULT_CERTS['keyfile'],
                                       certfile=DEFAULT_CERTS['certfile'],
                                       ca_certs=DEFAULT_CA)

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += ssl_sock.recv(65536)

            # Deliberately send from the non-SSL socket.
            sock2.send(('HTTP/1.1 200 OK\r\n'
                       'Content-Type: text/plain\r\n'
                       'Content-Length: 2\r\n'
                       '\r\n'
                       'Hi').encode('utf-8'))
            sock2.close()
            ssl_sock.close()

        self._start_server(socket_handler)
        pool = HTTPSConnectionPool(self.host, self.port)

        self.assertRaises(SSLError, pool.request, 'GET', '/', retries=0)
