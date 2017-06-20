import threading
import socket

from urllib3.contrib import socks
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError

from dummyserver.server import DEFAULT_CERTS
from dummyserver.testcase import IPV4SocketDummyServerTestCase

from nose.plugins.skip import SkipTest

try:
    import ssl
    from urllib3.util import ssl_ as better_ssl
    HAS_SSL = True
except ImportError:
    ssl = None
    better_ssl = None
    HAS_SSL = False


SOCKS_NEGOTIATION_NONE = b'\x00'
SOCKS_NEGOTIATION_PASSWORD = b'\x02'

SOCKS_VERSION_SOCKS4 = b'\x04'
SOCKS_VERSION_SOCKS5 = b'\x05'


def _get_free_port(host):
    """
    Gets a free port by opening a socket, binding it, checking the assigned
    port, and then closing it.
    """
    s = socket.socket()
    s.bind((host, 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _read_exactly(sock, amt):
    """
    Read *exactly* ``amt`` bytes from the socket ``sock``.
    """
    data = b''

    while amt > 0:
        chunk = sock.recv(amt)
        data += chunk
        amt -= len(chunk)

    return data


def _read_until(sock, char):
    """
    Read from the socket until the character is received.
    """
    chunks = []
    while True:
        chunk = sock.recv(1)
        chunks.append(chunk)
        if chunk == char:
            break

    return b''.join(chunks)


def _address_from_socket(sock):
    """
    Returns the address from the SOCKS socket
    """
    addr_type = sock.recv(1)

    if addr_type == b'\x01':
        ipv4_addr = _read_exactly(sock, 4)
        return socket.inet_ntoa(ipv4_addr)
    elif addr_type == b'\x04':
        ipv6_addr = _read_exactly(sock, 16)
        return socket.inet_ntop(socket.AF_INET6, ipv6_addr)
    elif addr_type == b'\x03':
        addr_len = ord(sock.recv(1))
        return _read_exactly(sock, addr_len)
    else:
        raise RuntimeError("Unexpected addr type: %r" % addr_type)


def handle_socks5_negotiation(sock, negotiate, username=None,
                              password=None):
    """
    Handle the SOCKS5 handshake.

    Returns a generator object that allows us to break the handshake into
    steps so that the test code can intervene at certain useful points.
    """
    received_version = sock.recv(1)
    assert received_version == SOCKS_VERSION_SOCKS5
    nmethods = ord(sock.recv(1))
    methods = _read_exactly(sock, nmethods)

    if negotiate:
        assert SOCKS_NEGOTIATION_PASSWORD in methods
        send_data = SOCKS_VERSION_SOCKS5 + SOCKS_NEGOTIATION_PASSWORD
        sock.sendall(send_data)

        # This is the password negotiation.
        negotiation_version = sock.recv(1)
        assert negotiation_version == b'\x01'
        ulen = ord(sock.recv(1))
        provided_username = _read_exactly(sock, ulen)
        plen = ord(sock.recv(1))
        provided_password = _read_exactly(sock, plen)

        if username == provided_username and password == provided_password:
            sock.sendall(b'\x01\x00')
        else:
            sock.sendall(b'\x01\x01')
            sock.close()
            yield False
            return
    else:
        assert SOCKS_NEGOTIATION_NONE in methods
        send_data = SOCKS_VERSION_SOCKS5 + SOCKS_NEGOTIATION_NONE
        sock.sendall(send_data)

    # Client sends where they want to go.
    received_version = sock.recv(1)
    command = sock.recv(1)
    reserved = sock.recv(1)
    addr = _address_from_socket(sock)
    port = _read_exactly(sock, 2)
    port = (ord(port[0:1]) << 8) + (ord(port[1:2]))

    # Check some basic stuff.
    assert received_version == SOCKS_VERSION_SOCKS5
    assert command == b'\x01'  # Only support connect, not bind.
    assert reserved == b'\x00'

    # Yield the address port tuple.
    succeed = yield addr, port

    if succeed:
        # Hard-coded response for now.
        response = (
            SOCKS_VERSION_SOCKS5 + b'\x00\x00\x01\x7f\x00\x00\x01\xea\x60'
        )
    else:
        # Hard-coded response for now.
        response = SOCKS_VERSION_SOCKS5 + b'\x01\00'

    sock.sendall(response)
    yield True  # Avoid StopIteration exceptions getting fired.


def handle_socks4_negotiation(sock, username=None):
    """
    Handle the SOCKS4 handshake.

    Returns a generator object that allows us to break the handshake into
    steps so that the test code can intervene at certain useful points.
    """
    received_version = sock.recv(1)
    command = sock.recv(1)
    port = _read_exactly(sock, 2)
    port = (ord(port[0:1]) << 8) + (ord(port[1:2]))
    addr = _read_exactly(sock, 4)
    provided_username = _read_until(sock, b'\x00')[:-1]  # Strip trailing null.

    if addr == b'\x00\x00\x00\x01':
        # Magic string: means DNS name.
        addr = _read_until(sock, b'\x00')[:-1]  # Strip trailing null.
    else:
        addr = socket.inet_ntoa(addr)

    # Check some basic stuff.
    assert received_version == SOCKS_VERSION_SOCKS4
    assert command == b'\x01'  # Only support connect, not bind.

    if username is not None and username != provided_username:
        sock.sendall(b'\x00\x5d\x00\x00\x00\x00\x00\x00')
        sock.close()
        yield False
        return

    # Yield the address port tuple.
    succeed = yield addr, port

    if succeed:
        response = b'\x00\x5a\xea\x60\x7f\x00\x00\x01'
    else:
        response = b'\x00\x5b\x00\x00\x00\x00\x00\x00'

    sock.sendall(response)
    yield True  # Avoid StopIteration exceptions getting fired.


class TestSocks5Proxy(IPV4SocketDummyServerTestCase):
    """
    Test the SOCKS proxy in SOCKS5 mode.
    """
    def test_basic_request(self):
        def request_handler(listener):
            sock = listener.accept()[0]

            handler = handle_socks5_negotiation(sock, negotiate=False)
            addr, port = next(handler)

            self.assertEqual(addr, '16.17.18.19')
            self.assertTrue(port, 80)
            handler.send(True)

            while True:
                buf = sock.recv(65535)
                if buf.endswith(b'\r\n\r\n'):
                    break

            sock.sendall(b'HTTP/1.1 200 OK\r\n'
                         b'Server: SocksTestServer\r\n'
                         b'Content-Length: 0\r\n'
                         b'\r\n')
            sock.close()

        self._start_server(request_handler)
        proxy_url = "socks5://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(proxy_url)
        self.addCleanup(pm.clear)
        response = pm.request('GET', 'http://16.17.18.19')

        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, b'')
        self.assertEqual(response.headers['Server'], 'SocksTestServer')

    def test_local_dns(self):
        def request_handler(listener):
            sock = listener.accept()[0]

            handler = handle_socks5_negotiation(sock, negotiate=False)
            addr, port = next(handler)

            self.assertIn(addr, ['127.0.0.1', '::1'])
            self.assertTrue(port, 80)
            handler.send(True)

            while True:
                buf = sock.recv(65535)
                if buf.endswith(b'\r\n\r\n'):
                    break

            sock.sendall(b'HTTP/1.1 200 OK\r\n'
                         b'Server: SocksTestServer\r\n'
                         b'Content-Length: 0\r\n'
                         b'\r\n')
            sock.close()

        self._start_server(request_handler)
        proxy_url = "socks5://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(proxy_url)
        self.addCleanup(pm.clear)
        response = pm.request('GET', 'http://localhost')

        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, b'')
        self.assertEqual(response.headers['Server'], 'SocksTestServer')

    def test_correct_header_line(self):
        def request_handler(listener):
            sock = listener.accept()[0]

            handler = handle_socks5_negotiation(sock, negotiate=False)
            addr, port = next(handler)

            self.assertEqual(addr, b'example.com')
            self.assertTrue(port, 80)
            handler.send(True)

            buf = b''
            while True:
                buf += sock.recv(65535)
                if buf.endswith(b'\r\n\r\n'):
                    break

            self.assertTrue(buf.startswith(b'GET / HTTP/1.1'))
            self.assertTrue(b'Host: example.com' in buf)

            sock.sendall(b'HTTP/1.1 200 OK\r\n'
                         b'Server: SocksTestServer\r\n'
                         b'Content-Length: 0\r\n'
                         b'\r\n')
            sock.close()

        self._start_server(request_handler)
        proxy_url = "socks5h://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(proxy_url)
        self.addCleanup(pm.clear)
        response = pm.request('GET', 'http://example.com')
        self.assertEqual(response.status, 200)

    def test_connection_timeouts(self):
        event = threading.Event()

        def request_handler(listener):
            event.wait()

        self._start_server(request_handler)
        proxy_url = "socks5h://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(proxy_url)
        self.addCleanup(pm.clear)

        self.assertRaises(
            ConnectTimeoutError, pm.request, 'GET', 'http://example.com',
            timeout=0.001, retries=False
        )
        event.set()

    def test_connection_failure(self):
        event = threading.Event()

        def request_handler(listener):
            listener.close()
            event.set()

        self._start_server(request_handler)
        proxy_url = "socks5h://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(proxy_url)
        self.addCleanup(pm.clear)

        event.wait()
        self.assertRaises(
            NewConnectionError, pm.request, 'GET', 'http://example.com',
            retries=False
        )

    def test_proxy_rejection(self):
        evt = threading.Event()

        def request_handler(listener):
            sock = listener.accept()[0]

            handler = handle_socks5_negotiation(sock, negotiate=False)
            addr, port = next(handler)
            handler.send(False)

            evt.wait()
            sock.close()

        self._start_server(request_handler)
        proxy_url = "socks5h://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(proxy_url)
        self.addCleanup(pm.clear)

        self.assertRaises(
            NewConnectionError, pm.request, 'GET', 'http://example.com',
            retries=False
        )
        evt.set()

    def test_socks_with_password(self):
        def request_handler(listener):
            sock = listener.accept()[0]

            handler = handle_socks5_negotiation(
                sock, negotiate=True, username=b'user', password=b'pass'
            )
            addr, port = next(handler)

            self.assertEqual(addr, '16.17.18.19')
            self.assertTrue(port, 80)
            handler.send(True)

            while True:
                buf = sock.recv(65535)
                if buf.endswith(b'\r\n\r\n'):
                    break

            sock.sendall(b'HTTP/1.1 200 OK\r\n'
                         b'Server: SocksTestServer\r\n'
                         b'Content-Length: 0\r\n'
                         b'\r\n')
            sock.close()

        self._start_server(request_handler)
        proxy_url = "socks5://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(proxy_url, username='user',
                                     password='pass')
        self.addCleanup(pm.clear)

        response = pm.request('GET', 'http://16.17.18.19')

        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, b'')
        self.assertEqual(response.headers['Server'], 'SocksTestServer')

    def test_socks_with_invalid_password(self):
        def request_handler(listener):
            sock = listener.accept()[0]

            handler = handle_socks5_negotiation(
                sock, negotiate=True, username=b'user', password=b'pass'
            )
            next(handler)

        self._start_server(request_handler)
        proxy_url = "socks5h://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(proxy_url, username='user',
                                     password='badpass')
        self.addCleanup(pm.clear)

        try:
            pm.request('GET', 'http://example.com', retries=False)
        except NewConnectionError as e:
            self.assertTrue("SOCKS5 authentication failed" in str(e))
        else:
            self.fail("Did not raise")

    def test_source_address_works(self):
        expected_port = _get_free_port(self.host)

        def request_handler(listener):
            sock = listener.accept()[0]
            self.assertEqual(sock.getpeername()[0], '127.0.0.1')
            self.assertEqual(sock.getpeername()[1], expected_port)

            handler = handle_socks5_negotiation(sock, negotiate=False)
            addr, port = next(handler)

            self.assertEqual(addr, '16.17.18.19')
            self.assertTrue(port, 80)
            handler.send(True)

            while True:
                buf = sock.recv(65535)
                if buf.endswith(b'\r\n\r\n'):
                    break

            sock.sendall(b'HTTP/1.1 200 OK\r\n'
                         b'Server: SocksTestServer\r\n'
                         b'Content-Length: 0\r\n'
                         b'\r\n')
            sock.close()

        self._start_server(request_handler)
        proxy_url = "socks5://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(
            proxy_url, source_address=('127.0.0.1', expected_port)
        )
        self.addCleanup(pm.clear)
        response = pm.request('GET', 'http://16.17.18.19')
        self.assertEqual(response.status, 200)


class TestSOCKS4Proxy(IPV4SocketDummyServerTestCase):
    """
    Test the SOCKS proxy in SOCKS4 mode.

    Has relatively fewer tests than the SOCKS5 case, mostly because once the
    negotiation is done the two cases behave identically.
    """
    def test_basic_request(self):
        def request_handler(listener):
            sock = listener.accept()[0]

            handler = handle_socks4_negotiation(sock)
            addr, port = next(handler)

            self.assertEqual(addr, '16.17.18.19')
            self.assertTrue(port, 80)
            handler.send(True)

            while True:
                buf = sock.recv(65535)
                if buf.endswith(b'\r\n\r\n'):
                    break

            sock.sendall(b'HTTP/1.1 200 OK\r\n'
                         b'Server: SocksTestServer\r\n'
                         b'Content-Length: 0\r\n'
                         b'\r\n')
            sock.close()

        self._start_server(request_handler)
        proxy_url = "socks4://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(proxy_url)
        self.addCleanup(pm.clear)
        response = pm.request('GET', 'http://16.17.18.19')

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers['Server'], 'SocksTestServer')
        self.assertEqual(response.data, b'')

    def test_local_dns(self):
        def request_handler(listener):
            sock = listener.accept()[0]

            handler = handle_socks4_negotiation(sock)
            addr, port = next(handler)

            self.assertEqual(addr, '127.0.0.1')
            self.assertTrue(port, 80)
            handler.send(True)

            while True:
                buf = sock.recv(65535)
                if buf.endswith(b'\r\n\r\n'):
                    break

            sock.sendall(b'HTTP/1.1 200 OK\r\n'
                         b'Server: SocksTestServer\r\n'
                         b'Content-Length: 0\r\n'
                         b'\r\n')
            sock.close()

        self._start_server(request_handler)
        proxy_url = "socks4://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(proxy_url)
        self.addCleanup(pm.clear)
        response = pm.request('GET', 'http://localhost')

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers['Server'], 'SocksTestServer')
        self.assertEqual(response.data, b'')

    def test_correct_header_line(self):
        def request_handler(listener):
            sock = listener.accept()[0]

            handler = handle_socks4_negotiation(sock)
            addr, port = next(handler)

            self.assertEqual(addr, b'example.com')
            self.assertTrue(port, 80)
            handler.send(True)

            buf = b''
            while True:
                buf += sock.recv(65535)
                if buf.endswith(b'\r\n\r\n'):
                    break

            self.assertTrue(buf.startswith(b'GET / HTTP/1.1'))
            self.assertTrue(b'Host: example.com' in buf)

            sock.sendall(b'HTTP/1.1 200 OK\r\n'
                         b'Server: SocksTestServer\r\n'
                         b'Content-Length: 0\r\n'
                         b'\r\n')
            sock.close()

        self._start_server(request_handler)
        proxy_url = "socks4a://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(proxy_url)
        self.addCleanup(pm.clear)
        response = pm.request('GET', 'http://example.com')
        self.assertEqual(response.status, 200)

    def test_proxy_rejection(self):
        evt = threading.Event()

        def request_handler(listener):
            sock = listener.accept()[0]

            handler = handle_socks4_negotiation(sock)
            addr, port = next(handler)
            handler.send(False)

            evt.wait()
            sock.close()

        self._start_server(request_handler)
        proxy_url = "socks4a://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(proxy_url)
        self.addCleanup(pm.clear)

        self.assertRaises(
            NewConnectionError, pm.request, 'GET', 'http://example.com',
            retries=False
        )
        evt.set()

    def test_socks4_with_username(self):
        def request_handler(listener):
            sock = listener.accept()[0]

            handler = handle_socks4_negotiation(sock, username=b'user')
            addr, port = next(handler)

            self.assertEqual(addr, '16.17.18.19')
            self.assertTrue(port, 80)
            handler.send(True)

            while True:
                buf = sock.recv(65535)
                if buf.endswith(b'\r\n\r\n'):
                    break

            sock.sendall(b'HTTP/1.1 200 OK\r\n'
                         b'Server: SocksTestServer\r\n'
                         b'Content-Length: 0\r\n'
                         b'\r\n')
            sock.close()

        self._start_server(request_handler)
        proxy_url = "socks4://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(proxy_url, username='user')
        self.addCleanup(pm.clear)
        response = pm.request('GET', 'http://16.17.18.19')

        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, b'')
        self.assertEqual(response.headers['Server'], 'SocksTestServer')

    def test_socks_with_invalid_username(self):
        def request_handler(listener):
            sock = listener.accept()[0]

            handler = handle_socks4_negotiation(sock, username=b'user')
            next(handler)

        self._start_server(request_handler)
        proxy_url = "socks4a://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(proxy_url, username='baduser')
        self.addCleanup(pm.clear)

        try:
            pm.request('GET', 'http://example.com', retries=False)
        except NewConnectionError as e:
            self.assertTrue("different user-ids" in str(e))
        else:
            self.fail("Did not raise")


class TestSOCKSWithTLS(IPV4SocketDummyServerTestCase):
    """
    Test that TLS behaves properly for SOCKS proxies.
    """
    def test_basic_request(self):
        if not HAS_SSL:
            raise SkipTest("No TLS available")

        def request_handler(listener):
            sock = listener.accept()[0]

            handler = handle_socks5_negotiation(sock, negotiate=False)
            addr, port = next(handler)

            self.assertEqual(addr, b'localhost')
            self.assertTrue(port, 443)
            handler.send(True)

            # Wrap in TLS
            context = better_ssl.SSLContext(ssl.PROTOCOL_SSLv23)
            context.load_cert_chain(
                DEFAULT_CERTS['certfile'], DEFAULT_CERTS['keyfile']
            )
            tls = context.wrap_socket(sock, server_side=True)
            buf = b''

            while True:
                buf += tls.recv(65535)
                if buf.endswith(b'\r\n\r\n'):
                    break

            self.assertTrue(buf.startswith(b'GET / HTTP/1.1\r\n'))

            tls.sendall(b'HTTP/1.1 200 OK\r\n'
                        b'Server: SocksTestServer\r\n'
                        b'Content-Length: 0\r\n'
                        b'\r\n')
            tls.close()
            sock.close()

        self._start_server(request_handler)
        proxy_url = "socks5h://%s:%s" % (self.host, self.port)
        pm = socks.SOCKSProxyManager(proxy_url)
        self.addCleanup(pm.clear)
        response = pm.request('GET', 'https://localhost')

        self.assertEqual(response.status, 200)
        self.assertEqual(response.data, b'')
        self.assertEqual(response.headers['Server'], 'SocksTestServer')
