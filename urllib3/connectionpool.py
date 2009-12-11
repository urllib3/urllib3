import logging
log = logging.getLogger(__name__)

from Queue import Queue, Empty, Full
from StringIO import StringIO
from itertools import count

from urllib import urlencode
from httplib import HTTPConnection, HTTPException
from socket import error as SocketError, timeout as SocketTimeout

from filepost import encode_multipart_formdata

## Exceptions

class HTTPError(Exception):
    "Base exception used by this module."
    pass

class MaxRetryError(HTTPError):
    "Raised when the maximum number of retries is exceeded."
    pass

class TimeoutError(HTTPError):
    "Raised when a socket timeout occurs."
    pass

## Response objects

class HTTPResponse(object):
    """
    HTTP Response container.

    Similar to httplib's HTTPResponse but the data is pre-loaded.
    """
    def __init__(self, data='', headers={}, status=0, version=0, reason=None, strict=0):
        self.data = data
        self.headers = headers
        self.status = status
        self.version = version
        self.reason = reason
        self.strict = strict

    @staticmethod
    def from_httplib(r):
        """
        Given an httplib.HTTPResponse instance, return a corresponding
        urllib3.HTTPResponse object.

        NOTE: This method will perform r.read() which will have side effects
        on the original http.HTTPResponse object.
        """
        return HTTPResponse(data=r.read(),
                    headers=dict(r.getheaders()),
                    status=r.status,
                    version=r.version,
                    reason=r.reason,
                    strict=r.strict)

    # Backwards-compatibility methods for httplib.HTTPResponse
    def getheaders(self):
        return self.headers

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

## Pool objects

class HTTPConnectionPool(object):
    """
    Thread-safe connection pool for one host.

    host
        Host used for this HTTP Connection (e.g. "localhost"), passed into
        httplib.HTTPConnection()

    port
        Port used for this HTTP Connection (None is equivalent to 80), passed
        into httplib.HTTPConnection()

    timeout
        Socket timeout for each individual connection, can be a float. None
        disables timeout.

    maxsize
        Number of connections to save that can be reused. More than 1 is useful
        in multithreaded situations. If ``block`` is set to false, more
        connections will be created but they will not be saved once they've
        been used.

    block
        If set to True, no more than ``maxsize`` connections will be used at
        a time. When no free connections are available, the call will block
        until a connection has been released. This is a useful side effect for
        particular multithreaded situations where one does not want to use more
        than maxsize connections per host to prevent flooding.

    """
    def __init__(self, host, port=None, timeout=None, maxsize=1, block=False):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.pool = Queue(maxsize)
        self.block = block

        # Fill the queue up so that doing get() on it will block properly
        [self.pool.put(None) for i in xrange(maxsize)]

        self.num_connections = 0
        self.num_requests = 0

    @staticmethod
    def get_host(url):
        """
        Given a url, return its host and port (None if it's not there).

        For example:
        >>> HTTPConnectionPool.get_host('http://google.com/mail/')
        google.com, None
        >>> HTTPConnectionPool.get_host('google.com:80')
        google.com, 80
        """
        # This code is actually similar to urlparse.urlsplit, but much
        # simplified for our needs.
        port = None
        if '//' in url:
            scheme, url = url.split('//', 1)
        if '/' in url:
            url, path = url.split('/', 1)
        if ':' in url:
            url, port = url.split(':', 1)
            port = int(port)
        return url, port

    @staticmethod
    def from_url(url, timeout=None, maxsize=10):
        """
        Given a url, return an HTTPConnectionPool instance of its host.

        This is a shortcut for not having to determine the host of the url
        before creating an HTTPConnectionPool instance.
        """
        host, port = HTTPConnectionPool.get_host(url)
        return HTTPConnectionPool(host, port=port, timeout=timeout, maxsize=maxsize)

    def _new_conn(self):
        """
        Return a fresh HTTPConnection.
        """
        self.num_connections += 1
        log.info("Starting new HTTP connection (%d): %s" % (self.num_connections, self.host))
        return HTTPConnection(host=self.host, port=self.port)

    def _get_conn(self, timeout=None):
        """
        Get a connection. Will return a pooled connection if one is available.
        Otherwise, a fresh connection is returned.
        """
        conn = None
        try:
            conn = self.pool.get(block=self.block, timeout=timeout)
        except Empty, e:
            pass # Oh well, we'll create a new connection then

        return conn or self._new_conn()

    def _put_conn(self, conn):
        """
        Put a connection back into the pool.
        If the pool is already full, the connection is discarded because we
        exceeded maxsize. If connections are discarded frequently, then maxsize
        should be increased.
        """
        try:
            self.pool.put(conn, block=False)
        except Full, e:
            # This should never happen if self.block == True
            log.warning("HttpConnectionPool is full, discarding connection: %s" % self.host)

    def urlopen(self, method, url, body=None, headers={}, retries=3, redirect=True):
        """
        Get a connection from the pool and perform an HTTP request.

        method
            HTTP request method (such as GET, POST, PUT, etc.)

        body
            Data to send in the request body (useful for creating POST requests,
            see HTTPConnectionPool.post_url for more convenience).

        headers
            Custom headers to send (such as User-Agent, If-None-Match, etc.)

        retries
            Number of retries to allow before raising a MaxRetryError exception.

        redirect
            Automatically handle redirects (status codes 301, 302, 303, 307),
            each redirect counts as a retry.
        """
        if retries < 0:
            raise MaxRetryError("Max retries exceeded for url: %s" % url)

        try:
            # Request a connection from the queue
            conn = self._get_conn()

            # Make the request
            self.num_requests += 1
            conn.request(method, url, body=body, headers=headers)
            conn.sock.settimeout(self.timeout)
            httplib_response = conn.getresponse()
            log.debug("\"%s %s %s\" %s %s" % (method, url, conn._http_vsn_str, httplib_response.status, httplib_response.length))

            # from_httplib will perform httplib_response.read() which will have
            # the side effect of letting us use this connection for another
            # request.
            response = HTTPResponse.from_httplib(httplib_response)

            # Put the connection back to be reused
            self._put_conn(conn)

        except (SocketTimeout, Empty), e:
            # Timed out either by socket or queue
            raise TimeoutError("Request timed out after %f seconds" % self.timeout)

        except (HTTPException, SocketError), e:
            log.warn("Retrying (%d attempts remain) after connection broken by '%r': %s" % (retries, e, url))
            return self.urlopen(method, url, body, headers, retries-1, redirect) # Try again

        # Handle redirection
        if redirect and response.status in [301, 302, 303, 307] and 'location' in response.headers: # Redirect, retry
            log.info("Redirecting %s -> %s" % (url, response.headers.get('location')))
            return self.urlopen(method, response.headers.get('location'), body, headers, retries-1, redirect)

        return response

    def get_url(self, url, fields={}, headers={}, retries=3, redirect=True):
        """
        Wrapper for performing GET with urlopen (see urlopen for more details).

        Supports an optional ``fields`` parameter of key/value strings. If
        provided, they will be added to the url.
        """
        if fields:
            url += '?' + urlencode(fields)
        return self.urlopen('GET', url, headers=headers, retries=retries, redirect=redirect)

    def post_url(self, url, fields={}, headers={}, retries=3, redirect=True):
        """
        Wrapper for performing POST with urlopen (see urlopen for more details).

        Supports an optional ``fields`` parameter of key/value strings AND
        key/filetuple. A filetuple is a (filename, data) tuple. For example:

        fields = {
            'foo': 'bar',
            'foofile': ('foofile.txt', 'contents of foofile'),
        }

        NOTE: If ``headers`` are supplied, the 'Content-Type' value will be
        overwritten because it depends on the dynamic random boundary string
        which is used to compose the body of the request.
        """
        body, content_type = encode_multipart_formdata(fields)
        headers.update({'Content-Type': content_type})
        return self.urlopen('POST', url, body, headers=headers, retries=retries, redirect=redirect)
