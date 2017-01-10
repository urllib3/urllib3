# -*- coding: utf-8 -*-
"""
This module implements the synchronous connection management logic.

Unlike in http.client, the connection here is an object that is responsible
for a very small number of tasks:

    1. Serializing/deserializing data to/from the network.
    2. Being able to do basic parsing of HTTP and maintaining the framing.
    3. Understanding connection state.

This object knows very little about the semantics of HTTP in terms of how to
construct HTTP requests and responses. It mostly manages the socket itself.
"""
from __future__ import absolute_import

import collections
import io
import itertools
import socket
import ssl
import warnings

import h11

from .base import Response
from .exceptions import (
    ConnectTimeoutError, NewConnectionError, SubjectAltNameWarning
)
from .packages import six
from .util import selectors, connection, ssl_ as ssl_util


def _read_readable(readable):
    # TODO: reconsider this block size
    blocksize = 8192
    # TODO: is this acceptable? Is it too optimistic?
    encode = isinstance(readable, io.TextIOBase)
    while True:
        datablock = readable.read(blocksize)
        if not datablock:
            break
        if encode:
            datablock = datablock.encode("utf-8")
        yield datablock


def _make_body_iterable(body):
    """
    This function turns all possible body types that urllib3 supports into an
    iterable of bytes. The goal is to expose a uniform structure to request
    bodies so that they all appear to be identical to the low-level code.

    The basic logic here is:
        - byte strings are turned into single-element lists
        - unicode strings are encoded and turned into single-element lists
        - readables are wrapped in an iterable that repeatedly calls read until
          nothing is returned anymore
        - other iterables are used directly
        - anything else is not acceptable
    """
    if isinstance(body, six.binary_type):
        return [body]
    elif isinstance(body, six.text_type):
        # TODO: Consider raising warnings on auto-encode?
        body = body.encode('utf-8')
        return [body]
    elif hasattr(body, "read"):
        return _read_readable(body)
    elif isinstance(body, collections.Iterable):
        # TODO: Should we wrap this in an iterable that auto-encodes text?
        return body
    else:
        # TODO: Better exception.
        raise RuntimeError("Unacceptable body type")


def _request_to_bytes(request, state_machine):
    """
    Returns the request header bytes for sending.
    """
    h11_request = h11.Request(
        method=request.method,
        target=request.target,
        headers=request.headers
    )
    return state_machine.send(h11_request)


def _body_bytes(request, state_machine):
    """
    An iterable that serialises a set of bytes for the body.
    """
    iterable_body = _make_body_iterable(request.body)

    for chunk in iterable_body:
        yield state_machine.send(h11.Data(chunk))

    yield state_machine.send(h11.EndOfMessage())


def _maybe_read_response(data, state_machine):
    """
    Feeds some more data into the state machine and potentially returns a
    response object.
    """
    response = None
    event = None
    state_machine.receive_data(data)

    while event is not h11.NEED_DATA:
        event = state_machine.next_event()
        if isinstance(event, h11.Response):
            response = event
            break

    return response


_DEFAULT_SOCKET_OPTIONS = object()


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
    #: Disable Nagle's algorithm by default.
    #: ``[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]``
    default_socket_options = [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]

    def __init__(self, host, port, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                 socket_options=_DEFAULT_SOCKET_OPTIONS, source_address=None,
                 tunnel_host=None, tunnel_port=None, tunnel_headers=None):
        self.is_verified = False

        self._host = host
        self._port = port
        self._timeout = timeout
        self._socket_options = (
            socket_options if socket_options is not _DEFAULT_SOCKET_OPTIONS
            else self.default_socket_options
        )
        self._source_address = source_address
        self._tunnel_host = tunnel_host
        self._tunnel_port = tunnel_port
        self._tunnel_headers = tunnel_headers
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

    def _send_unless_readable(self, data):
        """
        This method sends the data in ``data`` on the given socket. It will
        abort early if the socket became readable for any reason.

        If the socket became readable, this returns True. Otherwise, returns
        False.
        """
        # We take a memoryview here because if the chunk is very large we're
        # going to slice it a few times, and we'd like to avoid doing copies as
        # we do that.
        chunk = memoryview(data)

        while chunk:
            events = self._selector.select()[0][1]  # TODO: timeout!

            # If the socket is readable, we stop uploading.
            if events & selectors.EVENT_READ:
                return True
            assert events & selectors.EVENT_WRITE

            chunk_sent = self._sock.send(chunk)
            chunk = chunk[chunk_sent:]

        return False

    def _receive_bytes(self):
        """
        This method blocks until the socket is readable or the read times out
        (TODO), and then returns whatever data was read. Signals EOF the same
        way ``recv`` does: by returning the empty string.
        """
        events = self._selector.select()[0][1]  # TODO: timeout!
        assert events == selectors.EVENT_READ
        data = self._sock.recv(65536)
        return data

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

        # Now that the connection is created, we want to set the socket to
        # non-blocking mode. We're going to select on it for the rest of its
        # lifetime, so we need it non-blocking. We also register it with our
        # selector to allow us to assume that it is *always* registered.
        conn.setblocking(0)
        self._sock = conn
        self._selector.register(
            self._sock, selectors.EVENT_READ | selectors.EVENT_WRITE
        )

    def send_request(self, request):
        """
        Sends a single Request object. Returns a Response.
        """
        # Before we begin, confirm that the state machine is ok.
        assert self._state_machine.our_state is h11.IDLE
        assert self._state_machine.their_state is h11.IDLE

        # First, register the socket with the selector. We want to look for
        # readability *and* writability, because if the socket suddenly becomes
        # readable we need to stop our upload immediately.
        self._selector.modify(
            self._sock, selectors.EVENT_READ | selectors.EVENT_WRITE
        )
        header_bytes = _request_to_bytes(request, self._state_machine)
        body_chunks = _body_bytes(request, self._state_machine)
        request_chunks = itertools.chain([header_bytes], body_chunks)

        for chunk in request_chunks:
            # If the socket becomes readable we don't need to error out or
            # anything: we can just continue with our current logic.
            readable = self._send_unless_readable(chunk)
            if readable:
                break

        # At this point we no longer care if the socket is writable.
        self._selector.modify(self._sock, selectors.EVENT_READ)

        response = None
        while response is None:
            read_bytes = self._receive_bytes()
            response = _maybe_read_response(read_bytes, self._state_machine)

        version = b'HTTP/' + response.version
        our_response = Response(
            status_code=response.status_code,
            headers=response.headers,
            body=self,
            version=version
        )
        return our_response

    def close(self):
        """
        Close this connection, suitable for being re-added to a connection
        pool.
        """
        if self._sock is not None:
            sock, self._sock = self._sock, None
            sock.setblocking(1)
            sock.close()

        if self._selector is not None:
            selector, self._selector = self._selector, None
            selector.close()

        self._state_machine = None

    def _reset(self):
        """
        Called once we hit EndOfMessage, and checks whether we can re-use this
        state machine and connection or not, and if not, closes the socket and
        state machine.

        This method is safe to call multiple times.
        """
        # The logic here is as follows. Once we've got EndOfMessage, only two
        # things can be true. Either a) the connection is suitable for
        # connection re-use per RFC 7230, or b) it is not. h11 signals this
        # difference by what happens when you call `next_event()`.
        #
        # If the connection is safe to re-use, when we call `next_event()`
        # we'll get back a h11.NEED_DATA and the state machine will be reset to
        # (IDLE, IDLE). If it's not, we'll get either ConnectionClosed or we'll
        # find that our state is MUST_CLOSE, and then we should close the
        # connection accordingly.
        event = self._state_machine.next_event()
        our_state = self._state_machine.our_state
        their_state = self._state_machine.their_state
        must_close = (
            event is not h11.NEED_DATA or
            our_state is not h11.IDLE or
            their_state is not h11.IDLE
        )
        if must_close:
            self.close()

    def __iter__(self):
        return self

    def next(self):
        """
        Iterate over the body bytes of the response until end of message.
        """
        data = None

        while data is None:
            event = self._state_machine.next_event()
            if event is h11.NEED_DATA:
                received_bytes = self._receive_bytes()
                self._state_machine.receive_data(received_bytes)
            elif isinstance(event, h11.Data):
                data = event.data
            elif isinstance(event, h11.EndOfMessage):
                self._reset()
                raise StopIteration()

        return data

    __next__ = next
