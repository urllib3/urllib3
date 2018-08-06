#!/usr/bin/env python

"""
Dummy server used for unit testing.
"""
from __future__ import print_function

import errno
import logging
import os
import random
import string
import sys
import threading
import socket
import warnings
import ssl
from datetime import datetime

from urllib3.exceptions import HTTPWarning

from tornado.platform.auto import set_close_exec
import tornado.httpserver
import tornado.ioloop
import tornado.web


log = logging.getLogger(__name__)

CERTS_PATH = os.path.join(os.path.dirname(__file__), 'certs')
DEFAULT_CERTS = {
    'certfile': os.path.join(CERTS_PATH, 'server.crt'),
    'keyfile': os.path.join(CERTS_PATH, 'server.key'),
    'cert_reqs': ssl.CERT_OPTIONAL,
    'ca_certs': os.path.join(CERTS_PATH, 'cacert.pem'),
}
DEFAULT_CLIENT_CERTS = {
    'certfile': os.path.join(CERTS_PATH, 'client_intermediate.pem'),
    'keyfile': os.path.join(CERTS_PATH, 'client_intermediate.key'),
    'subject': dict(countryName=u'FI', stateOrProvinceName=u'dummy',
                    organizationName=u'dummy', organizationalUnitName=u'dummy',
                    commonName=u'SnakeOilClient',
                    emailAddress=u'dummy@test.local'),
}
DEFAULT_CLIENT_NO_INTERMEDIATE_CERTS = {
    'certfile': os.path.join(CERTS_PATH, 'client_no_intermediate.pem'),
    'keyfile': os.path.join(CERTS_PATH, 'client_intermediate.key'),
}
NO_SAN_CERTS = {
    'certfile': os.path.join(CERTS_PATH, 'server.no_san.crt'),
    'keyfile': DEFAULT_CERTS['keyfile']
}
IP_SAN_CERTS = {
    'certfile': os.path.join(CERTS_PATH, 'server.ip_san.crt'),
    'keyfile': DEFAULT_CERTS['keyfile']
}
IPV6_ADDR_CERTS = {
    'certfile': os.path.join(CERTS_PATH, 'server.ipv6addr.crt'),
    'keyfile': os.path.join(CERTS_PATH, 'server.ipv6addr.key'),
}
DEFAULT_CA = os.path.join(CERTS_PATH, 'cacert.pem')
DEFAULT_CA_BAD = os.path.join(CERTS_PATH, 'client_bad.pem')
NO_SAN_CA = os.path.join(CERTS_PATH, 'cacert.no_san.pem')
DEFAULT_CA_DIR = os.path.join(CERTS_PATH, 'ca_path_test')
IPV6_ADDR_CA = os.path.join(CERTS_PATH, 'server.ipv6addr.crt')
COMBINED_CERT_AND_KEY = os.path.join(CERTS_PATH, 'server.combined.pem')


def _has_ipv6(host):
    """ Returns True if the system can bind an IPv6 address. """
    sock = None
    has_ipv6 = False

    if socket.has_ipv6:
        # has_ipv6 returns true if cPython was compiled with IPv6 support.
        # It does not tell us if the system has IPv6 support enabled. To
        # determine that we must bind to an IPv6 address.
        # https://github.com/shazow/urllib3/pull/611
        # https://bugs.python.org/issue658327
        try:
            sock = socket.socket(socket.AF_INET6)
            sock.bind((host, 0))
            has_ipv6 = True
        except Exception:
            pass

    if sock:
        sock.close()
    return has_ipv6


# Some systems may have IPv6 support but DNS may not be configured
# properly. We can not count that localhost will resolve to ::1 on all
# systems. See https://github.com/shazow/urllib3/pull/611 and
# https://bugs.python.org/issue18792
HAS_IPV6_AND_DNS = _has_ipv6('localhost')
HAS_IPV6 = _has_ipv6('::1')


# Different types of servers we have:


class NoIPv6Warning(HTTPWarning):
    "IPv6 is not available"
    pass


class SocketServerThread(threading.Thread):
    """
    :param socket_handler: Callable which receives a socket argument for one
        request.
    :param ready_event: Event which gets set when the socket handler is
        ready to receive requests.
    """
    USE_IPV6 = HAS_IPV6_AND_DNS

    def __init__(self, socket_handler, host='localhost', port=8081,
                 ready_event=None):
        threading.Thread.__init__(self)
        self.daemon = True

        self.socket_handler = socket_handler
        self.host = host
        self.ready_event = ready_event

    def _start_server(self):
        if self.USE_IPV6:
            sock = socket.socket(socket.AF_INET6)
        else:
            warnings.warn("No IPv6 support. Falling back to IPv4.",
                          NoIPv6Warning)
            sock = socket.socket(socket.AF_INET)
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


# FIXME: there is a pull request patching bind_sockets in Tornado directly.
# If it gets merged and released we can drop this and use
# `tornado.netutil.bind_sockets` again.
# https://github.com/facebook/tornado/pull/977

def bind_sockets(port, address=None, family=socket.AF_UNSPEC, backlog=128,
                 flags=None):
    """Creates listening sockets bound to the given port and address.

    Returns a list of socket objects (multiple sockets are returned if
    the given address maps to multiple IP addresses, which is most common
    for mixed IPv4 and IPv6 use).

    Address may be either an IP address or hostname.  If it's a hostname,
    the server will listen on all IP addresses associated with the
    name.  Address may be an empty string or None to listen on all
    available interfaces.  Family may be set to either `socket.AF_INET`
    or `socket.AF_INET6` to restrict to IPv4 or IPv6 addresses, otherwise
    both will be used if available.

    The ``backlog`` argument has the same meaning as for
    `socket.listen() <socket.socket.listen>`.

    ``flags`` is a bitmask of AI_* flags to `~socket.getaddrinfo`, like
    ``socket.AI_PASSIVE | socket.AI_NUMERICHOST``.
    """
    sockets = []
    if address == "":
        address = None
    if not HAS_IPV6 and family == socket.AF_UNSPEC:
        # Python can be compiled with --disable-ipv6, which causes
        # operations on AF_INET6 sockets to fail, but does not
        # automatically exclude those results from getaddrinfo
        # results.
        # http://bugs.python.org/issue16208
        family = socket.AF_INET
    if flags is None:
        flags = socket.AI_PASSIVE
    binded_port = None
    for res in set(socket.getaddrinfo(address, port, family,
                                      socket.SOCK_STREAM, 0, flags)):
        af, socktype, proto, canonname, sockaddr = res
        try:
            sock = socket.socket(af, socktype, proto)
        except socket.error as e:
            if e.args[0] == errno.EAFNOSUPPORT:
                continue
            raise
        set_close_exec(sock.fileno())
        if os.name != 'nt':
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if af == socket.AF_INET6:
            # On linux, ipv6 sockets accept ipv4 too by default,
            # but this makes it impossible to bind to both
            # 0.0.0.0 in ipv4 and :: in ipv6.  On other systems,
            # separate sockets *must* be used to listen for both ipv4
            # and ipv6.  For consistency, always disable ipv4 on our
            # ipv6 sockets and use a separate ipv4 socket when needed.
            #
            # Python 2.x on windows doesn't have IPPROTO_IPV6.
            if hasattr(socket, "IPPROTO_IPV6"):
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)

        # automatic port allocation with port=None
        # should bind on the same port on IPv4 and IPv6
        host, requested_port = sockaddr[:2]
        if requested_port == 0 and binded_port is not None:
            sockaddr = tuple([host, binded_port] + list(sockaddr[2:]))

        sock.setblocking(0)
        sock.bind(sockaddr)
        binded_port = sock.getsockname()[1]
        sock.listen(backlog)
        sockets.append(sock)
    return sockets


def run_tornado_app(app, io_loop, certs, scheme, host):
    assert io_loop == tornado.ioloop.IOLoop.current()

    # We can't use fromtimestamp(0) because of CPython issue 29097, so we'll
    # just construct the datetime object directly.
    app.last_req = datetime(1970, 1, 1)

    if scheme == 'https':
        http_server = tornado.httpserver.HTTPServer(app, ssl_options=certs)
    else:
        http_server = tornado.httpserver.HTTPServer(app)

    sockets = bind_sockets(None, address=host)
    port = sockets[0].getsockname()[1]
    http_server.add_sockets(sockets)
    return http_server, port


def run_loop_in_thread(io_loop):
    t = threading.Thread(target=io_loop.start)
    t.start()
    return t


def get_unreachable_address():
    while True:
        host = ''.join(random.choice(string.ascii_lowercase)
                       for _ in range(60))
        sockaddr = (host, 54321)

        # check if we are really "lucky" and hit an actual server
        try:
            s = socket.create_connection(sockaddr)
        except socket.error:
            return sockaddr
        else:
            s.close()


if __name__ == '__main__':
    # For debugging dummyserver itself - python -m dummyserver.server
    from .testcase import TestingApp
    host = '127.0.0.1'

    io_loop = tornado.ioloop.IOLoop.current()
    app = tornado.web.Application([(r".*", TestingApp)])
    server, port = run_tornado_app(app, io_loop, None,
                                   'http', host)
    server_thread = run_loop_in_thread(io_loop)

    print("Listening on http://{host}:{port}".format(host=host, port=port))
