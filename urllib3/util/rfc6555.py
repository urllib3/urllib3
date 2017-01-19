import errno
import socket
from urllib3.util.selectors import (
    DefaultSelector,
    EVENT_WRITE
)
from urllib3.util.timeout import current_time


_HAPPY_EYEBALLS_CACHE = {}
_HAPPY_EYEBALLS_CACHE_TIME = 60 * 10  # 10 minutes according to RFC 6555
_ASYNC_ERROR_NUMBERS = set([errno.EINPROGRESS,
                            errno.EAGAIN,
                            errno.EWOULDBLOCK])
if hasattr(errno, "WSAEWOULDBLOCK"):  # Platform-specific: Windows
    _ASYNC_ERROR_NUMBERS.add(errno.WSAEWOULDBLOCK)

_IP_FAMILIES = set([socket.AF_INET, socket.AF_INET6])


def _safely_close_socket(sock):
    """ Close a socket and guarantee it won't
    error as Python 3.4< can actually error
    on socket closure if it's interrupted. """
    try:
        sock.close()
    except (OSError, socket.error):
        pass


class _HappyEyeballs(object):
    """ One-time use object that implements RFC 6555, should
    not be instantiated directly, instead use the happy_eyeballs_algorithm
    function which uses this class as a helper. """
    def __init__(self, address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                 source_address=None, socket_options=None):
        self._address = address
        self._error = None
        self._timeout = timeout
        self._source_address = source_address
        self._socket_options = socket_options
        self._sockets = []
        self._selector = DefaultSelector()
        self._start_time = None

    def connect(self):
        """ Given the setup of the algorithm, attempt to
        use a cached value for socket family.  If no cached
        value exists or the cached value fails, follow RFC 6555
        in order to determine whether to use AF_INET or AF_INET6
        to connect to the remote host. """
        sock = self._connect_cached_socket_family()

        if sock is None:
            sock = self._connect_first_socket_family()
            # Only add an entry to the cache if it's
            # newly connected to, don't 'refresh' the cache
            # whenever it's used.
            self._cache_socket_family(sock.family)
        return sock

    def _cache_socket_family(self, family):
        """ Add a socket family to the cache for the
         address that is currently being connected to. """
        cache_entry = (family, current_time() + _HAPPY_EYEBALLS_CACHE_TIME)
        _HAPPY_EYEBALLS_CACHE[self._address] = cache_entry

    def _connect_cached_socket_family(self):
        """ If there is a cached value for socket
        family for a given host / port combo and the
        cached value is still valid, try that value first. """
        sock = None
        if self._address in _HAPPY_EYEBALLS_CACHE:
            family, expires = _HAPPY_EYEBALLS_CACHE[self._address]

            # Invalidate the cache if it's expired.
            if expires > current_time():
                del _HAPPY_EYEBALLS_CACHE[self._address]
            else:
                try:
                    sock = self._connect_first_socket_family(family)
                # Invalidate the cache if connecting doesn't work.
                except (OSError, socket.error):
                    del _HAPPY_EYEBALLS_CACHE[self._address]

        return sock

    def _connect_first_socket_family(self, family=socket.AF_UNSPEC):
        """ Executes the algorithm for a given family
        or no family if IPv4 or IPv6 are allowed. """
        self._start_time = current_time()
        host, port = self._address
        dns_results = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
        dns_results = [result for result in dns_results if result[0] in _IP_FAMILIES]

        # If we don't have any proper DNS results left,
        # then we should raise a GAI error.
        if not dns_results:
            raise socket.gaierror()

        result = None
        for family, socktype, proto, _, sa in dns_results:
            self._create_socket(family, socktype, proto, sa)
            result = self._wait_for_connection()
            if result:
                break
            self._timeout_check()
        else:
            if self._error:
                raise self._error

        if result is None:
            raise socket.timeout()

        return result

    def _wait_for_connection(self):
        """ Does the actual selecting on the sockets waiting
        for one to be ready to be written to. """
        # Make sure we don't have any errored sockets.
        self._remove_errored_sockets()

        # If there are no sockets to select on, then don't try.
        if not self._sockets:
            return None

        ready = self._selector.select(self._calculate_select_time())

        for key, _ in ready:
            sock = key.fileobj

            # If the socket is not in an error state we can use it.
            if not self._is_socket_errored(sock):

                # Restore the old timeout value and remove it from cleanup.
                sock.settimeout(self._timeout)
                self._sockets.remove(sock)
                self._selector.unregister(sock)

                return sock

        return None

    def _create_socket(self, family, socktype, proto, sa):
        """ Tries its best to create a socket and register
        the new socket with the selector. If it fails, no
        problem, the algorithm continues as usual. """
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)

            # If the global socket timeout is used, then we must
            # figure out this value as soon as possible from an
            # actual socket object as it's the only way to tell
            # for sure what this value truly is when we use it.
            if self._timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
                self._timeout = sock.gettimeout()

            if self._socket_options:
                for opt in self._socket_options:
                    sock.setsockopt(*opt)

            if self._source_address:
                sock.bind(self._source_address)

            # Set the socket to non-blocking so we can select it.
            sock.settimeout(0.0)

            error_code = sock.connect_ex(sa)
            if error_code and error_code not in _ASYNC_ERROR_NUMBERS:
                self._error = socket.error(error_code)
            else:
                self._sockets.append(sock)
                self._selector.register(sock, EVENT_WRITE)
        except (socket.error, OSError) as e:
            self._error = e
            if sock is not None:
                _safely_close_socket(sock)

    def _remove_errored_sockets(self):
        """ Removes all errored sockets from tracking. """
        for sock in self._sockets:
            self._is_socket_errored(sock)

    def _is_socket_errored(self, sock):
        """ Checks a socket to see if it is in an
        error state, if so deal with cleaning it up. """
        error_code = sock.getsockopt(socket.SOL_SOCKET,
                                     socket.SO_ERROR)

        # If the socket is errored, then we need to clean it up.
        if error_code and error_code not in _ASYNC_ERROR_NUMBERS:
            self._error = socket.error(error_code)
            self._selector.unregister(sock)
            self._sockets.remove(sock)
            _safely_close_socket(sock)
            return True

        return False

    def _timeout_check(self):
        """ Checks to see if the algorithm has timed out
        and if it has, raise a timeout error. """
        if self._has_timed_out():
            raise socket.timeout()

    def _has_timed_out(self):
        """ Checks to see if the algorithm has timed out. """
        if self._timeout is None:
            return False
        else:
            return current_time() > self._start_time + self._timeout

    def _cleanup(self):
        for sock in self._sockets:
            _safely_close_socket(sock)
        self._selector.close()

    def _calculate_select_time(self):
        if self._timeout is None:
            return 0.2
        else:
            return min(0.2, max(0.0, self._timeout - (current_time() - self._start_time)))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._cleanup()


def happy_eyeballs_algorithm(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                             source_address=None, socket_options=None):
    """ Implements the Happy Eyeballs protocol (RFC 6555) which allows
    multiple sockets to attempt to connect from different families
    for better connect times for dual-stack clients where server
    IPv6 service is advertised but broken. """
    with _HappyEyeballs(address, timeout, source_address, socket_options) as happy_eyeballs:
        return happy_eyeballs.connect()
