from __future__ import absolute_import, with_statement
import errno
import socket
from urllib3.util.selectors import (
    HAS_SELECT,
    DefaultSelector,
    EVENT_WRITE,
    wait_for_read
)

try:  # time.monotonic is Python 3.x only
    from time import monotonic
except ImportError:
    from time import time as monotonic


def is_connection_dropped(conn):  # Platform-specific
    """
    Returns True if the connection is dropped and should be closed.

    :param conn:
        :class:`httplib.HTTPConnection` object.

    Note: For platforms like AppEngine, this will always return ``False`` to
    let the platform handle connection recycling transparently for us.
    """
    sock = getattr(conn, 'sock', False)
    if sock is False:  # Platform-specific: AppEngine
        return False

    if sock is None:  # Connection already closed (such as by httplib).
        return True

    if not HAS_SELECT: # Platform-specific: AppEngine
        return False

    try:
        return wait_for_read(sock, 0.0)
    except socket.error:
        return True


# This function is copied from socket.py in the Python 2.7 standard
# library test suite. Added to its signature is only `socket_options`.
# One additional modification is that we avoid binding to IPv6 servers
# discovered in DNS if the system doesn't have IPv6 functionality.
def create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                      source_address=None, socket_options=None):
    """Connect to *address* and return the socket object.

    Convenience function.  Connect to *address* (a 2-tuple ``(host,
    port)``) and return the socket object.  Passing the optional
    *timeout* parameter will set the timeout on the socket instance
    before attempting to connect.  If no *timeout* is supplied, the
    global default timeout setting returned by :func:`getdefaulttimeout`
    is used.  If *source_address* is set it must be a tuple of (host, port)
    for the socket to bind as a source address before making the connection.
    An host of '' or port 0 tells the OS to use the default.
    """

    host, port = address
    if host.startswith('['):
        host = host.strip('[]')
    err = None

    # Using the value from allowed_gai_family() in the context of getaddrinfo lets
    # us select whether to work with IPv4 DNS records, IPv6 records, or both.
    # The original create_connection function always returns all records.
    family = allowed_gai_family()

    # If IPv6 and selectors are available, use the Happy Eyes algorithm.
    # (RFC 6555 https://tools.ietf.org/html/rfc6555)
    if HAS_HAPPY_EYEBALLS and ENABLE_HAPPY_EYEBALLS:
        return _connect_happy_eyeballs((host, port), timeout,
                                       source_address, socket_options)

    for res in socket.getaddrinfo(host, port, family, socket.SOCK_STREAM):
        af, socktype, proto, canonname, sa = res
        sock = None
        try:
            sock = socket.socket(af, socktype, proto)

            # If provided, set socket level options before connecting.
            _set_socket_options(sock, socket_options)

            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sa)
            return sock

        except socket.error as e:
            err = e
            if sock is not None:
                sock.close()

    if err is not None:
        raise err

    raise socket.error("getaddrinfo returns an empty list")


def _set_socket_options(sock, options):
    if options is None:
        return

    for opt in options:
        sock.setsockopt(*opt)


def _connect_happy_eyeballs(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                            source_address=None, socket_options=None):
    """ Implements the Happy Eyeballs protocol (RFC 6555) which allows
    multiple sockets to attempt to connect from different families
    for better connect times for dual-stack clients where server
    IPv6 service is advertised but broken. """
    result = None  # This is the actual connected socket eventually.
    err = None
    family = 0

    # We need to keep track of the time so we don't exceed timeout.
    start_time = monotonic()
    if timeout is not None and timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
        timeout_time = start_time + timeout
    else:
        timeout_time = None

    # Check the cache to see if our address is already there.
    if address in HAPPY_EYEBALLS_CACHE:
        family, expires = HAPPY_EYEBALLS_CACHE[address]

        # If the cache entry is expired, don't use it.
        if start_time < expires:
            del HAPPY_EYEBALLS_CACHE[address]
            family = 0

    host, port = address
    socks = []

    # Make sure we close the selector after we're done.
    with DefaultSelector() as selector:

        # Perform a DNS lookup for the address for IPv4 or IPv6 families.
        if not family:
            family = allowed_gai_family()

        dns_results = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
        dns_results_len = len(dns_results)

        for i in range(dns_results_len):
            af, socktype, proto, canonname, sa = dns_results[i]

            # We only care about IPv4 and IPv6 addresses.
            if af not in [socket.AF_INET, socket.AF_INET6]:
                continue

            sock = None
            try:
                sock = socket.socket(af, socktype, proto)

                _set_socket_options(sock, socket_options)

                # If we're given a source address, bind to it.
                if source_address:
                    sock.bind(source_address)

                # Set non-blocking for selecting.
                sock.settimeout(0.0)

                # Connect to the host.
                errcode = sock.connect_ex(sa)
                if errcode and errcode not in [errno.EINPROGRESS,
                                               errno.EAGAIN,
                                               errno.ENOTCONN]:
                    raise socket.error(errcode)

                # Register this new socket with the selector.
                socks.append(sock)

                # Using EVENT_WRITE to detect a connection.
                selector.register(sock, EVENT_WRITE)

            except (socket.error, OSError) as e:
                err = e
                if sock is not None:
                    sock.close()

            # This is where the selecting logic occurs. Once all sockets
            # have been created and are added to the selector, they should
            # be continually selected until one of them works.  If there are
            # still sockets to add to the selector, then select for only 200
            # ms before adding the next socket to the selector.
            reattempt_select = True
            while reattempt_select:
                if i < dns_results_len - 1:
                    # If this isn't the last socket to try, then only try
                    # for 200 ms before adding the next preferred connection
                    # to the selector. The 200 ms constant is the recommended
                    # value by the RFC.
                    select_time = 0.2
                    reattempt_select = False  # Only want one round.
                else:
                    # Here we need to calculate how long we're willing to wait
                    # as there are no sockets left to add to the selector.
                    if timeout_time is not None:
                        # If there are no more entries to add to the selector
                        # we're going to keep trying until we either find
                        # a socket without errors or we run out of time
                        # to establish a connection.
                        select_time = timeout_time - monotonic()

                        # We do this for safety reasons, as negative timeout
                        # may mean no timeout for certain selectors.
                        if select_time < 0.0:
                            break
                    else:
                        # Otherwise we're willing to block forever.
                        select_time = None

                connected = selector.select(timeout=select_time)

                # Iterate over the sockets that are reporting writable.
                for key, _ in connected:
                    # Check to see if there's an error post-connection.
                    conn = key.fileobj
                    errcode = conn.getsockopt(socket.SOL_SOCKET,
                                              socket.SO_ERROR)
                    if errcode and errcode not in [
                        errno.EAGAIN, errno.EINPROGRESS
                    ]:
                        selector.unregister(conn)
                        try:
                            socks.remove(conn)
                            conn.close()
                        except (OSError, socket.error) as e:
                            err = e
                        continue

                    # Finally found a suitable socket!
                    if errcode == 0:
                        # Make sure to remove from socks to avoid closing.
                        result = conn
                        socks.remove(conn)
                        break

                if result:
                    break

                # Empty list means that we timed out as system call
                # interrupts don't affect us here anymore.
                if not len(connected):
                    break

                # If there are no more sockets to look through, then
                # we should give up immediately with a non-timeout error.
                if not len(socks) and i == dns_results_len - 1:
                    err = ConnectionRefusedError()
                    break

            if result:
                break

        # Close all the sockets that weren't used.
        for sock in socks:
            try:
                sock.close()
            except (OSError, socket.error):
                pass

        if result:
            # If we found a successful result, cache it here.
            expire_time = monotonic() + HAPPY_EYEBALLS_CACHE_TIME
            HAPPY_EYEBALLS_CACHE[address] = (result.family, expire_time)

            # Restore the old timeout here.
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                result.settimeout(timeout)
            else:
                result.settimeout(None)
            return result

        if err:
            raise err

        # Otherwise if there's no other errors we timed out.
        raise TimeoutError


def allowed_gai_family():
    """This function is designed to work in the context of
    getaddrinfo, where family=socket.AF_UNSPEC is the default and
    will perform a DNS search for both IPv6 and IPv4 records."""

    family = socket.AF_INET
    if HAS_IPV6:
        family = socket.AF_UNSPEC
    return family


def _has_ipv6(host):
    """ Returns True if the system can bind an IPv6 address. """
    sock = None
    has_ipv6 = False

    if socket.has_ipv6:
        # has_ipv6 returns true if cPython was compiled with IPv6 support.
        # It does not tell us if the system has IPv6 support enabled. To
        # determine that we must bind to an IPv6 address.
        # https://github.com/shazow/urllib3/pull/611
        # https://bugs.python.org/issue658327
        try:
            sock = socket.socket(socket.AF_INET6)
            sock.bind((host, 0))
            has_ipv6 = True
        except Exception:
            pass

    if sock:
        sock.close()
    return has_ipv6

HAS_IPV6 = _has_ipv6('::1')
HAS_HAPPY_EYEBALLS = HAS_SELECT and HAS_IPV6
ENABLE_HAPPY_EYEBALLS = True  # Provided to optionally disable this feature.
HAPPY_EYEBALLS_CACHE = {}
HAPPY_EYEBALLS_CACHE_TIME = 600  # 10 minutes, as defined by the RFC.
