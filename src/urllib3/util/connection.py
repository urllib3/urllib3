from __future__ import annotations

import errno
import ipaddress
import selectors
import socket
import time
import typing

from ..exceptions import LocationParseError
from .timeout import _DEFAULT_TIMEOUT, _TYPE_TIMEOUT

_TYPE_SOCKET_OPTIONS = list[tuple[int, int, int | bytes]]
_HAPPY_EYEBALLS_DELAY = 0.25
_CONNECT_IN_PROGRESS_ERRORS = {
    errno.EINPROGRESS,
    errno.EWOULDBLOCK,
    errno.EALREADY,
}

if typing.TYPE_CHECKING:
    from .._base_connection import BaseHTTPConnection


def is_connection_dropped(conn: BaseHTTPConnection) -> bool:  # Platform-specific
    """
    Returns True if the connection is dropped and should be closed.
    :param conn: :class:`urllib3.connection.HTTPConnection` object.
    """
    return not conn.is_connected


# This function is copied from socket.py in the Python 2.7 standard
# library test suite. Added to its signature is only `socket_options`.
# One additional modification is that we avoid binding to IPv6 servers
# discovered in DNS if the system doesn't have IPv6 functionality.
def create_connection(
    address: tuple[str, int],
    timeout: _TYPE_TIMEOUT = _DEFAULT_TIMEOUT,
    source_address: tuple[str, int] | None = None,
    socket_options: _TYPE_SOCKET_OPTIONS | None = None,
) -> socket.socket:
    """Connect to *address* and return the socket object.

    Convenience function.  Connect to *address* (a 2-tuple ``(host,
    port)``) and return the socket object.  Passing the optional
    *timeout* parameter will set the timeout on the socket instance
    before attempting to connect.  If no *timeout* is supplied, the
    global default timeout setting returned by :func:`socket.getdefaulttimeout`
    is used.  If *source_address* is set it must be a tuple of (host, port)
    for the socket to bind as a source address before making the connection.
    An host of '' or port 0 tells the OS to use the default.
    """

    host, port = address
    if host.startswith("["):
        host = host.strip("[]")

    # Using the value from allowed_gai_family() in the context of getaddrinfo lets
    # us select whether to work with IPv4 DNS records, IPv6 records, or both.
    # The original create_connection function always returns all records.
    family = allowed_gai_family()

    try:
        host.encode("idna")
    except UnicodeError:
        raise LocationParseError(f"'{host}', label empty or too long") from None

    addrinfo = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
    if len(addrinfo) == 1 or _is_loopback_host(host):
        return _connect_to_resolved_addresses(
            addrinfo, timeout, source_address, socket_options
        )

    return _happy_eyeballs_connect(
        _interleave_addrinfo_by_family(addrinfo),
        timeout,
        source_address,
        socket_options,
    )


def _connect_to_resolved_addresses(
    addrinfo: list[
        tuple[
            socket.AddressFamily,
            socket.SocketKind,
            int,
            str,
            tuple[typing.Any, ...],
        ]
    ],
    timeout: _TYPE_TIMEOUT,
    source_address: tuple[str, int] | None,
    socket_options: _TYPE_SOCKET_OPTIONS | None,
) -> socket.socket:
    err = None
    for res in addrinfo:
        af, socktype, proto, canonname, sa = res
        sock = None
        try:
            sock = socket.socket(af, socktype, proto)

            # If provided, set socket level options before connecting.
            _set_socket_options(sock, socket_options)

            if timeout is not _DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sa)
            # Break explicitly a reference cycle
            err = None
            return sock

        except OSError as _:
            err = _
            if sock is not None:
                sock.close()

    if err is not None:
        try:
            raise err
        finally:
            # Break explicitly a reference cycle
            err = None
    raise OSError("getaddrinfo returns an empty list")


def _happy_eyeballs_connect(
    addrinfo: list[
        tuple[
            socket.AddressFamily,
            socket.SocketKind,
            int,
            str,
            tuple[typing.Any, ...],
        ]
    ],
    timeout: _TYPE_TIMEOUT,
    source_address: tuple[str, int] | None,
    socket_options: _TYPE_SOCKET_OPTIONS | None,
) -> socket.socket:
    if not addrinfo:
        raise OSError("getaddrinfo returns an empty list")

    timeout_value = (
        socket.getdefaulttimeout() if timeout is _DEFAULT_TIMEOUT else timeout
    )
    deadline = None if timeout_value is None else time.monotonic() + timeout_value
    next_attempt_at = time.monotonic()
    pending = list(addrinfo)
    active: dict[int, socket.socket] = {}
    selector = selectors.DefaultSelector()
    err: OSError | None = None

    try:
        while pending or active:
            now = time.monotonic()
            while pending and now >= next_attempt_at:
                try:
                    sock, connected = _start_connect_attempt(
                        pending.pop(0),
                        source_address,
                        socket_options,
                    )
                except OSError as e:
                    err = e
                    continue

                if connected:
                    _close_active_sockets(active)
                    _restore_socket_timeout(sock, timeout)
                    return sock

                try:
                    selector.register(sock, selectors.EVENT_WRITE)
                    active[sock.fileno()] = sock
                except BaseException:
                    sock.close()
                    raise
                next_attempt_at = now + _HAPPY_EYEBALLS_DELAY

            if deadline is not None and now >= deadline:
                raise TimeoutError("timed out")

            if not active:
                break

            select_timeout = None
            if pending:
                select_timeout = max(0.0, next_attempt_at - now)
            if deadline is not None:
                deadline_timeout = max(0.0, deadline - now)
                select_timeout = (
                    deadline_timeout
                    if select_timeout is None
                    else min(select_timeout, deadline_timeout)
                )

            events = selector.select(select_timeout)
            for key, _ in events:
                sock = typing.cast(socket.socket, key.fileobj)
                selector.unregister(sock)
                active.pop(sock.fileno(), None)
                connect_error = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if connect_error == 0:
                    _close_active_sockets(active)
                    _restore_socket_timeout(sock, timeout)
                    return sock
                sock.close()
                err = OSError(
                    connect_error, errno.errorcode.get(connect_error, "error")
                )
                if pending:
                    next_attempt_at = time.monotonic()

        if err is not None:
            raise err
        raise OSError("getaddrinfo returns an empty list")  # pragma: no cover
    finally:
        selector.close()
        _close_sockets(active.values())


def _interleave_addrinfo_by_family(
    addrinfo: list[
        tuple[
            socket.AddressFamily,
            socket.SocketKind,
            int,
            str,
            tuple[typing.Any, ...],
        ]
    ],
) -> list[
    tuple[
        socket.AddressFamily,
        socket.SocketKind,
        int,
        str,
        tuple[typing.Any, ...],
    ]
]:
    by_family: dict[
        socket.AddressFamily,
        list[
            tuple[
                socket.AddressFamily,
                socket.SocketKind,
                int,
                str,
                tuple[typing.Any, ...],
            ]
        ],
    ] = {}
    family_order = []
    for res in addrinfo:
        family = res[0]
        if family not in by_family:
            by_family[family] = []
            family_order.append(family)
        by_family[family].append(res)

    if len(family_order) < 2:
        return addrinfo

    interleaved = []
    while by_family:
        for family in list(family_order):
            family_results = by_family[family]
            interleaved.append(family_results.pop(0))
            if not family_results:
                by_family.pop(family)
                family_order.remove(family)
    return interleaved


def _start_connect_attempt(
    res: tuple[
        socket.AddressFamily,
        socket.SocketKind,
        int,
        str,
        tuple[typing.Any, ...],
    ],
    source_address: tuple[str, int] | None,
    socket_options: _TYPE_SOCKET_OPTIONS | None,
) -> tuple[socket.socket, bool]:
    af, socktype, proto, canonname, sa = res
    sock = socket.socket(af, socktype, proto)
    try:
        _set_socket_options(sock, socket_options)
        if source_address:
            sock.bind(source_address)
        sock.setblocking(False)
        connect_error = sock.connect_ex(sa)
        if connect_error == 0:
            return sock, True
        if connect_error in _CONNECT_IN_PROGRESS_ERRORS:
            return sock, False
    except OSError:
        sock.close()
        raise

    sock.close()
    raise OSError(connect_error, errno.errorcode.get(connect_error, "error"))


def _restore_socket_timeout(sock: socket.socket, timeout: _TYPE_TIMEOUT) -> None:
    if timeout is _DEFAULT_TIMEOUT:
        sock.settimeout(socket.getdefaulttimeout())
    else:
        sock.settimeout(timeout)


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _close_sockets(sockets: typing.Iterable[socket.socket]) -> None:
    for sock in sockets:
        sock.close()


def _close_active_sockets(active: dict[int, socket.socket]) -> None:
    _close_sockets(active.values())
    active.clear()


def _set_socket_options(
    sock: socket.socket, options: _TYPE_SOCKET_OPTIONS | None
) -> None:
    if options is None:
        return

    for opt in options:
        sock.setsockopt(*opt)


def allowed_gai_family() -> socket.AddressFamily:
    """This function is designed to work in the context of
    getaddrinfo, where family=socket.AF_UNSPEC is the default and
    will perform a DNS search for both IPv6 and IPv4 records."""

    family = socket.AF_INET
    if HAS_IPV6:
        family = socket.AF_UNSPEC
    return family


def _has_ipv6(host: str) -> bool:
    """Returns True if the system can bind an IPv6 address."""
    sock = None
    has_ipv6 = False

    if socket.has_ipv6:
        # has_ipv6 returns true if cPython was compiled with IPv6 support.
        # It does not tell us if the system has IPv6 support enabled. To
        # determine that we must bind to an IPv6 address.
        # https://github.com/urllib3/urllib3/pull/611
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


HAS_IPV6 = _has_ipv6("::1")
