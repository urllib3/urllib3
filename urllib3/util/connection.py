from __future__ import absolute_import
import errno
import socket
import select
import time
from .wait import (
    wait_for_read,
    wait_for_write,
    HAS_SELECT
)


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

    if not HAS_SELECT:
        return False

    try:
        return wait_for_read(sock, timeout=0)
    except select.error:
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

    # If IPv6 and select are available, use the Happy Eyes protocol.
    # (RFC 6555 https://tools.ietf.org/html/rfc6555)
    if HAS_HAPPY_EYES:
        return _connect_happy_eyes((host, port), timeout,
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


def _connect_happy_eyes(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                        source_address=None, socket_options=None):
    """ Implements the Happy Eyes protocol (RFC 6555) which allows
    multiple sockets to attempt to connect from different families
    for better connect times for dual-stack clients where server
    IPv6 service is advertised but broken. """
    err = None

    if address in HAPPY_EYES_CACHE:
        family, proto, expires = HAPPY_EYES_CACHE[address]

        # If the cache entry is expired, don't use it.
        if time.time() < expires:
            del HAPPY_EYES_CACHE[address]

        # Otherwise try to use the entry right away, if this
        # fails then run the Happy Eyes protocol again.
        else:
            sock = None
            try:
                sock = socket.socket(family, socket.SOCK_STREAM, proto)

                _set_socket_options(sock, socket_options)

                if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    sock.settimeout(timeout)
                if source_address:
                    sock.bind(source_address)

                sock.connect(address)
                return sock
            except socket.error as e:
                err = e
                sock.close()

    # Couldn't find a cached value or cached value didn't work.
    host, port = address
    socks = []

    # Perform a DNS lookup for the address for IPv4 or IPv6 families.
    family = allowed_gai_family()
    for res in socket.getaddrinfo(host, port, family, socket.SOCK_STREAM):
        af, socktype, proto, canonname, sa = res

        # Create and connect the socket for each address we get back.
        sock = None
        try:
            sock = socket.socket(af, socktype, proto)

            _set_socket_options(sock, socket_options)

            if source_address:
                sock.bind(source_address)
            sock.settimeout(0)  # Make the socket non-blocking to use select.

            # We should catch all errors except all non-blocking error codes.
            errcode = sock.connect_ex(sa)
            if errcode not in [errno.EINPROGRESS,
                               errno.EAGAIN,
                               errno.ENOTCONN]:
                raise socket.error(errcode)

            socks.append(sock)

        except socket.error as e:
            err = e
            if sock is not None:
                sock.close()

    found = None
    while socks:
        select_timeout = timeout
        if timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
            select_timeout = None

        # Use select to detect which sockets are connected.
        connected = wait_for_write(socks, timeout=select_timeout)
        connected = [sock for sock in socks if sock.fileno() in connected]

        # If no sockets are ready, then we timed out.
        if not connected:
            err = socket.error(errno.ETIMEDOUT)
            for sock in socks:
                sock.close()
            break

        # For each "connected" socket, check that it didn't error out.
        for sock in connected:
            socks.remove(sock)

            errcode = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if errcode:
                sock.close()
                err = socket.error(errcode)
                continue

            found = sock

            # If the socket is IPv6 then we'll use it, otherwise we
            # should give the other sockets a chance just in case
            # an IPv4 socket finished first. Always prefer IPv6.
            if found.family == socket.AF_INET6:
                break

        if found is not None:
            break

    for sock in socks:
        sock.close()

    if found:
        # We found a proper socket, set the timeout now.
        if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
            found.settimeout(timeout)
        else:
            found.settimeout(None)

        # Cache the results of Happy Eyes protocol.
        expires = time.time() + HAPPY_EYES_CACHE_TIME
        HAPPY_EYES_CACHE[address] = (found.family, found.proto, expires)

        return found

    if err is not None:
        raise err

    raise socket.error("getaddrinfo returns an empty list")


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
HAS_HAPPY_EYES = select and HAS_IPV6
HAPPY_EYES_CACHE = {}
HAPPY_EYES_CACHE_TIME = 600
