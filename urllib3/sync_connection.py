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
import socket
import warnings

import h11

from .base import Request, Response
from .exceptions import (
    ConnectTimeoutError, NewConnectionError, SubjectAltNameWarning,
    SystemTimeWarning, BadVersionError, FailedTunnelError, InvalidBodyError,
    ProtocolError, _LoopAbort
)
from .packages import six
from .util import ssl_ as ssl_util

try:
    import ssl
except ImportError:
    ssl = None


# When updating RECENT_DATE, move it to
# within two years of the current date, and no
# earlier than 6 months ago.
RECENT_DATE = datetime.date(2016, 1, 1)

_SUPPORTED_VERSIONS = frozenset([b'1.0', b'1.1'])

# A sentinel object returned when some syscalls return EAGAIN.
_EAGAIN = object()


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


# XX this should return an async iterator
def _make_body_iterable(body):
    """
    This function turns all possible body types that urllib3 supports into an
    iterable of bytes. The goal is to expose a uniform structure to request
    bodies so that they all appear to be identical to the low-level code.

    The basic logic here is:
        - byte strings are turned into single-element lists
        - readables are wrapped in an iterable that repeatedly calls read until
          nothing is returned anymore
        - other iterables are used directly
        - anything else is not acceptable

    In particular, note that we do not support *text* data of any kind. This
    is deliberate: users must make choices about the encoding of the data they
    use.
    """
    if body is None:
        return []
    elif isinstance(body, six.binary_type):
        return [body]
    elif hasattr(body, "read"):
        return _read_readable(body)
    elif isinstance(body, collections.Iterable) and not isinstance(body, six.text_type):
        return body
    else:
        raise InvalidBodyError("Unacceptable body type: %s" % type(body))


# XX this should return an async iterator
def _request_bytes_iterable(request, state_machine):
    """
    An iterable that serialises a set of bytes for the body.
    """
    h11_request = h11.Request(
        method=request.method,
        target=request.target,
        headers=_stringify_headers(request.headers.items())
    )
    yield state_machine.send(h11_request)

    for chunk in _make_body_iterable(request.body):
        yield state_machine.send(h11.Data(data=chunk))

    yield state_machine.send(h11.EndOfMessage())


def _response_from_h11(h11_response, body_object):
    """
    Given a h11 Response object, build a urllib3 response object and return it.
    """
    if h11_response.http_version not in _SUPPORTED_VERSIONS:
        raise BadVersionError(h11_response.http_version)

    version = b'HTTP/' + h11_response.http_version
    our_response = Response(
        status_code=h11_response.status_code,
        headers=_headers_to_native_string(h11_response.headers),
        body=body_object,
        version=version
    )
    return our_response


def _build_tunnel_request(host, port, headers):
    """
    Builds a urllib3 Request object that is set up correctly to request a proxy
    to establish a TCP tunnel to the remote host.
    """
    target = "%s:%d" % (host, port)
    if not isinstance(target, bytes):
        target = target.encode('latin1')

    tunnel_request = Request(
        method=b"CONNECT",
        target=target,
        headers=headers
    )
    tunnel_request.add_host(
        host=host,
        port=port,
        scheme='http'
    )
    return tunnel_request


async def _start_http_request(request, state_machine, conn):
    """
    Send the request using the given state machine and connection, wait
    for the response headers, and return them.

    If we get response headers early, then we stop sending and return
    immediately, poisoning the state machine along the way so that we know
    it can't be re-used.

    This is a standalone function because we use it both to set up both
    CONNECT requests and real requests.
    """
    # Before we begin, confirm that the state machine is ok.
    if (state_machine.our_state is not h11.IDLE or
            state_machine.their_state is not h11.IDLE):
        raise ProtocolError("Invalid internal state transition")

    request_bytes_iterable = _request_bytes_iterable(request, state_machine)

    send_aborted = True

    async def next_bytes_to_send():
        nonlocal send_aborted
        try:
            return next(request_bytes_iterable)
        except StopIteration:
            # We successfully sent the whole body!
            send_aborted = False
            return None

    h11_response = None

    def consume_bytes(data):
        nonlocal h11_response

        state_machine.receive_data(data)
        while True:
            event = state_machine.next_event()
            if event is h11.NEED_DATA:
                break
            elif isinstance(event, h11.InformationalResponse):
                # Ignore 1xx responses
                continue
            elif isinstance(event, h11.Response):
                # We have our response! Save it and get out of here.
                h11_response = event
                raise LoopAbort
            else:
                # Can't happen
                raise RuntimeError("Unexpected h11 event {}".format(event))

    await conn.send_and_receive_for_a_while(
        next_bytes_to_send, consume_bytes)
    assert h11_response is not None

    if send_aborted:
        # Our state machine thinks we sent a bunch of data... but maybe we
        # didn't! Maybe our send got cancelled while we were only half-way
        # through sending the last chunk, and then h11 thinks we sent a
        # complete request and we actually didn't. Then h11 might think we can
        # re-use this connection, even though we can't. So record this in
        # h11's state machine.
        # XX need to implement this in h11
        # state_machine.poison()
        # XX kluge for now
        state_machine._cstate.process_error(state_machine.our_role)

    return h11_response


async def _read_until_event(state_machine, conn):
    """
    A loop that keeps issuing reads and feeding the data into h11 and
    checking whether h11 has an event for us. The moment there is an event
    other than h11.NEED_DATA, this function returns that event.
    """
    while True:
        event = state_machine.next_event()
        if event is not h11.NEED_DATA:
            return event
        state_machine.receive_data(await conn.receive_some())


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

    def __init__(self, backend, host, port,
                 socket_options=_DEFAULT_SOCKET_OPTIONS,
                 source_address=None, tunnel_host=None, tunnel_port=None,
                 tunnel_headers=None):
        self.is_verified = False

        self._backend = backend
        self._host = host
        self._port = port
        self._socket_options = (
            socket_options if socket_options is not _DEFAULT_SOCKET_OPTIONS
            else self.default_socket_options
        )
        self._source_address = source_address
        self._tunnel_host = tunnel_host
        self._tunnel_port = tunnel_port
        self._tunnel_headers = tunnel_headers
        self._sock = None
        self._state_machine = h11.Connection(our_role=h11.CLIENT)

    async def _wrap_socket(self, conn, ssl_context, fingerprint, assert_hostname):
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

        conn = await conn.start_tls(self._host, ssl_context)

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

    async def send_request(self, request, read_timeout):
        """
        Given a Request object, performs the logic required to get a response.
        """
        h11_response = await _start_http_request(
            request, self._state_machine, self._sock
        )
        return _response_from_h11(h11_response, self)

    async def _tunnel(self, conn):
        """
        This method establishes a CONNECT tunnel shortly after connection.
        """
        # Basic sanity check that _tunnel is only called at appropriate times.
        assert self._state_machine.our_state is h11.IDLE

        tunnel_request = _build_tunnel_request(
            self._tunnel_host, self._tunnel_port, self._tunnel_headers
        )

        tunnel_state_machine = h11.Connection(our_role=h11.CLIENT)

        h11_response = await _start_http_request(
            tunnel_request, tunnel_state_machine, conn
        )
        # XX this is wrong -- 'self' here will try to iterate using
        # self._state_machine, not tunnel_state_machine. Also, we need to
        # think about how this failure case interacts with the pool's
        # connection lifecycle management.
        tunnel_response = _response_from_h11(h11_response, self)

        if h11_response.status_code != 200:
            conn.forceful_close()
            raise FailedTunnelError(
                "Unable to establish CONNECT tunnel", tunnel_response
            )

    async def connect(self, ssl_context=None,
                      fingerprint=None, assert_hostname=None,
                      connect_timeout=None):
        """
        Connect this socket to the server, applying the source address, any
        relevant socket options, and the relevant connection timeout.
        """
        if self._sock is not None:
            # We're already connected, move on.
            self._sock.set_readable_watch_state(False)
            return

        extra_kw = {}
        if self._source_address:
            extra_kw['source_address'] = self._source_address

        if self._socket_options:
            extra_kw['socket_options'] = self._socket_options
        # XX pass connect_timeout to backend

        # This was factored out into a separate function to allow overriding
        # by subclasses, but in the backend approach the way to to this is to
        # provide a custom backend. (Composition >> inheritance.)
        try:
            conn = await self._backend.connect(
                self._host, self._port, **extra_kw)
        # XX these two error handling blocks needs to be re-done in a
        # backend-agnostic way
        except socket.timeout:
            raise ConnectTimeoutError(
                self, "Connection to %s timed out. (connect timeout=%s)" %
                (self._host, connect_timeout))

        except socket.error as e:
            raise NewConnectionError(
                self, "Failed to establish a new connection: %s" % e)

        if ssl_context is not None:
            if self._tunnel_host is not None:
                self._tunnel(conn)

            conn = await self._wrap_socket(
                conn, ssl_context, fingerprint, assert_hostname
            )

        # XX We should pick one of these names and use it consistently...
        self._sock = conn

    def close(self):
        """
        Close this connection.
        """
        if self._sock is not None:
            # Make sure self._sock is None even if closing raises an exception
            sock, self._sock = self._sock, None
            sock.forceful_close()

    def is_dropped(self):
        """
        Returns True if the connection is closed: returns False otherwise. This
        includes closures that do not mark the FD as closed, such as when the
        remote peer has sent EOF but we haven't read it yet.

        Pre-condition: _reset must have been called.
        """
        if self._sock is None:
            return True

        # We check for droppedness by checking the socket for readability. If
        # it's not readable, it's not dropped. If it is readable, then we
        # assume that the thing we'd read from the socket is EOF. It might not
        # be, but if it's not then the server has busted its HTTP/1.1 framing
        # and so we want to drop the connection anyway.
        return self._sock.is_readable()

    def _reset(self):
        """
        Called once we hit EndOfMessage, and checks whether we can re-use this
        state machine and connection or not, and if not, closes the socket and
        state machine.
        """
        try:
            self._state_machine.start_next_cycle()
        except h11.LocalProtocolError:
            # Not re-usable
            self.close()
        else:
            # This connection can be returned to the connection pool, and
            # eventually we'll take it out again and want to know if it's been
            # dropped.
            self._sock.set_readable_watch_state(True)

    @property
    def complete(self):
        """
        XX what is this supposed to do? check if the response has been fully
        iterated over? check for that + the connection being reusable?
        """
        our_state = self._state_machine.our_state
        their_state = self._state_machine.their_state

        return (our_state is h11.IDLE and their_state is h11.IDLE)

    def __aiter__(self):
        return self

    async def __anext__(self):
        """
        Iterate over the body bytes of the response until end of message.
        """
        event = await _read_until_event(self._state_machine, self._sock)
        if isinstance(event, h11.Data):
            return bytes(event.data)
        elif isinstance(event, h11.EndOfMessage):
            self._reset()
            raise StopAsyncIteration
        else:
            # can't happen
            raise RuntimeError("Unexpected h11 event {}".format(event))
