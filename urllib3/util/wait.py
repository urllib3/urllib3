import select

HAS_SELECT = True
_READ_SELECTOR = None
_WRITE_SELECTOR = None

# BSD
if hasattr(select, "kqueue"):
    def _kqueue_wait_for_read(socks, timeout=None):
        kqueue = select.kqueue()
        flags = select.KQ_EV_ADD | select.KQ_EV_ENABLE
        kevents = []
        for sock in socks:
            kevents.append(select.kevent(sock.fileno(),
                                         filter=select.KQ_FILTER_READ,
                                         flags=flags))
        kevents = kqueue.control(kevents, len(socks), timeout)
        return [kev.ident for kev in kevents]

    def _kqueue_wait_for_write(socks, timeout=None):
        kqueue = select.kqueue()
        flags = select.KQ_EV_ADD | select.KQ_EV_ENABLE
        kevents = []
        for sock in socks:
            kevents.append(select.kevent(sock.fileno(),
                                         filter=select.KQ_FILTER_WRITE,
                                         flags=flags))
        kevents = kqueue.control(kevents, len(socks), timeout)
        return [kev.ident for kev in kevents]

# Linux 2.5.44+
if hasattr(select, "epoll"):
    def _epoll_wait_for_read(socks, timeout=None):
        if timeout is None:
            timeout = -1
        timeout = float(timeout)  # Epoll must take a float, no ints.
        epoll = select.epoll()
        for sock in socks:
            epoll.register(sock.fileno(), select.EPOLLIN)
        return [fd for fd, _ in epoll.poll(timeout)]

    def _epoll_wait_for_write(socks, timeout=None):
        if timeout is None:
            timeout = -1
        timeout = float(timeout)  # Epoll must take a float, no ints.
        epoll = select.epoll()
        for sock in socks:
            epoll.register(sock.fileno(), select.EPOLLOUT)
        return [fd for fd, _ in epoll.poll(timeout)]

# Solaris
if hasattr(select, "devpoll"):
    def _devpoll_wait_for_read(socks, timeout=None):
        devpoll = select.devpoll()
        for sock in socks:
            devpoll.register(sock.fileno(), select.POLLIN)
        return [fd for fd, _ in devpoll.poll(timeout)]

    def _devpoll_wait_for_write(socks, timeout=None):
        devpoll = select.devpoll()
        for sock in socks:
            devpoll.register(sock.fileno(), select.POLLOUT)
        return [fd for fd, _ in devpoll.poll(timeout)]

# Almost all Linux
if hasattr(select, "poll"):
    def _poll_wait_for_read(socks, timeout=None):
        poll = select.poll()
        for sock in socks:
            poll.register(sock.fileno(), select.POLLIN)
        return [fd for fd, _ in poll.poll(timeout)]

    def _poll_wait_for_write(socks, timeout=None):
        poll = select.poll()
        for sock in socks:
            poll.register(sock.fileno(), select.POLLOUT)
        return [fd for fd, _ in poll.poll(timeout)]

# Windows
if hasattr(select, "select"):
    def _select_wait_for_read(socks, timeout=None):
        if not socks:  # Windows is not tolerant of empty selects.
            return []
        return select.select([s.fileno() for s in socks], [], [], timeout)[0]

    def _select_wait_for_write(socks, timeout=None):
        if not socks:  # Windows is not tolerant of empty selects.
            return []
        return select.select([], [s.fileno() for s in socks], [], timeout)[1]

# Platform doesn't have a selector
else:
    HAS_SELECT = False

# If we have a selector, choose the fastest.
# According to selectors.py the best order is:
# kqueue == epoll == devpoll > poll > select
if HAS_SELECT:
    if hasattr(select, "kqueue"):
        _READ_SELECTOR = _kqueue_wait_for_read
        _WRITE_SELECTOR = _kqueue_wait_for_write

    elif hasattr(select, "epoll"):
        _READ_SELECTOR = _epoll_wait_for_read
        _WRITE_SELECTOR = _epoll_wait_for_write

    elif hasattr(select, "devpoll"):
        _READ_SELECTOR = _devpoll_wait_for_read
        _WRITE_SELECTOR = _devpoll_wait_for_write

    elif hasattr(select, "poll"):
        _READ_SELECTOR = _poll_wait_for_read
        _WRITE_SELECTOR = _poll_wait_for_write

    else:
        _READ_SELECTOR = _select_wait_for_read
        _WRITE_SELECTOR = _select_wait_for_write


def wait_for_read(socks, timeout=None):
    """ Waits for reading to be available from a list of sockets
    or optionally a single socket if passed in. Returns a list of
    sockets that can be read from immediately. """
    try:
        if not HAS_SELECT:
            raise ValueError('Platform does not have a selector.')
        if not isinstance(socks, list):
            socks = [socks]
        return _READ_SELECTOR(socks, timeout)
    except OSError:
        return []


def wait_for_write(socks, timeout=None):
    """ Waits for writing to be available from a list of sockets
    or optionally a single socket if passed in. Returns a list of
    sockets that can be written to immediately. """
    try:
        if not HAS_SELECT:
            raise ValueError('Platform does not have a selector.')
        if not isinstance(socks, list):
            socks = [socks]
        return _WRITE_SELECTOR(socks, timeout)
    except OSError:
        return []
