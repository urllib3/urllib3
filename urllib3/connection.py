from __future__ import absolute_import
import datetime
import collections
import io
import logging
import os
import re
import socket
from socket import error as SocketError, timeout as SocketTimeout
import warnings
from .packages import six

import h11

try:  # Compiled with SSL?
    import ssl
    BaseSSLError = ssl.SSLError
except (ImportError, AttributeError):  # Platform-specific: No SSL.
    ssl = None

    class BaseSSLError(BaseException):
        pass


from .exceptions import (
    NewConnectionError,
    ConnectTimeoutError,
    SubjectAltNameWarning,
    SystemTimeWarning,
    BadVersionError,
    ProtocolError
)
from .packages.ssl_match_hostname import match_hostname, CertificateError

from .util.ssl_ import (
    resolve_cert_reqs,
    resolve_ssl_version,
    assert_fingerprint,
    create_urllib3_context,
    ssl_wrap_socket
)
from .util import parse_url


from .util import connection

from ._collections import HTTPHeaderDict

log = logging.getLogger(__name__)

port_by_scheme = {
    'http': 80,
    'https': 443,
}

# When updating RECENT_DATE, move it to
# within two years of the current date, and no
# earlier than 6 months ago.
RECENT_DATE = datetime.date(2016, 1, 1)

# the patterns for both name and value are more lenient than RFC
# definitions to allow for backwards compatibility
# TODO: I pulled these out of httplib: does h11 obviate them?
_is_legal_header_name = re.compile(
    r'^[^:\s][^:\r\n]*$'.encode('ascii')
).match
_is_illegal_header_value = re.compile(
    r'\n(?![ \t])|\r(?![ \t\n])'.encode('ascii')
).search


def _encode(data, name='data'):
    """Call data.encode("latin-1") but show a better error message."""
    # TODO: Do we want to do better than this?
    try:
        return data.encode("latin-1")
    except UnicodeEncodeError as err:
        raise UnicodeEncodeError(
            err.encoding,
            err.object,
            err.start,
            err.end,
            "%s (%.20r) is not valid Latin-1. Use %s.encode('utf-8') "
            "if you want to send it encoded in UTF-8." %
            (name.title(), data[err.start:err.end], name))


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


def _validate_headers(headers):
    """
    A generator that validates headers as they are iterated over and then emits
    them, one at a time. Used to apply validation to headers before sending
    them.
    """
    for name, value in headers:
        if hasattr(name, 'encode'):
            name = name.encode('ascii')

        if not _is_legal_header_name(name):
            raise ValueError('Invalid header name %r' % (name,))

        if hasattr(value, 'encode'):
            value = value.encode('latin-1')
        elif isinstance(value, int):
            value = str(value).encode('ascii')

        if _is_illegal_header_value(value):
            raise ValueError('Invalid header value %r' % (value,))

        yield (name, value)


class DummyConnection(object):
    """Used to detect a failed ConnectionCls import."""
    pass


_DEFAULT_SOCKET_OPTS = object()


# TODO: This is a holdover from httplib, do we need it?
class ResponseNotReady(Exception):
    """
    A holdover exception raised when urllib3 incorrectly asks for a response
    before it's done with the last one.
    """
    pass


class OldHTTPResponse(io.BufferedIOBase):

    # See RFC 2616 sec 19.6 and RFC 1945 sec 6 for details.

    # The bytes from the socket object are iso-8859-1 strings.
    # See RFC 2616 sec 2.2 which notes an exception for MIME-encoded
    # text following RFC 2047.  The basic status line parsing only
    # accepts iso-8859-1.

    def __init__(self, sock, state_machine, method=None, url=None):
        # If the response includes a content-length header, we need to
        # make sure that the client doesn't read more than the
        # specified number of bytes.  If it does, it will block until
        # the server times out and closes the connection.  This will
        # happen if a self.fp.read() is done (without a size) whether
        # self.fp is buffered or not.  So, no self.fp.read() by
        # clients unless they know what they are doing.
        self.fp = sock
        self._state_machine = state_machine
        self._method = method

        self._buffered_data = b''

        # The HTTPResponse object is returned via urllib.  The clients
        # of http and urllib expect different attributes for the
        # headers.  headers is used here and supports urllib.  msg is
        # provided as a backwards compatibility layer for http
        # clients.

        self.headers = self.msg = None

        # from the Status-Line of the response
        self.version = None
        self.status = None
        self.reason = None

        self.length = None          # number of bytes left in response
        self.will_close = None      # conn will close at end of response

    def _read_response(self):
        """
        Grab the response.
        """
        while True:
            data = self.fp.recv(8192)
            self._state_machine.receive_data(data)

            while True:
                event = self._state_machine.next_event()
                if event is h11.NEED_DATA:
                    break

                if isinstance(event, h11.Response):
                    return event
                elif isinstance(event, h11.ConnectionClosed):
                    raise ProtocolError(
                        "Remote end closed connection without response"
                    )
                else:
                    # TODO: better exception
                    raise RuntimeError("Unexpected event %s" % event)

    def begin(self):
        # TODO: rewrite in our own style.
        if self.headers is not None:
            # we've already started reading the response
            return

        # read until we get a non-100 response
        event = self._read_response()

        self.code = self.status = event.status_code
        self.reason = b''
        version = event.http_version
        if version in (b"1.0", b"0.9"):
            # Some servers might still return "0.9", treat it as 1.0 anyway
            self.version = 10
        elif version == b"1.1":
            self.version = 11
        else:
            raise BadVersionError(version)

        self.headers = self.msg = HTTPHeaderDict(
            _headers_to_native_string(event.headers)
        )
        connection = self.headers.get("connection", "")
        self.will_close = "close" in connection.strip()

    def _close_conn(self):
        # We need to check what we're doing. h11 will tell us if we have to
        # actually close the socket or not.
        our_state = self._state_machine.our_state
        their_state = self._state_machine.their_state

        # If both sides are at DONE, we can re-use this connection.
        # In literally any other case, we need to close the connection.
        can_reuse = (our_state is h11.DONE and their_state is h11.DONE)

        # Regardless, we want to hide the fp from this response: it's not
        # allowed to see it.
        fp, self.fp = self.fp, None

        if can_reuse:
            self._state_machine.start_next_cycle()
        else:
            fp.close()

    def close(self):
        # TODO: rewrite in our own style.
        try:
            super(OldHTTPResponse, self).close()  # set "closed" flag
        finally:
            if self.fp:
                self._close_conn()

    # These implementations are for the benefit of io.BufferedReader.

    # XXX This class should probably be revised to act more like
    # the "raw stream" that BufferedReader expects.

    def readable(self):
        """Always returns True"""
        return True

    # End of "raw stream" methods

    def isclosed(self):
        """True if the connection is closed."""
        # TODO: rewrite in our own style
        return self.fp is None

    def read(self, amt=None):
        # TODO: definitely needs a rewrite
        if self.fp is None:
            return b""

        data_out = [self._buffered_data]
        out_len = len(self._buffered_data)

        if amt is not None:
            # Amount is given
            while out_len < amt:
                event = self._state_machine.next_event()
                if event == h11.NEED_DATA:
                    data = self.fp.recv(65536)
                    self._state_machine.receive_data(data)
                    continue

                if isinstance(event, h11.Data):
                    data_out.append(bytes(event.data))
                    out_len += len(event.data)
                elif isinstance(event, h11.EndOfMessage):
                    self._close_conn()
                    break
                elif isinstance(event, h11.ConnectionClosed):
                    # TODO: better exception
                    raise ProtocolError("Connection closed early!")

            received_data = b''.join(data_out)
            data_to_return, self._buffered_data = (
                received_data[:amt], received_data[amt:]
            )
            return data_to_return
        else:
            # Amount is not given (unbounded read)
            # TODO: this loop is *basically* identical to the one above it.
            # we should really try to refactor to remove the duplication.
            while True:
                event = self._state_machine.next_event()
                if event == h11.NEED_DATA:
                    self._state_machine.receive_data(self.fp.recv(65536))
                    continue

                if isinstance(event, h11.Data):
                    data_out.append(bytes(event.data))
                elif isinstance(event, h11.EndOfMessage):
                    self._close_conn()
                    break
                elif isinstance(event, h11.ConnectionClosed):
                    # TODO: better exception
                    raise ProtocolError("Connection closed early!")

            return b''.join(data_out)

    def readinto(self, b):
        """Read up to len(b) bytes into bytearray b and return the number
        of bytes read.
        """
        if self.fp is None:
            return 0

        data = self.read(len(b))
        b[:] = data
        return len(data)

    def read1(self, n=-1):
        """Read with at most one underlying system call.  If at least one
        byte is buffered, return that instead.
        """
        if self.fp is None:
            return b""

        if self._buffered_data:
            # This is a dumb default value of this argument.
            if n == -1:
                n == len(self._buffered_data)
            return self._buffered_data[:n]

        # 65536 is a nice number
        if n == -1:
            n == 65536

        self._state_machine.receive_data(self.fp.recv(n))
        data = []

        while True:
            event = self.state_machine.next_event()
            if event is h11.NEED_DATA:
                break

            if isinstance(event, h11.Data):
                data.append(event.data)
            elif isinstance(event, h11.EndOfMessage):
                self._close_conn()
                break
            elif isinstance(event, h11.ConnectionClosed):
                raise ProtocolError("Connection closed early!")

        # Thanks to the fact that we called recv with n, we cannot possibly get
        # too much data here.
        return b''.join(data)

    def peek(self, size=None):
        data_out = [self._buffered_data]
        data_out_len = len(self._buffered_data)

        while (size is None) or (data_out_len < size):
            event = self._state_machine.next_event()
            if event is h11.NEED_DATA:
                self._state_machine.receive_data(self.fp.recv(8192))
                continue

            if isinstance(event, h11.Data):
                data_out.append(bytes(event.data))
                data_out_len += len(event.data)
            elif isinstance(event, h11.EndOfMessage):
                self._close_conn()
                break
            elif isinstance(event, h11.ConnectionClosed):
                raise ProtocolError("Connection closed early!")

        self._buffered_data = b''.join(data_out)
        if size is None:
            return self._buffered_data
        else:
            return self._buffered_data[:size]

    def readline(self, limit=-1):
        # TODO: the performance here sucks.
        if self.fp is None:
            return b""

        # Fallback to IOBase readline which uses peek() and read()
        return super().readline(limit)

    def fileno(self):
        return self.fp.fileno()

    def getheader(self, name, default=None):
        '''Returns the value of the header matching *name*.
        If there are multiple matching headers, the values are
        combined into a single string separated by commas and spaces.
        If no matching header is found, returns *default* or None if
        the *default* is not specified.
        If the headers are unknown, raises http.client.ResponseNotReady.
        '''
        if self.headers is None:
            # TODO: this exception isn't real
            raise ResponseNotReady()
        headers = self.headers.getlist(name)
        if not headers:
            return default
        else:
            return b', '.join(headers)

    def getheaders(self):
        """Return list of (header, value) tuples."""
        if self.headers is None:
            # TODO: this exception isn't real
            raise ResponseNotReady()
        return list(self.headers.items())

    # We override IOBase.__iter__ so that it doesn't check for closed-ness
    def __iter__(self):
        return self


class HTTPConnection(object):
    """
    A custom HTTP connection class that is compatible with httplib, but does
    not use httplib at all. This class exists to enable a transition from older
    versions of urllib3, which used httplib to provide their HTTP support, to
    the current h11-based model for HTTP support which requires no HTTP from
    the standard library.

    Additional keyword parameters are used to configure attributes of the connection.
    Accepted parameters include:

      - ``source_address``: Set the source address for the current connection.
      - ``socket_options``: Set specific options on the underlying socket. If not specified, then
        defaults are loaded from ``HTTPConnection.default_socket_options`` which includes disabling
        Nagle's algorithm (sets TCP_NODELAY to 1) unless the connection is behind a proxy.

        For example, if you wish to enable TCP Keep Alive in addition to the defaults,
        you might pass::

            HTTPConnection.default_socket_options + [
                (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
            ]

        Or you may want to disable the defaults by passing an empty list (e.g., ``[]``).
    """

    default_port = port_by_scheme['http']

    #: Disable Nagle's algorithm by default.
    #: ``[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]``
    default_socket_options = [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]

    #: Whether this connection verifies the host's certificate.
    is_verified = False

    response_class = OldHTTPResponse

    def __init__(self, host, port, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                 source_address=None, socket_options=_DEFAULT_SOCKET_OPTS):

        # TODO: Do we need this? I think we might not: urllib3 may not ever
        # provide host and port in one string like the stdlib allows.
        (self.host, self.port) = self._get_hostport(host, port)
        self.sock = None
        self.timeout = timeout
        self.source_address = source_address

        # These are from httplib, and we may want to replace them with
        # something less dumb.
        # TODO: reconsider tunnelling.
        self._tunnel_host = None
        self._tunnel_port = None
        self._tunnel_headers = {}

        #: The socket options provided by the user. If no options are
        #: provided, we use the default options.
        self.socket_options = (
            socket_options if socket_options is not _DEFAULT_SOCKET_OPTS
            else self.default_socket_options
        )

        self.__response = None

        self._state_machine = h11.Connection(our_role=h11.CLIENT)

        # If we need to tunnel through a CONNECT proxy, we need an extra state
        # machine to manage the "outer" HTTP connection. We only use it to set
        # up the connection: once it is set up, we throw this back away.
        self._tunnel_state_machine = None

    @staticmethod
    def _get_content_length(body, method):
        """Get the content-length based on the body.
        If the body is None, we set Content-Length: 0 for methods that expect
        a body (RFC 7230, Section 3.3.2). We also set the Content-Length for
        any method if the body is a str or bytes-like object and not a file.
        """
        if body is None:
            # do an explicit check for not None here to distinguish
            # between unset and set but empty
            if method.upper() in set(['PATCH', 'POST', 'PUT']):
                return 0
            else:
                return None

        if hasattr(body, 'read'):
            # file-like object.
            return None

        try:
            return len(body)
        except (AttributeError, TypeError):
            return None

    def set_tunnel(self, host, port=None, headers=None):
        """
        Set up host and port for HTTP CONNECT tunnelling.

        In a connection that uses HTTP CONNECT tunneling, the host passed to
        the constructor is used as a proxy server that relays all communication
        to the endpoint passed to `set_tunnel`. This done by sending an HTTP
        CONNECT request to the proxy server when the connection is established.

        This method must be called before the HTTP connection has been
        established.

        The headers argument should be a mapping of extra HTTP headers to send
        with the CONNECT request.
        """
        self._tunnel_host, self._tunnel_port = self._get_hostport(host, port)
        if headers:
            self._tunnel_headers = headers
        else:
            self._tunnel_headers.clear()

    def _get_hostport(self, host, port):
        """
        Handle parsing host/port descriptions to tolerate the cases where the
        host is a string that also contains port information.
        """
        if port is None:
            url = parse_url(host)
            host = url.host
            port = url.port if url.port is not None else self.default_port
            if host and host[0] == '[' and host[-1] == ']':
                host = host[1:-1]

        return (host, port)

    def _tunnel(self):
        """
        We have been asked to set up a CONNECT tunnel. We do this using a
        temporary state machine to manage the CONNECT request.

        If the attempt to tunnel fails, we will throw an exception that
        includes the response object so that callers can extract that response
        and use it to make sensible decisions.
        """
        # Basic sanity check that _tunnel is only called at appropriate times.
        assert self._state_machine.our_state is h11.IDLE

        target = "%s:%d" % (self._tunnel_host, self._tunnel_port)
        if not isinstance(target, bytes):
            target = target.encode('latin1')

        # We need to set the Host header.
        headers = dict(_validate_headers(self._tunnel_headers.items()))
        if b"host" not in frozenset(k.lower() for k in headers):
            headers[b"host"] = target

        self._tunnel_state_machine = h11.Connection(our_role=h11.CLIENT)
        request = h11.Request(
            method=b"CONNECT",
            target=target,
            headers=headers.items(),
        )
        bytes_to_send = self._tunnel_state_machine.send(request)
        self.sock.sendall(bytes_to_send)

        response = self.response_class(
            self.sock, self._tunnel_state_machine, method=b"CONNECT"
        )

        try:
            response.begin()
        except SocketError:
            self.close()
            raise

        if response.status != 200:
            # TODO: include the response here.
            self.close()
            raise RuntimeError("Bad response!")

        # Tunnel is complete. Throw away our tunnel state machine, we don't
        # need it now.
        self._tunnel_state_machine = None

        # Before we exit, we need to take the socket away from the response.
        # This is because the response will try to close it when it gets
        # GC'd, which is double-plus-un-good.
        # TODO: Can we do better here? Surely we must.
        response.fp = None

    def _new_conn(self):
        """ Establish a socket connection and set nodelay settings on it.

        :return: New socket connection.
        """
        extra_kw = {}
        if self.source_address:
            extra_kw['source_address'] = self.source_address

        if self.socket_options:
            extra_kw['socket_options'] = self.socket_options

        try:
            conn = connection.create_connection(
                (self.host, self.port), self.timeout, **extra_kw)

        except SocketTimeout as e:
            raise ConnectTimeoutError(
                self, "Connection to %s timed out. (connect timeout=%s)" %
                (self.host, self.timeout))

        except SocketError as e:
            raise NewConnectionError(
                self, "Failed to establish a new connection: %s" % e)

        return conn

    def _prepare_conn(self, conn):
        self.sock = conn
        if self._tunnel_host is not None:
            self._tunnel()

    def connect(self):
        conn = self._new_conn()
        self._prepare_conn(conn)

    def close(self):
        """Close the connection to the HTTP server."""
        try:
            sock = self.sock
            if sock:
                self.sock = None
                sock.close()   # close it manually... there may be other refs

        finally:
            response = self.__response
            if response:
                self.__response = None
                response.close()

            self._state_machine = h11.Connection(our_role=h11.CLIENT)

    def send(self, data):
        """Send `data' to the server.
        ``data`` can be a string object, a bytes object, an array object, a
        file-like object that supports a .read() method, or an iterable object.
        """
        if hasattr(data, "read"):
            for datablock in self._read_readable(data):
                to_send = self._state_machine.send(h11.Data(data=datablock))
                self.sock.sendall(to_send)
            return
        try:
            to_send = self._state_machine.send(h11.Data(data=data))
            self.sock.sendall(to_send)
        except TypeError:
            if isinstance(data, collections.Iterable):
                for d in data:
                    to_send = self._state_machine.send(h11.Data(data=data))
                    self.sock.sendall(to_send)
            else:
                raise TypeError("data should be a bytes-like object "
                                "or an iterable, got %r" % type(data))

    def _read_readable(self, readable):
        # TODO: reconsider this block size
        blocksize = 8192
        encode = isinstance(readable, io.TextIOBase)
        while True:
            datablock = readable.read(blocksize)
            if not datablock:
                break
            if encode:
                datablock = datablock.encode("iso-8859-1")
            yield datablock

    def _send_output(self, message_body=None):
        """Send the currently buffered request and clear the buffer.

        Appends an extra \\r\\n to the buffer.
        A message_body may be specified, to be appended to the request.
        """
        if message_body is not None:
            # create a consistent interface to message_body
            if hasattr(message_body, 'read'):
                # Let file-like take precedence over byte-like.  This
                # is needed to allow the current position of mmap'ed
                # files to be taken into account.
                chunks = self._read_readable(message_body)
            else:
                try:
                    # this is solely to check to see if message_body
                    # implements the buffer API.  it /would/ be easier
                    # to capture if PyObject_CheckBuffer was exposed
                    # to Python.
                    memoryview(message_body)
                except TypeError:
                    try:
                        chunks = iter(message_body)
                    except TypeError:
                        raise TypeError("message_body should be a bytes-like "
                                        "object or an iterable, got %r"
                                        % type(message_body))
                else:
                    # the object implements the buffer interface and
                    # can be passed directly into socket methods
                    chunks = (message_body,)

            for chunk in chunks:
                # Ignore zero-length chunks. This was originally done in
                # httplib and we're just leaving it here.
                if not chunk:
                    continue

                if not isinstance(chunk, six.binary_type):
                    chunk = chunk.encode('utf8')

                self.send(chunk)

        self._complete_request()

    def _complete_request(self):
        """
        We're done with the request.
        """
        to_send = self._state_machine.send(h11.EndOfMessage())
        self.sock.sendall(to_send)

    def _get_host_header(self, url):
        """
        For a given URL, extracts the appropriate value for the Host header
        field for the request.
        """
        # If we need a non-standard port, include it in the header. If the
        # request is going through a proxy, we want to set the host of the
        # actual URL, not the host of the proxy.
        netloc = ''
        if url.startswith('http'):
            netloc = parse_url(url).netloc

        if netloc:
            try:
                netloc_enc = netloc.encode("ascii")
            except UnicodeEncodeError:
                netloc_enc = netloc.encode("idna")
            return netloc_enc
        else:
            if self._tunnel_host:
                host = self._tunnel_host
                port = self._tunnel_port
            else:
                host = self.host
                port = self.port

            try:
                host_enc = host.encode("ascii")
            except UnicodeEncodeError:
                host_enc = host.encode("idna")

            # As per RFC 273, IPv6 address should be wrapped with []
            # when used as Host header

            if host.find(':') >= 0:
                host_enc = b'[' + host_enc + b']'

            if port == self.default_port:
                return host_enc
            else:
                host_enc = host_enc.decode("ascii")
                return u"%s:%s" % (host_enc, port)

    def request(self, method, url, body=None, headers={}):
        """Send a complete request to the server."""
        self._send_request(method, url, body, headers.copy())

    def _send_request(self, method, url, body, headers):
        # if a prior response has been completed, then forget about it.
        if self.__response and self.__response.isclosed():
            self.__response = None

        # Save the method we use, we need it later in the response phase
        # TODO: We need to encode all these strings to bytes.
        self._method = method
        if not url:
            url = '/'

        # Honor explicitly requested Host: and Accept-Encoding: headers.
        header_names = frozenset(k.lower() for k in headers)
        if 'host' not in header_names:
            headers['Host'] = self._get_host_header(url)
        if 'accept-encoding' not in header_names:
            headers['Accept-Encoding'] = 'identity'

        # chunked encoding will happen if the following conditions hold:
        # 1. content-length has not been explicitly set
        # 2. the body is a file or iterable, but not a str or bytes-like
        # 3. Transfer-Encoding has NOT been explicitly set by the caller
        no_content_length = 'content-length' not in header_names
        no_transfer_encoding = 'transfer-encoding' not in header_names

        if no_content_length and no_transfer_encoding:
            # if content-length cannot be automatically determined, fall
            # back to chunked encoding
            content_length = self._get_content_length(body, method)
            if content_length is None:
                if body is not None:
                    headers['Transfer-Encoding'] = 'chunked'
            else:
                headers['Content-Length'] = str(content_length)

        headers = _validate_headers(headers.items())

        if isinstance(body, six.text_type):
            # RFC 2616 Section 3.7.1 says that text default has a
            # default charset of iso-8859-1.
            # TODO: what?
            body = _encode(body, 'body')

        if self.sock is None:
            self.connect()

        request = h11.Request(
            method=method,
            target=url,
            headers=headers,
        )

        bytes_to_send = self._state_machine.send(request)
        self.sock.sendall(bytes_to_send)
        self._send_output(body)

    def getresponse(self):
        """Get the response from the server.

        If the HTTPConnection is in the correct state, returns an
        instance of HTTPResponse or of whatever object is returned by
        the response_class variable.

        If a request has not been sent or if a previous response has
        not be handled, ResponseNotReady is raised.  If the HTTP
        response indicates that the connection should be closed, then
        it will be closed before the response is returned.  When the
        connection is closed, the underlying socket is closed.
        """
        # TODO: rewrite this from httplib form to our own form.

        # if a prior response has been completed, then forget about it.
        if self.__response and self.__response.isclosed():
            self.__response = None

        # if a prior response exists, then it must be completed (otherwise, we
        # cannot read this response's header to determine the connection-close
        # behavior)
        #
        # note: if a prior response existed, but was connection-close, then the
        # socket and response were made independent of this HTTPConnection
        # object since a new request requires that we open a whole new
        # connection
        #
        # this means the prior response had one of two states:
        #   1) will_close: this connection was reset and the prior socket and
        #                  response operate independently
        #   2) persistent: the response was retained and we await its
        #                  isclosed() status to become true.
        #
        if self.__response:
            raise ResponseNotReady()

        response = self.response_class(
            self.sock, self._state_machine, method=self._method
        )

        try:
            try:
                response.begin()
            except SocketError:
                self.close()
                raise

            if response.will_close:
                # this effectively passes the connection to the response
                self.close()
            else:
                # remember this, so we can tell when it is complete
                self.__response = response

            return response
        except Exception:
            response.close()
            raise

    def request_chunked(self, method, url, body=None, headers=None):
        """
        Alternative to the common request method, which sends the
        body with chunked encoding and not as one block
        """
        headers = HTTPHeaderDict(headers if headers is not None else {})
        # TODO: throw exception if we have content-length too.
        if 'transfer-encoding' not in headers:
            headers['Transfer-Encoding'] = 'chunked'

        if body is not None:
            stringish_types = six.string_types + (six.binary_type,)
            if isinstance(body, stringish_types):
                body = (body,)

        self.request(method, url, body, headers)


class HTTPSConnection(HTTPConnection):
    default_port = port_by_scheme['https']

    ssl_version = None

    def __init__(self, host, port=None, key_file=None, cert_file=None,
                 timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                 ssl_context=None, **kw):

        HTTPConnection.__init__(self, host, port, timeout=timeout, **kw)

        self.key_file = key_file
        self.cert_file = cert_file
        self.ssl_context = ssl_context

        # Required property for Google AppEngine 1.9.0 which otherwise causes
        # HTTPS requests to go out as HTTP. (See Issue #356)
        self._protocol = 'https'

    def connect(self):
        conn = self._new_conn()
        self._prepare_conn(conn)

        if self.ssl_context is None:
            self.ssl_context = create_urllib3_context(
                ssl_version=resolve_ssl_version(None),
                cert_reqs=resolve_cert_reqs(None),
            )

        self.sock = ssl_wrap_socket(
            sock=conn,
            keyfile=self.key_file,
            certfile=self.cert_file,
            ssl_context=self.ssl_context,
        )


class VerifiedHTTPSConnection(HTTPSConnection):
    """
    Based on httplib.HTTPSConnection but wraps the socket with
    SSL certification.
    """
    cert_reqs = None
    ca_certs = None
    ca_cert_dir = None
    ssl_version = None
    assert_fingerprint = None

    def set_cert(self, key_file=None, cert_file=None,
                 cert_reqs=None, ca_certs=None,
                 assert_hostname=None, assert_fingerprint=None,
                 ca_cert_dir=None):
        """
        This method should only be called once, before the connection is used.
        """
        # If cert_reqs is not provided, we can try to guess. If the user gave
        # us a cert database, we assume they want to use it: otherwise, if
        # they gave us an SSL Context object we should use whatever is set for
        # it.
        if cert_reqs is None:
            if ca_certs or ca_cert_dir:
                cert_reqs = 'CERT_REQUIRED'
            elif self.ssl_context is not None:
                cert_reqs = self.ssl_context.verify_mode

        self.key_file = key_file
        self.cert_file = cert_file
        self.cert_reqs = cert_reqs
        self.assert_hostname = assert_hostname
        self.assert_fingerprint = assert_fingerprint
        self.ca_certs = ca_certs and os.path.expanduser(ca_certs)
        self.ca_cert_dir = ca_cert_dir and os.path.expanduser(ca_cert_dir)

    def connect(self):
        # Add certificate verification
        conn = self._new_conn()

        hostname = self.host
        if self._tunnel_host is not None:

            self.sock = conn
            # Calls self._set_hostport(), so self.host is
            # self._tunnel_host below.
            self._tunnel()

            # Override the host with the one we're requesting data from.
            hostname = self._tunnel_host

        is_time_off = datetime.date.today() < RECENT_DATE
        if is_time_off:
            warnings.warn((
                'System time is way off (before {0}). This will probably '
                'lead to SSL verification errors').format(RECENT_DATE),
                SystemTimeWarning
            )

        # Wrap socket using verification with the root certs in
        # trusted_root_certs
        if self.ssl_context is None:
            self.ssl_context = create_urllib3_context(
                ssl_version=resolve_ssl_version(self.ssl_version),
                cert_reqs=resolve_cert_reqs(self.cert_reqs),
            )

        context = self.ssl_context
        context.verify_mode = resolve_cert_reqs(self.cert_reqs)
        self.sock = ssl_wrap_socket(
            sock=conn,
            keyfile=self.key_file,
            certfile=self.cert_file,
            ca_certs=self.ca_certs,
            ca_cert_dir=self.ca_cert_dir,
            server_hostname=hostname,
            ssl_context=context)

        if self.assert_fingerprint:
            assert_fingerprint(self.sock.getpeercert(binary_form=True),
                               self.assert_fingerprint)
        elif context.verify_mode != ssl.CERT_NONE \
                and self.assert_hostname is not False:
            cert = self.sock.getpeercert()
            if not cert.get('subjectAltName', ()):
                warnings.warn((
                    'Certificate for {0} has no `subjectAltName`, falling back to check for a '
                    '`commonName` for now. This feature is being removed by major browsers and '
                    'deprecated by RFC 2818. (See https://github.com/shazow/urllib3/issues/497 '
                    'for details.)'.format(hostname)),
                    SubjectAltNameWarning
                )
            _match_hostname(cert, self.assert_hostname or hostname)

        self.is_verified = (
            context.verify_mode == ssl.CERT_REQUIRED or
            self.assert_fingerprint is not None
        )


def _match_hostname(cert, asserted_hostname):
    try:
        match_hostname(cert, asserted_hostname)
    except CertificateError as e:
        log.error(
            'Certificate did not match expected hostname: %s. '
            'Certificate: %s', asserted_hostname, cert
        )
        # Add cert to exception and reraise so client code can inspect
        # the cert when catching the exception, if they want to
        e._peer_cert = cert
        raise


if ssl:
    # Make a copy for testing.
    UnverifiedHTTPSConnection = HTTPSConnection
    HTTPSConnection = VerifiedHTTPSConnection
else:
    HTTPSConnection = DummyConnection
