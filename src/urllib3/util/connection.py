from __future__ import annotations

import socket
import typing

from time import perf_counter

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
# import pysnooper
# @pysnooper.snoop(depth=1, normalize=False)
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

    # Check if we have IPv6 and IPv4 addresses to use happy eyeballs
    has_ipv4, has_ipv6 = (False, False)
    for af, _, _, _, sa in addr_info:
        if af == socket.AF_INET:
            has_ipv4 = True
        elif af == socket.AF_INET6:
            has_ipv6 = True
    has_ipv6_and_ipv4 = has_ipv6 and has_ipv4

    # Order our address results so we try IPv6 addresses first
    # and IPv4 addresses second
    if has_ipv6_and_ipv4:
        addr_info = sorted(
            addr_info,
            key=lambda x: 0
            if x[0] == socket.AF_INET6
            else (1 if x[0] == socket.AF_INET else 2)
        )
    
    sockets = []
    start_time = perf_counter()
    print(f"Initial start time:{start_time}")

    for res in addr_info:
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
            
            sock.setblocking(False)

            try:
                sock.connect(sa)
            except BlockingIOError as exc:
                if exc.errno != 115:  # EINPROGRESS
                    raise
            
            sockets.append(sock)
             
            # Break explicitly a reference cycle
            err = None
            # return sock

        except OSError as _:
            err = _
            if sock is not None:
                sock.close()

    # Provide the connect that returns the first connection
    counter = 0
    while (perf_counter() - start_time) < 0.2:
        print(f"counter: {counter} start_time:{start_time} - perf_counter:{perf_counter()}")
        for sock in sockets:
            print(f"Trying {sock.getsockname()}")
            result = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            import errno
            
            print(f"Socket state: {result} - {'NO-ERROR' if result == 0 else errno.errorcode[result]}")

            # If connection is successful return it
            if result == 0:
                sock.setblocking(True)
                if timeout is not _DEFAULT_TIMEOUT:
                    sock.settimeout(timeout)
                # There's a timing problem here
                # Sleeping for a little bit lets the connection finish establishing
                # import time
                # time.sleep(0.2)
                # We're returning sockets as healthly when they're not
                # Checking the peer name is a rough proxy for health
                try:
                    sock.getpeername()
                except OSError as e:
                    print("Not a healthy socket")
                    raise e
                # print(f"Closing other sockets")
                for to_close_sock in sockets:
                    if to_close_sock != sock:
                        print(f"Closing {to_close_sock}")
                        to_close_sock.close()
                print(f"Returning {sock}")
                return sock
        import time
        time.sleep(0.15)
        counter += 1
    
    print("Broke out")

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
