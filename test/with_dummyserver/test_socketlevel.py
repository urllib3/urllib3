
from urllib3 import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.poolmanager import proxy_from_url
from urllib3.exceptions import (
        ConnectionError,
        MaxRetryError,
        ProxyError,
        ReadTimeoutError,
        SSLError,
)
from urllib3 import util

from dummyserver.testcase import SocketDummyServerTestCase
from dummyserver.server import (
    DEFAULT_CERTS, DEFAULT_CA, get_unreachable_address)

from nose.plugins.skip import SkipTest
from threading import Event
import socket
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
        self.assertEqual(r.headers, {'set-cookie': 'foo=1, bar=1'})


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
        host, port = get_unreachable_address()
        pool = HTTPConnectionPool(host, port)
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
            sock_timeout = listener.accept()[0]

            # Wait for a second request before closing the first socket.
            sock = listener.accept()[0]
            sock_timeout.close()

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

        # In situations where the main thread throws an exception, the server
        # thread can hang on an accept() call. This ensures everything times
        # out within 3 seconds. This should be long enough for any socket
        # operations in the test suite to complete
        default_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(1)

        try:
            self._start_server(socket_handler)
            t = util.Timeout(connect=0.001, read=0.001)
            pool = HTTPConnectionPool(self.host, self.port, timeout=t)

            response = pool.request('GET', '/', retries=1)
            self.assertEqual(response.status, 200)
            self.assertEqual(response.data, b'Response 2')
        finally:
            socket.setdefaulttimeout(default_timeout)

    def test_delayed_body_read_timeout(self):
        timed_out = Event()

        def socket_handler(listener):
            sock = listener.accept()[0]
            buf = b''
            body = 'Hi'
            while not buf.endswith(b'\r\n\r\n'):
                buf = sock.recv(65536)
            sock.send(('HTTP/1.1 200 OK\r\n'
                       'Content-Type: text/plain\r\n'
                       'Content-Length: %d\r\n'
                       '\r\n' % len(body)).encode('utf-8'))

            timed_out.wait(timeout=0.05)
            sock.send(body.encode('utf-8'))
            sock.close()

        self._start_server(socket_handler)
        pool = HTTPConnectionPool(self.host, self.port)

        response = pool.urlopen('GET', '/', retries=0, preload_content=False,
                                timeout=util.Timeout(connect=1, read=0.001))
        self.assertRaises(ReadTimeoutError, response.read)
        timed_out.set()

    def test_incomplete_response(self):
        body = 'Response'
        partial_body = body[:2]

        def socket_handler(listener):
            sock = listener.accept()[0]

            # Consume request
            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf = sock.recv(65536)

            # Send partial response and close socket.
            sock.send((
                'HTTP/1.1 200 OK\r\n'
                'Content-Type: text/plain\r\n'
                'Content-Length: %d\r\n'
                '\r\n'
                '%s' % (len(body), partial_body)).encode('utf-8')
            )
            sock.close()

        self._start_server(socket_handler)
        pool = HTTPConnectionPool(self.host, self.port)

        response = pool.request('GET', '/', retries=0, preload_content=False)
        self.assertRaises(ConnectionError, response.read)


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

    def test_headers(self):
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

        # Define some proxy headers.
        proxy_headers = {'For The Proxy': 'YEAH!'}
        proxy = proxy_from_url(base_url, proxy_headers=proxy_headers)

        conn = proxy.connection_from_url('http://www.google.com/')

        r = conn.urlopen('GET', 'http://www.google.com/', assert_same_host=False)

        self.assertEqual(r.status, 200)
        # FIXME: The order of the headers is not predictable right now. We
        # should fix that someday (maybe when we migrate to
        # OrderedDict/MultiDict).
        self.assertTrue(b'For The Proxy: YEAH!\r\n' in r.data)

    def test_retries(self):
        def echo_socket_handler(listener):
            sock = listener.accept()[0]
            # First request, which should fail
            sock.close()

            # Second request
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
        conn = proxy.connection_from_url('http://www.google.com')

        r = conn.urlopen('GET', 'http://www.google.com',
                         assert_same_host=False, retries=1)
        self.assertEqual(r.status, 200)

        self.assertRaises(ProxyError, conn.urlopen, 'GET',
                'http://www.google.com',
                assert_same_host=False, retries=0)

    def test_connect_reconn(self):
        def proxy_ssl_one(listener):
            sock = listener.accept()[0]

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)
            s = buf.decode('utf-8')
            if not s.startswith('CONNECT '):
                sock.send(('HTTP/1.1 405 Method not allowed\r\n'
                           'Allow: CONNECT\r\n\r\n').encode('utf-8'))
                sock.close()
                return

            if not s.startswith('CONNECT %s:443' % (self.host,)):
                sock.send(('HTTP/1.1 403 Forbidden\r\n\r\n').encode('utf-8'))
                sock.close()
                return

            sock.send(('HTTP/1.1 200 Connection Established\r\n\r\n').encode('utf-8'))
            ssl_sock = ssl.wrap_socket(sock,
                                       server_side=True,
                                       keyfile=DEFAULT_CERTS['keyfile'],
                                       certfile=DEFAULT_CERTS['certfile'],
                                       ca_certs=DEFAULT_CA)

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += ssl_sock.recv(65536)

            ssl_sock.send(('HTTP/1.1 200 OK\r\n'
                           'Content-Type: text/plain\r\n'
                           'Content-Length: 2\r\n'
                           'Connection: close\r\n'
                           '\r\n'
                           'Hi').encode('utf-8'))
            ssl_sock.close()
        def echo_socket_handler(listener):
            proxy_ssl_one(listener)
            proxy_ssl_one(listener)

        self._start_server(echo_socket_handler)
        base_url = 'http://%s:%d' % (self.host, self.port)

        proxy = proxy_from_url(base_url)

        url = 'https://{0}'.format(self.host)
        conn = proxy.connection_from_url(url)
        r = conn.urlopen('GET', url, retries=0)
        self.assertEqual(r.status, 200)
        r = conn.urlopen('GET', url, retries=0)
        self.assertEqual(r.status, 200)


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
