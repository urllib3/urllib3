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


def run_tornado_app(app, io_loop, certs, scheme, host):
    if scheme == 'https':
        http_server = tornado.httpserver.HTTPServer(app, ssl_options=certs,
                                                    io_loop=io_loop)
    else:
        http_server = tornado.httpserver.HTTPServer(app, io_loop=io_loop)

    family = socket.AF_INET6 if ':' in host else socket.AF_INET
    sock, = netutil.bind_sockets(None, address=host, family=family)
    port = sock.getsockname()[1]
    http_server.add_sockets([sock])
    return http_server, port


def run_loop_in_thread(io_loop):
    t = threading.Thread(target=io_loop.start)
    t.start()
    return t
