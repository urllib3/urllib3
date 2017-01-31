# TODO: Break this module up into pieces. Maybe group by functionality tested
# rather than the socket level-ness of it.

from urllib3 import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.poolmanager import proxy_from_url
from urllib3.exceptions import (
        MaxRetryError,
        ProxyError,
        ReadTimeoutError,
        SSLError,
        ProtocolError,
        BadVersionError
)
from urllib3.util.ssl_ import HAS_SNI
from urllib3.util.timeout import Timeout
from urllib3.util.retry import Retry
from urllib3._collections import HTTPHeaderDict, OrderedDict

from dummyserver.testcase import SocketDummyServerTestCase, consume_socket
from dummyserver.server import (
    DEFAULT_CERTS, DEFAULT_CA, get_unreachable_address)

from .. import onlyPy3, LogRecorder

from nose.plugins.skip import SkipTest
try:
    from mimetools import Message as MimeToolMessage
except ImportError:
    class MimeToolMessage(object):
        pass
from threading import Event
import io
import select
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
        self.addCleanup(pool.close)
        r = pool.request('GET', '/', retries=0)
        self.assertEqual(r.headers, {'set-cookie': 'foo=1, bar=1'})
        self.assertEqual(r.headers.getlist('set-cookie'), ['foo=1', 'bar=1'])


class TestSNI(SocketDummyServerTestCase):

    def test_hostname_in_first_request_packet(self):
        if not HAS_SNI:
            raise SkipTest('SNI-support not available')

        done_receiving = Event()
        self.buf = b''

        def socket_handler(listener):
            sock = listener.accept()[0]

            self.buf = sock.recv(65536)  # We only accept one packet
            done_receiving.set()  # let the test know it can proceed
            sock.close()

        self._start_server(socket_handler)
        pool = HTTPSConnectionPool(self.host, self.port)
        self.addCleanup(pool.close)
        try:
            pool.request('GET', '/', retries=0)
        except SSLError:  # We are violating the protocol
            pass
        done_receiving.wait()
        self.assertTrue(self.host.encode('ascii') in self.buf,
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
        self.addCleanup(pool.close)

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
        http = HTTPConnectionPool(host, port, maxsize=3, block=True)
        self.addCleanup(http.close)
        self.assertRaises(MaxRetryError, http.request, 'GET', '/', retries=0, release_conn=False)
        self.assertEqual(http.pool.qsize(), http.pool.maxsize)

    def test_connection_read_timeout(self):
        timed_out = Event()

        def socket_handler(listener):
            sock = listener.accept()[0]
            while not sock.recv(65536).endswith(b'\r\n\r\n'):
                pass

            timed_out.wait()
            sock.close()

        self._start_server(socket_handler)
        http = HTTPConnectionPool(self.host, self.port,
                                  timeout=0.001,
                                  retries=False,
                                  maxsize=3,
                                  block=True)
        self.addCleanup(http.close)

        try:
            self.assertRaises(ReadTimeoutError, http.request, 'GET', '/', release_conn=False)
        finally:
            timed_out.set()

        self.assertEqual(http.pool.qsize(), http.pool.maxsize)

    def test_read_timeout_dont_retry_method_not_in_whitelist(self):
        timed_out = Event()

        def socket_handler(listener):
            sock = listener.accept()[0]
            sock.recv(65536)
            timed_out.wait()
            sock.close()

        self._start_server(socket_handler)
        pool = HTTPConnectionPool(self.host, self.port, timeout=0.001, retries=True)
        self.addCleanup(pool.close)

        try:
            self.assertRaises(ReadTimeoutError, pool.request, 'POST', '/')
        finally:
            timed_out.set()

    def test_https_connection_read_timeout(self):
        """ Handshake timeouts should fail with a Timeout"""
        timed_out = Event()

        def socket_handler(listener):
            sock = listener.accept()[0]
            while not sock.recv(65536):
                pass

            timed_out.wait()
            sock.close()

        self._start_server(socket_handler)
        pool = HTTPSConnectionPool(self.host, self.port, timeout=0.001, retries=False)
        self.addCleanup(pool.close)
        try:
            self.assertRaises(ReadTimeoutError, pool.request, 'GET', '/')
        finally:
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

            sock.close()

        # In situations where the main thread throws an exception, the server
        # thread can hang on an accept() call. This ensures everything times
        # out within 1 second. This should be long enough for any socket
        # operations in the test suite to complete
        default_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(1)

        try:
            self._start_server(socket_handler)
            t = Timeout(connect=0.001, read=0.001)
            pool = HTTPConnectionPool(self.host, self.port, timeout=t)
            self.addCleanup(pool.close)

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

            timed_out.wait()
            sock.send(body.encode('utf-8'))
            sock.close()

        self._start_server(socket_handler)
        pool = HTTPConnectionPool(self.host, self.port)
        self.addCleanup(pool.close)

        response = pool.urlopen('GET', '/', retries=0, preload_content=False,
                                timeout=Timeout(connect=1, read=0.001))
        try:
            self.assertRaises(ReadTimeoutError, response.read)
        finally:
            timed_out.set()

    def test_delayed_body_read_timeout_with_preload(self):
        timed_out = Event()

        def socket_handler(listener):
            sock = listener.accept()[0]
            buf = b''
            body = 'Hi'
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)
            sock.send(('HTTP/1.1 200 OK\r\n'
                       'Content-Type: text/plain\r\n'
                       'Content-Length: %d\r\n'
                       '\r\n' % len(body)).encode('utf-8'))

            timed_out.wait(5)
            sock.close()

        self._start_server(socket_handler)
        pool = HTTPConnectionPool(self.host, self.port)
        self.addCleanup(pool.close)

        try:
            self.assertRaises(ReadTimeoutError, pool.urlopen,
                              'GET', '/', retries=False,
                              timeout=Timeout(connect=1, read=0.001))
        finally:
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
        self.addCleanup(pool.close)

        response = pool.request('GET', '/', retries=0, preload_content=False)
        self.assertRaises(ProtocolError, response.read)

    def test_retry_weird_http_version(self):
        """ Retry class should handle httplib.BadStatusLine errors properly """

        def socket_handler(listener):
            sock = listener.accept()[0]
            # First request.
            # Pause before responding so the first request times out.
            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            # send bad response
            body = "bad http response"
            sock.send(('HTTP0.5 200 OK\r\n'
                      'Content-Type: text/plain\r\n'
                      'Content-Length: %d\r\n'
                      '\r\n'
                      '%s' % (len(body), body)).encode('utf-8'))
            sock.close()

            # Second request.
            sock = listener.accept()[0]
            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            # Now respond immediately.
            sock.send(('HTTP/1.1 200 OK\r\n'
                       'Content-Type: text/plain\r\n'
                       'Content-Length: %d\r\n'
                       '\r\n'
                       'foo' % (len('foo'))).encode('utf-8'))

            sock.close()  # Close the socket.

        self._start_server(socket_handler)
        pool = HTTPConnectionPool(self.host, self.port)
        self.addCleanup(pool.close)
        retry = Retry(read=1)
        response = pool.request('GET', '/', retries=retry)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, b'foo')

    def test_dont_tolerate_bad_versions(self):
        """We don't tolerate weird versions of HTTP"""

        def socket_handler(listener):
            sock = listener.accept()[0]
            # First request.
            # Pause before responding so the first request times out.
            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            # send bad response
            body = "bad http response"
            sock.send(('HTTP/1.2 200 OK\r\n'
                      'Content-Type: text/plain\r\n'
                      'Content-Length: %d\r\n'
                      '\r\n'
                      '%s' % (len(body), body)).encode('utf-8'))
            sock.close()

        self._start_server(socket_handler)
        pool = HTTPConnectionPool(self.host, self.port)
        self.addCleanup(pool.close)

        with self.assertRaises(MaxRetryError) as cm:
            pool.request('GET', '/', retries=0)

        self.assertIsInstance(cm.exception.reason, BadVersionError)

    def test_connection_cleanup_on_read_timeout(self):
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

            timed_out.wait()
            sock.close()

        self._start_server(socket_handler)
        with HTTPConnectionPool(self.host, self.port) as pool:
            poolsize = pool.pool.qsize()
            response = pool.urlopen('GET', '/', retries=0, preload_content=False,
                                    timeout=Timeout(connect=1, read=0.001))
            try:
                self.assertRaises(ReadTimeoutError, response.read)
                self.assertEqual(poolsize, pool.pool.qsize())
            finally:
                timed_out.set()

    def test_connection_cleanup_on_protocol_error_during_read(self):
        body = 'Response'
        partial_body = body[:2]

        def socket_handler(listener):
            sock = listener.accept()[0]

            # Consume request
            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf = sock.recv(65536)

            # Send partial response and close socket.
            sock.send(('HTTP/1.1 200 OK\r\n'
                       'Content-Type: text/plain\r\n'
                       'Content-Length: %d\r\n'
                       '\r\n'
                       '%s' % (len(body), partial_body)).encode('utf-8'))
            sock.close()

        self._start_server(socket_handler)
        with HTTPConnectionPool(self.host, self.port) as pool:
            poolsize = pool.pool.qsize()
            response = pool.request('GET', '/', retries=0, preload_content=False)

            self.assertRaises(ProtocolError, response.read)
            self.assertEqual(poolsize, pool.pool.qsize())

    def test_connection_closed_on_read_timeout_preload_false(self):
        timed_out = Event()

        def socket_handler(listener):
            sock = listener.accept()[0]

            # Consume request
            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf = sock.recv(65535)

            # Send partial chunked response and then hang.
            sock.send((
                'HTTP/1.1 200 OK\r\n'
                'Content-Type: text/plain\r\n'
                'Transfer-Encoding: chunked\r\n'
                '\r\n'
                '8\r\n'
                '12345678\r\n').encode('utf-8')
            )
            timed_out.wait(5)

            # Expect a new request, but keep hold of the old socket to avoid
            # leaking it. Because we don't want to hang this thread, we
            # actually use select.select to confirm that a new request is
            # coming in: this lets us time the thread out.
            rlist, _, _ = select.select([listener], [], [], 1)
            assert rlist
            new_sock = listener.accept()[0]

            # Consume request
            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf = new_sock.recv(65535)

            # Send complete chunked response.
            new_sock.send((
                'HTTP/1.1 200 OK\r\n'
                'Content-Type: text/plain\r\n'
                'Transfer-Encoding: chunked\r\n'
                '\r\n'
                '8\r\n'
                '12345678\r\n'
                '0\r\n\r\n').encode('utf-8')
            )

            new_sock.close()
            sock.close()

        self._start_server(socket_handler)
        with HTTPConnectionPool(self.host, self.port) as pool:
            # First request should fail.
            response = pool.urlopen('GET', '/', retries=0,
                                    preload_content=False,
                                    timeout=Timeout(connect=1, read=0.001))
            try:
                self.assertRaises(ReadTimeoutError, response.read)
            finally:
                timed_out.set()

            # Second should succeed.
            response = pool.urlopen('GET', '/', retries=0,
                                    preload_content=False,
                                    timeout=Timeout(connect=1, read=0.1))
            self.assertEqual(len(response.read()), 8)

    def test_closing_response_actually_closes_connection(self):
        done_closing = Event()
        complete = Event()
        # The insane use of this variable here is to get around the fact that
        # Python 2.6 does not support returning a value from Event.wait(). This
        # means we can't tell if an event timed out, so we can't use the timing
        # out of the 'complete' event to determine the success or failure of
        # the test. Python 2 also doesn't have the nonlocal statement, so we
        # can't write directly to this variable, only mutate it. Hence: list.
        successful = []

        def socket_handler(listener):
            sock = listener.accept()[0]

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf = sock.recv(65536)

            sock.send(('HTTP/1.1 200 OK\r\n'
                       'Content-Type: text/plain\r\n'
                       'Content-Length: 0\r\n'
                       '\r\n').encode('utf-8'))

            # Wait for the socket to close.
            done_closing.wait(timeout=1)

            # Look for the empty string to show that the connection got closed.
            # Don't get stuck in a timeout.
            sock.settimeout(1)
            new_data = sock.recv(65536)
            self.assertFalse(new_data)
            successful.append(True)
            sock.close()
            complete.set()

        self._start_server(socket_handler)
        pool = HTTPConnectionPool(self.host, self.port)
        self.addCleanup(pool.close)

        response = pool.request('GET', '/', retries=0, preload_content=False)
        self.assertEqual(response.status, 200)
        response.close()

        done_closing.set()  # wait until the socket in our pool gets closed
        complete.wait(timeout=1)
        if not successful:
            self.fail("Timed out waiting for connection close")

    def test_release_conn_param_is_respected_after_timeout_retry(self):
        """For successful ```urlopen(release_conn=False)```,
        the connection isn't released, even after a retry.

        This test allows a retry: one request fails, the next request succeeds.

        This is a regression test for issue #651 [1], where the connection
        would be released if the initial request failed, even if a retry
        succeeded.

        [1] <https://github.com/shazow/urllib3/issues/651>
        """
        def socket_handler(listener):
            sock = listener.accept()[0]
            consume_socket(sock)

            # Close the connection, without sending any response (not even the
            # HTTP status line). This will trigger a `Timeout` on the client,
            # inside `urlopen()`.
            sock.close()

            # Expect a new request. Because we don't want to hang this thread,
            # we actually use select.select to confirm that a new request is
            # coming in: this lets us time the thread out.
            rlist, _, _ = select.select([listener], [], [], 5)
            assert rlist
            sock = listener.accept()[0]
            consume_socket(sock)

            # Send complete chunked response.
            sock.send((
                'HTTP/1.1 200 OK\r\n'
                'Content-Type: text/plain\r\n'
                'Transfer-Encoding: chunked\r\n'
                '\r\n'
                '8\r\n'
                '12345678\r\n'
                '0\r\n\r\n').encode('utf-8')
            )

            sock.close()

        self._start_server(socket_handler)
        with HTTPConnectionPool(self.host, self.port, maxsize=1) as pool:
            # First request should fail, but the timeout and `retries=1` should
            # save it.
            response = pool.urlopen('GET', '/', retries=1,
                                    release_conn=False, preload_content=False,
                                    timeout=Timeout(connect=1, read=0.001))

            # The connection should still be on the response object, and none
            # should be in the pool. We opened two though.
            self.assertEqual(pool.num_connections, 2)
            self.assertEqual(pool.pool.qsize(), 0)
            self.assertTrue(response.connection is not None)

            # Consume the data. This should put the connection back.
            response.read()
            self.assertEqual(pool.pool.qsize(), 1)
            self.assertTrue(response.connection is None)

    def test_early_response(self):
        """
        When the server responds to a request before we've finished sending it,
        we stop our upload immediately.
        """
        client_send_event = Event()

        def socket_handler(listener):
            sock = listener.accept()[0]

            body = b''
            while not body.endswith(b'a\r\nfirst data\r\n'):
                body += sock.recv(65536)

            body = body.split(b'\r\n\r\n', 1)[1]
            body = body.decode('utf-8')

            # send response containing the body we've received
            sock.sendall(('HTTP/1.1 400 CLIENT ERROR\r\n'
                          'Content-Type: text/plain\r\n'
                          'Content-Length: %d\r\n'
                          '\r\n'
                          '%s' % (len(body), body)).encode('utf-8'))

            sock.close()

            # Tell the client it is now allowed to send. We deliberately do
            # this after the close so that the client will encounter a closed
            # pipe error if it screws up.
            client_send_event.set()

        def body_uploader():
            yield b"first data"
            client_send_event.wait(0.5)
            yield b"second data"
            yield b"third data"

        self._start_server(socket_handler)
        pool = HTTPConnectionPool(self.host, self.port)
        self.addCleanup(pool.close)

        response = pool.request("POST", "/", body=body_uploader(), retries=0)

        # Only the first data should have been received by the server.
        self.assertEqual(response.status, 400)
        self.assertEqual(response.data, b"a\r\nfirst data\r\n")


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
        self.addCleanup(proxy.clear)

        r = proxy.request('GET', 'http://google.com/')

        self.assertEqual(r.status, 200)
        # FIXME: The order of the headers is not predictable right now. We
        # should fix that someday (maybe when we migrate to
        # OrderedDict/MultiDict).
        self.assertEqual(sorted(r.data.split(b'\r\n')),
                         sorted([
                             b'GET http://google.com/ HTTP/1.1',
                             b'host: google.com',
                             b'accept: */*',
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
        proxy_headers = HTTPHeaderDict({'For-The-Proxy': 'YEAH!'})
        proxy = proxy_from_url(base_url, proxy_headers=proxy_headers)
        self.addCleanup(proxy.clear)

        conn = proxy.connection_from_url('http://www.google.com/')

        r = conn.urlopen('GET', 'http://www.google.com/', assert_same_host=False)

        self.assertEqual(r.status, 200)
        # FIXME: The order of the headers is not predictable right now. We
        # should fix that someday (maybe when we migrate to
        # OrderedDict/MultiDict).
        self.assertTrue(b'for-the-proxy: YEAH!\r\n' in r.data)

    def test_retries(self):
        close_event = Event()

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
            close_event.set()

        self._start_server(echo_socket_handler)
        base_url = 'http://%s:%d' % (self.host, self.port)

        proxy = proxy_from_url(base_url)
        self.addCleanup(proxy.clear)
        conn = proxy.connection_from_url('http://www.google.com')

        r = conn.urlopen('GET', 'http://www.google.com',
                         assert_same_host=False, retries=1)
        self.assertEqual(r.status, 200)

        close_event.wait(timeout=1)
        self.assertRaises(ProxyError, conn.urlopen, 'GET',
                          'http://www.google.com',
                          assert_same_host=False, retries=False)

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
        self.addCleanup(proxy.clear)

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
            sock2.send((
                'HTTP/1.1 200 OK\r\n'
                'Content-Type: text/plain\r\n'
                'Content-Length: 2\r\n'
                '\r\n'
                'Hi').encode('utf-8'))
            sock2.close()
            ssl_sock.close()

        self._start_server(socket_handler)
        pool = HTTPSConnectionPool(self.host, self.port)
        self.addCleanup(pool.close)

        self.assertRaises(SSLError, pool.request, 'GET', '/', retries=0)

    def test_ssl_read_timeout(self):
        timed_out = Event()

        def socket_handler(listener):
            sock = listener.accept()[0]
            ssl_sock = ssl.wrap_socket(sock,
                                       server_side=True,
                                       keyfile=DEFAULT_CERTS['keyfile'],
                                       certfile=DEFAULT_CERTS['certfile'],
                                       ca_certs=DEFAULT_CA)

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += ssl_sock.recv(65536)

            # Send incomplete message (note Content-Length)
            ssl_sock.send((
                'HTTP/1.1 200 OK\r\n'
                'Content-Type: text/plain\r\n'
                'Content-Length: 10\r\n'
                '\r\n'
                'Hi-').encode('utf-8'))
            timed_out.wait()

            sock.close()
            ssl_sock.close()

        self._start_server(socket_handler)
        pool = HTTPSConnectionPool(self.host, self.port)
        self.addCleanup(pool.close)

        response = pool.urlopen('GET', '/', retries=0, preload_content=False,
                                timeout=Timeout(connect=1, read=0.001))
        try:
            self.assertRaises(ReadTimeoutError, response.read)
        finally:
            timed_out.set()

    def test_ssl_failed_fingerprint_verification(self):
        def socket_handler(listener):
            for i in range(2):
                sock = listener.accept()[0]
                ssl_sock = ssl.wrap_socket(sock,
                                           server_side=True,
                                           keyfile=DEFAULT_CERTS['keyfile'],
                                           certfile=DEFAULT_CERTS['certfile'],
                                           ca_certs=DEFAULT_CA)

                ssl_sock.send(b'HTTP/1.1 200 OK\r\n'
                              b'Content-Type: text/plain\r\n'
                              b'Content-Length: 5\r\n\r\n'
                              b'Hello')

                ssl_sock.close()
                sock.close()

        self._start_server(socket_handler)
        # GitHub's fingerprint. Valid, but not matching.
        fingerprint = ('A0:C4:A7:46:00:ED:A7:2D:C0:BE:CB'
                       ':9A:8C:B6:07:CA:58:EE:74:5E')

        def request():
            pool = HTTPSConnectionPool(self.host, self.port,
                                       assert_fingerprint=fingerprint)
            try:
                response = pool.urlopen('GET', '/', preload_content=False,
                                        timeout=Timeout(connect=1, read=0.001))
                response.read()
            finally:
                pool.close()

        self.assertRaises(SSLError, request)
        # Should not hang, see https://github.com/shazow/urllib3/issues/529
        self.assertRaises(SSLError, request)


class TestErrorWrapping(SocketDummyServerTestCase):

    def test_bad_statusline(self):
        self.start_response_handler(
           b'HTTP/1.1 Omg What Is This?\r\n'
           b'Content-Length: 0\r\n'
           b'\r\n'
        )
        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        self.addCleanup(pool.close)
        self.assertRaises(ProtocolError, pool.request, 'GET', '/')

    def test_unknown_protocol(self):
        self.start_response_handler(
           b'HTTP/1000 200 OK\r\n'
           b'Content-Length: 0\r\n'
           b'\r\n'
        )
        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        self.addCleanup(pool.close)
        self.assertRaises(ProtocolError, pool.request, 'GET', '/')


class TestHeaders(SocketDummyServerTestCase):
    def test_headers_always_lowercase(self):
        self.start_response_handler(
           b'HTTP/1.1 200 OK\r\n'
           b'Content-Length: 0\r\n'
           b'Content-type: text/plain\r\n'
           b'\r\n'
        )
        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        self.addCleanup(pool.close)
        HEADERS = {'content-length': '0', 'content-type': 'text/plain'}
        r = pool.request('GET', '/')
        self.assertEqual(HEADERS, dict(r.headers.items()))  # to preserve case sensitivity

    def test_headers_are_sent_with_lower_case(self):
        headers = {'Foo': 'bar', 'bAz': 'quux'}
        parsed_headers = {}

        def socket_handler(listener):
            sock = listener.accept()[0]

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            headers_list = [header for header in buf.split(b'\r\n')[1:] if header]

            for header in headers_list:
                (key, value) = header.split(b': ')
                parsed_headers[key.decode('ascii')] = value.decode('ascii')

            sock.send((
                'HTTP/1.1 204 No Content\r\n'
                'Content-Length: 0\r\n'
                '\r\n').encode('utf-8'))

            sock.close()

        self._start_server(socket_handler)
        expected_headers = {'host': '{0}:{1}'.format(self.host, self.port)}
        for key, value in headers.items():
            expected_headers[key.lower()] = value

        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        self.addCleanup(pool.close)
        pool.request('GET', '/', headers=HTTPHeaderDict(headers))
        self.assertEqual(expected_headers, parsed_headers)

    def test_request_headers_are_sent_in_the_original_order(self):
        # NOTE: Probability this test gives a false negative is 1/(K!)
        K = 16
        # NOTE: Provide headers in non-sorted order (i.e. reversed)
        #       so that if the internal implementation tries to sort them,
        #       a change will be detected.
        expected_request_headers = [(u'x-header-%d' % i, str(i)) for i in reversed(range(K))]

        actual_request_headers = []

        def socket_handler(listener):
            sock = listener.accept()[0]

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            headers_list = [header for header in buf.split(b'\r\n')[1:] if header]

            for header in headers_list:
                (key, value) = header.split(b': ')
                if not key.decode('ascii').startswith(u'x-header-'):
                    continue
                actual_request_headers.append((key.decode('ascii'), value.decode('ascii')))

            sock.send((
                u'HTTP/1.1 204 No Content\r\n'
                u'Content-Length: 0\r\n'
                u'\r\n').encode('ascii'))

            sock.close()

        self._start_server(socket_handler)

        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        self.addCleanup(pool.close)
        pool.request('GET', '/', headers=OrderedDict(expected_request_headers))
        self.assertEqual(expected_request_headers, actual_request_headers)

    def test_response_headers_are_returned_in_the_original_order(self):
        # NOTE: Probability this test gives a false negative is 1/(K!)
        K = 16
        # NOTE: Provide headers in non-sorted order (i.e. reversed)
        #       so that if the internal implementation tries to sort them,
        #       a change will be detected.
        expected_response_headers = [('x-header-%d' % i, str(i)) for i in reversed(range(K))]

        def socket_handler(listener):
            sock = listener.accept()[0]

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            sock.send(b'HTTP/1.1 200 OK\r\n' +
                      b'\r\n'.join([
                          (k.encode('utf8') + b': ' + v.encode('utf8'))
                          for (k, v) in expected_response_headers
                      ]) +
                      b'\r\n\r\n')
            sock.close()

        self._start_server(socket_handler)
        pool = HTTPConnectionPool(self.host, self.port)
        self.addCleanup(pool.close)
        r = pool.request('GET', '/', retries=0)
        actual_response_headers = [
            (k, v) for (k, v) in r.headers.items()
            if k.startswith('x-header-')
        ]
        self.assertEqual(expected_response_headers, actual_response_headers)

    def test_integer_values_are_sent_as_decimal_strings(self):
        headers = {'Foo': 88}
        parsed_headers = {}

        def socket_handler(listener):
            sock = listener.accept()[0]

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            headers_list = [header for header in buf.split(b'\r\n')[1:] if header]

            for header in headers_list:
                (key, value) = header.split(b': ')
                parsed_headers[key.decode('ascii')] = value.decode('ascii')

            sock.send((
                'HTTP/1.1 204 No Content\r\n'
                'Content-Length: 0\r\n'
                '\r\n').encode('utf-8'))

            sock.close()

        self._start_server(socket_handler)
        expected_headers = {'host': '{0}:{1}'.format(self.host, self.port),
                            'foo': '88'}

        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        pool.request('GET', '/', headers=HTTPHeaderDict(headers))
        self.assertEqual(expected_headers, parsed_headers)



class TestBrokenHeaders(SocketDummyServerTestCase):

    def _test_broken_header_parsing(self, headers):
        self.start_response_handler((
           b'HTTP/1.1 200 OK\r\n'
           b'Content-Length: 0\r\n'
           b'Content-type: text/plain\r\n'
           ) + b''.join(headers) + b'\r\n'
        )

        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        self.addCleanup(pool.close)
        self.assertRaises(ProtocolError, pool.request, 'GET', '/')

    def test_header_without_name(self):
        self._test_broken_header_parsing([
            b': Value\r\n',
            b'Another: Header\r\n',
        ])

    def test_header_without_name_or_value(self):
        self._test_broken_header_parsing([
            b':\r\n',
            b'Another: Header\r\n',
        ])

    def test_header_without_colon_or_value(self):
        self._test_broken_header_parsing([
            b'Broken Header\r\n',
            b'Another: Header\r\n',
        ])


class TestHEAD(SocketDummyServerTestCase):
    def test_chunked_head_response_does_not_hang(self):
        self.start_response_handler(
           b'HTTP/1.1 200 OK\r\n'
           b'Transfer-Encoding: chunked\r\n'
           b'Content-type: text/plain\r\n'
           b'\r\n'
        )
        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        self.addCleanup(pool.close)
        r = pool.request('HEAD', '/', timeout=1, preload_content=False)

        # stream will use the read_chunked method here.
        self.assertEqual([], list(r.stream()))

    def test_empty_head_response_does_not_hang(self):
        self.start_response_handler(
           b'HTTP/1.1 200 OK\r\n'
           b'Content-Length: 256\r\n'
           b'Content-type: text/plain\r\n'
           b'\r\n'
        )
        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        self.addCleanup(pool.close)
        r = pool.request('HEAD', '/', timeout=1, preload_content=False)

        # stream will use the read method here.
        self.assertEqual([], list(r.stream()))


class TestStream(SocketDummyServerTestCase):
    def test_stream_none_unchunked_response_does_not_hang(self):
        done_event = Event()

        def socket_handler(listener):
            sock = listener.accept()[0]

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            sock.send(
                b'HTTP/1.1 200 OK\r\n'
                b'Content-Length: 12\r\n'
                b'Content-type: text/plain\r\n'
                b'\r\n'
                b'hello, world'
            )
            done_event.wait(5)
            sock.close()

        self._start_server(socket_handler)
        pool = HTTPConnectionPool(self.host, self.port, retries=False)
        self.addCleanup(pool.close)
        r = pool.request('GET', '/', timeout=1, preload_content=False)

        # Stream should read to the end.
        self.assertEqual([b'hello, world'], list(r.stream(None)))

        done_event.set()


class TestBadContentLength(SocketDummyServerTestCase):
    def test_enforce_content_length_get(self):
        done_event = Event()

        def socket_handler(listener):
            sock = listener.accept()[0]

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            sock.send(
                b'HTTP/1.1 200 OK\r\n'
                b'Content-Length: 22\r\n'
                b'Content-type: text/plain\r\n'
                b'\r\n'
                b'hello, world'
            )
            done_event.wait(1)
            sock.close()

        self._start_server(socket_handler)
        conn = HTTPConnectionPool(self.host, self.port, maxsize=1)
        self.addCleanup(conn.close)

        # Test stream read when content length less than headers claim
        get_response = conn.request('GET', url='/', preload_content=False)
        data = get_response.stream(100)
        try:
            next(data)
            self.assertFail()
        except ProtocolError as e:
            self.assertTrue('received 12 bytes, expected 22' in str(e))

        done_event.set()

    def test_enforce_content_length_no_body(self):
        done_event = Event()

        def socket_handler(listener):
            sock = listener.accept()[0]

            buf = b''
            while not buf.endswith(b'\r\n\r\n'):
                buf += sock.recv(65536)

            sock.send(
                b'HTTP/1.1 200 OK\r\n'
                b'Content-Length: 22\r\n'
                b'Content-type: text/plain\r\n'
                b'\r\n'
            )
            done_event.wait(1)
            sock.close()

        self._start_server(socket_handler)
        conn = HTTPConnectionPool(self.host, self.port, maxsize=1)
        self.addCleanup(conn.close)

        #Test stream on 0 length body
        head_response = conn.request('HEAD', url='/', preload_content=False)
        data = [chunk for chunk in head_response.stream(1)]
        self.assertEqual(len(data), 0)

        done_event.set()


class TestAutomaticHeaderInsertion(SocketDummyServerTestCase):
    """
    Tests for automatically inserting headers, including for chunked transfer
    encoding.
    """
    def test_automatic_chunking_fileobj(self):
        """
        A file-like object should automatically be chunked if the user provides
        neither content-length nor transfer encoding.
        """
        done_event = Event()
        data = []

        def socket_handler(listener):
            sock = listener.accept()[0]

            buf = b''
            while not buf.endswith(b'0\r\n\r\n'):
                buf += sock.recv(65536)
            data.append(buf)

            sock.send(
                b'HTTP/1.1 200 OK\r\n'
                b'Content-Length: 0\r\n'
                b'\r\n'
            )
            done_event.wait(1)
            sock.close()

        self._start_server(socket_handler)
        conn = HTTPConnectionPool(self.host, self.port)

        myfileobj = io.BytesIO(b'helloworld')
        response = conn.request('POST', url='/', body=myfileobj)
        self.assertEqual(response.status, 200)

        # Confirm we auto chunked the body.
        self.assertIn(b'transfer-encoding: chunked\r\n', data[0])
        self.assertTrue(
            data[0].endswith(b'a\r\nhelloworld\r\n0\r\n\r\n')
        )
