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
import datetime
import io
import itertools
import socket
import warnings

import h11

from .base import Response
from .exceptions import (
    ConnectTimeoutError, NewConnectionError, SubjectAltNameWarning,
    SystemTimeWarning, BadVersionError, FailedTunnelError
)
from .packages import six
from .util import selectors, connection, ssl_ as ssl_util

try:
    import ssl
except ImportError:
    ssl = None


# When updating RECENT_DATE, move it to
# within two years of the current date, and no
# earlier than 6 months ago.
RECENT_DATE = datetime.date(2016, 1, 1)

_SUPPORTED_VERSIONS = frozenset([b'1.0', b'1.1'])


def _headers_to_native_string(headers):
    """
    A temporary shim to convert received headers to native strings, to match
    the behaviour of httplib. We will reconsider this later in the process.
    """
    # TODO: revisit.
    # This works because fundamentally we know that all headers coming from
    # h11 are bytes, so if they aren't of type `str` then we must be on Python
    # 3 and need to decode the headers using Latin1.
    for n, v in headers:
        if not isinstance(n, str):
            n = n.decode('latin1')
        if not isinstance(v, str):
            v = v.decode('latin1')
        yield (n, v)


def _stringify_headers(headers):
    """
    A generator that transforms headers so they're suitable for sending by h11.
    """
    # TODO: revisit
    for name, value in headers:
        if isinstance(name, six.text_type):
            name = name.encode('ascii')

        if isinstance(value, six.text_type):
            value = value.encode('latin-1')
        elif isinstance(value, int):
            value = str(value).encode('ascii')

        yield (name, value)


def _read_readable(readable):
    # TODO: reconsider this block size
    blocksize = 8192
    while True:
        datablock = readable.read(blocksize)
        if not datablock:
            break
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
    if body is None:
        return []
    elif isinstance(body, six.binary_type):
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
        headers=_stringify_headers(request.headers.items())
    )
    return state_machine.send(h11_request)


def _body_bytes(request, state_machine):
    """
    An iterable that serialises a set of bytes for the body.
    """
    iterable_body = _make_body_iterable(request.body)

    for chunk in iterable_body:
        yield state_machine.send(h11.Data(data=chunk))

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

    def __init__(self, host, port, socket_options=_DEFAULT_SOCKET_OPTIONS,
                 source_address=None, tunnel_host=None, tunnel_port=None,
                 tunnel_headers=None):
        self.is_verified = False

        self._host = host
        self._port = port
        self._read_timeout = None
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

    def _wrap_socket(self, conn, ssl_context, fingerprint, assert_hostname):
        """
        Handles extra logic to wrap the socket in TLS magic.
        """
        is_time_off = datetime.date.today() < RECENT_DATE
        if is_time_off:
            warnings.warn((
                'System time is way off (before {0}). This will probably '
                'lead to SSL verification errors').format(RECENT_DATE),
                SystemTimeWarning
            )

        conn = ssl_util.ssl_wrap_socket(
            conn, server_hostname=self._host, ssl_context=ssl_context
        )

        if fingerprint:
            ssl_util.assert_fingerprint(conn.getpeercert(binary_form=True),
                                        fingerprint)

        elif (ssl_context.verify_mode != ssl.CERT_NONE
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
            check_host = assert_hostname or self._tunnel_host or self._host
            ssl_util.match_hostname(cert, check_host)

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

    def _receive_bytes(self, read_timeout):
        """
        This method blocks until the socket is readable or the read times out
        (TODO), and then returns whatever data was read. Signals EOF the same
        way ``recv`` does: by returning the empty string.
        """
        keys = self._selector.select(read_timeout)
        if not keys:
            # TODO: Raise our own timeouts later.
            raise socket.timeout()
        events = keys[0][1]
        assert events == selectors.EVENT_READ
        data = self._sock.recv(65536)
        return data

    def _tunnel(self, conn):
        """
        This method establishes a CONNECT tunnel shortly after connection.
        """
        # Basic sanity check that _tunnel is only called at appropriate times.
        assert self._state_machine.our_state is h11.IDLE

        target = "%s:%d" % (self._tunnel_host, self._tunnel_port)
        if not isinstance(target, bytes):
            target = target.encode('latin1')

        # We need to set the Host header.
        headers = dict(self._tunnel_headers.items())
        if b"host" not in frozenset(k.lower() for k in headers):
            headers[b"host"] = target

        tunnel_state_machine = h11.Connection(our_role=h11.CLIENT)
        request = h11.Request(
            method=b"CONNECT",
            target=target,
            headers=headers.items(),
        )
        bytes_to_send = tunnel_state_machine.send(request)
        bytes_to_send += tunnel_state_machine.send(h11.EndOfMessage())

        # First, register the socket with the selector. We want to look for
        # readability *and* writability, because if the socket suddenly becomes
        # readable we need to stop our upload immediately. Then, send the
        # request.
        # Because this method is called before we have fully set the connection
        # up, we need to briefly register the socket with the connection.
        conn.setblocking(0)
        self._sock = conn
        self._selector.register(
            self._sock, selectors.EVENT_READ | selectors.EVENT_WRITE
        )
        self._send_unless_readable(bytes_to_send)

        # At this point we no longer care if the socket is writable.
        self._selector.modify(self._sock, selectors.EVENT_READ)

        response = None
        while response is None:
            # TODO: Add a timeout here.
            # TODO: Error handling.
            read_bytes = self._receive_bytes(read_timeout=None)
            response = _maybe_read_response(read_bytes, tunnel_state_machine)

        if response.status_code != 200:
            # TODO: This is duplicate code
            version = b'HTTP/' + response.http_version
            response = Response(
                status_code=response.status_code,
                headers=_headers_to_native_string(response.headers),
                body=self,
                version=version
            )
            self.close()
            raise FailedTunnelError(
                "Unable to establish CONNECT tunnel", response
            )

        # Re-establish our green state so that we can do TLS handshake if we
        # need to.
        self._selector.unregister(self._sock)
        self._sock = None
        conn.setblocking(1)

    def _do_socket_connect(self, connect_timeout, connect_kw):
        """
        A low-level method that does the actual socket connection. This is
        factored out from inside connect() to allow for easier overriding by
        sublasses (like SOCKS).
        """
        try:
            conn = connection.create_connection(
                (self._host, self._port), connect_timeout, **connect_kw)

        except socket.timeout:
            raise ConnectTimeoutError(
                self, "Connection to %s timed out. (connect timeout=%s)" %
                (self._host, connect_timeout))

        except socket.error as e:
            raise NewConnectionError(
                self, "Failed to establish a new connection: %s" % e)

        return conn

    def connect(self, ssl_context=None,
                fingerprint=None, assert_hostname=None, connect_timeout=None):
        """
        Connect this socket to the server, applying the source address, any
        relevant socket options, and the relevant connection timeout.
        """
        if self._sock is not None:
            # We're already connected, move on.
            return

        self._state_machine = h11.Connection(our_role=h11.CLIENT)
        self._selector = selectors.DefaultSelector()

        extra_kw = {}
        if self._source_address:
            extra_kw['source_address'] = self._source_address

        if self._socket_options:
            extra_kw['socket_options'] = self._socket_options

        conn = self._do_socket_connect(connect_timeout, extra_kw)

        if ssl_context is not None:
            if self._tunnel_host is not None:
                self._tunnel(conn)

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

    def send_request(self, request, read_timeout):
        """
        Sends a single Request object. Returns a Response.
        """
        # TODO: Replace read_timeout with something smarter.
        self._read_timeout = read_timeout

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
            read_bytes = self._receive_bytes(read_timeout)
            response = _maybe_read_response(read_bytes, self._state_machine)

        if response.http_version not in _SUPPORTED_VERSIONS:
            raise BadVersionError(response.http_version)

        version = b'HTTP/' + response.http_version
        our_response = Response(
            status_code=response.status_code,
            headers=_headers_to_native_string(response.headers),
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
        continue_states = (h11.IDLE, h11.DONE)
        event = self._state_machine.next_event()
        our_state = self._state_machine.our_state
        their_state = self._state_machine.their_state
        must_close = (
            event is not h11.NEED_DATA or
            our_state not in continue_states or
            their_state not in continue_states
        )
        if must_close:
            self.close()
        elif our_state is h11.DONE and their_state is h11.DONE:
            self._state_machine.start_next_cycle()

    @property
    def complete(self):
        """
        Returns True if this connection should be returned to the pool: False
        otherwise.
        """
        if self._state_machine is None:
            return True

        our_state = self._state_machine.our_state
        their_state = self._state_machine.their_state

        return (our_state is h11.IDLE and their_state is h11.IDLE)

    def __iter__(self):
        return self

    def next(self):
        """
        Iterate over the body bytes of the response until end of message.
        """
        if self._state_machine is None:
            raise StopIteration()

        data = None

        while data is None:
            event = self._state_machine.next_event()
            if event is h11.NEED_DATA:
                received_bytes = self._receive_bytes(self._read_timeout)
                self._state_machine.receive_data(received_bytes)
            elif isinstance(event, h11.Data):
                data = event.data
            elif isinstance(event, h11.EndOfMessage):
                self._reset()
                raise StopIteration()

        return data

    __next__ = next
