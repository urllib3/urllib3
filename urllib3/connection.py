# urllib3/connection.py
# Copyright 2008-2013 Andrey Petrov and contributors (see CONTRIBUTORS.txt)
#
# This module is part of urllib3 and is released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php

# This class contains connection objects as extensions of the connection objects in
# httplib.py. Generally they have to be overridden to set custom timeouts

import socket
from socket import error as SocketError, timeout as SocketTimeout

from .exceptions import ConnectTimeoutError, ProxyError
from .packages.ssl_match_hostname import match_hostname
from .util import (
    assert_fingerprint,
    DEFAULT_TIMEOUT,
    resolve_cert_reqs,
    resolve_ssl_version,
    ssl_wrap_socket,
    Timeout,
)

try: # Python 3
    from http.client import HTTPConnection as _HTTPConnection
    from http.client import HTTPS_PORT
except ImportError:
    from httplib import HTTPConnection as _HTTPConnection
    from httplib import HTTPS_PORT

try: # Compiled with SSL?

    class BaseSSLError(BaseException):
        pass

    ssl = None

    import ssl
    BaseSSLError = ssl.SSLError

except (ImportError, AttributeError): # Platform-specific: No SSL.
    pass


class HTTPConnection(_HTTPConnection):
    """ A :class:`httplib.HTTPConnection` that supports connection timeouts

    It would be nice not to have to override this class, however the default
    httplib.py does not allow setting separate connection and request timeouts,
    see http://hg.python.org/cpython/file/2.7/Lib/httplib.py#l769

    The behavior of this class and httplib.py should differ mainly in the
    connection timeout setting.
    """

    def __init__(self, host, port=None, strict=None, timeout=DEFAULT_TIMEOUT,
                 source_address=None):
        """ Create a new HTTPConnection.

        This function is necessary to set our connect timeout value, otherwise
        the interface should mirror the HTTPConnection.__init__ interface in
        httplib.py
        """

        # source_address only added to httplib in python 2.7 - move this into
        # the __init__ call below if python2.6 support is dropped.
        self.source_address = source_address

        if isinstance(timeout, Timeout):
            # Call our timeout value enhanced_timeout to avoid type/assignment
            # errors with the parent class
            self.enhanced_timeout = timeout.clone()
            HTTPConnection.__init__(self, host, port=port, strict=strict,
                                    timeout=timeout.request)
        else:
            # This branch is for backwards compatibility, can be removed later
            self.enhanced_timeout = Timeout.from_legacy(timeout)
            HTTPConnection.__init__(self, host, port=port, strict=strict,
                                    timeout=timeout)

    def connect(self):
        """Connect to the host and port specified in __init__.

        This should mirror the implementation in httplib except to insert our
        connect timeout, instead of the global timeout attribute specified by
        :class:`httplib.HTTPConnection`, and then set the timeout on the socket
        to the new request timeout.
        """
        try:
            self.enhanced_timeout.start()
            try:
                self.sock = socket.create_connection(
                    address=(self.host, self.port),
                    timeout=self.enhanced_timeout.connect_timeout,
                    source_address=self.source_address)
            except TypeError: # Python 2.6
                self.sock = socket.create_connection(
                    address=(self.host, self.port),
                    timeout=self.enhanced_timeout.connect_timeout)
            self.enhanced_timeout.stop()
        except SocketTimeout:
            raise ConnectTimeoutError(
                self, "Connection to %s timed out. (connect timeout=%s)" %
                (self.host, self.enhanced_timeout.connect))

        try:
            # After the connection is established, set the timeout on the socket
            # to the request timeout
            self.sock.settimeout(self.enhanced_timeout.request_timeout)
        except (TypeError, ValueError):
            # the DEFAULT_TIMEOUT can be an object, which means setting the
            # timeout fails. in this case we did not mean to set the timeout to
            # a specific value and we pass.
            # If request_timeout is negative a ValueError is raised, ignore this
            pass

        if self._tunnel_host:
            self._tunnel()


class HTTPSConnection(HTTPConnection):
    """ Like a :class:`httplib.HTTPSConnection`, but allowing the user to set
    the timeout to a :class:`urllib.util.Timeout` object

    :param timeout:
        Socket timeout in seconds for each individual connection. This can
        be a float or integer , which sets the timeout for the HTTP request,
        or an instance of :class:`urllib3.util.Timeout` which gives you more
        fine-grained control over request timeouts.
    """
    default_port = HTTPS_PORT

    def __init__(self, host, port=None, key_file=None, cert_file=None,
                 strict=None, timeout=DEFAULT_TIMEOUT, source_address=None):
        HTTPConnection.__init__(self, host, port, strict, timeout,
                                source_address)
        self.key_file = key_file
        self.cert_file = cert_file

    def connect(self):
        """Connect to a host on a given (SSL) port."""
        try:
            self.enhanced_timeout.start()
            try:
                sock = socket.create_connection(
                    address=(self.host, self.port),
                    timeout=self.enhanced_timeout.connect_timeout,
                    source_address=self.source_address)
            except TypeError: # Python 2.6
                sock = socket.create_connection(
                    address=(self.host, self.port),
                    timeout=self.enhanced_timeout.connect_timeout)
            self.enhanced_timeout.stop()
        except SocketTimeout:
            raise ConnectTimeoutError(
                self, "Connection to %s timed out. (connect timeout=%s)" %
                (self.host, self.enhanced_timeout.connect))

        try:
            # We've connected, so set the timeout on the socket to the request
            # timeout
            sock.settimeout(self.enhanced_timeout.request_timeout)
        except (TypeError, ValueError):
            # the _DEFAULT_TIMEOUT can be an object, which means setting the
            # timeout fails. in this case we did not mean to set the timeout to
            # a specific value and we pass.
            # If request_timeout is negative a ValueError is raised, ignore this
            pass

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
            self.enhanced_timeout.start()
            try:
                sock = socket.create_connection(
                    address=(self.host, self.port),
                    timeout=self.enhanced_timeout.connect_timeout,
                    source_address=self.source_address)
            except TypeError: # Python 2.6
                sock = socket.create_connection(
                    address=(self.host, self.port),
                    timeout=self.enhanced_timeout.connect_timeout)
            self.enhanced_timeout.stop()
        except SocketError as e:
            if 'timed out' in str(e):
                raise ConnectTimeoutError(
                    self, "Connection to %s timed out. (connect timeout=%s)" %
                    (self.host, self.enhanced_timeout.connect))
            # XXX is this the correct error to raise in this case?
            raise ProxyError('Cannot connect to proxy. Socket error: %s.' % e)

        try:
            # We've connected, so set the timeout on the socket to the request
            # timeout
            sock.settimeout(self.enhanced_timeout.request_timeout)
        except (TypeError, ValueError):
            # the _DEFAULT_TIMEOUT can be an object, which means setting the
            # timeout fails. in this case we did not mean to set the timeout to
            # a specific value and we pass.
            # If request_timeout is negative a ValueError is raised, ignore this
            pass

        resolved_cert_reqs = resolve_cert_reqs(self.cert_reqs)
        resolved_ssl_version = resolve_ssl_version(self.ssl_version)

        if self._tunnel_host:
            self.sock = sock
            # Calls self._set_hostport(), so self.host is
            # self._tunnel_host below.
            self._tunnel()

        # Wrap socket using verification with the root certs in
        # trusted_root_certs
        self.sock = ssl_wrap_socket(sock, self.key_file, self.cert_file,
                                    cert_reqs=resolved_cert_reqs,
                                    ca_certs=self.ca_certs,
                                    server_hostname=self.host,
                                    ssl_version=resolved_ssl_version)

        if resolved_cert_reqs != ssl.CERT_NONE:
            if self.assert_fingerprint:
                assert_fingerprint(self.sock.getpeercert(binary_form=True),
                                   self.assert_fingerprint)
            elif self.assert_hostname is not False:
                match_hostname(self.sock.getpeercert(),
                               self.assert_hostname or self.host)

