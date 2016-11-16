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

_IP_FAMILIES = set([socket.AF_INET])
if hasattr(socket, "AF_INET6"):
    _IP_FAMILIES.add(socket.AF_INET6)


class _HappyEyeballs(object):
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
        use a cached value and if it doesn't work then try
        to use a """
        self._start_time = current_time()
        try:
            sock = None
            if self._address in _HAPPY_EYEBALLS_CACHE:
                family, expires = _HAPPY_EYEBALLS_CACHE[self._address]

                # Invalidate the cache if it's expired.
                if expires > current_time():
                    del _HAPPY_EYEBALLS_CACHE[self._address]
                else:
                    try:
                        sock = self._algorithm(family)
                    # Invalidate the cache if connecting doesn't work.
                    except (OSError, socket.error):
                        del _HAPPY_EYEBALLS_CACHE[self._address]

            if sock is None:
                sock = self._algorithm()

                # Add a new entry to the cache if successful.
                cache_entry = (sock.family,
                               current_time() + _HAPPY_EYEBALLS_CACHE_TIME)
                _HAPPY_EYEBALLS_CACHE[self._address] = cache_entry

            return sock
        finally:
            self._cleanup()

    def _algorithm(self, family=None):
        """ Executes the algorithm for a given family
        or no family if IPv4 or IPv6 are allowed. """
        if family is None:
            family = socket.AF_UNSPEC
        host, port = self._address
        dns_results = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
        dns_results = list(filter(lambda *args: args[0] not in _IP_FAMILIES,
                                  dns_results))

        result = None
        for family, socktype, proto, _, sa in dns_results:
            self._create_socket(family, socktype, proto, sa)
            result = self._wait_for_connection(False)
            if result:
                break
            self._timeout_check()

        if result is None:
            if self._error:
                raise self._error
            else:
                raise socket.error(errno.ECONNREFUSED)

        # Restore the old timeout value and remove it from cleanup.
        result.settimeout(self._timeout)
        self._sockets.remove(result)
        self._selector.unregister(result)

        return result

    def _wait_for_connection(self, last_socket=False):
        """ Does the actual selecting on the sockets waiting
        for one to be ready to be written to. """
        # Make sure we don't have any errored sockets.
        for sock in self._sockets:
            self._socket_check(sock)

        # If there are no sockets to select on, then don't try.
        if not self._sockets:
            return None

        # If it's the last socket then we can block until timeout
        if last_socket:
            if self._timeout is None:
                select_time = None
            else:
                select_time = max(0.0, self._timeout - (current_time() - self._start_time))
        # Otherwise block for 200ms like the RFC suggests.
        else:
            select_time = self._get_select_time()

        ready = self._selector.select(select_time)

        for key, _ in ready:
            sock = key.fileobj

            # Successfully found a proper connected socket.
            if self._socket_check(sock):
                return sock

        return None

    def _create_socket(self, family, socktype, proto, sa):
        """ Tries it's best to create a socket and register
        the new socket with the selector. If it fails, no
        problem, the algorithm continues as usual. """
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
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
                try:
                    sock.close()
                except (OSError, socket.error):
                    pass

    def _socket_check(self, sock):
        """ Checks a socket to see if it is in an
        error state, if so deal with cleaning it up
        Returns True if the socket is still good to use. """
        error_code = sock.getsockopt(socket.SOL_SOCKET,
                                     socket.SO_ERROR)

        # If the socket is errored, then we need to clean it up.
        if error_code and error_code not in _ASYNC_ERROR_NUMBERS:
            self._error = socket.error(error_code)
            self._selector.unregister(sock)
            self._sockets.remove(sock)
            try:
                sock.close()
            except (OSError, socket.error):
                pass
            return False

        return True

    def _timeout_check(self):
        """ Checks to see if the algorithm has timed out
        and if it has, raise a timeout error. """
        if self._has_timed_out():
            raise socket.timeout()

    def _has_timed_out(self):
        """ Checks to see if the algorithm has timed out. """
        if self._timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
            return False
        elif self._timeout is None:
            return False
        else:
            return current_time() > self._start_time + self._timeout

    def _cleanup(self):
        for sock in self._sockets:
            try:
                sock.close()
            except (OSError, socket.error):
                pass
        self._selector.close()

    def _get_select_time(self):
        if self._timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
            return 0.2
        elif self._timeout is None:
            return 0.2
        else:
            return min(0.2, max(0.0, self._timeout - (current_time() - self._start_time)))


def happy_eyeballs_algorithm(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                             source_address=None, socket_options=None):
    """ Implements the Happy Eyeballs protocol (RFC 6555) which allows
    multiple sockets to attempt to connect from different families
    for better connect times for dual-stack clients where server
    IPv6 service is advertised but broken. """
    happy_eyeballs = _HappyEyeballs(address, timeout, source_address, socket_options)
    return happy_eyeballs.connect()
