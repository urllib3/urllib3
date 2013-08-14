import unittest
import socket
import threading
from nose.plugins.skip import SkipTest

from dummyserver.server import (
    TornadoServerThread, SocketServerThread,
    DEFAULT_CERTS,
    ProxyServerThread,
)

has_ipv6 = hasattr(socket, 'has_ipv6')


class SocketDummyServerTestCase(unittest.TestCase):
    """
    A simple socket-based server is created for this class that is good for
    exactly one request.
    """
    scheme = 'http'
    host = 'localhost'

    @classmethod
    def _start_server(cls, socket_handler):
        ready_event = threading.Event()
        cls.server_thread = SocketServerThread(socket_handler=socket_handler,
                                               ready_event=ready_event,
                                               host=cls.host)
        cls.server_thread.start()
        ready_event.wait()
        cls.port = cls.server_thread.port

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'server_thread'):
            cls.server_thread.join()


class HTTPDummyServerTestCase(unittest.TestCase):
    scheme = 'http'
    host = 'localhost'
    host_alt = '127.0.0.1'  # Some tests need two hosts
    certs = DEFAULT_CERTS

    @classmethod
    def _start_server(cls):
        ready_event = threading.Event()
        cls.server_thread = TornadoServerThread(host=cls.host,
                                                scheme=cls.scheme,
                                                certs=cls.certs,
                                                ready_event=ready_event)
        cls.server_thread.start()
        ready_event.wait()
        cls.port = cls.server_thread.port

    @classmethod
    def _stop_server(cls):
        cls.server_thread.stop()
        cls.server_thread.join()

    @classmethod
    def setUpClass(cls):
        cls._start_server()

    @classmethod
    def tearDownClass(cls):
        cls._stop_server()


class HTTPSDummyServerTestCase(HTTPDummyServerTestCase):
    scheme = 'https'
    host = 'localhost'
    certs = DEFAULT_CERTS


class HTTPDummyProxyTestCase(unittest.TestCase):

    http_host = 'localhost'
    http_host_alt = '127.0.0.1'

    https_host = 'localhost'
    https_host_alt = '127.0.0.1'
    https_certs = DEFAULT_CERTS

    proxy_host = 'localhost'
    proxy_host_alt = '127.0.0.1'

    @classmethod
    def setUpClass(cls):
        cls.http_thread = TornadoServerThread(host=cls.http_host,
                                              scheme='http')
        cls.http_thread._start_server()
        cls.http_port = cls.http_thread.port

        cls.https_thread = TornadoServerThread(
            host=cls.https_host, scheme='https', certs=cls.https_certs)
        cls.https_thread._start_server()
        cls.https_port = cls.https_thread.port

        ready_event = threading.Event()
        cls.proxy_thread = ProxyServerThread(
            host=cls.proxy_host, ready_event=ready_event)
        cls.proxy_thread.start()
        ready_event.wait()
        cls.proxy_port = cls.proxy_thread.port

    @classmethod
    def tearDownClass(cls):
        cls.proxy_thread.stop()
        cls.proxy_thread.join()


class IPv6HTTPDummyServerTestCase(HTTPDummyServerTestCase):
    host = '::1'

    @classmethod
    def setUpClass(cls):
        if not has_ipv6:
            raise SkipTest('IPv6 not available')
        else:
            super(IPv6HTTPDummyServerTestCase, cls).setUpClass()
