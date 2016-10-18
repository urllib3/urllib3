from __future__ import absolute_import
import socket

try:
    # `select` doesn't exist on AppEngine.
    import select
except ImportError:
    select = False


def wait_to_read_data(sock, timeout=0.0):
    has_poll = hasattr(select, 'poll')
    has_epoll = hasattr(select, 'epoll')
    has_kevent = hasattr(select, 'kevent')
    has_kqueue = hasattr(select, 'kqueue')
    if has_poll or has_epoll:
        if has_epoll:
            _poll = select.epoll
            read_flag = select.EPOLLIN
            exc_flag = select.EPOLLERR
        else:
            _poll = select.poll
            read_flag = select.POLLIN
            exc_flag = select.POLLERR
        p = _poll()
        p.register(sock.fileno(), read_flag)
        rd = p.poll(timeout)
    elif has_kevent and has_kqueue:
        kq = select.kqueue()
        flags = select.KQ_EV_ADD | select.KQ_EV_ENABLE
        ke = select.kevent(sock.fileno(), filter=select.KQ_FILTER_READ, flags=flags)
        rd = kq.control([ke], 1, timeout)
    else:
        rd, _, _ = select.select([sock], [], [], timeout)
    return rd


def wait_to_write_data(sock, timeout=0.0):
    has_poll = hasattr(select, 'poll')
    has_epoll = hasattr(select, 'epoll')
    has_kevent = hasattr(select, 'kevent')
    has_kqueue = hasattr(select, 'kqueue')
    if has_poll or has_epoll:
        if has_epoll:
            _poll = select.epoll
            write_flag = select.EPOLLOUT
            exc_flag = select.EPOLLERR
        else:
            _poll = select.poll
            write_flag = select.POLLOUT
            exc_flag = select.POLLERR
        p = _poll()
        p.register(sock.fileno(), write_flag)
        wlist = p.poll(timeout)
    elif has_kevent and has_kqueue:
        kq = select.kqueue()
        flags = select.KQ_EV_ADD | select.KQ_EV_ENABLE
        ke = select.kevent(sock.fileno(), filter=select.KQ_FILTER_WRITE, flags=flags)
        wlist = kq.control([ke], 1, timeout)
    else:
        _, wlist, _ = select.select([], [sock], [], timeout)
    return wlist


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

    if not select:
        return False

    try:
        return wait_to_read_data(sock)
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
                sock = None

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
