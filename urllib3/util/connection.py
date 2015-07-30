import socket
try:
    from select import poll, POLLIN, POLLOUT, POLLERR
except ImportError:  # `poll` doesn't exist on OSX and other platforms
    poll = False

try:
    from select import select
except ImportError:  # `select` doesn't exist on AppEngine.
    select = False

try:
    from select import epoll, EPOLLIN, EPOLLOUT, EPOLLERR
except ImportError:  # `epoll` only exists on Linux
    epoll = False

try:
    from select import kqueue, kevent
except ImportError:  # `kqueue` is only available for BSDs
    kevent = kqueue = False


def _poll(reads, writes, exceptions, timeout):
    # Assume that if we're being called then poll or epoll is defined
    pollfunc = poll
    read_flag = POLLIN
    write_flag = POLLOUT
    exc_flag = POLLERR

    if epoll:
        pollfunc = epoll
        read_flag = EPOLLIN
        write_flag = EPOLLOUT
        exc_flag = EPOLLERR

    p = pollfunc()
    for fd in reads:
        p.register(fd, read_flag)

    for fd in writes:
        p.register(fd, write_flag)

    for fd in exceptions:
        p.register(fd, exc_flag)

    return p.poll(timeout)


def _kqueue(*args):
    pass


def _select(readlist, writelist, exceptionallist, timeout):
    # Some platforms, e.g., OSX do not support poll
    if epoll or poll:
        return _poll(readlist, writelist, exceptionallist, timeout)

    if kqueue and kevent:
        return _kqueue(readlist, writelist, exceptionallist, timeout)

    if select:
        return select(readlist, writelist, exceptionallist, timeout)


def wait_to_read_data(socket, timeout=0.0):
    sockets = _select([socket], [], [], timeout)

    # select.select returns ([...], [...], [...])
    if isinstance(sockets, tuple):
        return sockets[0]

    return sockets


def wait_to_write_data(socket, timeout=0.0):
    sockets = _select([], [socket], [], timeout)

    # select.select returns ([...], [...], [...])
    if isinstance(sockets, tuple):
        return sockets[1]

    return sockets


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

    try:
        sockets = wait_to_read_data(sock)
    except socket.error:
        return True

    try:
        for (fno, ev) in sockets:
            if fno == sock.fileno():
                # Either data is buffered (bad), or the connection is dropped.
                return True
    except TypeError:
        return sockets


# This function is copied from socket.py in the Python 2.7 standard
# library test suite. Added to its signature is only `socket_options`.
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
    for res in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
        af, socktype, proto, canonname, sa = res
        sock = None
        try:
            sock = socket.socket(af, socktype, proto)

            # If provided, set socket level options before connecting.
            # This is the only addition urllib3 makes to this function.
            _set_socket_options(sock, socket_options)

            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sa)
            return sock

        except socket.error as _:
            err = _
            if sock is not None:
                sock.close()
                sock = None

    if err is not None:
        raise err
    else:
        raise socket.error("getaddrinfo returns an empty list")


def _set_socket_options(sock, options):
    if options is None:
        return

    for opt in options:
        sock.setsockopt(*opt)
