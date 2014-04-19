# urllib3/connection.py
# Copyright 2008-2013 Andrey Petrov and contributors (see CONTRIBUTORS.txt)
#
# This module is part of urllib3 and is released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php

import sys
import socket
from socket import timeout as SocketTimeout

import backports.ssl as backports_ssl

try: # Python 3
    from http.client import HTTPConnection as _HTTPConnection, HTTPException
except ImportError:
    from httplib import HTTPConnection as _HTTPConnection, HTTPException

class DummyConnection(object):
    "Used to detect a failed ConnectionCls import."
    pass

try: # Compiled with SSL?
    HTTPSConnection = DummyConnection

    try: # Python 3
        from http.client import HTTPSConnection as _HTTPSConnection
    except ImportError:
        from httplib import HTTPSConnection as _HTTPSConnection

except (ImportError, AttributeError): # Platform-specific: No SSL.
    pass

from .exceptions import (
    ConnectTimeoutError,
)
from .packages import six
from .util import (
    assert_fingerprint,
    base_ssl,
    resolve_cert_reqs,
    resolve_ssl_version,
    ssl_wrap_socket,
)


port_by_scheme = {
    'http': 80,
    'https': 443,
}


class HTTPConnection(_HTTPConnection, object):
    """
    Based on httplib.HTTPConnection but provides an extra constructor
    backwards-compatibility layer between older and newer Pythons.
    """

    default_port = port_by_scheme['http']

    # By default, disable Nagle's Algorithm.
    tcp_nodelay = 1

    def __init__(self, *args, **kw):
        if six.PY3:  # Python 3
            kw.pop('strict', None)

        if sys.version_info < (2, 7):  # Python 2.6 and earlier
            kw.pop('source_address', None)
            self.source_address = None

        _HTTPConnection.__init__(self, *args, **kw)

    def _new_conn(self):
        """ Establish a socket connection and set nodelay settings on it

        :return: a new socket connection
        """
        extra_args = []
        if self.source_address:  # Python 2.7+
            extra_args.append(self.source_address)

        conn = socket.create_connection(
            (self.host, self.port),
            self.timeout,
            *extra_args
        )
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY,
                        self.tcp_nodelay)
        return conn

    def _prepare_conn(self, conn):
        self.sock = conn
        if self._tunnel_host:
            # TODO: Fix tunnel so it doesn't depend on self.sock state.
            self._tunnel()

    def connect(self):
        conn = self._new_conn()
        self._prepare_conn(conn)


class HTTPSConnection(HTTPConnection):
    default_port = port_by_scheme['https']

    def __init__(self, host, port=None, key_file=None, cert_file=None,
                 strict=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                 source_address=None, ssl=base_ssl):

        HTTPConnection.__init__(self, host, port,
                                strict=strict,
                                timeout=timeout,
                                source_address=source_address)

        self.key_file = key_file
        self.cert_file = cert_file

        self._ssl = ssl

        # Required property for Google AppEngine 1.9.0 which otherwise causes
        # HTTPS requests to go out as HTTP. (See Issue #356)
        self._protocol = 'https'

    def connect(self):
        conn = self._new_conn()
        self._prepare_conn(conn)
        self.sock = self._ssl.wrap_socket(conn, self.key_file, self.cert_file)


class VerifiedHTTPSConnection(HTTPSConnection):
    """
    Based on httplib.HTTPSConnection but wraps the socket with
    SSL certification.
    """
    cert_reqs = None
    ca_certs = None
    ssl_version = None

    def set_cert(self, key_file=None, cert_file=None,
                 cert_reqs=None, ca_certs=None,
                 assert_hostname=None, assert_fingerprint=None):

        self.key_file = key_file
        self.cert_file = cert_file
        self.cert_reqs = cert_reqs
        self.ca_certs = ca_certs
        self.assert_hostname = assert_hostname
        self.assert_fingerprint = assert_fingerprint

    def connect(self):
        # Add certificate verification
        try:
            sock = socket.create_connection(
                address=(self.host, self.port),
                timeout=self.timeout,
            )
        except SocketTimeout:
            raise ConnectTimeoutError(
                self, "Connection to %s timed out. (connect timeout=%s)" %
                (self.host, self.timeout))

        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY,
                        self.tcp_nodelay)

        resolved_cert_reqs = resolve_cert_reqs(self._ssl, self.cert_reqs)
        resolved_ssl_version = resolve_ssl_version(self._ssl, self.ssl_version)

        # the _tunnel_host attribute was added in python 2.6.3 (via
        # http://hg.python.org/cpython/rev/0f57b30a152f) so pythons 2.6(0-2) do
        # not have them.
        if getattr(self, '_tunnel_host', None):
            self.sock = sock
            # Calls self._set_hostport(), so self.host is
            # self._tunnel_host below.
            self._tunnel()

        # Wrap socket using verification with the root certs in
        # trusted_root_certs
        self.sock = ssl_wrap_socket(self._ssl, sock, self.key_file,
                                    self.cert_file,
                                    cert_reqs=resolved_cert_reqs,
                                    ca_certs=self.ca_certs,
                                    server_hostname=self.host,
                                    ssl_version=resolved_ssl_version)

        if resolved_cert_reqs != self._ssl.CERT_NONE:
            if self.assert_fingerprint:
                assert_fingerprint(self.sock.getpeercert(binary_form=True),
                                   self.assert_fingerprint)
            elif self.assert_hostname is not False:
                # If the current SSL implementation doesn't provide
                # match_hostname(), use backports.ssl's.
                match_hostname = getattr(self._ssl, 'match_hostname', backports_ssl.match_hostname)
                match_hostname(self.sock.getpeercert(),
                               self.assert_hostname or self.host)


# Make a copy for testing.
UnverifiedHTTPSConnection = HTTPSConnection
HTTPSConnection = VerifiedHTTPSConnection
