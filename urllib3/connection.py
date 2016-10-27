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


try:  # Python 3:
    # Not a no-op, we're adding this to the namespace so it can be imported.
    ConnectionError = ConnectionError
except NameError:  # Python 2:
    class ConnectionError(Exception):
        pass


from .exceptions import (
    NewConnectionError,
    ConnectTimeoutError,
    SubjectAltNameWarning,
    SystemTimeWarning,
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

RECENT_DATE = datetime.date(2014, 1, 1)

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


class DummyConnection(object):
    """Used to detect a failed ConnectionCls import."""
    pass


# TODO: This is needed to avoid breaking imports, revisit it.
class HTTPException(object):
    pass


# TODO: This is a holdover from httplib, do we need it?
_UNKNOWN = object()


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
        self.version = _UNKNOWN
        self.status = _UNKNOWN
        self.reason = _UNKNOWN

        self.length = _UNKNOWN          # number of bytes left in response
        self.will_close = _UNKNOWN      # conn will close at end of response
        self.chunked = _UNKNOWN

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
                    # TODO: What exception?
                    raise RemoteDisconnected(
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
            # TODO: Need to replace exception
            raise UnknownProtocol(version)

        self.headers = self.msg = HTTPHeaderDict(event.headers)
        connection = self.headers.get("connection")
        self.will_close = "close" in connection.strip()

    def _close_conn(self):
        # Note that this closure only closes the backing socket if there is no
        # other reference to it.
        fp, self.fp = self.fp, None
        fp.close()

        if self._state_machine.our_state is h11.DONE:
            self._state_machine.start_next_cycle()

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
                    data = self.sock.recv(65536)
                    self._state_machine.receive_data(data)
                    continue

                if isinstance(event, h11.Data):
                    data_out.append(event.data)
                    out_len += len(event.data)
                elif isinstance(event, h11.EndOfMessage):
                    self._close_conn()
                    break
                elif isinstance(event, h11.ConnectionClosed):
                    # TODO: better exception
                    raise RuntimeError("Connection closed early!")

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
                    raise RuntimeError("Connection closed early!")

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
                # TODO: better exception
                raise RuntimeError("Connection closed early!")

        # Thanks to the fact that we called recv with n, we cannot possibly get
        # too much data here.
        return b''.join(data)

    def peek(self, size=None):
        data_out = [self._buffered_data]
        data_out_len = len(self._buffered_data)

        while (size is None) or (size < data_out_len):
            event = self._state_machine.next_event()
            if event is h11.NEED_DATA:
                self._state_machine.receive_data(self.fp.recv(8192))
                continue

            if isinstance(event, h11.Data):
                data_out.append(event.data)
                data_out_len += len(event.data)
            elif isinstance(event, h11.EndOfMessage):
                self._close_conn()
                break
            elif isinstance(event, h11.ConnectionClosed):
                # TODO: better exception
                raise RuntimeError("Connection closed early!")

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

      - ``strict``: See the documentation on :class:`urllib3.connectionpool.HTTPConnectionPool`
      - ``source_address``: Set the source address for the current connection.

        .. note:: This is ignored for Python 2.6. It is only applied for 2.7 and 3.x

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
                 source_address=None, socket_options=None):

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
            socket_options if socket_options is not None
            else self.default_socket_options
        )

        self.__response = None
        self._pending_headers = []
        self._url = None

        self._state_machine = h11.Connection(our_role=h11.CLIENT)

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
            # does it implement the buffer protocol (bytes, bytearray, array)?
            mv = memoryview(body)
            return mv.nbytes
        except TypeError:
            pass

        if isinstance(body, str):
            return len(body)

        return None

    def set_tunnel(self, host, port=None, headers=None):
        """
        Set up host and port for HTTP CONNECT tunnelling.

        In a connection that uses HTTP CONNECT tunneling, the host passed to
        the constructor is used as a proxy server that relays all communication
        to the endpoint passed to `set_tunnel`. This done by sending an HTTP
        CONNECT request to the proxy server when the connection is established.

        This method must be called before the HTML connection has been
        established.

        The headers argument should be a mapping of extra HTTP headers to send
        with the CONNECT request.
        """
        # TODO: Rewrite this method from its httplib form.
        if self.sock:
            raise RuntimeError("Can't set up tunnel for established conn")

        self._tunnel_host, self._tunnel_port = self._get_hostport(host, port)
        if headers:
            self._tunnel_headers = headers
        else:
            self._tunnel_headers.clear()

    def _get_hostport(self, host, port):
        # TODO: We may not need this method. If we do, we should consider
        # whether we can rewrite it.
        if port is None:
            i = host.rfind(':')
            j = host.rfind(']')         # ipv6 addresses have [...]
            if i > j:
                try:
                    port = int(host[i + 1:])
                except ValueError:
                    if host[i + 1:] == "":  # http://foo.co:/ == http://foo.co/
                        port = self.default_port
                    else:
                        raise InvalidURL(
                            "nonnumeric port: '%s'" % host[i + 1:]
                        )
                host = host[:i]
            else:
                port = self.default_port
            if host and host[0] == '[' and host[-1] == ']':
                host = host[1:-1]

        return (host, port)

    def _tunnel(self):
        # TODO: replace this with a method that doesn't suck.
        connect_str = "CONNECT %s:%d HTTP/1.0\r\n" % (
            self._tunnel_host, self._tunnel_port
        )
        connect_bytes = connect_str.encode("ascii")
        self.send(connect_bytes)
        for header, value in self._tunnel_headers.items():
            header_str = "%s: %s\r\n" % (header, value)
            header_bytes = header_str.encode("latin-1")
            self.send(header_bytes)
        self.send(b'\r\n')

        response = self.response_class(self.sock, method=self._method)
        (version, code, message) = response._read_status()

        if code != http.HTTPStatus.OK:
            self.close()
            raise OSError("Tunnel connection failed: %d %s" % (
                code, message.strip())
            )
        while True:
            line = response.fp.readline(_MAXLINE + 1)
            if len(line) > _MAXLINE:
                raise LineTooLong("header line")
            if not line:
                # for sites which EOF without sending a trailer
                break
            if line in (b'\r\n', b'\n', b''):
                break

            if self.debuglevel > 0:
                print('header:', line.decode())

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
        # the _tunnel_host attribute was added in python 2.6.3 (via
        # http://hg.python.org/cpython/rev/0f57b30a152f) so pythons 2.6(0-2) do
        # not have them.
        if getattr(self, '_tunnel_host', None):
            # TODO: Fix tunnel so it doesn't depend on self.sock state.
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
            # TODO: We probably need to replicate this method.
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
        # TODO: We probably need to replicate this method.
        encode = self._is_textIO(readable)
        while True:
            datablock = readable.read(blocksize)
            if not datablock:
                break
            if encode:
                datablock = datablock.encode("iso-8859-1")
            yield datablock

    def _send_output(self, message_body=None, encode_chunked=False):
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

                self.send(chunk)

        self._complete_request()

    def _complete_request(self):
        """
        We're done with the request.
        """
        to_send = self._state_machine.send(h11.EndOfMessage())
        self.sock.sendall(to_send)

    def putrequest(self, method, url, skip_host=False,
                   skip_accept_encoding=False):
        """Send a request to the server.

        `method' specifies an HTTP request method, e.g. 'GET'.
        `url' specifies the object being requested, e.g. '/index.html'.
        `skip_host' if True does not add automatically a 'Host:' header
        `skip_accept_encoding' if True does not add automatically an
           'Accept-Encoding:' header
        """
        # TODO: rewrite this from httplib form to our own form.

        # if a prior response has been completed, then forget about it.
        if self.__response and self.__response.isclosed():
            self.__response = None

        # Save the method we use, we need it later in the response phase
        # TODO: We need to encode all these strings to bytes.
        self._method = method
        if not url:
            url = '/'
        self._url = url

        if not skip_host:
            # this header is issued *only* for HTTP/1.1
            # connections. more specifically, this means it is
            # only issued when the client uses the new
            # HTTPConnection() class. backwards-compat clients
            # will be using HTTP/1.0 and those clients may be
            # issuing this header themselves. we should NOT issue
            # it twice; some web servers (such as Apache) barf
            # when they see two Host: headers

            # If we need a non-standard port,include it in the
            # header.  If the request is going through a proxy,
            # but the host of the actual URL, not the host of the
            # proxy.

            netloc = ''
            if url.startswith('http'):
                netloc = parse_url(url).netloc

            if netloc:
                try:
                    netloc_enc = netloc.encode("ascii")
                except UnicodeEncodeError:
                    netloc_enc = netloc.encode("idna")
                self.putheader('Host', netloc_enc)
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
                    self.putheader('Host', host_enc)
                else:
                    host_enc = host_enc.decode("ascii")
                    self.putheader('Host', "%s:%s" % (host_enc, port))

        # we only want a Content-Encoding of "identity" since we don't
        # support encodings such as x-gzip or x-deflate.
        if not skip_accept_encoding:
            self.putheader('Accept-Encoding', 'identity')

    def putheader(self, header, *values):
        """Send a request header line to the server.

        For example: h.putheader('Accept', 'text/html')
        """
        # TODO: rewrite this from httplib form to our own form.
        if hasattr(header, 'encode'):
            header = header.encode('ascii')

        # TODO: gotta get this method or assume h11 resolves it for us
        if not _is_legal_header_name(header):
            raise ValueError('Invalid header name %r' % (header,))

        values = list(values)
        for value in values:
            if hasattr(value, 'encode'):
                value = value.encode('latin-1')
            elif isinstance(value, int):
                value = str(value).encode('ascii')

            # TODO: gotta get this method or assume h11 resolves it for us
            if _is_illegal_header_value(value):
                raise ValueError('Invalid header value %r' % (value,))

            self._pending_headers.append((header, value))

    def endheaders(self, message_body=None, encode_chunked=False):
        """Indicate that the last header line has been sent to the server.

        This method sends the request to the server.  The optional message_body
        argument can be used to pass a message body associated with the
        request.
        """
        if self.sock is None:
            self.connect()

        request = h11.Request(
            method=self._method,
            target=self._url,
            headers=self._pending_headers,
        )
        self._pending_headers = []
        self._url = None

        bytes_to_send = self._state_machine.send(request)
        self.sock.sendall(bytes_to_send)
        self._send_output(message_body, encode_chunked=encode_chunked)

    def request(self, method, url, body=None, headers={},
                encode_chunked=False):
        """Send a complete request to the server."""
        # TODO: rewrite this from httplib form to our own form.
        self._send_request(method, url, body, headers, encode_chunked)

    def _send_request(self, method, url, body, headers, encode_chunked):
        # TODO: rewrite this from httplib form to our own form.
        # Honor explicitly requested Host: and Accept-Encoding: headers.
        header_names = frozenset(k.lower() for k in headers)
        skips = {}
        if 'host' in header_names:
            skips['skip_host'] = 1
        if 'accept-encoding' in header_names:
            skips['skip_accept_encoding'] = 1

        self.putrequest(method, url, **skips)

        # chunked encoding will happen if HTTP/1.1 is used and either
        # the caller passes encode_chunked=True or the following
        # conditions hold:
        # 1. content-length has not been explicitly set
        # 2. the body is a file or iterable, but not a str or bytes-like
        # 3. Transfer-Encoding has NOT been explicitly set by the caller

        if 'content-length' not in header_names:
            # only chunk body if not explicitly set for backwards
            # compatibility, assuming the client code is already handling the
            # chunking
            if 'transfer-encoding' not in header_names:
                # if content-length cannot be automatically determined, fall
                # back to chunked encoding
                encode_chunked = False
                content_length = self._get_content_length(body, method)
                if content_length is None:
                    if body is not None:
                        encode_chunked = True
                        self.putheader('Transfer-Encoding', 'chunked')
                else:
                    self.putheader('Content-Length', str(content_length))
        else:
            encode_chunked = False

        for hdr, value in headers.items():
            self.putheader(hdr, value)
        if isinstance(body, str):
            # RFC 2616 Section 3.7.1 says that text default has a
            # default charset of iso-8859-1.
            # TODO: what?
            body = _encode(body, 'body')
        self.endheaders(body, encode_chunked=encode_chunked)

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
            except ConnectionError:
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
        skip_accept_encoding = 'accept-encoding' in headers
        self.putrequest(method, url, skip_accept_encoding=skip_accept_encoding)
        for header, value in headers.items():
            self.putheader(header, value)
        if 'transfer-encoding' not in headers:
            self.putheader('Transfer-Encoding', 'chunked')
        self.endheaders()

        if body is not None:
            stringish_types = six.string_types + (six.binary_type,)
            if isinstance(body, stringish_types):
                body = (body,)
            for chunk in body:
                if not chunk:
                    continue
                if not isinstance(chunk, six.binary_type):
                    chunk = chunk.encode('utf8')
                self.send(chunk)

        self._complete_request()


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
        if getattr(self, '_tunnel_host', None):
            # _tunnel_host was added in Python 2.6.3
            # (See: http://hg.python.org/cpython/rev/0f57b30a152f)

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
