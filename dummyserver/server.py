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

import tornado.wsgi
import tornado.httpserver
import tornado.ioloop

from dummyserver.handlers import TestingApp


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
    :param ready_lock: Lock which gets released when the socket handler is
        ready to receive requests.
    """
    def __init__(self, socket_handler, host='localhost', port=8081,
                 ready_lock=None):
        threading.Thread.__init__(self)

        self.socket_handler = socket_handler
        self.host = host
        self.port = port
        self.ready_lock = ready_lock
        self.sock = socket.socket()
        self._stopping = False

    def _start_server(self):
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))

        # Once listen() returns, the server socket is ready
        self.sock.listen(1)

        if self.ready_lock:
            self.ready_lock.release()

        try:
            self.socket_handler(self.sock)
        except KeyboardInterrupt:
            raise
        except:
            if not self._stopping:
                raise

    def run(self):
        self.server = self._start_server()

    def stop(self):
        if self.sock:
            # If a test did not complete, it is possible that the socket handler
            # is blocking on accept(). To overcome this, we shutdown the socket.
            # This will cause a blocking accept() call to raise an exception
            self._stopping = True
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
            self.sock = None

            self.join()


class TornadoServerThread(threading.Thread):
    def __init__(self, host='localhost', port=8081, scheme='http', certs=None):
        threading.Thread.__init__(self)

        self.host = host
        self.port = port
        self.scheme = scheme
        self.certs = certs

    def _start_server(self):
        container = tornado.wsgi.WSGIContainer(TestingApp())

        if self.scheme == 'https':
            http_server = tornado.httpserver.HTTPServer(container,
                                                        ssl_options=self.certs)
        else:
            http_server = tornado.httpserver.HTTPServer(container)

        http_server.listen(self.port, address=self.host)
        return http_server

    def run(self):
        self.server = self._start_server()
        self.ioloop = tornado.ioloop.IOLoop.instance()
        self.ioloop.start()

    def stop(self):
        self.server.stop()
        self.ioloop.stop()


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
