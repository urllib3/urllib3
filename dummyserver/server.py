#!/usr/bin/env python

"""
Dummy server used for unit testing.
"""

import logging
import os
import sys

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

def eventlet_server(wsgi_handler, host="localhost", port=8081, scheme='http',
                    certs=None, **kw):
    import eventlet
    import eventlet.wsgi

    certs = certs or {}

    sock = eventlet.listen((host, port))

    if scheme == 'https':
        sock = eventlet.wrap_ssl(sock, server_side=True, **certs)

    dummy_log_fp = open(os.devnull, 'a')

    return eventlet.wsgi.server(sock, wsgi_handler, log=dummy_log_fp, **kw)


def simple_server(wsgi_handler, host="localhost", port=8081, **kw):
    from wsgiref.simple_server import make_server as _make_server
    return _make_server(host, port, wsgi_handler)


def socket_server(socket_handler, host="localhost", port=8081, lock=None):
    """
    :param request_handler: Callable which receives a socket argument for one request.
    :param lock: Lock which gets acquired immediately and released when the
        socket handler is ready to receive requests.

    :returns: a callable which starts a socket-based server that releases the
        lock when ready.
    """
    lock and lock.acquire()

    import socket

    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))

    # Once listen() returns, the server socket is ready
    sock.listen(1)
    lock and lock.release()

    socket_handler(sock)


def make_wsgi_server(App=TestingApp, **kw):
    try:
        return eventlet_server(App(), **kw)
    except ImportError:
        return simple_server(App(), **kw)


def make_server_thread(target, daemon=False, **kw):
    from threading import Thread

    t = Thread(target=target, kwargs=kw)
    t.daemon = daemon
    t.start()

    return t


if __name__ == '__main__':
    log.setLevel(logging.DEBUG)
    log.addHandler(logging.StreamHandler(sys.stderr))

    from urllib3 import get_host

    url = "http://localhost:8081"
    if len(sys.argv) > 1:
        url = sys.argv[1]

    print "Starting WSGI server at: %s" % url

    scheme, host, port = get_host(url)
    make_wsgi_server(scheme=scheme, host=host, port=port)
