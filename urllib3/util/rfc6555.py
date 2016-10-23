import errno
import socket
from urllib3.util.selectors import (
    DefaultSelector,
    EVENT_WRITE
)

try:  # time.monotonic is Python 3.x only
    from time import monotonic
except ImportError:
    from time import time as monotonic

HAPPY_EYEBALLS_CACHE = {}
HAPPY_EYEBALLS_CACHE_TIME = 60 * 10  # 10 minutes according to RFC 6555
_ASYNC_ERROR_NUMBERS = set([errno.EINPROGRESS,
                            errno.EAGAIN,
                            errno.EWOULDBLOCK,
                            errno.WSAEWOULDBLOCK])

_IP_FAMILIES = set([socket.AF_INET])
if hasattr(socket, "AF_INET6"):
    _IP_FAMILIES.add(socket.AF_INET6)


def happy_eyeballs_algorithm(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
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
    if timeout is None:
        timeout_time = None
    elif timeout is socket._GLOBAL_DEFAULT_TIMEOUT:
        timeout_time = socket._GLOBAL_DEFAULT_TIMEOUT
    else:
        timeout_time = start_time + timeout

    # Check the cache to see if our address is already there.
    if address in HAPPY_EYEBALLS_CACHE:
        family, expires = HAPPY_EYEBALLS_CACHE[address]

        # If the cache entry is expired, don't use it.
        if start_time > expires:
            del HAPPY_EYEBALLS_CACHE[address]
            family = 0

    host, port = address
    socks = []

    # Make sure we close the selector after we're done.
    with DefaultSelector() as selector:
        # Perform a DNS lookup for the address for IPv4 or IPv6 families.
        if not family:
            family = socket.AF_UNSPEC

        dns_results = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
        dns_results_len = len(dns_results)

        for i in range(dns_results_len):
            af, socktype, proto, canonname, sa = dns_results[i]

            # We only care about IPv4 and IPv6 addresses.
            if af not in _IP_FAMILIES:
                continue

            sock = None
            try:
                sock = socket.socket(af, socktype, proto)
                if timeout_time is socket._GLOBAL_DEFAULT_TIMEOUT:
                    sock_timeout = sock.gettimeout()
                    if sock_timeout is None:
                        timeout_time = None
                    else:
                        timeout_time = start_time + sock_timeout

                if socket_options:
                    for opt in socket_options:
                        sock.setsockopt(*opt)

                # If we're given a source address, bind to it.
                if source_address:
                    sock.bind(source_address)

                # Set non-blocking for selecting.
                sock.settimeout(0.0)

                # Connect to the host.
                errcode = sock.connect_ex(sa)
                if errcode and errcode not in _ASYNC_ERROR_NUMBERS:
                    err = socket.error(errcode)
                    continue

                errcode = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if errcode and errcode not in _ASYNC_ERROR_NUMBERS:
                    err = socket.error(errcode)
                    continue

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
                        # Otherwise we're willing to block forever, but set a time
                        # so that we can still filter out errored sockets.
                        select_time = 1.0

                # Make sure we don't have any errored sockets.
                for sock in socks:
                    errcode = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                    if errcode and errcode not in _ASYNC_ERROR_NUMBERS:
                        err = socket.error(errcode)
                        socks.remove(sock)
                        selector.unregister(sock)

                # If we don't have any sockets, don't try selecting.
                if not socks:
                    # If there are no more sockets to look through, then
                    # we should give up immediately with a non-timeout error.
                    if i == dns_results_len - 1:
                        err = socket.error(errno.ECONNREFUSED)
                    break

                # Monitor our selector for a new connection.
                connected = selector.select(timeout=select_time)

                # Iterate over the sockets that are reporting writable.
                for key, _ in connected:
                    # Check to see if there's an error post-connection.
                    conn = key.fileobj
                    errcode = conn.getsockopt(socket.SOL_SOCKET,
                                              socket.SO_ERROR)

                    if errcode and errcode not in _ASYNC_ERROR_NUMBERS:
                        selector.unregister(conn)
                        try:
                            socks.remove(conn)
                            conn.close()
                        except (OSError, socket.error) as e:
                            err = e
                        continue

                    # Finally found a suitable socket!
                    elif errcode == 0:
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
        raise socket.timeout()
