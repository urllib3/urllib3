'''
See also shazow/urllib3/#236
'''

from .collections_ import HTTPHeaderDict

import socket
from httplib import (
    HTTPException, # for the public api
    UnknownProtocol, # for use in the HTTPResponse.begin method
    HTTPResponse as _HTTPResponse,
    HTTPConnection as _HTTPConnection
)

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

class HTTPMessage:

    def __init__(self, fp, _seekable=None): # _seekable for backwards compat
        self.fp = fp
        self.seekable = None
        self.headers = HTTPHeaderDict()
        self._set_seekable(fp)
        self.readheaders()

    def _set_seekable(self, fp):
        try:
            fp.tell()
        except (AttributeError, IOError):
            self.seekable = False
        else:
            self.seekable = True

    def readheaders(self):
        headerseen = ''
        startofline = unread = tell = None
        if hasattr(self.fp, 'unread'):
            unread = self.fp.unread
        elif self.seekable:
            tell = self.fp.tell
        while True:
            if tell:
                try:
                    startofline = tell()
                except IOError:
                    startofline = tell = None
                    self.seekable = False
            line = self.fp.readline()
            if not line:
                break
            if headerseen and line[0] in ' \t':
                self.addcontinue(headerseen, line.strip())
                continue
            elif self.islast(line):
                # Note! No pushback here!  The delimiter line gets eaten.
                break
            headerseen = self.isheader(line)
            if headerseen:
                self.addheader(headerseen, line[len(headerseen)+1:].strip())
                continue
            else:
                # Try to undo the read.
                if unread:
                    unread(line)
                elif tell:
                    self.fp.seek(startofline)
                break

    def isheader(self, line):
        i = line.find(':')
        if i > 0:
            return line[:i]
        return None

    def islast(self, line):
        return line in ('\r\n', '\n')

    def addcontinue(self, name, more):
        raw_header = self.headers.raw_header(name)
        extra = '\n ' + more
        raw_header[-1][1] += extra
        del self.headers[name]
        for key, value in raw_header:
            self.headers.append(key, value)

    def addheader(self, key, value):
        self.headers.append(key, value)

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def items(self):
        return self.headers.items()

HTTPS_PORT = 443

CONTINUE = 100
NO_CONTENT = 204
NOT_MODIFIED = 304

class HTTPResponse(_HTTPResponse):

    def begin(self):
        if self.msg is not None:
            # we've already started reading the response
            return

        # read until we get a non-100 response
        while True:
            version, status, reason = self._read_status()
            if status != CONTINUE:
                break
            # skip the header from the 100 response
            while True:
                skip = self.fp.readline().strip()
                if not skip:
                    break
                if self.debuglevel > 0:
                    print "header:", skip

        self.status = status
        self.reason = reason.strip()
        if version == 'HTTP/1.0':
            self.version = 10
        elif version.startswith('HTTP/1.'):
            self.version = 11   # use HTTP/1.1 code for HTTP/1.x where x>=1
        elif version == 'HTTP/0.9':
            self.version = 9
        else:
            raise UnknownProtocol(version)

        if self.version == 9:
            self.length = None
            self.chunked = 0
            self.will_close = 1
            self.msg = HTTPMessage(StringIO())
            return

        self.msg = HTTPMessage(self.fp, 0)
        if self.debuglevel > 0:
            for hdr in self.msg.headers:
                print "header:", hdr,

        # don't let the msg keep an fp
        self.msg.fp = None

        # are we using the chunked-style of transfer encoding?
        tr_enc = self.msg.getheader('transfer-encoding')
        if tr_enc and tr_enc.lower() == "chunked":
            self.chunked = 1
            self.chunk_left = None
        else:
            self.chunked = 0

        # will the connection close at the end of the response?
        self.will_close = self._check_close()

        # do we have a Content-Length?
        # NOTE: RFC 2616, S4.4, #3 says we ignore this if tr_enc is "chunked"
        length = self.msg.getheader('content-length')
        if length and not self.chunked:
            try:
                self.length = int(length)
            except ValueError:
                self.length = None
            else:
                if self.length < 0:  # ignore nonsensical negative lengths
                    self.length = None
        else:
            self.length = None

        # does the body have a fixed length? (of zero)
        if (status == NO_CONTENT or status == NOT_MODIFIED or
            100 <= status < 200 or      # 1xx codes
            self._method == 'HEAD'):
            self.length = 0

        # if the connection remains open, and we aren't using chunked, and
        # a content-length was not provided, then assume that the connection
        # WILL close.
        if not self.will_close and \
           not self.chunked and \
           self.length is None:
            self.will_close = 1

class HTTPConnection(_HTTPConnection):
    response_class = HTTPResponse

try:
    import ssl
except ImportError:
    pass
else:
    class HTTPSConnection(HTTPConnection):
        "This class allows communication via SSL."

        default_port = HTTPS_PORT

        def __init__(self, host, port=None, key_file=None, cert_file=None,
                     strict=None, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                     source_address=None):
            HTTPConnection.__init__(self, host, port, strict, timeout,
                                    source_address)
            self.key_file = key_file
            self.cert_file = cert_file

        def connect(self):
            "Connect to a host on a given (SSL) port."

            sock = socket.create_connection((self.host, self.port),
                                            self.timeout, self.source_address)
            if self._tunnel_host:
                self.sock = sock
                self._tunnel()
            self.sock = ssl.wrap_socket(sock, self.key_file, self.cert_file)
