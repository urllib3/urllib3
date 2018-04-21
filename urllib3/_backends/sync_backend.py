import errno
import socket
from ..util.connection import create_connection
from ..util.ssl_ import ssl_wrap_socket
from ..util import selectors
from .. import util

from ._common import DEFAULT_SELECTOR, is_readable, LoopAbort

__all__ = ["SyncBackend"]

BUFSIZE = 65536


class SyncBackend(object):
    def connect(self, host, port, connect_timeout,
                source_address=None, socket_options=None):
        conn = create_connection(
            (host, port), connect_timeout,
            source_address=source_address, socket_options=socket_options)
        return SyncSocket(conn)


class SyncSocket(object):
    # _selector is a hack for testing. Note that normally, we create a
    # new selector object each time we block, but if _selector is passed
    # we use the object every time. See test_sync_connection.py for the
    # tests that use this.
    def __init__(self, sock, _selector=None):
        self._sock = sock
        # We keep the socket in non-blocking mode, except during connect() and
        # during the SSL handshake:
        self._sock.setblocking(False)
        self._selector = _selector

    def start_tls(self, server_hostname, ssl_context):
        self._sock.setblocking(True)
        wrapped = ssl_wrap_socket(
            self._sock,
            server_hostname=server_hostname, ssl_context=ssl_context)
        wrapped.setblocking(False)
        return SyncSocket(wrapped)

    # Only for SSL-wrapped sockets
    def getpeercert(self, binary_form=False):
        return self._sock.getpeercert(binary_form=binary_form)

    def _wait(self, readable, writable, read_timeout=None):
        assert readable or writable
        s = self._selector or DEFAULT_SELECTOR()
        flags = 0
        if readable:
            flags |= selectors.EVENT_READ
        if writable:
            flags |= selectors.EVENT_WRITE
        s.register(self._sock, flags)
        events = s.select(timeout=read_timeout)
        if not events:
            raise socket.timeout()  # XX use a backend-agnostic exception
        _, event = events[0]
        return (event & selectors.EVENT_READ, event & selectors.EVENT_WRITE)

    def receive_some(self):
        while True:
            try:
                return self._sock.recv(BUFSIZE)
            except util.SSLWantReadError:
                self._wait(readable=True, writable=False)
            except util.SSLWantWriteError:
                self._wait(readable=False, writable=True)
            except (OSError, socket.error) as exc:
                if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                    self._wait(readable=True, writable=False)
                else:
                    raise

    def send_and_receive_for_a_while(
            self, produce_bytes, consume_bytes, read_timeout):
        outgoing_finished = False
        outgoing = b""
        try:
            while True:
                if not outgoing_finished and not outgoing:
                    # Can exit loop here with error
                    b = produce_bytes()
                    if b is None:
                        outgoing = None
                        outgoing_finished = True
                    else:
                        assert b
                        outgoing = memoryview(b)

                # This controls whether or not we block
                made_progress = False
                # If we do block, then these determine what can wake us up
                want_read = False
                want_write = False

                # Important: we do recv before send. This is because we want
                # to make sure that after a send completes, we immediately
                # call produce_bytes before calling recv and potentially
                # getting a LoopAbort. This avoids a race condition -- see the
                # "subtle invariant" in the backend API documentation.

                try:
                    incoming = self._sock.recv(BUFSIZE)
                except util.SSLWantReadError:
                    want_read = True
                except util.SSLWantWriteError:
                    want_write = True
                except (OSError, socket.error) as exc:
                    if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                        want_read = True
                    else:
                        raise
                else:
                    made_progress = True
                    # Can exit loop here with LoopAbort
                    consume_bytes(incoming)

                if not outgoing_finished:
                    try:
                        sent = self._sock.send(outgoing)
                        outgoing = outgoing[sent:]
                    except util.SSLWantReadError:
                        want_read = True
                    except util.SSLWantWriteError:
                        want_write = True
                    except (OSError, socket.error) as exc:
                        if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                            want_write = True
                        else:
                            raise
                    else:
                        made_progress = True

                if not made_progress:
                    self._wait(want_read, want_write, read_timeout)
        except LoopAbort:
            pass

    def forceful_close(self):
        self._sock.close()

    def is_readable(self):
        return is_readable(self._sock)

    def set_readable_watch_state(self, enabled):
        pass
