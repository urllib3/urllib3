import time
import errno
from socket import error as SocketError

try: # Python 3
    from http.client import (
        BadStatusLine,
        ImproperConnectionState,
        IncompleteRead,
        InvalidURL,
        UnknownProtocol,
    )
except ImportError:
    from httplib import (
        BadStatusLine,
        ImproperConnectionState,
        IncompleteRead,
        InvalidURL,
        UnknownProtocol,
    )

from ..exceptions import (
    ConnectTimeoutError,
    ReadTimeoutError,
)


SOCKET_CONNECT_EXCEPTIONS = frozenset([errno.ENETUNREACH, errno.ECONNREFUSED])


class Retry(object):
    """ Granular retry configuration.

    This object should be treated as immutable. Each retry creates a new Retry
    object with updated values.

    Example usage::

        retries = urllib3.util.Retry(connect=5, read=2,
            status_forcelist=[429, 500, 503])
        pool = HTTPConnectionPool('www.google.com', 80)
        pool.request(retries=retries)

    :param int total:
        Total number of retries to allow. Takes precedence over other counts.

        Set to ``None`` to remove this constraint and fall back on other
        counts. It's a good idea to set this to some sensibly-high value to
        account for unexpected edge cases and avoid infinite retry loops.

        Set to ``0`` to fail on the first retry.

    :param int connect:
        How many connection-related errors to retry on.

        These are errors raised before the request is sent to the remote server,
        which we assume has not triggered the server to process the request.

        Set to ``0`` to fail on the first retry of this type.

    :param int read:
        How many times to retry on read errors.

        These errors are raised after the request was sent to the server, so the
        request may have side-effects.

        Set to ``0`` to fail on the first retry of this type.

    :param int redirect:
        How many redirects to perform. Limit this to avoid infinite redirect
        loops.

        A redirect is a HTTP response with a status code 301, 302, 303, 307 or
        308.

        Set to ``0`` to fail on the first retry of this type.

        Set to ``False`` to disable and imply ``raise_on_redirect=False``.

    :param iterable method_whitelist:
        Set of uppercased HTTP method verbs that we should retry on.

        By default, we only retry on methods which are considered to be
        indempotent (multiple requests with the same parameters end with the
        same state). See :attr:`Retry.DEFAULT_METHOD_WHITELIST`.

    :param iterable status_forcelist:
        A set of HTTP status codes that we should force a retry on. 

        By default, this is disabled with ``None``.

    :param float backoff_factor:
        A backoff factor to apply between attempts. urllib3 will sleep for::

            {backoff factor} * (2 ^ ({number of total retries} - 1))

        seconds. If the backoff_factor is 0.1, then each retry will sleep for
        [0.1s, 0.2s, 0.4s, ...] between retries. It will never be longer than
        :attr:`Retry.MAX_BACKOFF`.

        By default, backoff is disabled (set to 0).

    :param bool raise_on_redirect: Whether, if the number of redirects is
        exhausted, to raise a MaxRetryError, or to return a response with a
        response code in the 3xx range.

    :param int observed_errors: The number of errors observed so far. This is
        used to compute the backoff time and other factors.
    """

    DEFAULT_METHOD_WHITELIST = frozenset([
        'HEAD', 'GET', 'PUT', 'DELETE', 'OPTIONS', 'TRACE'])

    # A connection error is one that is raised before the request is sent to
    # the remote server. Once it has been sent to the remote server, the server
    # may begin processing the request, which can lead to bad consequences and
    # is handled in the read section below. Connection errors in general are
    # retryable because the remote server hasn't received any data.
    CONNECT_EXCEPTIONS = (
            ImproperConnectionState, InvalidURL, ConnectTimeoutError)

    # Even though we didn't get a response back from the server, these
    # exceptions are different than connection errors, because they imply
    # the the remote server accepted the request. The server may have begun
    # processing the request and performed some side effects (wrote data to a
    # database, sent a message, etc).
    READ_EXCEPTIONS = (
            BadStatusLine, IncompleteRead, UnknownProtocol, ReadTimeoutError)


    #: Maximum backoff value.
    BACKOFF_MAX = 120

    def __init__(self, total=10, connect=None, read=None, redirect=None,
                 observed_errors=0,
                 method_whitelist=DEFAULT_METHOD_WHITELIST, status_forcelist=None,
                 backoff_factor=0, raise_on_redirect=True):

        self.total = total
        self.connect = connect
        self.read = read
        self.redirect = redirect # XXX: singular?

        if redirect is False:
            self.redirect = 0
            raise_on_redirect = False

        self.status_forcelist = status_forcelist or set()
        self.method_whitelist = method_whitelist
        self.backoff_factor = backoff_factor
        self.raise_on_redirect = raise_on_redirect
        self.observed_errors = observed_errors # XXX: use .history instead?

    @property
    def count(self):
        # XXX: This is wrong right now.
        return self.observed_errors

    def new(self, total=None, connect=3, read=0, redirect=3, observed_errors=0):
        return type(self)(
            total=total,
            connect=connect, read=read, redirect=redirect,
            observed_errors=observed_errors,
            method_whitelist=self.method_whitelist,
            status_forcelist=self.status_forcelist,
            backoff_factor=self.backoff_factor,
            raise_on_redirect=self.raise_on_redirect,
        )

    def get_backoff_time(self):
        """ Formula for computing the current backoff

        :rtype: float
        """
        if self.observed_errors <= 1:
            return 0

        backoff_value = self.backoff_factor * (2 ** (self.observed_errors - 1))
        return min(self.BACKOFF_MAX, backoff_value)

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
        if isinstance(err, self.CONNECT_EXCEPTIONS):
            return True

        if not isinstance(err, SocketError):
            return False

        return getattr(err, 'errno') in SOCKET_CONNECT_EXCEPTIONS

    def _is_read_error(self, err):
        return isinstance(err, self.READ_EXCEPTIONS)

    def is_retryable(self, method, status_code=None, response=None):
        """ Is this method/response retryable? (Based on method/codes whitelists)
        """
        if self.is_exhausted():
            return False

        if self.method_whitelist and method.upper() not in self.method_whitelist:
            return False

        status_code = status_code or response and response.status
        if self.status_forcelist and status_code in self.status_forcelist:
            return True

        if not response:
            return status_code is None

        return bool(response.get_redirect_location())

    def is_exhausted(self):
        """ Are we out of retries?
        """
        if self.total is not None and self.total < 0:
            return True

        retry_counts = list(filter(None, (self.connect, self.read, self.redirect)))
        if not retry_counts:
            return False

        return min(retry_counts) < 0

    def increment(self, method='GET', response=None, error=None):
        """ Return a new Retry object with incremented retry counters.

        :param response: A response object, or None, if the server did not
            return a response.
        :type response: :class:`~urllib3.response.HTTPResponse`
        :param Exception error: An error encountered during the request, or
            None if the response was received successfully.

        :return: A new Retry object.
        """
        total = self.total
        if total is not None:
            total -= 1

        observed_errors = self.observed_errors
        connect = self.connect
        read = self.read
        redirect = self.redirect

        if self._is_connection_error(error):
            # Connect retry?
            observed_errors += 1
            if connect is not None:
                connect -= 1

        elif self._is_read_error(error):
            # Read retry?
            observed_errors += 1
            if read is not None:
                read -= 1

        elif response and response.get_redirect_location():
            # Redirect retry?
            if redirect is not None:
                redirect -= 1

        else:
            # FIXME: Nothing changed, scenario doesn't make sense.
            observed_errors += 1

        return self.new(
            total=total,
            connect=connect, read=read, redirect=redirect,
            observed_errors=observed_errors)


    def __repr__(self):
        return ('{cls.__name__}(total={self.total}, connect={self.connect}, '
                'read={self.read}, redirect={self.redirect})').format(
                    cls=type(self), self=self)

    def __str__(self):
        return '{cls.__name__}(total={total}, count={count})'.format(
                    cls=type(self), total=self.total+self.count, count=self.count)
