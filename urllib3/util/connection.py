from __future__ import absolute_import
import socket
from urllib3.util.rfc6555 import (
    happy_eyeballs_algorithm
)
from .wait import wait_for_read
from .selectors import HAS_SELECT, SelectorError

# This global is here for the case where Happy
# Eyeballs Algorithm (RFC 6555) needs to be disabled
# such as for debugging a connection.
_ENABLE_HAPPY_EYEBALLS = True

# List of addresses for 'loopback'
_LOOPBACK_ADDRESSES = ['127.0.0.1', '::1']


def is_connection_dropped(conn):  # Platform-specific
    """
    Returns True if the connection is dropped and should be closed.

    :param conn: :class:`httplib.HTTPConnection` object.

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
        return bool(wait_for_read(sock, timeout=0.0))
    except SelectorError:
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

    # Don't connect using Happy Eyeballs if this is a loopback address.
    is_loopback = False

    # Save this information as it may be used later.
    addr_info = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)

    for af, _, _, _, sa in addr_info:
        if af == socket.AF_INET or af == socket.AF_INET6:
            if sa[0] in _LOOPBACK_ADDRESSES:
                is_loopback = True
                break

    # If IPv6 and selectors are available, use the Happy Eyeballs algorithm.
    # (RFC 6555 https://tools.ietf.org/html/rfc6555)
    if not is_loopback and HAS_IPV6 and HAS_SELECT and _ENABLE_HAPPY_EYEBALLS:
        return happy_eyeballs_algorithm((host, port), timeout,
                                        source_address, socket_options)

    for af, socktype, proto, canonname, sa in addr_info:
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
