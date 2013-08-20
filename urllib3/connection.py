# urllib3/connectionpool.py
# Copyright 2008-2012 Andrey Petrov and contributors (see CONTRIBUTORS.txt)
#
# This module is part of urllib3 and is released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php

import socket
from socket import timeout as SocketTimeout

try:  # Python 3
    from http.client import HTTPConnection as _HTTPConnection
except ImportError:
    from httplib import HTTPConnection as _HTTPConnection

try:  # Compiled with SSL?
    _HTTPSConnection = object
    BaseSSLError = None
    ssl = None

    try:  # Python 3
        from http.client import HTTPSConnection as _HTTPSConnection
    except ImportError:
        from httplib import HTTPSConnection as _HTTPSConnection

    import ssl
    BaseSSLError = ssl.SSLError

except (ImportError, AttributeError):  # Platform-specific: No SSL.
    pass

from .util import ssl_wrap_socket
from .util import resolve_cert_reqs, resolve_ssl_version
from .packages.ssl_match_hostname import match_hostname
from .exceptions import InnerConnectionTimeoutError

## Connection objects (extension of httplib)


class HTTPConnection(_HTTPConnection):
    """
    Based on httplib.HTTPConnection but has differents timeouts
    for connection time and operation (waiting for actual reply)
    also throws different exceptions in those two cases.
    """

    def __init__(self, host, port=None, strict=None,
                 timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                 connect_timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                 source_address=None):

        _HTTPConnection.__init__(self, host, port=port, strict=strict, timeout=timeout)
        self.source_address = source_address
        self.connect_timeout = connect_timeout

    def connect(self):
        """Connect to the host and port specified in __init__ with connect_timeout instead of timeout."""
        try:
            self.sock = socket.create_connection((self.host, self.port), self.connect_timeout)
        except SocketTimeout:
            raise InnerConnectionTimeoutError()

        if self.timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
            self.sock.settimeout(socket.getdefaulttimeout())
        else:
            self.sock.settimeout(self.timeout)

HTTPSConnection = object

if ssl:
    class HTTPSConnection(_HTTPSConnection):
        """
        Based on httplib.HTTPConnection but has differents timeouts
        for connection time and operation (waiting for actual reply)
        also throws different exceptions in those two cases.
        """

        def __init__(self, host, port=None, key_file=None,
                     cert_file=None, strict=None,
                     timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                     connect_timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                     source_address=None):

            _HTTPSConnection.__init__(self, host, port=port, key_file=key_file, cert_file=cert_file,
                                      strict=strict, timeout=timeout)
            self.source_address = source_address
            self.connect_timeout = connect_timeout

        def connect(self):
            """Connect to the host and port specified in __init__ with connect_timeout instead of timeout."""
            try:
                sock = socket.create_connection((self.host, self.port), self.connect_timeout, self.source_address)
            except SocketTimeout:
                raise InnerConnectionTimeoutError()

            if self.timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(socket.getdefaulttimeout())
            else:
                sock.settimeout(self.timeout)

            if self._tunnel_host:
                self.sock = sock
                self._tunnel()
            self.sock = ssl.wrap_socket(sock, self.key_file, self.cert_file)

    class VerifiedHTTPSConnection(HTTPSConnection):
        """
        Based on httplib.HTTPSConnection but wraps the socket with
        SSL certification.
        """
        cert_reqs = None
        ca_certs = None
        ssl_version = None

        def __init__(self, host, port=None, key_file=None, cert_file=None,
                     strict=None,
                     timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                     connect_timeout=socket._GLOBAL_DEFAULT_TIMEOUT):

            HTTPSConnection.__init__(self, host, port=port, key_file=key_file,
                                     cert_file=cert_file, strict=strict,
                                     timeout=timeout, connect_timeout=connect_timeout)
            self.connect_timeout = connect_timeout

        def set_cert(self, key_file=None, cert_file=None,
                     cert_reqs=None, ca_certs=None):

            self.key_file = key_file
            self.cert_file = cert_file
            self.cert_reqs = cert_reqs
            self.ca_certs = ca_certs

        def connect(self):
            # Add certificate verification
            try:
                sock = socket.create_connection((self.host, self.port), self.connect_timeout)
            except SocketTimeout, err:
                raise InnerConnectionTimeoutError()

            if self.timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(socket.getdefaulttimeout())
            else:
                sock.settimeout(self.timeout)

            if self._tunnel_host:
                self.sock = sock
                self._tunnel()

            resolved_cert_reqs = resolve_cert_reqs(self.cert_reqs)
            resolved_ssl_version = resolve_ssl_version(self.ssl_version)

            # Wrap socket using verification with the root certs in
            # trusted_root_certs
            self.sock = ssl_wrap_socket(sock, self.key_file, self.cert_file,
                                        cert_reqs=resolved_cert_reqs,
                                        ca_certs=self.ca_certs,
                                        server_hostname=self.host,
                                        ssl_version=resolved_ssl_version)

            if resolved_cert_reqs != ssl.CERT_NONE:
                match_hostname(self.sock.getpeercert(), self.host)
