import unittest
import socket
import threading
from nose.plugins.skip import SkipTest
from tornado import ioloop, web, wsgi

from dummyserver.server import (
    SocketServerThread,
    run_tornado_app,
    run_loop_in_thread,
    DEFAULT_CERTS,
)
from dummyserver.handlers import TestingApp
from dummyserver.proxy import ProxyHandler



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
    """ A simple HTTP server that runs when your test class runs

    Have your unittest class inherit from this one, and then a simple server
    will start when your tests run, and automatically shut down when they
    complete. For examples of what test requests you can send to the server,
    see the TestingApp in dummyserver/handlers.py.
    """
    scheme = 'http'
    host = 'localhost'
    host_alt = '127.0.0.1'  # Some tests need two hosts
    certs = DEFAULT_CERTS

    @classmethod
    def _start_server(cls):
        cls.io_loop = ioloop.IOLoop()
        app = wsgi.WSGIContainer(TestingApp())
        cls.server, cls.port = run_tornado_app(app, cls.io_loop, cls.certs,
                                               cls.scheme, cls.host)
        cls.server_thread = run_loop_in_thread(cls.io_loop)

    @classmethod
    def _stop_server(cls):
        cls.io_loop.add_callback(cls.server.stop)
        cls.io_loop.add_callback(cls.io_loop.stop)
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
        cls.io_loop = ioloop.IOLoop()

        app = wsgi.WSGIContainer(TestingApp())
        cls.http_server, cls.http_port = run_tornado_app(
            app, cls.io_loop, None, 'http', cls.http_host)

        app = wsgi.WSGIContainer(TestingApp())
        cls.https_server, cls.https_port = run_tornado_app(
            app, cls.io_loop, cls.https_certs, 'https', cls.http_host)

        app = web.Application([(r'.*', ProxyHandler)])
        cls.proxy_server, cls.proxy_port = run_tornado_app(
            app, cls.io_loop, None, 'http', cls.proxy_host)

        cls.server_thread = run_loop_in_thread(cls.io_loop)

    @classmethod
    def tearDownClass(cls):
        cls.io_loop.add_callback(cls.http_server.stop)
        cls.io_loop.add_callback(cls.https_server.stop)
        cls.io_loop.add_callback(cls.proxy_server.stop)
        cls.io_loop.add_callback(cls.io_loop.stop)
        cls.server_thread.join()


class IPv6HTTPDummyServerTestCase(HTTPDummyServerTestCase):
    host = '::1'

    @classmethod
    def setUpClass(cls):
        if not socket.has_ipv6:
            raise SkipTest('IPv6 not available')
        else:
            super(IPv6HTTPDummyServerTestCase, cls).setUpClass()
