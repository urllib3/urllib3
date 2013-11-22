import unittest
import socket
import threading
import multiprocessing
import time
from nose.plugins.skip import SkipTest

from dummyserver.server import (
    TornadoServerThread,
    SocketServerThread,
    HTTPProxyServerThread,
    run_socks4_proxy,
    run_socks5_proxy,
    DEFAULT_CERTS
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
            cls.server_thread.join(0.1)


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


class DummyProxyTestCase(unittest.TestCase):
    http_host = 'localhost'
    http_host_alt = '127.0.0.1'

    https_host = 'localhost'
    https_host_alt = '127.0.0.1'
    https_certs = DEFAULT_CERTS

    proxy_host = 'localhost'
    proxy_host_alt = '127.0.0.1'

    @classmethod
    def _start_http_servers(cls):
        ready_event = threading.Event()
        cls.http_thread = TornadoServerThread(
            host=cls.http_host, scheme='http',
            ready_event=ready_event)
        cls.http_thread.start()
        ready_event.wait()
        cls.http_port = cls.http_thread.port

        ready_event = threading.Event()
        cls.https_thread = TornadoServerThread(
            host=cls.https_host, scheme='https',
            certs=cls.https_certs,
            ready_event=ready_event)
        cls.https_thread.start()
        ready_event.wait()
        cls.https_port = cls.https_thread.port

    @classmethod
    def _stop_http_servers(cls):
        cls.http_thread.stop()
        cls.https_thread.stop()

class DummyHTTPProxyTestCase(DummyProxyTestCase):
    @classmethod
    def setUpClass(cls):
        raise SkipTest()
        cls._start_http_servers()
        ready_event = threading.Event()
        cls.proxy_thread = HTTPProxyServerThread(
            host=cls.proxy_host, ready_event=ready_event)
        cls.proxy_thread.start()
        ready_event.wait()
        cls.proxy_port = cls.proxy_thread.port
        

    @classmethod
    def tearDownClass(cls):
        cls._stop_http_servers()
        cls.proxy_thread.stop()
        cls.proxy_thread.join()


class DummySOCKS4ProxyTestCase(DummyProxyTestCase):
    proxy_port = 1080

    @classmethod
    def setUpClass(cls):
        #raise SkipTest()
        cls._start_http_servers()
        # Twisted doesn't play along well with multithreading
        cls.proxy_process = multiprocessing.Process(target=run_socks4_proxy, args=(cls.proxy_host, cls.proxy_port))
        cls.proxy_process.start()
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        cls._stop_http_servers()
        cls.proxy_process.terminate()

class DummySOCKS5ProxyTestCase(DummyProxyTestCase):
    proxy_port = 1081

    @classmethod
    def setUpClass(cls):
        raise SkipTest()
        cls._start_http_servers()
        cls.proxy_process = multiprocessing.Process(target=run_socks5_proxy, args=(cls.proxy_host, cls.proxy_port))
        cls.proxy_process.start()

    @classmethod
    def tearDownClass(cls):
        cls.proxy_process.terminate()

class IPv6HTTPDummyServerTestCase(HTTPDummyServerTestCase):
    host = '::1'

    @classmethod
    def setUpClass(cls):
        if not has_ipv6:
            raise SkipTest('IPv6 not available')
        else:
            super(IPv6HTTPDummyServerTestCase, cls).setUpClass()
