#!/usr/bin/env python

"""
Dummy server used for unit testing.
"""
from __future__ import print_function

import logging
import os
import sys
import threading
import socket

from tornado import netutil
import tornado.wsgi
import tornado.httpserver
import tornado.ioloop
import tornado.web

from dummyserver.handlers import TestingApp
from dummyserver.proxy import ProxyHandler


log = logging.getLogger(__name__)

CERTS_PATH = os.path.join(os.path.dirname(__file__), 'certs')
DEFAULT_CERTS = {
    'certfile': os.path.join(CERTS_PATH, 'server.crt'),
    'keyfile': os.path.join(CERTS_PATH, 'server.key'),
}
DEFAULT_CA = os.path.join(CERTS_PATH, 'cacert.pem')
DEFAULT_CA_BAD = os.path.join(CERTS_PATH, 'client_bad.pem')


# Different types of servers we have:


class SocketServerThread(threading.Thread):
    """
    :param socket_handler: Callable which receives a socket argument for one
        request.
    :param ready_event: Event which gets set when the socket handler is
        ready to receive requests.
    """
    def __init__(self, socket_handler, host='localhost', port=8081,
                 ready_event=None):
        threading.Thread.__init__(self)

        self.socket_handler = socket_handler
        self.host = host
        self.ready_event = ready_event

    def _start_server(self):
        sock = socket.socket()
        if sys.platform != 'win32':
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, 0))
        self.port = sock.getsockname()[1]

        # Once listen() returns, the server socket is ready
        sock.listen(1)

        if self.ready_event:
            self.ready_event.set()

        self.socket_handler(sock)
        sock.close()

    def run(self):
        self.server = self._start_server()


class TornadoServerThread(threading.Thread):
    app = tornado.wsgi.WSGIContainer(TestingApp())

    def __init__(self, host='localhost', scheme='http', certs=None,
                 ready_event=None):
        threading.Thread.__init__(self)

        self.host = host
        self.scheme = scheme
        self.certs = certs
        self.ready_event = ready_event

    def _start_server(self):
        if self.scheme == 'https':
            http_server = tornado.httpserver.HTTPServer(self.app,
                                                        ssl_options=self.certs)
        else:
            http_server = tornado.httpserver.HTTPServer(self.app)

        family = socket.AF_INET6 if ':' in self.host else socket.AF_INET
        sock, = netutil.bind_sockets(None, address=self.host, family=family)
        self.port = sock.getsockname()[1]
        http_server.add_sockets([sock])
        return http_server

    def run(self):
        self.ioloop = tornado.ioloop.IOLoop.instance()
        self.server = self._start_server()
        if self.ready_event:
            self.ready_event.set()
        self.ioloop.start()

    def stop(self):
        self.ioloop.add_callback(self.server.stop)
        self.ioloop.add_callback(self.ioloop.stop)


class ProxyServerThread(TornadoServerThread):
    app = tornado.web.Application([(r'.*', ProxyHandler)])


if __name__ == '__main__':
    log.setLevel(logging.DEBUG)
    log.addHandler(logging.StreamHandler(sys.stderr))

    from urllib3 import get_host

    url = "http://localhost:8081"
    if len(sys.argv) > 1:
        url = sys.argv[1]

    print("Starting WSGI server at: %s" % url)

    scheme, host, port = get_host(url)
    t = TornadoServerThread(scheme=scheme, host=host, port=port)
    t.start()
