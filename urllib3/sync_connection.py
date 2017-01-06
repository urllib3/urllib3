"""
This module implements the synchronous connection management logic.

Unlike in http.client, the connection here is an object that is responsible
for a very small number of tasks:

    1. Serializing/deserializing data to/from the netwwork.
    2. Being able to do basic parsing of HTTP and maintaining the framing.
    3. Understanding connection state.

This object knows very little about the semantics of HTTP in terms of how to
construct HTTP requests and responses. It mostly manages the socket itself.
"""
from __future__ import absolute_import

from .exceptions import (
    ConnectTimeoutError, NewConnectionError, SubjectAltNameWarning
)
from .util import selectors, connection, ssl_ as ssl_util

import socket
import ssl
import warnings

import h11


def _request_to_bytes(request, state_machine):
    """
    Returns the request header bytes for sending.
    """
    pass


def _body_bytes(body_chunk, state_machine):
    """
    An iterable that serialises a set of bytes for the body.
    """
    pass


class SyncHTTP1Connection(object):
    """
    A synchronous wrapper around a single HTTP/1.1 connection.

    This wrapper manages connection state, ensuring that connections are
    appropriately managed throughout the lifetime of a HTTP transaction. In
    particular, this object understands the conditions in which connections
    should be torn down, and also manages sending data and handling early
    responses.

    This object can be iterated over to return the response body. When iterated
    over it will return all of the data that is currently buffered, and if no
    data is buffered it will issue one read syscall and return all of that
    data. Buffering of response data must happen at a higher layer.
    """
    def __init__(self, host, port, timeout, socket_options, source_address,
                 tunnel_host, tunnel_port):
        self.is_verified = False

        self._host = host
        self._port = port
        self._timeout = timeout
        self._socket_options = socket_options
        self._source_address = source_address
        self._tunnel_host = tunnel_host
        self._tunnel_port = tunnel_port
        self._sock = None
        self._state_machine = None
        self._selector = None

        # If we need to tunnel through a CONNECT proxy, we need an extra state
        # machine to manage the "outer" HTTP connection. We only use this to
        # set up the connection: once it is set up, we throw this away.
        self._tunnel_state_machine = None

    def _wrap_socket(self, conn, ssl_context, fingerprint, assert_hostname):
        """
        Handles extra logic to wrap the socket in TLS magic.
        """
        conn = ssl_util.ssl_wrap_socket(
            conn, server_hostname=self._host, ssl_context=ssl_context
        )

        if fingerprint:
            ssl_util.assert_fingerprint(conn.getpeercert(binary_form=True),
                                        fingerprint)

        if (ssl_context.verify_mode != ssl.CERT_NONE
            and assert_hostname is not False):
            cert = conn.getpeercert()
            if not cert.get('subjectAltName', ()):
                warnings.warn((
                    'Certificate for {0} has no `subjectAltName`, falling '
                    'back to check for a `commonName` for now. This '
                    'feature is being removed by major browsers and '
                    'deprecated by RFC 2818. (See '
                    'https://github.com/shazow/urllib3/issues/497 for '
                    'details.)'.format(self._host)),
                    SubjectAltNameWarning
                )
            ssl_util.match_hostname(cert, assert_hostname or self._host)

        self.is_verified = (
            ssl_context.verify_mode == ssl.CERT_REQUIRED and
            (assert_hostname is not False or fingerprint)
        )

        return conn

    def connect(self, ssl_context=None,
                fingerprint=None, assert_hostname=None):
        """
        Connect this socket to the server, applying the source address, any
        relevant socket options, and the relevant connection timeout.
        """
        self._state_machine = h11.Connection(our_role=h11.CLIENT)
        self._selector = selectors.DefaultSelector()

        extra_kw = {}
        if self._source_address:
            extra_kw['source_address'] = self._source_address

        if self._socket_options:
            extra_kw['socket_options'] = self._socket_options

        try:
            conn = connection.create_connection(
                (self._host, self._port), self._timeout, **extra_kw)

        except socket.timeout:
            raise ConnectTimeoutError(
                self, "Connection to %s timed out. (connect timeout=%s)" %
                (self._host, self._timeout))

        except socket.error as e:
            raise NewConnectionError(
                self, "Failed to establish a new connection: %s" % e)

        if ssl_context is not None:
            conn = self._wrap_socket(
                conn, ssl_context, fingerprint, assert_hostname
            )

        self._sock = conn

    def send_request(self, request):
        """
        Sends a single Request object. Returns a Response.
        """
        header_bytes = _request_to_bytes(request, self._state_machine)
        self._send_bytes(header_bytes)

        # We want to send the body bytes for as long as there is no response
        # for us to read. If there is a response for us to read, we should
        # immediately stop upload. This isn't an error condition, so we don't
        # need to detect it.
        for chunk in _body_bytes(request, self._state_machine):
            if self.readable:
                break
            self._send_bytes(header_bytes)

        response = None
        while response is None:
            read_bytes = self._receive_bytes()
            response = _maybe_read_response(read_bytes, self._state_machine)

        return response

    def close(self):
        """
        Close this connection, suitable for being re-added to a connection
        pool.
        """
        if self._sock is not None:
            sock, self._sock = self._sock, None
            sock.close()

        if self._selector is not None:
            selector, self._selector = self._selector, None
            selector.close()

        self._state_machine = None

    @property
    def readable(self):
        """
        Returns True if the connection is readable.
        """
        # This method only works if we have one socket per selector. Otherwise
        # we're totally hosed.
        results = self._selector.select(timeout=0)
        return any(result[1] & selectors.EVENT_READ for result in results)

    def __iter__(self):
        return self

    def next(self):
        pass

    __next__ = next
