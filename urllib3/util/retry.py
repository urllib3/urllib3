import errno
try: # Python 3
    from http.client import (
        BadStatusLine,
        CannotSendRequest,
        IncompleteRead,
        InvalidURL,
        NotConnected,
        ResponseNotReady,
        UnknownProtocol,
    )
except ImportError:
    from httplib import (
        BadStatusLine,
        CannotSendRequest,
        IncompleteRead,
        InvalidURL,
        NotConnected,
        ResponseNotReady,
        UnknownProtocol,
    )
from socket import error as SocketError
import time

from ..packages import six

from ..exceptions import (
    ConnectTimeoutError,
    ReadTimeoutError,
)

xrange = six.moves.xrange


SOCKET_CONNECT_EXCEPTIONS = frozenset([errno.ENETUNREACH, errno.ECONNREFUSED])


class Retry(object):
    """ Utility object for storing information about retry attempts

    Example usage::

        retries = urllib3.util.Retry(connect=10, read=2,
            codes_whitelist=[429, 500, 503])
        pool = HTTPConnectionPool('www.google.com', 80)
        pool.request(retries=retries)

    :param total:
        The total number of errors to allow. Omitting the parameter means the
        bottleneck becomes the specified number of errors for each sub-type
        (connect, read, redirect).

        If ``total`` is specified and is greater than any specific limit
        (``connect``, ``read``, ``redirect``), the ``total`` value will take
        precedence. If the total is specified and is lower than any specific
        limit (``connect``, ``read``, ``redirect``), the specific limit will take
        precedence.

    :type total: An integer number of retries, or None to specify that
        you'd like to use urllib3's defaults for specific limits.

    :param int connect:
        How many times to retry on connection errors.

        A connection error is one that is raised before the request is sent
        to the remote server. Once it has been sent to the remote server,
        the server may begin processing the request, which can lead to bad
        consequences and is handled in the read section below. Connection errors
        in general are good candidates for retries because the remote server
        hasn't received any data.

    :param int read:
        How many times to retry on read errors.

        A read error is one that is raised after the request has been sent to
        the server. Even though we didn't get a response back from the server,
        these exceptions are different than connection errors, because they
        imply the the remote server accepted the request. The server may have
        begun processing the request and performed some side effects (wrote
        data to a database, sent a message, etc).

    :param int redirects:
        How many times to retry on redirect responses.

        A redirect is a HTTP response with a status code 301, 302, 303, 307 or
        308. Specify this parameter to instruct urllib3 to follow redirects, up
        to this many times.

    :param frozenset method_whitelist:
        A list of HTTP methods that we should retry on.

        Some HTTP methods are `idempotent`: a request is idempotent if the
        world ends up in the same state whether you try the request once or
        a hundred times. For example, consider making a POST request to send
        a message. The recipient may receive a new copy of the same message
        for each time you send the request, meaning that another retry is not
        `safe`. By contrast, if the server accepts a PUT request to send a
        message, this implies that the server can detect whether the message
        has been sent already, and ensure that only one copy makes it to the
        recipient.

        The method_whitelist defaults to the subset of HTTP methods that are
        idempotent, and good candidates for retries.

    :param set codes_whitelist:
        A set of HTTP status codes that we should retry on.

        By default, the ``codes_whitelist`` is empty. urllib3 provides
        the following convenience values that you can specify.
        ``SERVER_ERROR_RESPONSE`` will retry any 5xx status code.
        ``NON_200_RESPONSE`` will retry any non-200 level response. You may
        want to pass a custom set of codes here depending on the logic in your
        server.

    :param float backoff_factor:
        A backoff factor to apply between attempts. urllib3 will sleep for::

            (backoff factor * (2 ^ (number of total retries - 1))

        seconds. So if the backoff factor is 1, urllib3 will sleep 1, 2, 4,
        8... seconds between retries. If the backoff factor is 0.5, urllib3
        will sleep 0.5, 1, 2, 4... seconds between retries.

        By default, the backoff factor is 0, which means that urllib3 will not
        sleep between retry attempts.

    :param bool raise_on_redirect: Whether, if the number of redirects is
        exhausted, to raise a MaxRetryError, or to return a response with a
        response code in the 3xx range.

    :param int observed_errors: The number of errors observed so far. This is
        used to compute the backoff time and other factors.
    """

    DEFAULT_METHOD_WHITELIST = frozenset([
        'HEAD', 'GET', 'PUT', 'DELETE', 'OPTIONS', 'TRACE'])
    SERVER_ERROR_RESPONSE = frozenset(xrange(500, 599))
    NON_200_RESPONSE = frozenset(xrange(300, 599))

    # A connection error is one that is raised before the request is sent to
    # the remote server. Once it has been sent to the remote server, the server
    # may begin processing the request, which can lead to bad consequences and
    # is handled in the read section below. Connection errors in general are
    # retryable because the remote server hasn't received any data.
    CONNECT_EXCEPTIONS = (
            CannotSendRequest, NotConnected, InvalidURL, ConnectTimeoutError)

    # Even though we didn't get a response back from the server, these
    # exceptions are different than connection errors, because they imply
    # the the remote server accepted the request. The server may have begun
    # processing the request and performed some side effects (wrote data to a
    # database, sent a message, etc).
    READ_EXCEPTIONS = (
            BadStatusLine, IncompleteRead, ResponseNotReady, UnknownProtocol,
            ReadTimeoutError)

    def __init__(self, total=None, connect=3, read=0, redirects=3,
                 observed_errors=0,
                 method_whitelist=DEFAULT_METHOD_WHITELIST, codes_whitelist=None,
                 backoff_factor=0, raise_on_redirect=True):

        self.total = total
        self.connect = connect
        self.read = read
        self.redirects = redirects
        self.codes_whitelist = codes_whitelist or set()
        self.method_whitelist = method_whitelist
        self.backoff_factor = backoff_factor
        self.raise_on_redirect = raise_on_redirect
        self.observed_errors = observed_errors

    def new(self, total=None, connect=3, read=0, redirects=3, observed_errors=0):
        return self.__class__(
            total=total,
            connect=connect, read=read, redirects=redirects,
            backoff_factor=self.backoff_factor,
            observed_errors=observed_errors,
            raise_on_redirect=self.raise_on_redirect,
        )

    def get_backoff_time(self):
        """ Formula for computing the current backoff

        :rtype: float
        """
        return self.backoff_factor * (2 ** max(self.observed_errors - 1, 0))

    def sleep(self):
        """ Sleep between retry attempts using an exponential backoff.

        By default, the backoff factor is 0 and this method will return
        immediately.
        """
        backoff = self.get_backoff_time()
        if backoff <= 0:
            return
        time.sleep(backoff)

    def _is_connection_error(self, err):
        """ Determine whether an error was a connection error """
        if err is None:
            return False

        if (isinstance(err, SocketError)
            and hasattr(err, 'errno')
            and (err.errno in SOCKET_CONNECT_EXCEPTIONS)):
            return True
        if isinstance(err, self.CONNECT_EXCEPTIONS):
            return True
        return False

    def is_retryable(self, method, response=None, error=None):
        """ Is this method/response retryable? (Based on method/codes whitelists)
        """
        if self.is_exhausted():
            return False

        if isinstance(error, self.READ_EXCEPTIONS):
            return True

        return (
            method in self.method_whitelist
            and response
            and response.status in self.codes_whitelist)

    def is_exhausted(self):
        """ Are we out of retries?
        """
        if self.total is not None and self.total < 0:
            return True
        return min(self.connect, self.read, self.redirects) < 0


    def increment(self, method='GET', response=None, error=None):
        """ Return a new Retry object with incremented retry counters.

        :param response: A response object, or None, if the server did not
            return a response.
        :type response: :class:`~urllib3.response.HTTPResponse`
        :param Exception error: An error encountered during the request, or
            None if the response was received successfully.

        :return: A new Retry object.
        """
        # The idea behind this is that a Retry object should be immutable. Once
        # counts are created for the object, they shouldn't be changed. Retries
        # are incremented by creating new objects.
        total = self.total is not None and self.total - 1

        # Create a helper variable to keep track of observed_errors (used to
        # compute the backoff factor). It would be simpler to increment this
        # everywhere, because we don't want to inflate the sleep counter in the
        # event of redirects.
        observed_errors = self.observed_errors

        # Connect retry?
        connect = self.connect
        if self._is_connection_error(error):
            connect -= 1
            observed_errors += 1

        # Redirect retry?
        redirects = self.redirects
        if response and response.get_redirect_location():
            redirects -= 1

        # Read retry?
        read = self.read
        if self.is_retryable(method, response=response, error=error):
            read = self.read - 1
            observed_errors += 1

        return self.new(
            total=total,
            connect=connect, read=read, redirects=redirects,
            observed_errors=observed_errors)


    def __str__(self):
        return ('{clsname}(count={total_errors})'.format(
            clsname=type(self).__name__,
            total_errors=self.observed_errors,
        ))
