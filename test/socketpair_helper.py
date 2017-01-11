import socket

if hasattr(socket, 'socketpair'):
    # Since Python 3.5, socket.socketpair() is now also available on Windows
    socketpair = socket.socketpair
else:
    # Replacement for socket.socketpair()
    def socketpair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
        """A socket pair usable as a self-pipe, for Windows.

        Origin: https://gist.github.com/4325783, by Geert Jansen.
        Public domain.
        """
        if family == socket.AF_INET:
            host = '127.0.0.1'
        elif family == socket.AF_INET6:
            host = '::1'
        else:
            raise ValueError("Only AF_INET and AF_INET6 socket address "
                             "families are supported")
        if type != socket.SOCK_STREAM:
            raise ValueError("Only SOCK_STREAM socket type is supported")
        if proto != 0:
            raise ValueError("Only protocol zero is supported")

        # We create a connected TCP socket. Note the trick with setblocking(0)
        # that prevents us from having to create a thread.
        lsock = socket.socket(family, type, proto)
        try:
            lsock.bind((host, 0))
            lsock.listen(1)
            # On IPv6, ignore flow_info and scope_id
            addr, port = lsock.getsockname()[:2]
            csock = socket.socket(family, type, proto)
            try:
                csock.setblocking(False)
                try:
                    csock.connect((addr, port))
                except (BlockingIOError, InterruptedError):
                    pass
                csock.setblocking(True)
                ssock, _ = lsock.accept()
            except:
                csock.close()
                raise
        finally:
            lsock.close()
        return (ssock, csock)
