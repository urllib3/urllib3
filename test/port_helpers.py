# These helpers are copied from test_support.py in the Python 2.7 standard
# library test suite.

import socket

# Don't use "localhost", since resolving it uses the DNS under recent
# Windows versions (see issue #18792).
HOST = "127.0.0.1"
HOSTv6 = "::1"


def find_unused_port(family=socket.AF_INET, socktype=socket.SOCK_STREAM):
    """Returns an unused port that should be suitable for binding.  This is
    achieved by creating a temporary socket with the same family and type as
    the 'sock' parameter (default is AF_INET, SOCK_STREAM), and binding it to
    the specified host address (defaults to 0.0.0.0) with the port set to 0,
    eliciting an unused ephemeral port from the OS.  The temporary socket is
    then closed and deleted, and the ephemeral port is returned.

    Either this method or bind_port() should be used for any tests where a
    server socket needs to be bound to a particular port for the duration of
    the test.  Which one to use depends on whether the calling code is creating
    a python socket, or if an unused port needs to be provided in a constructor
    or passed to an external program (i.e. the -accept argument to openssl's
    s_server mode).  Always prefer bind_port() over find_unused_port() where
    possible.  Hard coded ports should *NEVER* be used.  As soon as a server
    socket is bound to a hard coded port, the ability to run multiple instances
    of the test simultaneously on the same host is compromised, which makes the
    test a ticking time bomb in a buildbot environment. On Unix buildbots, this
    may simply manifest as a failed test, which can be recovered from without
    intervention in most cases, but on Windows, the entire python process can
    completely and utterly wedge, requiring someone to log in to the buildbot
    and manually kill the affected process.

    (This is easy to reproduce on Windows, unfortunately, and can be traced to
    the SO_REUSEADDR socket option having different semantics on Windows versus
    Unix/Linux.  On Unix, you can't have two AF_INET SOCK_STREAM sockets bind,
    listen and then accept connections on identical host/ports.  An EADDRINUSE
    socket.error will be raised at some point (depending on the platform and
    the order bind and listen were called on each socket).

    However, on Windows, if SO_REUSEADDR is set on the sockets, no EADDRINUSE
    will ever be raised when attempting to bind two identical host/ports. When
    accept() is called on each socket, the second caller's process will steal
    the port from the first caller, leaving them both in an awkwardly wedged
    state where they'll no longer respond to any signals or graceful kills, and
    must be forcibly killed via OpenProcess()/TerminateProcess().

    The solution on Windows is to use the SO_EXCLUSIVEADDRUSE socket option
    instead of SO_REUSEADDR, which effectively affords the same semantics as
    SO_REUSEADDR on Unix.  Given the propensity of Unix developers in the Open
    Source world compared to Windows ones, this is a common mistake.  A quick
    look over OpenSSL's 0.9.8g source shows that they use SO_REUSEADDR when
    openssl.exe is called with the 's_server' option, for example. See
    http://bugs.python.org/issue2550 for more info.  The following site also
    has a very thorough description about the implications of both REUSEADDR
    and EXCLUSIVEADDRUSE on Windows:
    http://msdn2.microsoft.com/en-us/library/ms740621(VS.85).aspx)

    XXX: although this approach is a vast improvement on previous attempts to
    elicit unused ports, it rests heavily on the assumption that the ephemeral
    port returned to us by the OS won't immediately be dished back out to some
    other process when we close and delete our temporary socket but before our
    calling code has a chance to bind the returned port.  We can deal with this
    issue if/when we come across it."""
    tempsock = socket.socket(family, socktype)
    port = bind_port(tempsock)
    tempsock.close()
    del tempsock
    return port


def bind_port(sock, host=HOST):
    """Bind the socket to a free port and return the port number.  Relies on
    ephemeral ports in order to ensure we are using an unbound port.  This is
    important as many tests may be running simultaneously, especially in a
    buildbot environment.  This method raises an exception if the sock.family
    is AF_INET and sock.type is SOCK_STREAM, *and* the socket has SO_REUSEADDR
    or SO_REUSEPORT set on it.  Tests should *never* set these socket options
    for TCP/IP sockets.  The only case for setting these options is testing
    multicasting via multiple UDP sockets.

    Additionally, if the SO_EXCLUSIVEADDRUSE socket option is available (i.e.
    on Windows), it will be set on the socket.  This will prevent anyone else
    from bind()'ing to our host/port for the duration of the test.
    """
    if sock.family == socket.AF_INET and sock.type == socket.SOCK_STREAM:
        if hasattr(socket, "SO_REUSEADDR"):
            if sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 1:
                raise ValueError(
                    "tests should never set the SO_REUSEADDR "
                    "socket option on TCP/IP sockets!"
                )
        if hasattr(socket, "SO_REUSEPORT"):
            if sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT) == 1:
                raise ValueError(
                    "tests should never set the SO_REUSEPORT "
                    "socket option on TCP/IP sockets!"
                )
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)

    sock.bind((host, 0))
    port = sock.getsockname()[1]
    return port
