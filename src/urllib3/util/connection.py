from __future__ import annotations

import socket
import typing
from time import perf_counter

from socket import timeout as SocketTimeout

from ..exceptions import LocationParseError
from .timeout import _DEFAULT_TIMEOUT, _TYPE_TIMEOUT

_TYPE_SOCKET_OPTIONS = typing.Sequence[typing.Tuple[int, int, typing.Union[int, bytes]]]

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
    err = None

    # Using the value from allowed_gai_family() in the context of getaddrinfo lets
    # us select whether to work with IPv4 DNS records, IPv6 records, or both.
    # The original create_connection function always returns all records.
    family = allowed_gai_family()

    try:
        host.encode("idna")
    except UnicodeError:
        raise LocationParseError(f"'{host}', label empty or too long") from None

    addr_info = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)

    if len(addr_info) == 0:
        raise OSError("getaddrinfo returns an empty list")

    # Order our address results so we try IPv6 addresses before IPv4
    addr_info = sorted(
        addr_info,
        key=lambda x: 0
        if x[0] == socket.AF_INET6
        else (1 if x[0] == socket.AF_INET else 2),
    )

    sockets = []
    start_time = perf_counter()

    for res in addr_info:
        af, socktype, proto, canonname, sa = res
        sock = None
        try:
            sock = socket.socket(af, socktype, proto)

            # If provided, set socket level options before connecting.
            _set_socket_options(sock, socket_options)

            # Blocking vs non-blocking should be set before binding
            # Setting non-blocking is equivalent to setting timeout to None
            sock.settimeout(1)
            sock.setblocking(False)

            if source_address:
                sock.bind(source_address)

            try:
                sock.connect(sa)
            except BlockingIOError as exc:
                if exc.errno != 115:  # EINPROGRESS
                    raise

            sockets.append(sock)

            # Break explicitly a reference cycle
            err = None

        except OSError as _:
            err = _
            if sock is not None:
                sock.close()

    # Provide the socket that returns the first connection
    # This section needs a timeout or it hangs forever trying to establish a connection
    # 0.2s is arbitary currently, need something more formal to use
    while perf_counter() - start_time < 0.2:
        for sock in sockets:
            result = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)

            # If connection is successful return it
            if result == 0:
                # Setting a timeout on the socket makes it blocking again
                # TODO: Fix setting timeout, currently just sticking in a default
                if timeout is not _DEFAULT_TIMEOUT:
                    sock.settimeout(timeout)
                else:
                    sock.settimeout(socket.getdefaulttimeout())

                # We're returning sockets as healthly when they're not
                # Checking the peer name is a rough proxy for health
                # This is a problem as we need to let things timeout before they
                # get here
                try:
                    sock.getpeername()
                    for to_close_sock in sockets:
                        if to_close_sock and to_close_sock != sock:
                            to_close_sock.close()
                    return sock
                except OSError:
                    err = SocketTimeout("Timed out inside of loop")
                    pass
            elif result == 111:
                raise ConnectionRefusedError("Raised by me")

    # If we have sockets that we've been waiting on, and no other errors raise a ConnectTimeoutError
    if len(sockets) > 0 and err is None:
        raise SocketTimeout("Timed out outside of loop")

    # If we get to here close all dangling sockets
    for to_close_sock in sockets:
        if to_close_sock:
            to_close_sock.close()

    # If we can't bind we shouldn't be raising a ConnectTimeoutError

    if err is not None:
        try:
            raise err
        finally:
            # Break explicitly a reference cycle
            err = None
    else:
        raise OSError("getaddrinfo returns an empty list")


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
